# -*- coding:utf-8 -*-
"""
Date: 2024-05-02
Desc: 更新ETF对应的指数的市盈率

阶段 1 重构：DB 访问 / 常量 / 路由函数已下沉到 src 包。
阶段 2 重构：5 个 update_* 数据源方法下沉为独立 DataSource 子类，
            ValuationService 通过 _try_fetch_and_store 编排。
阶段 3 重构：报告生成（order/_extend_*/classify/calc_percentile）下沉到
            services/report_service，懒加载下沉到 datasources/calendar，
            本模块只保留 update_db 的数据源编排。__main__ 只做 update_db。
"""

import logging

import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.config import MAX_WORKERS
from src.constants import UNSUPPORTED_INDEX_IDS
from src.db.connection import Database
from src.db.etf_repo import EtfRepository
from src.db.valuation_repo import ValuationRepository
from src.datasources.price_symbol import OVERSEAS_SPECIAL_CODES
from src.datasources._http import apply_default_timeout
from src.datasources.calendar import get_latest_trade_day, get_cni_index_list
from src.datasources.juquaner import JuquanerSource
from src.datasources.csindex import CsindexValueSource, CsindexHistSource
from src.datasources.cni import CniSource
from src.datasources.price import PriceSource
from src.datasources.base import DataSource

# 全局 HTTP 超时（akshare 内部不传 timeout，需 monkey-patch 兜底）
apply_default_timeout()

logger = logging.getLogger(__name__)


