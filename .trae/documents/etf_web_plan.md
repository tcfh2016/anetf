# ETF 估值查询 Web 版 实现方案（一期）

## 一、仓库调研结论

### 现有数据家底（anetf.db，SQLite + WAL）
- `etf` 表：**832 只 ETF**，字段 code/name/tag（多级中文标签，逗号分隔）/avgamount（日均成交额）/index_name/index_id/updated_at。
- `index_valuation` 表：**75 万行、306 个指数**，字段 index_id/date/pe/point/data_type/source/tag，按 (index_id, date) 主键 UPSERT。
- `index_source_preference` 表：288 行数据源偏好（Web 不直接用）。
- 数据由 cron 每日增量维护（`run.py` → `src.pe`），**Web 端必须纯读库、严禁现场调 akshare**（报告阶段现场回退网络曾致 90s+ 的教训，Web 场景更敏感）。

### 可复用的现有逻辑
- [report_service.py](file:///home/ubuntu/anetf/src/services/report_service.py)：`classify(tag)` 分类、`calc_percentile()` 历史百分位、`calc_price_percentile_pair()` 近5年/总历史双口径行情百分位、PE 类/点位类判定规则（「历史是否有 PE」、当前值取 `dropna().iloc[-1]`）。
- [html_renderer.py](file:///home/ubuntu/anetf/src/renderers/html_renderer.py)：`_eva_status` 着色规则（百分位<10% 绿 / >90% 红，PE<15 绿 / PE>50 红）。
- [report.html](file:///home/ubuntu/anetf/src/renderers/templates/report.html)：表格配色（Brown 表头、lightgreen/tomato 高低估）可沿用到 Web 样式。
- [constants.py](file:///home/ubuntu/anetf/src/constants.py)：`CATEGORIES` 七大类、`UNSUPPORTED_INDEX_IDS` 黑名单。
- [connection.py](file:///home/ubuntu/anetf/src/db/connection.py)：`Database` 启动时执行 `schema.sql`（幂等）——**新表只需加到 schema.sql，老库自动建表，无需迁移脚本**。
- [models.py](file:///home/ubuntu/anetf/src/models.py)：`ReportRow`/`CategoryReport` dataclass 已预留「未来 API 层序列化载体」。

### 必须遵守的已知坑（项目 memory 记录）
1. **指数代码归一化**：etf 表海外指数带后缀（`h30269.CSI`/`NDX.GI`/`SP500`），index_valuation 存净代码且大写。两表关联前必须 `index_id.split('.')[0].upper()`，否则误判「无数据」。
2. 模糊搜索用 `str.contains(kw, case=False, na=False)`；数值缺失显示「-」，**不得 dropna 丢整行**。
3. 百分位最小样本：PE 20 行、点位 20 行（`MIN_PE_ROWS`/`MIN_POINT_ROWS`），不足显示「-」。
4. 数据库文件只读共享：WAL 模式读写不互斥，Web 读不阻塞 cron 写。

## 二、一期范围（覆盖用户提出的全部 5 个功能 + 2 个白送功能）

| # | 功能 | 落地页面 |
|---|---|---|
| 1 | ETF 数量查询 | 仪表盘统计卡片 + ETF 列表 |
| 2 | ETF→对应指数 | ETF 列表列 + 指数详情页「跟踪该指数的 ETF」 |
| 3 | 指数估值和走势 | 指数详情页：PE 估值通道图 + 点位走势图（Chart.js） |
| 4 | ETF 推荐 | 推荐榜（规则型：低百分位 + 流动性过滤，展示推荐理由） |
| 5 | 关注列表 | watchlist 表 + 关注页增删/备注/阈值 |
| + | 搜索 | 代码/名称/指数名模糊搜索（ETF 维度） |
| + | 板块估值热力图 | 仪表盘按七大分类聚合平均百分位，格子着色 |

**二期不做（方案预留接口）**：预警邮件（挂 run.py 每日流程复用邮件通道）、回撤分析、同指数 ETF 规模/费率选基、报告在线归档、多指数对比。

## 三、文件与模块

### 新增
- `src/web/__init__.py`
- `src/web/__main__.py`：入口，支持 `python -m src.web`（host 127.0.0.1、port 8000，可 config.ini 覆盖）。
- `src/web/app.py`：Flask 应用工厂 + 全部路由（服务端渲染 Jinja2 + 少量 JSON API）。
- `src/web/service.py`：`WebSnapshotService`——
  - `build_snapshot()`：一次性遍历 306 个指数，产出每个指数的当前 PE/点位、PE 百分位、行情百分位（近5年/总历史）、数据行数、分类、代表 ETF；**按库内最新交易日 MAX(date) 做缓存 key**（数据不变则毫秒返回，数据更新后自动重算）。
  - `recommend()`：推荐榜（规则见下）。
  - `heatmap()`：七大类平均百分位聚合。
  - `search_etfs(keyword, category)`：ETF 搜索。
  - `index_detail(index_id)`：单指数 PE/点位序列 + 分位线 + 跟踪 ETF 列表。
- `src/db/watchlist_repo.py`：`WatchlistRepository`（add/remove/list/update）。
- `src/web/templates/base.html`：导航栏 + 样式骨架（沿用邮件配色）。
- `src/web/templates/dashboard.html`：统计卡片 + 热力图 + 低估推荐榜。
- `src/web/templates/etfs.html`：ETF 列表（搜索框、分类筛选、分页、着色、链接详情页）。
- `src/web/templates/index_detail.html`：估值卡片 + PE 通道图 + 点位图（Chart.js CDN）+ 跟踪 ETF 表 + 加关注按钮。
- `src/web/templates/watchlist.html`：关注列表（阈值/备注编辑、删除、当前状态着色）。
- `src/web/static/style.css`、`src/web/static/charts.js`：少量静态资源。

### 修改
- [src/db/schema.sql](file:///home/ubuntu/anetf/src/db/schema.sql)：追加 watchlist 建表（`CREATE TABLE IF NOT EXISTS`，老库下次连接自动创建）。
- [src/db/etf_repo.py](file:///home/ubuntu/anetf/src/db/etf_repo.py)：加 `search(keyword, category)`、`get_by_code(code)`、`list_by_index(index_id)`（同指数全部 ETF 按 avgamount 降序）。
- [src/db/valuation_repo.py](file:///home/ubuntu/anetf/src/db/valuation_repo.py)：加 `latest_date()`、`load_series(index_id, col)`（单指数单列序列，详情页用）。
- [src/services/report_service.py](file:///home/ubuntu/anetf/src/services/report_service.py)：**小重构（行为不变）**——把 generate_report 循环体中「单指数估值计算」抽成模块级函数 `compute_index_stats(etf_df) -> dict`（返回当前值/类型/PE百分位/行情双口径），`generate_report()` 与 `WebSnapshotService` 共同复用，保证邮件报告与 Web 口径永远一致。
- [run.py](file:///home/ubuntu/anetf/run.py)：加 `--web` 参数启动 Web 服务（与现有步骤互斥，不参与 cron 链）。
- [requirements.txt](file:///home/ubuntu/anetf/requirements.txt)：加 `flask`。

### 不修改
- `src/pe.py`、数据源层、邮件通知层：Web 不触碰数据采集链路。

## 四、数据库新增表

```sql
CREATE TABLE IF NOT EXISTS watchlist (
    code        TEXT PRIMARY KEY,          -- ETF 代码
    note        TEXT,                      -- 备注
    alert_low   REAL,                      -- 预警：PE百分位低于此值（如 0.2），二期用
    alert_high  REAL,                      -- 预警：高于此值（如 0.8），二期用
    created_at  TEXT NOT NULL
);
```
一期 alert_low/alert_high 只在页面上可编辑保存；二期 cron 检查触发邮件。

## 五、页面与接口设计

### 页面（服务端渲染，Jinja2）
1. `GET /` 仪表盘：
   - 卡片：ETF 总数、指数总数、数据最新日期、低估指数数（PE百分位<20%）。
   - 热力图：七大分类（跨境/宽基/行业/主题/策略/商品/债券）格子，背景色按该类指数平均百分位绿→红渐变。
   - 推荐榜：Top 20 低估且流动性好的 ETF/指数（见推荐规则）。
2. `GET /etfs?q=&category=&page=`：ETF 列表。
   - 搜索框（代码/名称/指数名 contains，回车或按钮触发）；分类下拉；分页每页 50。
   - 列：基金名称/代码/标签/指数名称/指数代码/指标类型/当前值/历史百分位/行情百分位/操作（加关注⭐）。
   - 百分位着色复用 eva_status 规则；缺失显示「-」；指数名链接到详情页。
3. `GET /index/<index_id>`：指数详情。
   - 顶部卡片：指数名/代码/分类/最新日期/当前 PE/PE 百分位/行情百分位双口径。
   - **PE 估值通道图**：PE 日线 + 10%/20%/50%/80% 历史分位虚线 + 当前点高亮（Chart.js line chart）。
   - **点位走势图**：point 日线。
   - 跟踪该指数的全部 ETF（按 avgamount 降序，高亮流动性最好的一只）。
   - 数据不足（<20 行）显示「数据不足」占位，不画图。
4. `GET /watchlist`：关注列表（同列表列 + 备注/阈值内联编辑 + 删除）。

### JSON API（供页面 JS fetch）
- `GET /api/overview`：仪表盘统计 + 热力图数据。
- `GET /api/etfs?q=&category=&page=`：ETF 列表（搜索走后端，避免 832 行全量渲染）。
- `GET /api/index/<index_id>`：详情页全部数据（含 PE/点位序列、分位线、跟踪 ETF）。
- `GET /api/recommend`：推荐榜。
- `POST /api/watchlist`（form/json：code/note/alert_low/alert_high）、`DELETE /api/watchlist/<code>`。
- 所有接口异常返回 `{"error": "..."}` + 合适状态码，**不静默返回空列表**。

### 推荐规则（规则型、可解释）
- 候选：有估值数据的指数（PE 类看 PE 百分位，点位类看行情百分位），排除 UNSUPPORTED 黑名单、样本不足者。
- 低估条件：主百分位 < 20%（近5年口径优先，两口径都展示）。
- 流动性过滤：跟踪 ETF 的 avgamount 取该指数对应 ETF 中最大值，低于全市场中位数的降权/剔除。
- 排序：百分位升序；每行展示推荐理由，如「PE 百分位 12.3%（近5年 8.1%），日均成交 2.3 亿」。
- 阈值集中在 service 顶部定义为常量，方便调整。

## 六、实施步骤（依赖顺序）

1. **依赖与骨架**：requirements 加 flask；建 `src/web/` 包与 `python -m src.web` 入口；Flask hello world 跑通。
2. **schema + repo**：schema.sql 加 watchlist 表；etf_repo/valuation_repo 加查询方法；watchlist_repo 实现。
3. **重构 report_service**：抽出 `compute_index_stats()`，跑 `python -m src.main --report-only` 对比重构前后报告行数与数值（用邮件 HTML 或落盘对比），确认零变化。
4. **WebSnapshotService**：快照构建（复用 compute_index_stats + 归一化 helper）、日期缓存、推荐、热力图、搜索、详情。
5. **路由 + 模板**：base → 仪表盘 → ETF 列表 → 指数详情（图表）→ 关注页；JSON API 同步。
6. **run.py --web** 接线。
7. **端到端验证**（见下）。

## 七、依赖与考虑

- 新增依赖仅 `flask`（Jinja2 已在 requirements；Flask 自带 Jinja2，模板引擎与现有 HtmlRenderer 一致）。
- 图表用 **Chart.js CDN**（jsdelivr）；若部署环境无外网，降级方案为把 chart.umd.min.js 下载到 `src/web/static/` 本地引用（一期先 CDN，模板里留本地切换注释）。
- 部署：个人单用户，Flask 内置服务器 + 绑定 127.0.0.1 足够；如需外网访问，二期换 `waitress`（纯 Python、Windows/Linux 通用），一期不加。
- 性能：快照首算约 3s（与报告生成 2.7s 同量级），按 MAX(date) 缓存后毫秒级；详情页单指数查询仅数千行，无压力。
- config.ini 增加可选 `[Web] host/port` 段，缺省 127.0.0.1:8000。

## 八、验证

1. `pip install flask` 后 `python -m src.web` 启动，浏览器逐页检查：
   - 仪表盘数字与 SQL 直查一致（ETF 832、指数 306、最新日期 = 库内 MAX(date)）。
   - 搜索：代码（513100）、名称（纳指）、指数名（沪深300）均能命中；空结果显示提示而非空白；特殊字符不报错。
   - 详情页：PE 通道图分位线与当前点位置和列表百分位一致；点位图正常；无数据指数（如 FCHI）显示「数据不足」不 500。
   - 关注：添加→刷新仍在→改备注/阈值→删除→重启服务持久化（落库）。
   - 推荐榜：每行百分位均 <20%，理由与数值一致。
2. 用本地 http 服务 + browser_use 实测页面渲染（memory 经验：file:// 被浏览器工具拒绝，必须起 http 服务）。
3. **回归**：重构后 `python run.py --report-only` 生成的邮件报告与重构前对比（分类行数、每行数值一致）。
4. cron 并发：Web 运行中手动跑一次 `python -m src.pe` 不报错（WAL 读写不互斥）。

## 九、风险与应对

- **风险 1：重构 report_service 改变邮件报告数值** → 抽取时逐行搬运不写新逻辑；重构前后落盘 HTML/数据对比，不一致不合并。
- **风险 2：指数代码后缀导致关联不上** → service 层统一 `normalize_index_id()`（split('.')[0].upper()），所有跨表查询必经此函数；用带后缀的 h30269.CSI/NDX.GI 做测试用例。
- **风险 3：快照全量计算慢** → 按数据日期缓存；cron 更新数据后下次访问自动重算，无需手动重启。
- **风险 4：Chart.js CDN 加载失败** → 图表区域提示「图表加载失败」，下方保留数据表格兜底；预留本地静态文件切换。
- **风险 5：Flask 开发服务器暴露风险** → 默认绑 127.0.0.1；不实现账号体系（个人工具）；watchlist 无敏感数据。
