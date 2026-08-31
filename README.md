# anetf

每日 ETF 估值海选邮件：拉取全市场 ETF，反查跟踪指数，按市盈率/点位分位生成 HTML 报告并发邮件。

## 项目结构

```
anetf/                          # 工程根（顶层唯一入口 run.py）
├── src/                        # 主包（分层架构）
│   ├── etf.py                  # ETF→指数映射刷新（周维度）
│   ├── pe.py                   # 指数估值更新（每日）
│   ├── main.py                 # 生成报告并发邮件（每日）
│   ├── config.py               # 路径 / 阈值 / HTTP 超时 / 邮件配置
│   ├── constants.py            # 指数映射表、标签、类目等业务常量
│   ├── models.py               # ReportRow / CategoryReport 数据模型
│   ├── db/
│   │   ├── schema.sql          # 三张表 DDL：index_valuation / index_source_preference / etf
│   │   ├── connection.py       # SQLite 连接（WAL + busy_timeout）
│   │   ├── etf_repo.py         # ETF→指数映射读写
│   │   └── valuation_repo.py   # 指数估值历史读写
│   ├── datasources/            # 外部数据源适配（韭圈儿/中证/国证/Sina）
│   ├── services/
│   │   └── report_service.py   # 报告编排：分类 + 分位计算
│   ├── renderers/
│   │   ├── html_renderer.py    # Jinja2 渲染 HTML
│   │   └── templates/report.html
│   └── notifiers/
│       └── email_notifier.py   # SMTP 发送
├── run.py                      # 跨平台编排：组合执行 etf/pe/main（含错误短路）
├── config.ini                  # 邮件服务器配置（在 .gitignore 中）
├── anetf.db                    # SQLite 数据库（在 .gitignore 中）
└── requirements.txt
```

## 数据存储

所有数据统一落在 `anetf.db`（SQLite，WAL 模式），schema 见 [schema.sql](file:///home/ubuntu/anetf/src/db/schema.sql)：

- `etf`：ETF→指数映射（code、name、tag、avgamount、index_id）
- `index_valuation`：指数估值历史，复合主键 `(index_id, date)` 天然防重，`pe`/`point` 均为可空列，由 `data_type` 区分
- `index_source_preference`：每个指数的优先数据源（韭圈儿/中证指数/国证指数/中证指数行情/指数行情）

历史遗留的 `db/*.csv` 与 `tmp/index.csv` 已废弃，迁移到 `anetf.db` 后即停用。

## 业务模块（src/ 内）

### `src/etf.py` —— 刷新 ETF 列表与指数映射

从 ETF 组合宝拉取全市场 ETF，按日均交易额过滤后，对每个 ETF 反查跟踪指数（先精确匹配、再模糊双向子串匹配，查表顺序：韭圈儿 → 国证 → 聚宽 → 中证全量 2356 只）。结果全量替换 `etf` 表。

- 频率：每周一次（数据源端点较脆弱，不必每日重跑）
- 依赖：`akshare`（中证/国证/聚宽指数列表）、韭圈儿、ETF 组合宝

### `src/pe.py` —— 更新指数估值

[pe.py](file:///home/ubuntu/anetf/src/pe.py) 的 `ValuationService.update_db()`：

1. 从 `etf` 表读 ETF→指数映射，按 `index_id` 去重（约 800 ETF → 270 唯一指数）
2. 对每个指数判断是否需要更新（本地缓存日期 ≥ 最新交易日且有效数据则跳过）
3. 用线程池（默认 12 线程）并发拉取，按 `index_source_preference` 表路由首选源，失败降级备选源
4. 所有 PE 源失败时：有 PE 历史的指数留空待下次重试（不写点位降级行，避免锁死 PE 恢复）；本就无 PE 的指数（商品/债券/海外）用点位兜底

数据源降级链（无偏好表时）：韭圈儿 → 中证指数 → 国证指数 → 中证指数行情。

### `src/main.py` —— 生成报告并发邮件

[main.py](file:///home/ubuntu/anetf/src/main.py) 的阶段 3 编排链：

```
ReportService.generate_report()  →  List[CategoryReport]
HtmlRenderer.render()           →  HTML 字符串
EmailNotifier.send()            →  SMTP 发送
```

不再依赖任何 CSV 中间产物，`pe.py` 与 `main.py` 之间通过 `anetf.db` 解耦。

### `run.py` —— 跨平台编排入口（顶层唯一入口）

[run.py](file:///home/ubuntu/anetf/run.py) 用纯 Python 编排 src/ 内的业务模块（Linux/Windows 通用，已替代原 `update_pe.sh`），任一步骤失败即短路退出，不发空邮件：

```
python run.py                # 每日默认：更新估值 → 生成报告发邮件
python run.py --etf          # 周维度合并跑：先刷新映射，再更新估值 + 发邮件
python run.py --etf-only     # 只刷新 ETF→指数映射（周日 cron 用）
python run.py --pe-only      # 只更新估值
python run.py --report-only  # 只生成报告并发邮件
```

## 执行方式

### 手动运行

```bash
cd /home/ubuntu/anetf
.venv/bin/python run.py             # 每日：更新估值 + 发邮件
.venv/bin/python run.py --etf-only  # 周维度：只刷新映射
# 或单步执行（模块方式，必须在工程根目录跑）：
.venv/bin/python -m src.pe          # 更新估值
.venv/bin/python -m src.main        # 发送邮件
```

Windows（PowerShell）：

```powershell
.venv\Scripts\python.exe run.py
```

### 定时任务

Linux cron：

```
# 每周日凌晨 2 点刷新 ETF 映射
0 2 * * 0  cd /home/ubuntu/anetf && .venv/bin/python run.py --etf-only >> tmp/etf_refresh.log 2>&1

# 每日上午 10 点更新估值并发邮件（日志按天滚动）
0 10 * * *  cd /home/ubuntu/anetf && .venv/bin/python run.py >> tmp/run_$(date +\%Y\%m\%d).log 2>&1
```

Windows 任务计划程序（taskschd.msc）：

```
程序或脚本：<项目路径>\.venv\Scripts\pythonw.exe
参数：      run.py
起始于：    <项目路径>
```

> 用 `pythonw.exe` 不弹控制台窗口；如需日志，改用 `python.exe` 并在批处理中重定向输出。

## 配置

`config.ini`（已加入 `.gitignore`，不入库）：

```ini
[MailServer]
server = smtp.163.com
port = 465
authcode = <SMTP 授权码>

[MailList]
from = <发件人邮箱>
to = <收件人邮箱列表，逗号分隔>
```

## 依赖

`requirements.txt`：`requests`、`pandas`、`akshare`、`jinja2`

建议使用虚拟环境：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 参考

- [ETF基金实时行情-东财](https://akshare.akfamily.xyz/data/fund/fund_public.html#etf)
- [基金持仓](https://akshare.akfamily.xyz/data/fund/fund_public.html#id40)
