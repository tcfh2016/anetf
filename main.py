# -*- coding:utf-8 -*-
"""每日 ETF 海选邮件编排入口。

阶段 3 编排链：
  ReportService.generate_report()  → 结构化 List[CategoryReport]
  HtmlRenderer.render()            → HTML 字符串
  EmailNotifier.send()              → 发送邮件

不再依赖 mail/*.csv，pe.py ↔ mail.py 的 CSV 隐式契约已废除。
"""

import logging
import datetime as dt

from src.config import load_mail_config
from src.db.connection import Database
from src.services.report_service import ReportService
from src.renderers.html_renderer import HtmlRenderer
from src.notifiers.email_notifier import EmailNotifier

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger(__name__)


def main():
    mail_config = load_mail_config()
    logger.info('Mail server configured: %s', bool(mail_config.server))

    db = Database()
    try:
        reports = ReportService(db).generate_report()
        html = HtmlRenderer().render(reports)
        subject = 'ETF海选列表(new) - ' + str(dt.date.today() - dt.timedelta(days=1))
        EmailNotifier(mail_config).send(html, subject)
    finally:
        db.close()


if __name__ == '__main__':
    main()
