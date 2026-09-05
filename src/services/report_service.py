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


def calc_price_percentile_pair(series):
    """计算 (近5年, 总历史) 行情百分位二元组。

    近5年 = 最后交易日往前推 5 个自然年内的子序列；
    历史不足 5 年或窗口样本不足 MIN_POINT_ROWS 时，近5年退化为全历史百分位。
    """
    full_pct = calc_percentile(series)
    if not np.isfinite(full_pct):
        return np.nan, np.nan
    idx = pd.to_datetime(pd.Index(series.index))
    cutoff = idx.max() - pd.DateOffset(years=5)
    recent = series[np.asarray(idx >= cutoff)]
    if len(recent) < MIN_POINT_ROWS:
        return full_pct, full_pct
    return calc_percentile(recent), full_pct


def compute_index_stats(etf_df):
    """单指数估值计算（报告与 Web 共用的口径，逐行搬运自 generate_report）。

    输入 load_index 返回的 DataFrame（date 索引，市盈率/点位 两列可为 NaN）。
    类型判定看「历史上是否有 PE」：最新交易日 PE 瞬时缺失（点位已入库）时，
    仍按 PE 类处理，当前值取最新非空 PE，避免误降级为点位类。
    返回 dict：当前值/历史百分位/指标类型/行情百分位(近5年)/行情百分位(总历史)。
    """
    stats = {
        '当前值': np.nan,
        '历史百分位': np.nan,
        '指标类型': '',
        '行情百分位(近5年)': np.nan,
        '行情百分位(总历史)': np.nan,
    }
    if etf_df is None or etf_df.empty:
        return stats

    has_pe = etf_df['市盈率'].notna().any()
    has_point = etf_df['点位'].notna().any()

    if has_pe:
        # 估值类型=PE：只使用 PE 数据计算百分位，绝不使用点位数据
        stats['当前值'] = etf_df['市盈率'].dropna().iloc[-1]
        extended_pe = _extend_pe_history(etf_df['市盈率'])
        if extended_pe is not None:
            stats['历史百分位'] = calc_percentile(extended_pe)
        # PE 扩展后仍不足，保持 "-"，绝不混用点位数据
        stats['指标类型'] = 'PE'
        # 行情百分位：只读库内点位历史（update_db 每日增量维护），
        # 同时给出 (近5年, 总历史) 两个口径
        extended_pt = _extend_point_history(etf_df['点位'])
        if extended_pt is not None:
            p5y, pfull = calc_price_percentile_pair(extended_pt)
            stats['行情百分位(近5年)'] = p5y
            stats['行情百分位(总历史)'] = pfull
    elif has_point:
        # 估值类型=点位：只使用点位数据计算百分位，绝不使用PE
        # 行情百分位与主指标百分位同源，按需求留空避免重复
        stats['当前值'] = etf_df['点位'].dropna().iloc[-1]
        extended_pt = _extend_point_history(etf_df['点位'])
        if extended_pt is not None:
            stats['历史百分位'] = calc_percentile(extended_pt)
        # 点位扩展后仍不足，保持 "-"
        stats['指标类型'] = '指数点位'
    # 既无PE也无点位有效数据时保持初始 NaN/''

    return stats


def _extend_pe_history(current_pe_s):
    """返回库内 PE 序列（去空值）；不足 MIN_PE_ROWS 返回 None。

    报告/Web 阶段只读库、不发网络请求——PE 历史由 update_db 每日增量维护，
    不足时百分位显示 '-' 而非现场拉取（现场拉取串行且不落库，曾导致报告耗时 90s+）。
    """
    pe_s = current_pe_s.dropna()
    return pe_s if len(pe_s) >= MIN_PE_ROWS else None


def _extend_point_history(current_point_s):
    """返回库内点位序列（去空值）；不足 MIN_POINT_ROWS 返回 None。

    报告/Web 阶段只读库、不发网络请求——点位历史由 update_db 每日增量维护
    （PE 类指数也回填 point 列），不足时行情百分位显示 '-'。
    """
    pt_s = current_point_s.dropna()
    return pt_s if len(pt_s) >= MIN_POINT_ROWS else None


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

        # 填充ETF的最新估值和百分位（单指数计算走 compute_index_stats，
        # 与 Web 快照共用同一口径）
        stat_cols = ['当前值', '历史百分位', '指标类型',
                     '行情百分位(近5年)', '行情百分位(总历史)']
        for col in stat_cols:
            # 指标类型是字符串列，其余为数值列
            drop_duplicate_df[col] = '' if col == '指标类型' else np.nan
        for i in range(len(drop_duplicate_df)):
            index_id = drop_duplicate_df['index_id'].iloc[i].split('.')[0].upper()
            etf_df = self._repo.load_index(index_id)
            stats = compute_index_stats(etf_df)
            for col in stat_cols:
                drop_duplicate_df.iat[i, drop_duplicate_df.columns.get_loc(col)] = stats[col]

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
                price_pct = row['行情百分位(总历史)']
                price_pct_5 = row['行情百分位(近5年)']
                rows.append(ReportRow(
                    etf_name=row['name'],
                    etf_code=str(row['code']),
                    index_name=row['index_name'],
                    index_id=str(row['index_id']),
                    value_type=row['指标类型'] if isinstance(row['指标类型'], str) else '',
                    value=None if pd.isna(value) else float(value),
                    percentile=None if pd.isna(percentile) else float(percentile),
                    price_percentile=None if pd.isna(price_pct) else float(price_pct),
                    price_percentile_5y=None if pd.isna(price_pct_5) else float(price_pct_5),
                ))
            logger.info('{} ETF count: {}'.format(label, len(rows)))
            reports.append(CategoryReport(key=key, label=label, rows=rows))

        return reports
