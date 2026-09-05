# -*- coding:utf-8 -*-
"""Web 快照服务。

纯读 anetf.db，不发网络请求——数据补齐全由每日 cron（run.py）维护。
快照按库内最新交易日 MAX(date) 做缓存 key：数据不变则直接复用，
cron 更新后下次访问自动重算，无需重启服务。

口径与邮件报告完全一致：单指数计算复用 report_service.compute_index_stats()。
"""

import logging
from typing import List, Optional

import numpy as np
import pandas as pd

from src.config import MIN_PE_ROWS, MIN_POINT_ROWS
from src.constants import CATEGORIES, CATEGORY_LABELS, UNSUPPORTED_INDEX_IDS
from src.db.connection import Database
from src.db.etf_repo import EtfRepository
from src.db.valuation_repo import ValuationRepository
from src.db.watchlist_repo import WatchlistRepository
from src.services.report_service import classify, compute_index_stats

logger = logging.getLogger(__name__)

# ========== 推荐规则参数 ==========
RECOMMEND_MAX_PCT = 0.20   # 主百分位低于该值视为低估
RECOMMEND_TOP_N = 20       # 推荐榜条数

# 指数详情页分位线
PERCENTILE_BANDS = [0.10, 0.20, 0.50, 0.80]


def normalize_index_id(index_id) -> str:
    """指数代码归一化：去 .CSI/.GI/.HI 等后缀并转大写。

    etf 表海外/策略指数带后缀（h30269.CSI/NDX.GI），index_valuation 存净代码，
    两表关联必须先归一化，否则误判「无数据」。
    """
    return str(index_id).split('.')[0].upper()


def _f(v):
    """NaN → None（JSON 序列化安全）。"""
    try:
        if v is None or pd.isna(v):
            return None
    except (TypeError, ValueError):
        return None
    return float(v)


