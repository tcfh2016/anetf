# -*- coding:utf-8 -*-
"""ETF→指数映射的 Repository。

封装 etf 表的读写，替代 etf.py 末段直接写库的样板与 pe.py 的 _load_etf_mapping。
"""

import logging
import sqlite3
from datetime import datetime
from typing import Optional

import pandas as pd

from src.db.connection import Database

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

    def count(self) -> int:
        """ETF 总数（Web 仪表盘统计卡片用）。"""
        return pd.read_sql_query("SELECT COUNT(*) AS n FROM etf",
                                 self._db.connection)['n'].iloc[0]

    def get_by_code(self, code: str) -> Optional[dict]:
        """按 ETF 代码查单条映射；不存在返回 None。"""
        df = pd.read_sql_query(
            "SELECT name, code, tag, avgamount, index_name, index_id "
            "FROM etf WHERE code = ?", self._db.connection, params=(code,))
        return df.iloc[0].to_dict() if not df.empty else None

    def list_by_index(self, index_id_normalized: str) -> pd.DataFrame:
        """查询跟踪某指数的全部 ETF（按 avgamount 降序）。

        参数须为归一化后的净代码（split('.')[0].upper()），与 etf 表
        带后缀的 index_id 在 SQL 层做归一化比较。
        """
        sql = ("SELECT name, code, tag, avgamount, index_name, index_id FROM etf "
               "WHERE UPPER(SUBSTR(index_id, 1, "
               "CASE WHEN INSTR(index_id, '.') > 0 THEN INSTR(index_id, '.') - 1 "
               "ELSE LENGTH(index_id) END)) = ? ORDER BY avgamount DESC NULLS LAST")
        return pd.read_sql_query(sql, self._db.connection,
                                 params=(index_id_normalized,))

    def search(self, keyword: str = '', category: str = '', ) -> pd.DataFrame:
        """按关键词/分类搜索 ETF（Web 列表页用）。

        - keyword 对 code/name/index_name 模糊匹配（大小写不敏感、空值安全）
        - category 为分类键（crossborder/broad/...），空串表示全部分类
        - 分类判定与 report_service.classify 同源：tag 含「跨境」→crossborder、
          含「宽基」→broad、否则按首段标签查 FIRST_TAG_CATEGORY
        """
        con = self._db.connection
        first_tag_clause = (
            "CASE tag "
            "WHEN NULL THEN NULL "
            "ELSE (SELECT key FROM (SELECT 'crossborder' AS key WHERE instr(tag, '跨境') > 0 "
            "UNION ALL SELECT 'broad' WHERE instr(tag, '宽基') > 0 "
            "UNION ALL SELECT (CASE SUBSTR(tag, 1, INSTR(tag || '，', '，') - 1) "
            "  WHEN '行业' THEN 'sector' WHEN '主题' THEN 'theme' "
            "  WHEN '策略' THEN 'strategy' WHEN '商品' THEN 'commodity' "
            "  WHEN '债券' THEN 'bond' END) "
            "  WHERE instr(tag, '跨境') = 0 AND instr(tag, '宽基') = 0) "
            " WHERE key IS NOT NULL LIMIT 1) END")

        where, params = [], []
        if category:
            where.append(f"({first_tag_clause}) = ?")
            params.append(category)
        if keyword:
            kw = f"%{keyword.strip()}%"
            where.append("(code LIKE ? OR name LIKE ? OR IFNULL(index_name, '') LIKE ?)")
            params.extend([kw, kw, kw])

        sql = ("SELECT name, code, tag, avgamount, index_name, index_id FROM etf"
               + (" WHERE " + " AND ".join(where) if where else "")
               + " ORDER BY avgamount DESC NULLS LAST")
        try:
            return pd.read_sql_query(sql, con, params=params)
        except sqlite3.OperationalError:
            logger.warning("etf table not found; search returns empty")
            return pd.DataFrame(columns=ETF_COLUMNS)
