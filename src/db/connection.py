# -*- coding:utf-8 -*-
"""SQLite 连接管理：WAL 模式 + busy_timeout + 跨线程锁。

之前 pe.py / etf.py / migrate_csv_to_db.py 各自连库的样板代码收敛于此。
所有写操作通过 Database.execute/executemany 走统一锁，保证并发 worker 共享连接安全。
"""

import sqlite3
import threading
import logging

from src.config import DB_FILE, SCHEMA_FILE

logger = logging.getLogger(__name__)


class Database:
    """线程安全的 SQLite 连接封装。

    - check_same_thread=False：连接在主线程创建，写库可能由 worker 触发；
      靠 self._lock 串行化所有写操作，跨线程共享安全。
    - WAL：读写不互斥，提升并发场景下的吞吐。
    - busy_timeout=30000：锁冲突时自动等 30 秒。
    """

    def __init__(self, db_file: str = None):
        self._db_file = db_file or DB_FILE
        self._conn = sqlite3.connect(self._db_file, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self):
        """执行 schema.sql 建表（幂等）。"""
        with open(SCHEMA_FILE, 'r', encoding='utf-8') as f:
            sql = f.read()
        self._conn.executescript(sql)
        self._conn.commit()

    @property
    def connection(self) -> sqlite3.Connection:
        """原始连接（仅用于 pandas.read_sql_query 等只读场景）。

        写操作请走 execute/executemany 以保证锁语义。
        """
        return self._conn

    @property
    def lock(self) -> threading.Lock:
        """暴露锁，便于需要多语句原子事务的调用方手动加锁。"""
        return self._lock

    def execute(self, sql: str, params=()):
        """执行单条写语句并提交（带锁）。"""
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def executemany(self, sql: str, records):
        """批量执行写语句并提交（带锁）。"""
        with self._lock:
            cur = self._conn.executemany(sql, records)
            self._conn.commit()
            return cur

    def close(self):
        with self._lock:
            self._conn.close()
