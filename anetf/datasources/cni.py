# -*- coding:utf-8 -*-
"""国证指数数据源。

拆自 pe.py 的 update_gz：从 ak.index_all_cni() 的"PE滚动"列读取最新 PE。
只返回单行快照（最新交易日的 PE），不分历史序列。

依赖 gz_df（国证指数全量列表）与 latest_trade_day，通过 callable 注入实现懒加载。
"""

import logging
from typing import Optional, Callable

import pandas as pd

from anetf.datasources.base import DataSource

logger = logging.getLogger(__name__)


class CniSource(DataSource):
    """国证指数 PE 快照数据源（仅当日值，无历史序列）。"""

    name = '国证指数'

    def __init__(self,
                 gz_df_fn: Callable[[], pd.DataFrame],
                 latest_trade_day_fn: Callable[[], str]):
        self._gz_df_fn = gz_df_fn
        self._latest_trade_day_fn = latest_trade_day_fn

    def fetch(self, index_id: str, index_name: str, index_tag: str) -> Optional[pd.DataFrame]:
        logger.info('GZ: Update PE index id(%s), name(%s)', index_id, index_name)
        gz_df = self._gz_df_fn()
        if index_id not in gz_df.index:
            logger.warning('GZ: Update %s failed, index not found in gz_df.', index_id)
            return None
        pe_val = gz_df.loc[index_id, 'PE滚动']
        if pd.isna(pe_val):
            logger.warning('GZ: Update %s skipped, PE is NaN in gz_df.', index_id)
            return None
        latest = self._latest_trade_day_fn()
        record = [latest, index_id, index_name, index_tag, pe_val, '国证指数']
        new_df = pd.DataFrame([record], columns=['日期', '指数代码', '指数名称', '标签', '市盈率', '数据源'])
        return new_df.set_index('日期')
