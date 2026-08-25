# -*- coding:utf-8 -*-
"""
一次性迁移脚本：把 db/*.csv 的 305 个文件导入 anetf.db 的 index_valuation 表。
PE 类（6 列）与点位类（7 列）合二为一，统一 schema。

用法：python migrate_csv_to_db.py
- 只读 db/ 下的 CSV，不修改它们
- 重复运行安全：INSERT OR IGNORE 跳过已存在的 (index_id, date)
- 跑通后即可删除本脚本；迁移前建议备份 db/ 目录
"""

import os
import glob
import sqlite3
import logging
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

SCRIPT_PATH = os.path.dirname(os.path.realpath(__file__))
DB_FILE = os.path.join(SCRIPT_PATH, 'anetf.db')
DB_DIR = os.path.join(SCRIPT_PATH, 'db')

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS index_valuation (
    index_id   TEXT NOT NULL,
    date       TEXT NOT NULL,
    index_name TEXT,
    tag        TEXT,
    pe         REAL,
    point      REAL,
    data_type  TEXT NOT NULL,
    source     TEXT,
    PRIMARY KEY (index_id, date)
);
"""

CREATE_ETF_SQL = """
CREATE TABLE IF NOT EXISTS etf (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    tag         TEXT,
    avgamount   REAL,
    index_name  TEXT,
    index_id    TEXT,
    updated_at  TEXT
);
"""

INSERT_SQL = ("INSERT OR IGNORE INTO index_valuation "
              "(index_id, date, index_name, tag, pe, point, data_type, source) "
              "VALUES (?, ?, ?, ?, ?, ?, ?, ?)")


def main():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(CREATE_TABLE_SQL)
    conn.commit()

    files = sorted(glob.glob(os.path.join(DB_DIR, '*.csv')))
    logger.info('Found %d CSV files in %s', len(files), DB_DIR)

    total_rows = 0
    migrated = 0
    for path in files:
        index_id = os.path.splitext(os.path.basename(path))[0]
        df = pd.read_csv(path, dtype={'指数代码': 'object'})
        if df.empty:
            continue

        is_pe = '市盈率' in df.columns
        is_point = '点位' in df.columns
        if not (is_pe or is_point):
            logger.warning('Skip %s: no 市盈率/点位 column', index_id)
            continue

        # 统一到 DB schema
        rows = pd.DataFrame({
            'index_id':   index_id,
            'date':       df['日期'].astype(str),
            'index_name': df['指数名称'] if '指数名称' in df.columns else None,
            'tag':        df['标签'] if '标签' in df.columns else None,
            'pe':         df['市盈率'] if is_pe else np.nan,
            'point':      df['点位'] if is_point else np.nan,
            'data_type':  df['数据类型'] if '数据类型' in df.columns else ('PE' if is_pe else '点位'),
            'source':     df['数据源'] if '数据源' in df.columns else None,
        })
        cols = ['index_id', 'date', 'index_name', 'tag', 'pe', 'point', 'data_type', 'source']
        records = [
            tuple(None if pd.isna(v) else v for v in row)
            for row in rows[cols].itertuples(index=False, name=None)
        ]
        conn.executemany(INSERT_SQL, records)
        conn.commit()
        total_rows += len(records)
        migrated += 1

    # —— 迁移 ETF→指数映射（tmp/index.csv → etf 表）——
    index_csv = os.path.join(SCRIPT_PATH, 'tmp', 'index.csv')
    if os.path.exists(index_csv):
        from datetime import datetime
        etf_df = pd.read_csv(index_csv, dtype={'code': str})
        etf_df = etf_df[pd.notnull(etf_df['index_id'])]
        etf_rows = etf_df[['name', 'code', 'tag', 'avgamount', 'index_name', 'index_id']].copy()
        etf_rows['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(CREATE_ETF_SQL)
        conn.execute("DELETE FROM etf")
        etf_rows.to_sql('etf', conn, if_exists='append', index=False, method='multi')
        conn.commit()
        logger.info('Migrated ETF mapping: %d rows from tmp/index.csv -> etf table', len(etf_rows))
    else:
        logger.warning('tmp/index.csv not found; skipping etf table migration')

    # 校验
    db_total = conn.execute("SELECT COUNT(*) FROM index_valuation").fetchone()[0]
    db_indices = conn.execute("SELECT COUNT(DISTINCT index_id) FROM index_valuation").fetchone()[0]
    etf_total = conn.execute("SELECT COUNT(*) FROM etf").fetchone()[0] if conn.execute(
        "SELECT name FROM sqlite_master WHERE name='etf'").fetchone() else 0
    logger.info('Done. files=%d migrated=%d, csv_rows=%d, db_rows=%d, unique_indices=%d, etf_rows=%d',
                len(files), migrated, total_rows, db_total, db_indices, etf_total)
    conn.close()


if __name__ == '__main__':
    main()
