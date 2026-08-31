# -*- coding:utf-8 -*-
"""报告生成服务。

阶段 3：把 pe.py 的 order() / _extend_pe_history / _extend_point_history /
classify / calc_percentile 迁移至此，产出结构化的 List[CategoryReport]，
废除 pe.py ↔ mail.py 之间基于 CSV 的隐式契约。

不再写 mail/*.csv，渲染层直接消费 ReportRow。
"""

import logging
from typing import List, Optional

import numpy as np
import pandas as pd
import akshare as ak

from anetf.config import MIN_PE_ROWS, MIN_POINT_ROWS
from anetf.constants import (
    CATEGORIES,
    FIRST_TAG_CATEGORY,
    UNSUPPORTED_INDEX_IDS,
)
from anetf.db.connection import Database
from anetf.db.etf_repo import EtfRepository
from anetf.db.valuation_repo import ValuationRepository
from anetf.datasources.calendar import get_latest_trade_day
from anetf.datasources.price_symbol import get_price_symbol
from anetf.models import ReportRow, CategoryReport

logger = logging.getLogger(__name__)


def classify(tag) -> Optional[str]:
    """根据标签判断ETF所属分类，返回分类键；无法识别时返回None"""
    if pd.isna(tag):
        return None
    if tag.find('跨境') != -1:
        return 'crossborder'
    if tag.find('宽基') != -1:
        return 'broad'
    return FIRST_TAG_CATEGORY.get(tag.split('，')[0])


def calc_percentile(arr) -> float:
    arr = arr.dropna()
    if len(arr) == 0:
        return np.nan
    lower = arr[arr < arr.iloc[-1]]
    return (lower.shape[0] / arr.shape[0])


