# -*- coding:utf-8 -*-
"""Web 关注列表 Repository。

封装 watchlist 表（schema.sql 自动建表，无需迁移脚本）。
一期提供增删查改；alert_low/alert_high 阈值二期 cron 预警用。
"""

import logging
import sqlite3
from datetime import datetime
from typing import List, Optional

import pandas as pd

from src.db.connection import Database

logger = logging.getLogger(__name__)


class WatchlistRepository:
    def __init__(self, db: Database):
        self._db = db

    def list_all(self) -> List[dict]:
        """全部关注项，按加入时间倒序。"""
        sql = ("SELECT code, note, alert_low, alert_high, created_at "
               "FROM watchlist ORDER BY created_at DESC")
        try:
            df = pd_read(sql, self._db.connection)
        except sqlite3.OperationalError:
            return []
        return df.to_dict('records')

    def get(self, code: str) -> Optional[dict]:
        sql = ("SELECT code, note, alert_low, alert_high, created_at "
               "FROM watchlist WHERE code=?")
        try:
            df = pd.read_sql_query(sql, self._db.connection, params=(code,))
        except sqlite3.OperationalError:
            return None
        return df.iloc[0].to_dict() if not df.empty else None

    def add(self, code: str, note: str = '', alert_low: float = None,
            alert_high: float = None) -> bool:
        """加入关注（已存在则更新备注/阈值），返回是否成功。"""
        try:
            self._db.execute(
                "INSERT INTO watchlist (code, note, alert_low, alert_high, created_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(code) DO UPDATE SET "
                "note=excluded.note, alert_low=excluded.alert_low, "
                "alert_high=excluded.alert_high",
                (code, note or None, alert_low, alert_high,
                 datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            return True
        except sqlite3.Error as e:
            logger.error('watchlist add %s failed: %s', code, e)
            return False

    def update(self, code: str, fields: dict) -> bool:
        """更新指定字段（fields 键 ∈ {note, alert_low, alert_high}）。

        传入的键一律写入（值为 None 写 NULL，即清除）；
        未传入的键不改动。返回是否成功。
        """
        allowed = {'note', 'alert_low', 'alert_high'}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return True
        try:
            self._db.execute(
                "UPDATE watchlist SET {} WHERE code=?".format(
                    ', '.join(f'{k}=?' for k in sets)),
                tuple(sets.values()) + (code,))
            return True
        except sqlite3.Error as e:
            logger.error('watchlist update %s failed: %s', code, e)
            return False

    def remove(self, code: str) -> bool:
        try:
            self._db.execute("DELETE FROM watchlist WHERE code=?", (code,))
            return True
        except sqlite3.Error as e:
            logger.error('watchlist remove %s failed: %s', code, e)
            return False


def pd_read(sql: str, conn, params=()):
    """局部 import pandas，避免模块加载顺序问题。"""
    import pandas as pd
    return pd.read_sql_query(sql, conn, params=params)
