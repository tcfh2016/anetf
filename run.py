# -*- coding:utf-8 -*-
"""跨平台编排入口（替代 update_pe.sh，Linux/Windows 通用）。

用法：
    python run.py                # 每日默认：更新估值 pe → 生成报告发邮件 main
    python run.py --etf          # 周维度：先刷新 ETF→指数映射，再 pe → main
    python run.py --pe-only      # 只更新估值，不发邮件
    python run.py --report-only  # 只生成报告并发邮件

任一步骤失败即短路退出（exit 1），不发空邮件。
ETF 映射已入库 anetf.db（etf 表），日常无需重跑 etf.py，周维度跑 --etf 即可。
"""

import argparse
import logging
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger('run')


def step_etf():
    """刷新 ETF→指数映射（周维度）。"""
    import etf
    etf.main()


def step_pe():
    """更新指数估值。"""
    import pe
    pe.main()


def step_report():
    """生成报告并发邮件。"""
    import main as report
    report.main()


def parse_args():
    parser = argparse.ArgumentParser(description='ETF 海选每日编排：估值更新 → 报告邮件')
    parser.add_argument('--etf', action='store_true',
                        help='先刷新 ETF→指数映射（周维度，一般配合周日 cron）')
    parser.add_argument('--pe-only', action='store_true',
                        help='只更新估值，不生成报告发邮件')
    parser.add_argument('--report-only', action='store_true',
                        help='只生成报告并发邮件（跳过估值更新）')
    return parser.parse_args()


def main():
    args = parse_args()

    steps = []
    if args.etf:
        steps.append(('Step 1: 刷新 ETF→指数映射', step_etf))
    if not args.report_only:
        steps.append(('Step: 更新指数估值', step_pe))
    if not args.pe_only:
        steps.append(('Step: 生成报告并发邮件', step_report))

    for name, step in steps:
        logger.info('=== %s ===', name)
        try:
            step()
        except Exception:
            logger.exception('%s failed, short-circuit exit', name)
            sys.exit(1)

    logger.info('=== All done ===')


if __name__ == '__main__':
    main()
