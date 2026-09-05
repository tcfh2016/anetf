# -*- coding:utf-8 -*-
"""`python -m src.web` 启动入口。

host/port 读 config.ini [Web] 段（可选），缺省 127.0.0.1:8000。
默认只绑本机回环地址：个人工具，无账号体系，不对外暴露。
"""

import configparser
import logging

from src.config import load_config
from src.db.connection import Database
from src.web.app import create_app

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger(__name__)


def main():
    cfg: configparser.ConfigParser = load_config()
    host = cfg.get('Web', 'host', fallback='127.0.0.1')
    port = cfg.getint('Web', 'port', fallback=8000)

    db = Database()
    app = create_app(db)
    logger.info('Web server starting at http://%s:%d', host, port)
    try:
        app.run(host=host, port=port, debug=False)
    finally:
        db.close()


if __name__ == '__main__':
    main()
