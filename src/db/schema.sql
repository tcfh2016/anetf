-- anetf 数据库 schema
-- 历史上嵌在 pe.py / etf.py / migrate_csv_to_db.py 中的 DDL 统一收纳于此。

-- index_valuation：替代 db/ 下 305 个 CSV 的统一存储
-- PE 类与点位类合二为一：pe/point 均为可空列，由 data_type 区分
-- 复合主键 (index_id, date) 天然实现"同日不重、新日才追加"
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

-- index_source_preference：每个指数的优先数据源（由历史扫描生成）
-- update_db 启动时一次性加载到内存，按 preferred_source 只打第一源，失败再降级 fallback_source
CREATE TABLE IF NOT EXISTS index_source_preference (
    index_id         TEXT PRIMARY KEY,
    preferred_source TEXT NOT NULL,   -- '韭圈儿'/'中证指数'/'国证指数'/'中证指数行情'/'指数行情'
    fallback_source  TEXT,            -- 备选源，可空
    reason           TEXT,            -- 'max_pe_rows'/'only_source'/'manual'
    pe_rows          INTEGER,         -- 首选源历史 PE 行数（扫描时刻）
    updated_at       TEXT
);

-- etf：ETF→指数映射（与 pe.py 共用同一个 anetf.db）
CREATE TABLE IF NOT EXISTS etf (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    tag         TEXT,
    avgamount   REAL,
    index_name  TEXT,
    index_id    TEXT,
    updated_at  TEXT
);

-- watchlist：Web 关注列表（Web 一期新增）
-- alert_low/alert_high 为 PE 百分位预警阈值（0~1），一期仅页面可编辑保存，二期 cron 检查触发邮件
CREATE TABLE IF NOT EXISTS watchlist (
    code        TEXT PRIMARY KEY,
    note        TEXT,
    alert_low   REAL,
    alert_high  REAL,
    created_at  TEXT NOT NULL
);
