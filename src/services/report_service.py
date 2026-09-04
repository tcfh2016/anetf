# -*- coding:utf-8 -*-
"""报告生成服务。

阶段 3：把 pe.py 的 order() / _extend_pe_history / _extend_point_history /
classify / calc_percentile 迁移至此，产出结构化的 List[CategoryReport]，
废除 pe.py ↔ mail.py 之间基于 CSV 的隐式契约。

不再写 mail/*.csv，渲染层直接消费 ReportRow。
"""

import logging
from typing import List, Optional

import numpy as np
import pandas as pd

from src.config import MIN_PE_ROWS, MIN_POINT_ROWS
from src.constants import (
    CATEGORIES,
    FIRST_TAG_CATEGORY,
    UNSUPPORTED_INDEX_IDS,
)
from src.db.connection import Database
from src.db.etf_repo import EtfRepository
from src.db.valuation_repo import ValuationRepository
from src.models import ReportRow, CategoryReport

logger = logging.getLogger(__name__)


def classify(tag) -> Optional[str]:
    """根据标签判断ETF所属分类，返回分类键；无法识别时返回None"""
    if pd.isna(tag):
        return None
    if tag.find('跨境') != -1:
        return 'crossborder'
    if tag.find('宽基') != -1:
        return 'broad'
    return FIRST_TAG_CATEGORY.get(tag.split('，')[0])


def calc_percentile(arr) -> float:
    arr = arr.dropna()
    if len(arr) == 0:
        return np.nan
    lower = arr[arr < arr.iloc[-1]]
    return (lower.shape[0] / arr.shape[0])