class ValuationService(object):
    """指数估值更新服务。

    阶段 3：只负责 update_db 的数据源编排（顺序、降级、存库）。
    报告生成已下沉到 src.services.report_service.ReportService。
    """

    def __init__(self, db: Database = None):
        self._db = db or Database()
        self._etf_repo = EtfRepository(self._db)
        self._repo = ValuationRepository(self._db)
        self._rewrite = False

        # 数据源实例：懒加载的 latest_trade_day / gz_df 由 calendar 模块单例提供
        self._src_jq = JuquanerSource()
        self._src_zz = CsindexValueSource()
        self._src_csi = CsindexHistSource(latest_trade_day_fn=get_latest_trade_day)
        self._src_gz = CniSource(
            gz_df_fn=get_cni_index_list,
            latest_trade_day_fn=get_latest_trade_day,
        )
        self._src_price = PriceSource(latest_trade_day_fn=get_latest_trade_day)

        # 数据源名→实例映射（偏好表路由用；'指数行情' 为点位兜底，不参与 PE 路由）
        self._source_by_name = {
            '韭圈儿': self._src_jq,
            '中证指数': self._src_zz,
            '国证指数': self._src_gz,
            '中证指数行情': self._src_csi,
        }
        self._preferences = {}

    def _load_preferences(self):
        """加载指数优先数据源配置到内存。
        数据来源：index_source_preference 表（由历史扫描脚本生成）。
        """
        sql = ("SELECT index_id, preferred_source, fallback_source "
               "FROM index_source_preference")
        df = pd.read_sql_query(sql, self._db.connection)
        self._preferences = {
            row['index_id']: (row['preferred_source'],
                              row['fallback_source'] if pd.notna(row['fallback_source']) else None)
            for _, row in df.iterrows()
        }
        logger.info('Loaded source preferences for %d indices', len(self._preferences))

    def _legacy_source_chain(self, index_id: str, index_tag) -> list:
        """无偏好表记录时（新指数），按旧降级顺序返回数据源名列表。"""
        is_cni = index_id.startswith('980') or index_id.startswith('987')
        first_tag = str(index_tag).split('，')[0] if pd.notna(index_tag) else ''
        is_non_equity = first_tag in ('商品', '债券')
        is_overseas_code = (
            index_id.startswith('HS')
            or index_id in OVERSEAS_SPECIAL_CODES
        )
        skip_domestic_pe = is_non_equity or is_overseas_code

        chain = ['韭圈儿']
        if not skip_domestic_pe and not is_cni:
            chain.append('中证指数')
        if not skip_domestic_pe:
            chain.append('国证指数')
        if not skip_domestic_pe and not is_cni:
            chain.append('中证指数行情')
        return chain

    def _try_fetch_and_store(self, source: DataSource, index_id: str,
                             index_name: str, index_tag: str, old_df) -> bool:
        """尝试从 source 拉取并存库，返回是否成功。

        - source.fetch() 返回 None / 空：视为无数据，返回 False（触发降级）
        - source.fetch() 抛异常：记录错误，返回 False（触发降级）
        - 成功：调 repo.store() 存库，返回 True
        """
        try:
            new_df = source.fetch(index_id, index_name, index_tag)
            if new_df is None or new_df.empty:
                return False
            self._repo.store(index_id, old_df, new_df, rewrite=self._rewrite)
            return True
        except Exception as e:
            logger.error('%s: fetch failed for %s: %s', source.name, index_id, e)
            return False

    def _has_pe_history(self, df) -> bool:
        """该指数历史上是否有市盈率数据。

        用于区分"PE 指数瞬时失败"与"本就无 PE 的点位指数"：
        前者 PE 源失败时应留空待下次重试，绝不能写点位降级行——
        否则点位行会使 update_db 视为"已缓存"而锁死 PE 恢复（降级锁死）。
        """
        return (not df.empty
                and '市盈率' in df.columns
                and df['市盈率'].notna().any())

    def _is_fresh(self, old_df, latest_trade_day: str) -> bool:
        """该指数的本地数据是否已更新到最新交易日（按列判定）。

        - 有 PE 历史的指数（股票类）：最新交易日行需 pe、point 均非空
          （point 为行情百分位的独立列，缺失则需补拉，不影响 PE 判定）
        - 无 PE 历史的指数（商品/债券等）：最新交易日行需 point 非空
        任一列缺失都不算新鲜，避免"点位行锁死 PE 恢复"或 PE 有值但点位欠补。
        """
        if self._rewrite or old_df.empty:
            return False
        if str(old_df.index[-1]) < latest_trade_day:
            return False
        last = old_df.iloc[-1]
        point_ok = pd.notna(last['点位'])
        if self._has_pe_history(old_df):
            return point_ok and pd.notna(last['市盈率'])
        return point_ok

    def update_db(self, max_workers=MAX_WORKERS):
        """更新指数数据库（PE/点位）。
        - 先对 index_id 去重，避免同一指数（被多只ETF复用）重复请求
        - 对需要真实请求的任务用线程池并发（HTTP IO 密集型，默认 12 线程提速 10x+）

        数据源路由（阶段 4：基于偏好表）：
        1. 查 index_source_preference 表，按首选源拉取；失败走备选源
        2. 无偏好记录的新指数：沿用旧降级链（韭圈儿→中证指数→国证→中证指数行情）
        3. 所有 PE 源失败后：有 PE 历史则留空待重试（避免点位锁死），
           无 PE 历史则点位兜底
        """
        self._load_preferences()
        df = self._etf_repo.load_mapping()

        # —— Step 1: 按 index_id 去重（和报告生成一样按 avgamount 排序保留最大那行）
        #    834 个 ETF → ~274 个唯一指数，直接砍掉约 2/3 的循环迭代
        uniq = df.sort_values(by=['avgamount']).drop_duplicates(
            subset=['index_id'], keep='last', ignore_index=True)
        logger.info('update_db: total ETF {} rows -> dedup to {} unique indices'.format(len(df), len(uniq)))

        # —— Step 2: 逐个做"跳过/需要更新"判定（纯本地 IO，毫秒级）
        latest_trade_day = get_latest_trade_day()
        tasks = []   # 需要真实请求的条目列表: (i, index_id, index_name, index_tag, old_df)
        skipped = 0
        for i in range(len(uniq)):
            index_id = str(uniq['index_id'].iloc[i]).split('.')[0].upper()
            index_name = uniq['index_name'].iloc[i]
            index_tag = uniq['tag'].iloc[i]

            # 跳过不支持的指数
            if index_id in UNSUPPORTED_INDEX_IDS:
                logger.info('{}: Skip unsupported index {}/{}'.format(i, index_id, index_name))
                skipped += 1
                continue

            old_df = self._repo.load_index(index_id)
            if self._is_fresh(old_df, latest_trade_day):
                need_update = False
                skipped += 1
            else:
                tasks.append((i, index_id, index_name, index_tag, old_df))

        logger.info('update_db: {} skip (cached/unsupported), {} need fresh fetch'.format(skipped, len(tasks)))

        # —— Step 3: 快速路径：如果没有需要更新的，直接返回
        if not tasks:
            return

        # —— Step 4: 用线程池并发执行需要数据源请求的任务（IO 密集型）
        def _update_one(tup):
            i, index_id, index_name, index_tag, old_df = tup
            try:
                logger.info('{}: Update index for {}/{}'.format(i, index_id, index_name))

                # 本地列新鲜度：PE 与点位各自独立判定，互不阻塞
                has_pe_hist = self._has_pe_history(old_df)
                date_fresh = (not old_df.empty
                              and str(old_df.index[-1]) >= latest_trade_day)
                last_row = old_df.iloc[-1] if not old_df.empty else None
                pe_fresh = (date_fresh and has_pe_hist
                            and last_row is not None and pd.notna(last_row['市盈率']))
                point_fresh = (date_fresh and last_row is not None
                               and pd.notna(last_row['点位']))

                # 1) PE 更新：仅当 PE 不新鲜时按偏好表/降级链拉取
                pe_updated = False
                if not pe_fresh:
                    # 按偏好表路由；无记录时沿用旧降级链
                    pref = self._preferences.get(index_id)
                    if pref is not None:
                        preferred, fallback = pref
                        source_names = [preferred] + ([fallback] if fallback else [])
                    else:
                        source_names = self._legacy_source_chain(index_id, index_tag)

                    for name in source_names:
                        source = self._source_by_name.get(name)
                        if source is None:
                            continue
                        pe_updated = self._try_fetch_and_store(
                            source, index_id, index_name, index_tag, old_df)
                        if pe_updated:
                            break

                    if has_pe_hist and not pe_updated:
                        # PE 源全部失败属瞬时故障：pe 列留空待下次重试。
                        # point 是独立列，照常更新不会锁死 PE（_is_fresh 要求 pe 非空才跳过）。
                        logger.warning(
                            '%s: all PE sources failed but index has PE history, '
                            'pe column left empty for retry', index_id)

                # 2) 点位更新：点位不新鲜时统一走行情源
                #    - PE 类指数：补 point 列供行情百分位使用（历史入库后报告零网络请求）
                #    - 无 PE 历史指数（商品/债券/无源主题等）：点位即主指标，兜底
                if not point_fresh:
                    point_ok = self._try_fetch_and_store(
                        self._src_price, index_id, index_name, index_tag, old_df)
                    if not point_ok and not has_pe_hist:
                        logger.warning(
                            '%s: all sources failed (no PE history, price fetch failed)',
                            index_id)

                return (index_id, True, None)
            except Exception as e:
                logger.error('{}: Update {}/{} raised exception: {}'.format(i, index_id, index_name, e))
                return (index_id, False, str(e))

        done, fail = 0, 0
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='pe-update') as pool:
            future_to_idx = {pool.submit(_update_one, t): t[1] for t in tasks}
            for fut in as_completed(future_to_idx):
                idx, ok, err = fut.result()
                if ok:
                    done += 1
                else:
                    fail += 1
                    logger.error('Index {} final update failed: {}'.format(idx, err))

        logger.info('update_db finished: done={}, failed={}'.format(done, fail))


# 向后兼容别名（如有外部代码仍引用 Pe）
Pe = ValuationService


def main():
    """更新指数估值（每日编排入口，只做 update_db；报告生成见 main.py）。"""
    service = ValuationService()
    service.update_db()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    logger.info('pe.py: update_db only (report generation moved to src.services.report_service)')
    main()
