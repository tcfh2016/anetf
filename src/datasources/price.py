# -*- coding:utf-8 -*-
"""指数点位行情数据源。

拆自 pe.py 的 update_price：对没有 PE 的指数（商品、债券、海外等），
用历史点位计算百分位。通过 get_price_symbol 路由到不同的 akshare 接口：
cn / cni / hk / us / futures / gold。

fetch() 返回 点位 类 DataFrame（点位列 + 数据类型='点位'），数据源列标 '指数行情'。
"""

import logging
import time
from typing import Optional, Callable

import pandas as pd
import akshare as ak

from src.datasources.base import DataSource
from src.datasources.price_symbol import get_price_symbol

logger = logging.getLogger(__name__)

# 网络拉取失败时的重试轮数与间隔（12 线程并发下 sina 偶发限流/超时，
# 串行重试验证成功率 100%；无路由的确定性失败不重试）
FETCH_RETRIES = 2
RETRY_BACKOFF = 2.0


class PriceSource(DataSource):
    """指数点位行情数据源（PE 降级路径）。"""

    name = '指数行情'

    def __init__(self, latest_trade_day_fn: Callable[[], str]):
        self._latest_trade_day_fn = latest_trade_day_fn

    def fetch(self, index_id: str, index_name: str, index_tag: str) -> Optional[pd.DataFrame]:
        symbol_info = get_price_symbol(index_id)
        if symbol_info is None:
            logger.warning('PRICE: No price source for %s', index_id)
            return None

        source_type, symbol = symbol_info
        logger.info('PRICE: Update index id(%s), name(%s), source=%s',
                   index_id, index_name, source_type)

        price_df = None
        for attempt in range(1, FETCH_RETRIES + 1):
            try:
                price_df = self._fetch_by_source(index_id, source_type, symbol)
            except Exception as e:
                logger.warning('PRICE: %s attempt %d raised: %s', index_id, attempt, e)
                price_df = None
            if price_df is not None and not price_df.empty:
                if attempt > 1:
                    logger.info('PRICE: %s succeeded on attempt %d', index_id, attempt)
                break
            if attempt < FETCH_RETRIES:
                logger.info('PRICE: %s attempt %d got no data, retry in %.0fs',
                            index_id, attempt, RETRY_BACKOFF)
                time.sleep(RETRY_BACKOFF)

        if price_df is None or price_df.empty:
            return None

        price_df['日期'] = pd.to_datetime(price_df['日期']).dt.strftime('%Y-%m-%d')
        price_df['指数代码'] = index_id
        price_df['指数名称'] = index_name
        price_df['标签'] = index_tag
        price_df['数据类型'] = '点位'
        price_df['数据源'] = '指数行情'
        price_df = price_df[['日期', '指数代码', '指数名称', '标签', '收盘', '数据类型', '数据源']].set_index('日期')
        return price_df.rename(columns={'收盘': '点位'})

    def _fetch_by_source(self, index_id: str, source_type: str, symbol: Optional[str]):
        """根据 source_type 获取行情，返回含 日期/收盘 列的 DataFrame 或 None。"""
        if source_type == 'cn':
            return self._fetch_cn(index_id, symbol)
        elif source_type == 'cni':
            return self._fetch_cni(symbol)
        elif source_type == 'hk':
            return self._fetch_hk(symbol)
        elif source_type == 'us':
            return self._fetch_us(symbol)
        elif source_type == 'futures':
            return self._fetch_futures(symbol)
        elif source_type == 'gold':
            return self._fetch_gold()
        return None

    def _fetch_cn(self, index_id, symbol):
        try:
            price_df = ak.stock_zh_index_daily(symbol=symbol)
            return price_df[['date', 'close']].rename(columns={'date': '日期', 'close': '收盘'})
        except Exception:
            # stock_zh_index_daily 不支持 csi 前缀代码，回退到中证指数历史行情
            logger.info('PRICE: primary API failed for %s, falling back to csindex', symbol)
            try:
                end_date = self._latest_trade_day_fn().replace('-', '')
                price_df = ak.stock_zh_index_hist_csindex(
                    symbol=index_id, start_date='20180101', end_date=end_date
                )
                if price_df.empty:
                    return None
                price_df = price_df.rename(columns={'收盘': '点位'})
                price_df = price_df[['日期', '点位']].copy()
                # 后续统一在 fetch() 里 rename 为 收盘
                return price_df.rename(columns={'点位': '收盘'})
            except Exception as e2:
                logger.warning('PRICE: fallback also failed for %s: %s', index_id, e2)
                return None

    def _fetch_cni(self, symbol):
        try:
            price_df = ak.index_hist_cni(symbol=symbol)
            if price_df.empty:
                logger.warning('PRICE: CNI index %s returned empty data', symbol)
                return None
            price_df = price_df.rename(columns={'收盘价': '收盘'})
            price_df = price_df[['日期', '收盘']].copy()
            logger.info('PRICE: CNI index %s loaded %d rows from index_hist_cni', symbol, len(price_df))
            return price_df
        except Exception as e2:
            logger.warning('PRICE: CNI index %s failed: %s', symbol, e2)
            return None

    def _fetch_hk(self, symbol):
        price_df = ak.stock_hk_index_daily_sina(symbol=symbol)
        return price_df[['date', 'close']].rename(columns={'date': '日期', 'close': '收盘'})

    def _fetch_us(self, symbol):
        try:
            price_df = ak.index_us_stock_sina(symbol=symbol)
            return price_df[['date', 'close']].rename(columns={'date': '日期', 'close': '收盘'})
        except Exception:
            logger.warning('PRICE: US index %s not supported by akshare, skipping', symbol)
            return None

    def _fetch_futures(self, symbol):
        price_df = ak.futures_zh_daily_sina(symbol=symbol)
        return price_df[['date', 'close']].rename(columns={'date': '日期', 'close': '收盘'})

    def _fetch_gold(self):
        price_df = ak.spot_golden_benchmark_sge()
        return price_df[['交易时间', '晚盘价']].rename(columns={'交易时间': '日期', '晚盘价': '收盘'})