class ReportService:
    """生成 ETF 估值分类报告（结构化数据，不落盘）。"""

    def __init__(self, db: Database = None):
        self._db = db or Database()
        self._etf_repo = EtfRepository(self._db)
        self._repo = ValuationRepository(self._db)

    def generate_report(self) -> List[CategoryReport]:
        # 去重：多只ETF跟踪同一指数，保留成交量最高的
        df = self._etf_repo.load_mapping()
        drop_duplicate_df = df.sort_values(by=['avgamount']).drop_duplicates(
            subset=['index_id'], keep='last')

        # 过滤不支持的指数
        before_filter = len(drop_duplicate_df)
        drop_duplicate_df = drop_duplicate_df[~drop_duplicate_df['index_id'].apply(
            lambda x: x.split('.')[0].upper() in UNSUPPORTED_INDEX_IDS)]
        logger.info('ETF number: {}, drop to {} after remove duplicated ETF, '
                    'filtered {} unsupported.'.format(
                        len(df), len(drop_duplicate_df),
                        before_filter - len(drop_duplicate_df)))

        # 填充ETF的最新估值和百分位
        # 股票类ETF用市盈率(PE)，非股票类ETF用指数点位
        # price_percentiles：PE 类额外计算指数点位的历史百分位（行情百分位），点位类留空
        values, value_percentile, data_types, price_percentiles = [], [], [], []
        for i in range(len(drop_duplicate_df)):
            index_id = drop_duplicate_df['index_id'].iloc[i].split('.')[0].upper()
            etf_df = self._repo.load_index(index_id)

            if not etf_df.empty:
                # load_index 总是返回 市盈率/点位 两列（缺值为 NaN）
                # 类型判定看"历史上是否有 PE"：最新交易日 PE 瞬时缺失（点位已入库）时，
                # 仍按 PE 类处理，当前值取最新非空 PE，避免误降级为点位类
                has_pe = etf_df['市盈率'].notna().any()
                has_point = etf_df['点位'].notna().any()

                if has_pe:
                    # 估值类型=PE：只使用 PE 数据计算百分位，绝不使用点位数据
                    val = etf_df['市盈率'].dropna().iloc[-1]
                    values.append(val)
                    extended_pe = self._extend_pe_history(index_id, etf_df['市盈率'])
                    if extended_pe is not None:
                        value_percentile.append(calc_percentile(extended_pe))
                    else:
                        # PE 扩展后仍不足，保持 "-"，绝不混用点位数据
                        value_percentile.append(np.nan)
                    data_types.append('PE')
                    # 行情百分位：优先用库内点位历史（update_db 每日增量维护），
                    # 库内不足时 _extend_point_history 才回退拉取 akshare
                    extended_pt = self._extend_point_history(index_id, etf_df['点位'])
                    if extended_pt is not None:
                        price_percentiles.append(calc_percentile(extended_pt))
                    else:
                        price_percentiles.append(np.nan)
                elif has_point:
                    # 估值类型=点位：只使用点位数据计算百分位，绝不使用PE
                    # 行情百分位与主指标百分位同源，按需求留空避免重复
                    val = etf_df['点位'].dropna().iloc[-1]
                    values.append(val)
                    extended_pt = self._extend_point_history(index_id, etf_df['点位'])
                    if extended_pt is not None:
                        value_percentile.append(calc_percentile(extended_pt))
                    else:
                        # 点位扩展后仍不足，保持 "-"
                        value_percentile.append(np.nan)
                    data_types.append('指数点位')
                    price_percentiles.append(np.nan)
                else:
                    # 既无PE也无点位有效数据
                    values.append(np.nan)
                    value_percentile.append(np.nan)
                    data_types.append('')
                    price_percentiles.append(np.nan)
            else:
                values.append(np.nan)
                value_percentile.append(np.nan)
                data_types.append('')
                price_percentiles.append(np.nan)

        drop_duplicate_df = drop_duplicate_df.copy()
        drop_duplicate_df['当前值'] = values
        drop_duplicate_df['历史百分位'] = value_percentile
        drop_duplicate_df['指标类型'] = data_types
        drop_duplicate_df['行情百分位'] = price_percentiles

        # 按分类拆分，分类规则见 classify()
        grouped = {key: [] for key, _ in CATEGORIES}
        for i in range(len(drop_duplicate_df)):
            key = classify(drop_duplicate_df['tag'].iloc[i])
            if key is None:
                logger.warning('Unclassified ETF: {} (tag={})'.format(
                    drop_duplicate_df['name'].iloc[i], drop_duplicate_df['tag'].iloc[i]))
                continue
            grouped[key].append(i)

        reports = []
        for key, label in CATEGORIES:
            subset = drop_duplicate_df.iloc[grouped[key]].sort_values(
                by=['当前值', '历史百分位']).reset_index(drop=True)
            rows = []
            for i in range(len(subset)):
                row = subset.iloc[i]
                value = row['当前值']
                percentile = row['历史百分位']
                price_pct = row['行情百分位']
                rows.append(ReportRow(
                    etf_name=row['name'],
                    etf_code=str(row['code']),
                    index_name=row['index_name'],
                    index_id=str(row['index_id']),
                    value_type=row['指标类型'] if isinstance(row['指标类型'], str) else '',
                    value=None if pd.isna(value) else float(value),
                    percentile=None if pd.isna(percentile) else float(percentile),
                    price_percentile=None if pd.isna(price_pct) else float(price_pct),
                ))
            logger.info('{} ETF count: {}'.format(label, len(rows)))
            reports.append(CategoryReport(key=key, label=label, rows=rows))

        return reports

    def _extend_pe_history(self, index_id, current_pe_s):
        """返回库内 PE 序列（去空值）；不足 MIN_PE_ROWS 返回 None。

        报告阶段只读库、不发网络请求——PE 历史由 update_db 每日增量维护，
        不足时百分位显示 '-' 而非现场拉取（现场拉取串行且不落库，曾导致报告耗时 90s+）。
        """
        pe_s = current_pe_s.dropna()
        return pe_s if len(pe_s) >= MIN_PE_ROWS else None

    def _extend_point_history(self, index_id, current_point_s):
        """返回库内点位序列（去空值）；不足 MIN_POINT_ROWS 返回 None。

        报告阶段只读库、不发网络请求——点位历史由 update_db 每日增量维护
        （PE 类指数也回填 point 列），不足时行情百分位显示 '-'。
        """
        pt_s = current_point_s.dropna()
        return pt_s if len(pt_s) >= MIN_POINT_ROWS else None
