# -*- coding:utf-8 -*-
"""数据模型：以 dataclass 定义贯穿 DB ↔ 服务层 ↔ 渲染层的统一结构。

阶段 1 先建立模型契约，DB 与服务层仍主要使用 DataFrame；
阶段 3 起渲染层与（未来的 API 层）将以这些模型为序列化载体。
"""

from dataclasses import dataclass, field
from typing import Optional, Sequence


@dataclass(frozen=True)
class IndexValuation:
    """index_valuation 表的一行：某指数某日的估值快照。

    PE 类与点位类合二为一：pe/point 均为可空列，由 data_type 区分。
    """
    index_id: str
    date: str
    data_type: str
    index_name: Optional[str] = None
    tag: Optional[str] = None
    pe: Optional[float] = None
    point: Optional[float] = None
    source: Optional[str] = None


@dataclass(frozen=True)
class EtfInfo:
    """etf 表的一行：ETF→指数映射。"""
    code: str
    name: str
    tag: Optional[str] = None
    avgamount: Optional[float] = None
    index_name: Optional[str] = None
    index_id: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class ReportRow:
    """报告中的一行：某只 ETF 的当前估值与历史百分位。

    与邮件表头一一对应：ETF名称/ETF代码/指数名称/指数代码/指标类型/当前值/历史百分位。
    value/percentile 为 None 时表示数据缺失，渲染为 '-'。
    """
    etf_name: str
    etf_code: str
    index_name: Optional[str]
    index_id: Optional[str]
    value_type: str = ''               # 'PE' / '指数点位' / ''
    value: Optional[float] = None
    percentile: Optional[float] = None

    @property
    def has_data(self) -> bool:
        """是否有可展示的当前值。"""
        return self.value is not None


@dataclass
class CategoryReport:
    """某分类下的完整报告：分类键 + 展示名 + 行列表。"""
    key: str
    label: str
    rows: Sequence[ReportRow] = field(default_factory=list)
