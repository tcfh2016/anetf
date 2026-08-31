# -*- coding:utf-8 -*-
"""HTML 渲染器：把结构化报告渲染为邮件 HTML。

阶段 3：取代 mail/mail.py 里手写字符串拼接的 construct_ETF_list/_head/_tail，
用 Jinja2 模板 + eva_status 过滤器统一渲染。
"""

import logging
from typing import List

from jinja2 import Environment, FileSystemLoader, select_autoescape

from anetf.config import TEMPLATES_DIR
from anetf.models import CategoryReport, ReportRow

logger = logging.getLogger(__name__)


class HtmlRenderer:
    """渲染 List[CategoryReport] 为 HTML 字符串。"""

    def __init__(self, template_dir: str = None):
        env = Environment(
            loader=FileSystemLoader(template_dir or TEMPLATES_DIR),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        env.filters['eva_status'] = self._eva_status
        self._template = env.get_template('report.html')

    def render(self, reports: List[CategoryReport]) -> str:
        return self._template.render(reports=reports)

    @staticmethod
    def _eva_status(row: ReportRow) -> str:
        """估值状态着色：low（绿）/ high（红）/ normal。

        规则与原 mail.py 的 get_eva_status 一致：
        - 市盈率阈值只对 PE 类型有意义（且需为正值），指数点位类只看百分位
        - 百分位 < 10% 或 PE<15 → low；百分位 > 90% 或 PE>50 → high
        """
        if row.percentile is None:
            return 'normal'

        if row.value_type == 'PE' and row.value is not None and 0 < row.value < 15:
            return 'low'
        if row.percentile < 0.10:
            return 'low'

        if row.value_type == 'PE' and row.value is not None and row.value > 50:
            return 'high'
        if row.percentile > 0.90:
            return 'high'

        return 'normal'
