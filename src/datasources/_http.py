# -*- coding:utf-8 -*-
"""全局 HTTP 超时控制（过渡方案）。

akshare 内部直接调用 requests 而不传 timeout，会无限挂死。
此处对 requests.Session.request 做 monkey-patch，注入默认超时。

副作用仅作用于本模块首次被 apply_default_timeout() 调用后的进程。
阶段 2 会改为显式注入带超时的 Session 给各数据源类，本模块届时退役。
"""

import socket
import logging

import requests

from src.config import HTTP_TIMEOUT, SOCKET_TIMEOUT

logger = logging.getLogger(__name__)

_applied = False


def apply_default_timeout() -> None:
    """应用全局 HTTP 超时（幂等，多次调用安全）。"""
    global _applied
    if _applied:
        return

    # 1. socket 层兜底
    socket.setdefaulttimeout(SOCKET_TIMEOUT)

    # 2. requests Session 层 monkey patch —— requests/urllib3 默认不继承
    #    socket.setdefaulttimeout，这样包括 akshare 内部的所有 requests
    #    调用都会自动带超时，永远不会无限挂死。
    _orig_session_request = requests.Session.request

    def _session_request_with_timeout(self, method, url, **kwargs):
        kwargs.setdefault('timeout', HTTP_TIMEOUT)
        return _orig_session_request(self, method, url, **kwargs)

    requests.Session.request = _session_request_with_timeout

    _applied = True
    logger.debug('Global HTTP timeout applied: socket=%ss, requests=%ss',
                SOCKET_TIMEOUT, HTTP_TIMEOUT)
