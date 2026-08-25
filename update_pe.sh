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

echo "=== Step 1: Update ETF index mapping ==="
$PYTHON etf.py
if [ $? -ne 0 ]; then
    echo "Error: etf.py failed"
    exit 1
fi

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
