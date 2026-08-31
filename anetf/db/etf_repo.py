# -*- coding:utf-8 -*-
"""ETF→指数映射的 Repository。

封装 etf 表的读写，替代 etf.py 末段直接写库的样板与 pe.py 的 _load_etf_mapping。
"""

import logging
import sqlite3
from datetime import datetime

import pandas as pd

from anetf.db.connection import Database

logger = logging.getLogger(__name__)

# etf 表列顺序约定（与历史 CSV usecols 一致）
ETF_COLUMNS = ['name', 'code', 'tag', 'avgamount', 'index_name', 'index_id']


class EtfRepository:
    def __init__(self, db: Database):
        self._db = db

    def load_mapping(self) -> pd.DataFrame:
        """读取 ETF→指数映射。

        表未创建时返回带列名的空 DataFrame（行为与原 _load_etf_mapping 一致），
        避免阻断每日流程。
        """
        sql = "SELECT name, code, tag, avgamount, index_name, index_id FROM etf"
        try:
            return pd.read_sql_query(sql, self._db.connection)
        except sqlite3.OperationalError:
            logger.warning("etf table not found; run `python etf.py` to refresh the mapping")
            return pd.DataFrame(columns=ETF_COLUMNS)

    def replace_all(self, df: pd.DataFrame) -> int:
        """全量刷新 etf 表（DELETE + INSERT），返回写入行数。

        - 输入 df 至少包含 ETF_COLUMNS 这些列
        - updated_at 自动填入当前时间
        - DELETE 与 INSERT 在同一锁内串行执行，保证原子性
        """
        rows = df[ETF_COLUMNS].copy()
        rows['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn = self._db.connection
        with self._db.lock:
            conn.execute("DELETE FROM etf")
            rows.to_sql('etf', conn, if_exists='append', index=False, method='multi')
            conn.commit()
        logger.info('ETF mapping refreshed: {} rows -> etf table'.format(len(rows)))
        return len(rows)
