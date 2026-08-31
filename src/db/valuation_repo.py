# -*- coding:utf-8 -*-
"""指数估值历史的 Repository。

封装 index_valuation 表的读写，替代 pe.py 的 _load_index / store_pe / _to_db_records。
对外仍返回带中文列名的 DataFrame，便于上层 service 沿用原逻辑（阶段 3 再彻底模型化）。
"""

import logging

import numpy as np
import pandas as pd

from src.db.connection import Database

logger = logging.getLogger(__name__)


# DB 列名 ↔ 中文列名映射（与历史 CSV / pe.py 中间 DataFrame 一致）
DB_TO_CN = {
    'index_id':   '指数代码',
    'index_name': '指数名称',
    'tag':        '标签',
    'pe':         '市盈率',
    'point':      '点位',
    'data_type':  '数据类型',
    'source':     '数据源',
}

INSERT_SQL = (
    "INSERT OR IGNORE INTO index_valuation "
    "(index_id, date, index_name, tag, pe, point, data_type, source) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)


class ValuationRepository:
    def __init__(self, db: Database):
        self._db = db

    def load_index(self, index_id: str) -> pd.DataFrame:
        """读取某指数的全部历史估值（按日期升序）。

        返回以 date 为索引的 DataFrame，列名为中文（市盈率/点位/数据类型/数据源…），
        与旧 CSV 格式兼容，便于上层逻辑沿用。
        """
        sql = ("SELECT date, index_id, index_name, tag, pe, point, data_type, source "
               "FROM index_valuation WHERE index_id=? ORDER BY date")
        df = pd.read_sql_query(sql, self._db.connection, params=(index_id,))
        df = df.rename(columns=DB_TO_CN)
        return df.set_index('date')

    def _to_db_records(self, index_id: str, diff: pd.DataFrame):
        """把 update_* 产出的 DataFrame（PE 类或点位类）转为统一 DB schema 的元组列表。

        NaN 统一转 None，以便 SQLite 存为 NULL。
        """
        is_pe = '市盈率' in diff.columns
        rows = pd.DataFrame({
            'index_id':   index_id,
            'date':       diff.index.astype(str),
            'index_name': diff['指数名称'] if '指数名称' in diff.columns else None,
            'tag':        diff['标签'] if '标签' in diff.columns else None,
            'pe':         diff['市盈率'] if is_pe else np.nan,
            'point':      diff['点位'] if '点位' in diff.columns else np.nan,
            'data_type':  diff['数据类型'] if '数据类型' in diff.columns else ('PE' if is_pe else '点位'),
            'source':     diff['数据源'] if '数据源' in diff.columns else None,
        })
        cols = ['index_id', 'date', 'index_name', 'tag', 'pe', 'point', 'data_type', 'source']
        return [
            tuple(None if pd.isna(v) else v for v in row)
            for row in rows[cols].itertuples(index=False, name=None)
        ]

    def store(self, index_id: str, old_df: pd.DataFrame, new_df: pd.DataFrame,
              rewrite: bool = False) -> None:
        """将新估值写入数据库 index_valuation 表。

        - rewrite=False（默认）：只追加 old_df 最新日期之后的新行（INSERT OR IGNORE 防重复）
        - rewrite=True：先删该指数全部旧数据，再全量写入
        线程安全：写库段加 self._db.lock 串行化，保证并发 worker 共享连接安全。
        """
        try:
            if rewrite:
                diff = new_df
                self._db.execute(
                    "DELETE FROM index_valuation WHERE index_id=?", (index_id,))
            elif old_df.empty:
                diff = new_df
            else:
                # 数据无更新（最新日期相同）
                if str(old_df.index[-1]) == str(new_df.index[-1]):
                    return
                diff = new_df[new_df.index > old_df.index[-1]] if len(new_df) > 1 else new_df
                if diff.empty:
                    return

            logger.debug(diff)
            records = self._to_db_records(index_id, diff)
            if not records:
                return
            self._db.executemany(INSERT_SQL, records)
        except Exception as e:
            logger.error('Store pe for {} failed because of {}'.format(index_id, str(e)))
