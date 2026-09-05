# -*- coding:utf-8 -*-
"""指数估值历史的 Repository。

封装 index_valuation 表的读写，替代 pe.py 的 _load_index / store_pe / _to_db_records。
对外仍返回带中文列名的 DataFrame，便于上层 service 沿用原逻辑（阶段 3 再彻底模型化）。
"""

import logging
from typing import Optional

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

# UPSERT：同一 (index_id, date) 已存在时用 COALESCE 互补空缺列，
# 使 PE 源与点位源写同一日期时互不覆盖（pe/point 各补各的空缺）。
# data_type/source 冲突时保留先入者（读取侧不依赖这两列）。
INSERT_SQL = (
    "INSERT INTO index_valuation "
    "(index_id, date, index_name, tag, pe, point, data_type, source) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(index_id, date) DO UPDATE SET "
    "pe = COALESCE(excluded.pe, index_valuation.pe), "
    "point = COALESCE(excluded.point, index_valuation.point), "
    "index_name = COALESCE(excluded.index_name, index_valuation.index_name), "
    "tag = COALESCE(excluded.tag, index_valuation.tag)"
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

    def latest_date(self) -> Optional[str]:
        """库内最新交易日（Web 快照缓存 key）；空库返回 None。"""
        row = self._db.connection.execute(
            "SELECT MAX(date) FROM index_valuation").fetchone()
        return row[0] if row and row[0] else None

    def count_indices(self) -> int:
        """库内不重复指数个数（Web 仪表盘统计卡片用）。"""
        row = self._db.connection.execute(
            "SELECT COUNT(DISTINCT index_id) FROM index_valuation").fetchone()
        return row[0] if row else 0

    def list_indices(self) -> pd.DataFrame:
        """库内全部指数的概况（指数/名称/标签/最新日期/PE行数/点位行数）。

        Web 仪表盘用：一次查询替代逐指数 load_index，只取概况不取序列。
        """
        sql = ("SELECT index_id, "
               "MAX(index_name) AS index_name, "
               "MAX(tag) AS tag, "
               "MAX(date) AS latest_date, "
               "SUM(CASE WHEN pe IS NOT NULL THEN 1 ELSE 0 END) AS pe_rows, "
               "SUM(CASE WHEN point IS NOT NULL THEN 1 ELSE 0 END) AS point_rows "
               "FROM index_valuation GROUP BY index_id ORDER BY index_id")
        return pd.read_sql_query(sql, self._db.connection)

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

        - rewrite=False（默认）：按数据列（市盈率/点位）各自的最新已存日期做增量追加，
          UPSERT 互补空缺列——PE 源与点位源可分别写入同一日期而不互相覆盖；
          也能补回"另一列先写入导致本列某日缺失"的空洞。
        - rewrite=True：先删该指数全部旧数据，再全量写入
        线程安全：写库段加 self._db.lock 串行化，保证并发 worker 共享连接安全。
        """
        try:
            is_pe = '市盈率' in new_df.columns
            if rewrite:
                diff = new_df
                self._db.execute(
                    "DELETE FROM index_valuation WHERE index_id=?", (index_id,))
            elif old_df.empty:
                diff = new_df
            else:
                # 按本次写入的列取该列在库中的最新日期（另一列的行不阻塞本列补写）
                col = '市盈率' if is_pe else '点位'
                have = old_df[col].dropna() if col in old_df.columns else pd.Series(dtype=float)
                if len(have) == 0:
                    diff = new_df
                else:
                    last_have = have.index[-1]
                    diff = new_df[new_df.index > last_have] if len(new_df) > 1 else new_df
                    if diff.empty:
                        return

            logger.debug(diff)
            records = self._to_db_records(index_id, diff)
            if not records:
                return
            self._db.executemany(INSERT_SQL, records)
        except Exception as e:
            logger.error('Store pe for {} failed because of {}'.format(index_id, str(e)))
