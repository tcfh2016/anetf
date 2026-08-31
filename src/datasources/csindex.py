# -*- coding:utf-8 -*-
"""中证指数数据源。

拆自 pe.py 的 update_zz 与 update_csindex：
- CsindexValueSource：中证指数官网 PE（stock_zh_index_value_csindex）
- CsindexHistSource：中证指数历史行情的滚动市盈率（stock_zh_index_hist_csindex）
"""

import logging
from typing import Optional, Callable

import pandas as pd
import akshare as ak

from src.datasources.base import DataSource

logger = logging.getLogger(__name__)


class CsindexValueSource(DataSource):
    """中证指数官网 PE 表（覆盖范围广，但部分指数更新滞后）。"""

    name = '中证指数'

    def fetch(self, index_id: str, index_name: str, index_tag: str) -> Optional[pd.DataFrame]:
        logger.info('ZZ: Update PE index id(%s)', index_id)
        new_df = ak.stock_zh_index_value_csindex(symbol=index_id).astype({'日期': str})
        new_df['指数名称'] = index_name
        new_df['标签'] = index_tag
        new_df['数据源'] = '中证指数'
        new_df = new_df.sort_values(by=['日期']).set_index('日期')[
            ['指数代码', '指数名称', '标签', '市盈率1', '数据源']
        ].rename(columns={'市盈率1': '市盈率'})
        return new_df


class CsindexHistSource(DataSource):
    """中证指数历史行情的滚动市盈率（覆盖 CSI 全量指数，WAF 可能间歇性封堵）。

    需要 latest_trade_day 作为 end_date，通过构造器注入 callable 实现懒加载。
    """

    name = '中证指数行情'

    def __init__(self, latest_trade_day_fn: Callable[[], str]):
        self._latest_trade_day_fn = latest_trade_day_fn

    def fetch(self, index_id: str, index_name: str, index_tag: str) -> Optional[pd.DataFrame]:
        logger.info('CSI: Update PE index id(%s), name(%s)', index_id, index_name)
        end_date = self._latest_trade_day_fn().replace('-', '')
        new_df = ak.stock_zh_index_hist_csindex(
            symbol=index_id, start_date='20180101', end_date=end_date
        )
        if new_df.empty:
            return None
        new_df = new_df.astype({'日期': str})
        pe_df = new_df[new_df['滚动市盈率'].notna() & (new_df['滚动市盈率'] > 0)].copy()
        if pe_df.empty:
            return None
        pe_df['指数代码'] = index_id
        pe_df['指数名称'] = index_name
        pe_df['标签'] = index_tag
        pe_df['数据源'] = '中证指数行情'
        pe_df = pe_df.rename(columns={'滚动市盈率': '市盈率'})
        return pe_df[['日期', '指数代码', '指数名称', '标签', '市盈率', '数据源']].set_index('日期')
