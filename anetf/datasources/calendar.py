# -*- coding:utf-8 -*-
"""交易日历与指数清单：进程级懒加载单例。

把原 ValuationService 的 _latest_trade_day / _gz_df 两个懒加载属性
下沉为模块级单例，供所有 DataSource 与 Service 共享，避免重复请求。

线程安全：首次访问加锁拉取，之后所有线程复用缓存值。
"""

import threading
import logging

import pandas as pd
import akshare as ak

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_latest_trade_day_cache: str = None
_cni_index_list_cache: pd.DataFrame = None


def get_latest_trade_day() -> str:
    """最新交易日（YYYY-MM-DD），进程级懒加载单例。

    akshare 不直接提供"最新交易日"，用平安银行（sz000001，始终上市、
    几乎每日交易）的行情末行作为近似。
    """
    global _latest_trade_day_cache
    if _latest_trade_day_cache is None:
        with _lock:
            if _latest_trade_day_cache is None:
                df = ak.stock_zh_a_daily(symbol="sz000001", start_date="20240301", adjust="qfq")
                _latest_trade_day_cache = str(df['date'].iloc[-1])
                logger.info('latest_trade_day resolved: %s', _latest_trade_day_cache)
    return _latest_trade_day_cache


def get_cni_index_list() -> pd.DataFrame:
    """国证指数全量列表，进程级懒加载单例。

    返回以"指数代码"为索引的 DataFrame，供 CniSource 查 PE滚动 列。
    """
    global _cni_index_list_cache
    if _cni_index_list_cache is None:
        with _lock:
            if _cni_index_list_cache is None:
                _cni_index_list_cache = ak.index_all_cni().set_index('指数代码')
                logger.info('cni_index_list loaded: %d indices', len(_cni_index_list_cache))
    return _cni_index_list_cache


def reset_cache() -> None:
    """清空缓存（仅供测试）。"""
    global _latest_trade_day_cache, _cni_index_list_cache
    with _lock:
        _latest_trade_day_cache = None
        _cni_index_list_cache = None
