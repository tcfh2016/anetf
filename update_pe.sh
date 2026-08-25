#!/bin/bash

script_root=$(cd "$(dirname "$0")" && pwd)
echo "script_root: $script_root"
cd "$script_root"

# 如果存在虚拟环境则使用，否则使用系统 python
if [ -f ".venv/bin/python3" ]; then
    PYTHON=.venv/bin/python3
else
    PYTHON=python3
fi

echo "=== Step 1: (skipped) ETF index mapping now in anetf.db (etf table) ==="
echo "    Refresh weekly via a separate cron: $PYTHON etf.py"
# 旧流程每日重跑 etf.py 重新拉取+匹配（5 个 HTTP，含中证 2356 指数全量+韭圈儿 md5）；
# 现已入库，每日 pe.py 只读 DB，避免脆弱端点拖垮整个流程

echo "=== Step 2: Update PE valuation data ==="
$PYTHON pe.py
if [ $? -ne 0 ]; then
    echo "Error: pe.py failed"
    exit 1
fi

echo "=== Step 3: Send email report ==="
$PYTHON main.py
if [ $? -ne 0 ]; then
    echo "Error: main.py failed"
    exit 1
fi

echo "=== All done ==="
