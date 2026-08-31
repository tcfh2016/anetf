# -*- coding:utf-8 -*-
"""邮件通知器：把渲染好的 HTML 发送出去。

阶段 3：取代 mail/mail.py 的 send_email，只负责 SMTP 收发，
不再关心 CSV 路径、表格构造等渲染细节。
"""

import logging
import smtplib
from email.message import EmailMessage

from anetf.config import MailConfig

logger = logging.getLogger(__name__)


class EmailNotifier:
    """基于 SMTP SSL 的邮件发送器。"""

    def __init__(self, mail_config: MailConfig):
        self._config = mail_config

    def send(self, html: str, subject: str) -> bool:
        """发送 HTML 邮件，返回是否成功。"""
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = self._config.sender
        msg['To'] = ', '.join(self._config.recipients)
        msg.set_content(html, subtype='html')

        try:
            with smtplib.SMTP_SSL(self._config.server, port=self._config.port) as server:
                server.login(self._config.sender, self._config.authcode)
                server.send_message(msg)
            logger.info('Email sent successfully.')
            return True
        except smtplib.SMTPException as ex:
            logger.error('Error: send failure = %s', ex)
            return False