class WebSnapshotService:
    """构建并缓存全库估值快照，供 Web 各页面查询。"""

    def __init__(self, db: Database = None):
        self._db = db or Database()
        self._etf_repo = EtfRepository(self._db)
        self._repo = ValuationRepository(self._db)
        self._watch_repo = WatchlistRepository(self._db)
        self._cache_key = object()   # 永不等于任何 date，保证首算
        self._snapshot = None

    # ---------- 快照 ----------
    def snapshot(self) -> dict:
        """返回全库快照（按最新交易日缓存）。"""
        key = self._repo.latest_date()
        if self._snapshot is None or key != self._cache_key:
            logger.info('Building web snapshot (data date: %s) ...', key)
            self._snapshot = self._build_snapshot()
            self._cache_key = key
        return self._snapshot

    def _build_snapshot(self) -> dict:
        mapping = self._etf_repo.load_mapping()
        if mapping.empty:
            return {'latest_date': None, 'etf_count': 0, 'indices': {},
                    'etfs': [], 'heatmap': [], 'recommend': [],
                    'overview': {}, 'median_avgamount': None}

        mapping = mapping.copy()
        mapping['norm_index_id'] = mapping['index_id'].apply(normalize_index_id)

        # 全体 ETF 日均成交额中位数（推荐流动性过滤基准）
        median_avg = mapping['avgamount'].dropna().median()

        # 每个指数的代表 ETF（流动性最高），供推荐/列表展示
        rep = (mapping.sort_values('avgamount')
               .drop_duplicates('norm_index_id', keep='last')
               .set_index('norm_index_id'))

        # 每指数一行计算估值（与邮件报告同口径）
        indices = {}
        for index_id in sorted(mapping['norm_index_id'].unique()):
            etf_df = self._repo.load_index(index_id)
            stats = compute_index_stats(etf_df)
            rep_row = rep.loc[index_id] if index_id in rep.index else None
            tag = rep_row['tag'] if rep_row is not None else None
            indices[index_id] = {
                'index_id': index_id,
                'index_name': (rep_row['index_name'] if rep_row is not None else None),
                'tag': tag,
                'category': classify(tag),
                'value_type': stats['指标类型'],
                'value': _f(stats['当前值']),
                'percentile': _f(stats['历史百分位']),
                'price_percentile': _f(stats['行情百分位(总历史)']),
                'price_percentile_5y': _f(stats['行情百分位(近5年)']),
                'pe_rows': int(etf_df['市盈率'].notna().sum()) if not etf_df.empty else 0,
                'point_rows': int(etf_df['点位'].notna().sum()) if not etf_df.empty else 0,
                'supported': index_id not in UNSUPPORTED_INDEX_IDS,
                'representative': self._etf_dict(rep_row) if rep_row is not None else None,
            }

        # ETF 列表（832 只全量，join 指数估值）
        idx_stats = {k: v for k, v in indices.items()}
        etfs = []
        for _, row in mapping.iterrows():
            s = idx_stats.get(row['norm_index_id'], {})
            etfs.append({**self._etf_dict(row), 'stats': {
                k: s.get(k) for k in
                ['value_type', 'value', 'percentile',
                 'price_percentile', 'price_percentile_5y']}})

        # 板块热力图：各大类指数平均百分位
        heatmap = []
        for key, label in CATEGORIES:
            pcts = [v['percentile'] for v in indices.values()
                    if v['category'] == key and v['percentile'] is not None]
            heatmap.append({
                'key': key, 'label': label,
                'count': len(pcts),
                'avg_percentile': float(np.mean(pcts)) if pcts else None,
            })

        # 推荐榜
        recommend = self._recommend(indices, median_avg)

        low_count = sum(1 for v in indices.values()
                        if v['percentile'] is not None and v['percentile'] < RECOMMEND_MAX_PCT)
        return {
            'latest_date': self._repo.latest_date(),
            'etf_count': len(mapping),
            'indices': indices,
            'etfs': etfs,
            'heatmap': heatmap,
            'recommend': recommend,
            'median_avgamount': _f(median_avg),
            'overview': {
                # 库内全部指数（含未被映射 ETF 覆盖的），比映射到的更全面
                'index_count': self._repo.count_indices(),
                'low_count': low_count,
            },
        }

    @staticmethod
    def _etf_dict(row) -> dict:
        return {
            'code': str(row['code']),
            'name': row['name'],
            'tag': row['tag'],
            'avgamount': _f(row['avgamount']),
            'index_name': row['index_name'],
            'index_id': row['index_id'],
        }

    def _recommend(self, indices: dict, median_avg) -> List[dict]:
        """规则型推荐：低百分位 + 流动性过滤，附可解释理由。"""
        candidates = []
        for v in indices.values():
            if not v['supported']:
                continue
            pct = v['percentile']
            if pct is None or pct >= RECOMMEND_MAX_PCT:
                continue
            # 负 PE（成分股整体亏损）不算低估，排除避免误导
            if v['value_type'] == 'PE' and (v['value'] is None or v['value'] <= 0):
                continue
            rep_avg = (v['representative'] or {}).get('avgamount')
            # 流动性过滤：代表 ETF 日均成交额低于全市场中位数则剔除
            if rep_avg is None or median_avg is None or rep_avg < median_avg:
                continue
            reason_parts = []
            if v['value_type'] == 'PE':
                p5y = v['price_percentile_5y']
                reason_parts.append('PE百分位 {:.1%}'.format(pct))
                if p5y is not None and v['price_percentile'] is not None \
                        and abs(p5y - v['price_percentile']) > 1e-9:
                    reason_parts.append('近5年 {:.1%}'.format(p5y))
                if v['value'] is not None:
                    reason_parts.append('当前PE {:.2f}'.format(v['value']))
            else:
                reason_parts.append('点位百分位 {:.1%}'.format(pct))
                if v['value'] is not None:
                    reason_parts.append('当前点位 {:.0f}'.format(v['value']))
            # avgamount 单位为万元（组合宝源），换算为亿元展示
            if rep_avg:
                reason_parts.append('日均成交 {:.2f} 亿'.format(rep_avg / 1e4))
            candidates.append({
                'index_id': v['index_id'],
                'index_name': v['index_name'],
                'category': v['category'],
                'percentile': pct,
                'etf': v['representative'],
                'reason': '，'.join(reason_parts),
            })
        candidates.sort(key=lambda x: x['percentile'])
        return candidates[:RECOMMEND_TOP_N]

    # ---------- 查询接口 ----------
    def overview(self) -> dict:
        s = self.snapshot()
        return {
            'latest_date': s['latest_date'],
            'etf_count': s['etf_count'],
            'index_count': s['overview']['index_count'],
            'low_count': s['overview']['low_count'],
            'heatmap': s['heatmap'],
            'recommend': s['recommend'],
        }

    def search_etfs(self, keyword: str = '', category: str = '') -> List[dict]:
        """ETF 搜索（后端 LIKE 过滤 + join 快照估值），全量返回由路由分页。"""
        kw = (keyword or '').strip()
        cat = (category or '').strip()
        if not kw and not cat:
            return self.snapshot()['etfs']
        df = self._etf_repo.search(kw, cat)
        if df.empty:
            return []
        idx_stats = self.snapshot()['indices']
        out = []
        for _, row in df.iterrows():
            s = idx_stats.get(normalize_index_id(row['index_id']), {})
            out.append({**self._etf_dict(row), 'stats': {
                k: s.get(k) for k in
                ['value_type', 'value', 'percentile',
                 'price_percentile', 'price_percentile_5y']}})
        return out

    def index_detail(self, index_id: str) -> Optional[dict]:
        """单指数详情：估值卡片 + PE/点位序列 + 分位线 + 跟踪 ETF。"""
        nid = normalize_index_id(index_id)
        snap = self.snapshot()
        info = snap['indices'].get(nid)
        if info is None:
            return None

        df = self._repo.load_index(nid)
        pe_s = df['市盈率'].dropna() if not df.empty else pd.Series(dtype=float)
        pt_s = df['点位'].dropna() if not df.empty else pd.Series(dtype=float)

        detail = dict(info)
        detail['min_pe_rows_ok'] = len(pe_s) >= MIN_PE_ROWS
        detail['min_point_rows_ok'] = len(pt_s) >= MIN_POINT_ROWS

        # 图表序列（日期 + 数值），降采样到 <=1000 点
        detail['pe_series'] = self._series(pe_s)
        detail['point_series'] = self._series(pt_s)

        # PE 估值通道：全历史分位线（样本足够才画）
        if len(pe_s) >= MIN_PE_ROWS:
            q = pe_s.quantile(PERCENTILE_BANDS)
            detail['pe_bands'] = {
                'labels': ['{}%'.format(int(b * 100)) for b in PERCENTILE_BANDS],
                'values': [_f(q[b]) for b in PERCENTILE_BANDS],
            }
        else:
            detail['pe_bands'] = None

        # 跟踪该指数的全部 ETF
        etf_list = self._etf_repo.list_by_index(nid)
        detail['etf_list'] = [self._etf_dict(row) for _, row in etf_list.iterrows()]
        return detail

    @staticmethod
    def _series(s: pd.Series, max_points: int = 1000):
        """时间序列降采样为 [[date, value], ...]（Chart.js 友好）。"""
        if s.empty:
            return []
        step = max(1, len(s) // max_points)
        s = s.iloc[::step]
        return [[str(d), _f(v)] for d, v in s.items()]

    # ---------- 关注列表 ----------
    def watchlist_view(self) -> List[dict]:
        """关注列表 join ETF 信息与估值快照。"""
        snap = self.snapshot()
        etf_by_code = {e['code']: e for e in snap['etfs']}
        out = []
        for w in self._watch_repo.list_all():
            e = etf_by_code.get(w['code'], {})
            out.append({
                'code': w['code'],
                'note': w.get('note'),
                'alert_low': w.get('alert_low'),
                'alert_high': w.get('alert_high'),
                'created_at': w.get('created_at'),
                'name': e.get('name'),
                'index_name': e.get('index_name'),
                'index_id': e.get('index_id'),
                'stats': e.get('stats'),
            })
        return out

    def add_watch(self, code: str, note: str = '', alert_low=None,
                  alert_high=None) -> bool:
        """加关注前校验 ETF 是否存在。"""
        if self._etf_repo.get_by_code(code) is None:
            return False
        return self._watch_repo.add(code, note, alert_low, alert_high)

    def remove_watch(self, code: str) -> bool:
        return self._watch_repo.remove(code)

    def update_watch(self, code: str, fields: dict) -> bool:
        """更新关注项字段（见 WatchlistRepository.update 的语义）。"""
        return self._watch_repo.update(code, fields)
