# -*- coding:utf-8 -*-
"""集中配置：路径、阈值、HTTP 超时、邮件服务器配置。

之前散落在 main.py / pe.py / etf.py 的常量与 config.ini 读取统一收纳于此。
项目根目录自动推断（src 包的父目录），调用方无需传 script_path。
"""

import os
import logging
import configparser
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ========== 路径 ==========
PACKAGE_DIR = os.path.dirname(os.path.realpath(__file__))   # .../anetf/src
PROJECT_ROOT = os.path.dirname(PACKAGE_DIR)                  # .../anetf

DB_FILE = os.path.join(PROJECT_ROOT, 'anetf.db')
CONFIG_FILE = os.path.join(PROJECT_ROOT, 'config.ini')
SCHEMA_FILE = os.path.join(PACKAGE_DIR, 'db', 'schema.sql')
TEMPLATES_DIR = os.path.join(PACKAGE_DIR, 'renderers', 'templates')

# ========== 业务阈值 ==========
# 计算百分位所需的最小数据点数（5% 精度）
MIN_PE_ROWS = 20
MIN_POINT_ROWS = 20

# 并发拉取指数估值的线程数（HTTP IO 密集型）
MAX_WORKERS = 12

# ========== HTTP 超时（秒）==========
# socket 层兜底，requests Session 层默认值
SOCKET_TIMEOUT = 15
HTTP_TIMEOUT = 12


@dataclass
class MailConfig:
    """邮件服务器配置。"""
    server: str
    port: int
    authcode: str
    sender: str
    recipients: list


def load_config() -> configparser.ConfigParser:
    """读取 config.ini；不存在时返回空 ConfigParser（调用方按需 has_option 判断）。"""
    cfg = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        cfg.read(CONFIG_FILE)
    else:
        logger.warning('config.ini not found at %s', CONFIG_FILE)
    return cfg


def load_mail_config() -> MailConfig:
    """从 config.ini 加载邮件配置。"""
    cfg = load_config()
    recipients_str = cfg.get('MailList', 'to', fallback='lianbch@163.com')
    recipients = [r.strip() for r in recipients_str.split(',') if r.strip()]
    return MailConfig(
        server=cfg.get('MailServer', 'server'),
        port=cfg.getint('MailServer', 'port'),
        authcode=cfg.get('MailServer', 'authcode'),
        sender=cfg.get('MailList', 'from'),
        recipients=recipients or ['lianbch@163.com'],
    )
