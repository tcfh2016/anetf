# -*- coding:utf-8 -*-
"""数据源抽象基类。

每个数据源（韭圈儿/中证/国证/价格行情）实现为一个 DataSource 子类，
封装 fetch + 转换逻辑；service 层负责编排（顺序、降级、存库）。

fetch() 返回的 DataFrame 统一 schema：
- index: 日期 (str)
- 列: 指数代码, 指数名称, 标签
- PE 类含 市盈率 列；点位类含 点位 + 数据类型='点位' 列
- 数据源 列标记来源

返回 None 表示该数据源无此指数数据（正常情况，触发降级）。
抛异常表示获取失败（由 service 层捕获记录）。
"""

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd


class DataSource(ABC):
    """数据源抽象基类。"""

    name: str = 'base'  # 子类覆盖：数据源名称，用于日志与 数据源 列

    @abstractmethod
    def fetch(self, index_id: str, index_name: str, index_tag: str) -> Optional[pd.DataFrame]:
        """获取指数估值数据，返回统一 schema 的 DataFrame 或 None。"""
        raise NotImplementedError