class ReportService:
    """生成 ETF 估值分类报告（结构化数据，不落盘）。"""

    def __init__(self, db: Database = None):
        self._db = db or Database()
        self._etf_repo = EtfRepository(self._db)
        self._repo = ValuationRepository(self._db)

    def generate_report(self) -> List[CategoryReport]:
        # 去重：多只ETF跟踪同一指数，保留成交量最高的
        df = self._etf_repo.load_mapping()
        drop_duplicate_df = df.sort_values(by=['avgamount']).drop_duplicates(
            subset=['index_id'], keep='last')

        # 过滤不支持的指数
        before_filter = len(drop_duplicate_df)
        drop_duplicate_df = drop_duplicate_df[~drop_duplicate_df['index_id'].apply(
            lambda x: x.split('.')[0].upper() in UNSUPPORTED_INDEX_IDS)]
        logger.info('ETF number: {}, drop to {} after remove duplicated ETF, '
                    'filtered {} unsupported.'.format(
                        len(df), len(drop_duplicate_df),
                        before_filter - len(drop_duplicate_df)))

        # 填充ETF的最新估值和百分位
        # 股票类ETF用市盈率(PE)，非股票类ETF用指数点位
        values, value_percentile, data_types = [], [], []
        for i in range(len(drop_duplicate_df)):
            index_id = drop_duplicate_df['index_id'].iloc[i].split('.')[0].upper()
            etf_df = self._repo.load_index(index_id)

            if not etf_df.empty:
                # load_index 总是返回 市盈率/点位 两列（缺值为 NaN），优先 PE，PE 全空降级用点位
                pe_valid = pd.notna(etf_df['市盈率'].iloc[-1])
                point_valid = pd.notna(etf_df['点位'].iloc[-1])

                if pe_valid:
                    # 估值类型=PE：只使用 PE 数据计算百分位，绝不使用点位数据
                    val = etf_df['市盈率'].iloc[-1]
                    values.append(val)
                    extended_pe = self._extend_pe_history(index_id, etf_df['市盈率'])
                    if extended_pe is not None:
                        value_percentile.append(calc_percentile(extended_pe))
                    else:
                        # PE 扩展后仍不足，保持 "-"，绝不混用点位数据
                        value_percentile.append(np.nan)
                    data_types.append('PE')
                elif point_valid:
                    # 估值类型=点位：只使用点位数据计算百分位，绝不使用PE
                    val = etf_df['点位'].iloc[-1]
                    values.append(val)
                    extended_pt = self._extend_point_history(index_id, etf_df['点位'])
                    if extended_pt is not None:
                        value_percentile.append(calc_percentile(extended_pt))
                    else:
                        # 点位扩展后仍不足，保持 "-"
                        value_percentile.append(np.nan)
                    data_types.append('指数点位')
                else:
                    # 既无PE也无点位有效数据
                    values.append(np.nan)
                    value_percentile.append(np.nan)
                    data_types.append('')
            else:
                values.append(np.nan)
                value_percentile.append(np.nan)
                data_types.append('')

        drop_duplicate_df = drop_duplicate_df.copy()
        drop_duplicate_df['当前值'] = values
        drop_duplicate_df['历史百分位'] = value_percentile
        drop_duplicate_df['指标类型'] = data_types

        # 按分类拆分，分类规则见 classify()
        grouped = {key: [] for key, _ in CATEGORIES}
        for i in range(len(drop_duplicate_df)):
            key = classify(drop_duplicate_df['tag'].iloc[i])
            if key is None:
                logger.warning('Unclassified ETF: {} (tag={})'.format(
                    drop_duplicate_df['name'].iloc[i], drop_duplicate_df['tag'].iloc[i]))
                continue
            grouped[key].append(i)

        reports = []
        for key, label in CATEGORIES:
            subset = drop_duplicate_df.iloc[grouped[key]].sort_values(
                by=['当前值', '历史百分位']).reset_index(drop=True)
            rows = []
            for i in range(len(subset)):
                row = subset.iloc[i]
                value = row['当前值']
                percentile = row['历史百分位']
                rows.append(ReportRow(
                    etf_name=row['name'],
                    etf_code=str(row['code']),
                    index_name=row['index_name'],
                    index_id=str(row['index_id']),
                    value_type=row['指标类型'] if isinstance(row['指标类型'], str) else '',
                    value=None if pd.isna(value) else float(value),
                    percentile=None if pd.isna(percentile) else float(percentile),
                ))
            logger.info('{} ETF count: {}'.format(label, len(rows)))
            reports.append(CategoryReport(key=key, label=label, rows=rows))

        return reports

    def _extend_pe_history(self, index_id, current_pe_s):
        """尝试扩展 PE 历史数据长度（仅使用 PE 数据源，绝不使用点位）。
        当前已有 PE 不足时，优先从中证历史行情（滚动市盈率列）扩展，
        再尝试通过韭圈儿获取更长的 PE 序列。达不到最小行数返回 None。
        """
        current_pe_s = current_pe_s.dropna()
        if len(current_pe_s) >= MIN_PE_ROWS:
            return current_pe_s

        # 1. 尝试 stock_zh_index_hist_csindex 的"滚动市盈率"列（覆盖 CSI 全量指数，可能被WAF封）
        try:
            df = ak.stock_zh_index_hist_csindex(
                symbol=index_id,
                start_date='20180101',
                end_date=get_latest_trade_day().replace('-', '')
            )
            if not df.empty and '滚动市盈率' in df.columns:
                extra_pe = df['滚动市盈率'].dropna()
                extra_pe = extra_pe[extra_pe > 0]  # 过滤 0 值
                # 合并当前 PE 与扩展 PE（去重，避免重复日期）
                merged = pd.concat([current_pe_s, extra_pe]).drop_duplicates()
                merged = merged[~merged.index.duplicated(keep='last')] if isinstance(merged.index, pd.DatetimeIndex) else merged
                if len(merged) >= MIN_PE_ROWS:
                    return merged
        except Exception:
            pass

        # 2. 韭圈儿 PE 扩展未启用：需要 index_name 才能匹配 funddb，
        #    此处只有 index_id，留待上层传入 index_name 后再实现。

        # 达不到最小要求
        extended = current_pe_s.dropna()
        return extended if len(extended) >= MIN_PE_ROWS else None

    def _extend_point_history(self, index_id, current_point_s):
        """尝试扩展点位历史长度（仅使用价格/行情数据源，绝不使用 PE）。
        当前点位不足时，从多种 akshare 接口回退获取。达不到最小行数返回 None。
        """
        current_point_s = current_point_s.dropna()
        if len(current_point_s) >= MIN_POINT_ROWS:
            return current_point_s

        def _from_close_col(df, aliases=None):
            if df is None or df.empty:
                return None
            for alias in (aliases or ['close', '收盘', '收盘价', 'Close', '晚盘价']):
                if alias in df.columns:
                    s = pd.Series(df[alias]).dropna()
                    merged = pd.concat([current_point_s, s]).drop_duplicates()
                    return merged if len(merged) >= MIN_POINT_ROWS else None
            return None

        symbol_info = get_price_symbol(index_id)
        if symbol_info is None:
            ext = current_point_s.dropna()
            return ext if len(ext) >= MIN_POINT_ROWS else None
        source_type, symbol = symbol_info

        try:
            # ===== 中证 / 国证 / 沪深 =====
            if source_type in ('cn', 'cni'):
                # 国证历史行情 (980xxx/987xxx 必中)
                try:
                    df = ak.index_hist_cni(symbol=index_id)
                    res = _from_close_col(df)
                    if res is not None:
                        return res
                except Exception:
                    pass
                # 中证历史行情 (930xxx/931xxx/932xxx，WAF 可能间歇性封堵)
                try:
                    df = ak.stock_zh_index_hist_csindex(
                        symbol=index_id,
                        start_date='20180101',
                        end_date=get_latest_trade_day().replace('-', '')
                    )
                    res = _from_close_col(df)
                    if res is not None:
                        return res
                except Exception:
                    pass
                # 新浪行情：多种前缀组合
                if not index_id.startswith('98'):
                    for prefix in ['', 'csi', 'sh', 'sz']:
                        try:
                            df = ak.stock_zh_index_daily(symbol=prefix + index_id)
                            res = _from_close_col(df)
                            if res is not None:
                                return res
                        except Exception:
                            pass

            # ===== 港股 =====
            elif source_type == 'hk':
                try:
                    df = ak.stock_hk_index_daily_sina(symbol=symbol)
                    res = _from_close_col(df)
                    if res is not None:
                        return res
                except Exception:
                    pass

            # ===== 美股 =====
            elif source_type == 'us':
                try:
                    df = ak.index_us_stock_sina(symbol=symbol)
                    res = _from_close_col(df)
                    if res is not None:
                        return res
                except Exception:
                    pass

            # ===== 期货 =====
            elif source_type == 'futures':
                try:
                    df = ak.futures_zh_daily_sina(symbol=symbol)
                    res = _from_close_col(df)
                    if res is not None:
                        return res
                except Exception:
                    pass
            # ===== 黄金 =====
            elif source_type == 'gold':
                try:
                    df = ak.spot_golden_benchmark_sge()
                    res = _from_close_col(df)
                    if res is not None:
                        return res
                except Exception:
                    pass
        except Exception:
            pass

        ext = current_point_s.dropna()
        return ext if len(ext) >= MIN_POINT_ROWS else None
