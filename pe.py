# -*- coding:utf-8 -*-
"""
Date: 2024-05-02
Desc: 更新ETF对应的指数的市盈率
"""

import os
import socket
import logging
import sqlite3
import threading
import requests
import pandas as pd
import numpy as np
import akshare as ak
from concurrent.futures import ThreadPoolExecutor, as_completed

from ext import jq

# ========== 全局 HTTP 超时控制（双保险） ==========
# 1. socket 层兜底
socket.setdefaulttimeout(15)

# 2. requests Session 层 Monkey Patch —— requests/urllib3 默认不继承 socket.setdefaulttimeout，
#    这样包括 akshare 内部的所有 requests 调用都会自动带 12 秒超时，永远不会无限挂死。
_DEFAULT_HTTP_TIMEOUT = 12
_orig_session_request = requests.Session.request

def _session_request_with_timeout(self, method, url, **kwargs):
    kwargs.setdefault('timeout', _DEFAULT_HTTP_TIMEOUT)
    return _orig_session_request(self, method, url, **kwargs)

requests.Session.request = _session_request_with_timeout

# index_valuation 表：替代 db/ 下 305 个 CSV 的统一存储
# PE 类与点位类合二为一：pe/point 均为可空列，由 data_type 区分
# 复合主键 (index_id, date) 天然实现"同日不重、新日才追加"
CREATE_INDEX_VALUATION_SQL = """
CREATE TABLE IF NOT EXISTS index_valuation (
    index_id   TEXT NOT NULL,
    date       TEXT NOT NULL,
    index_name TEXT,
    tag        TEXT,
    pe         REAL,
    point      REAL,
    data_type  TEXT NOT NULL,
    source     TEXT,
    PRIMARY KEY (index_id, date)
);
"""

logger = logging.getLogger(__name__)

# 一级标签 -> 分类（文件后缀，邮件展示名）
# 按优先级判断：先按市场属性（跨境/宽基），再按一级标签细分股票类型，
# 最后独立出非股票类资产（商品/债券），它们的估值口径与股票类不同
categories = [
    ('crossborder', '跨境股票'),
    ('broad', '宽基指数'),
    ('sector', '行业股票'),
    ('theme', '主题投资'),
    ('strategy', '策略指数'),
    ('commodity', '商品'),
    ('bond', '固定收益'),
]

first_tag_category = {
    '行业': 'sector',
    '主题': 'theme',
    '策略': 'strategy',
    '商品': 'commodity',
    '债券': 'bond',
}

def classify(tag) -> str:
    """根据标签判断ETF所属分类，返回分类键；无法识别时返回None"""
    if pd.isna(tag):
        return None
    if tag.find('跨境') != -1:
        return 'crossborder'
    if tag.find('宽基') != -1:
        return 'broad'
    return first_tag_category.get(tag.split('，')[0])

def calc_percentile(arr):
    arr = arr.dropna()
    if len(arr) == 0:
        return np.nan
    lower = arr[arr < arr.iloc[-1]]
    return(lower.shape[0] / arr.shape[0])

# 韭圈儿名称映射表：本地指数名称 -> 韭圈儿指数名称
# 仅包含经核实为"同一指数不同命名"的映射关系
# key 是 index.csv 中的 index_name 值，value 是韭圈儿(funddb)中的名称
# 注意：严禁映射不同指数，即使名称相似也会产生错误的估值
funddb_name_mapping = {
    # 海外指数：funddb 省略了"平均"两字
    '道琼斯工业平均指数': '道琼斯工业指数',
    # 港股通50：本地987003与funddb 930931可能为同一指数的不同编码
    # 仅在确认后启用此映射
    # '港股通50': '港股通50(HKD)',
}

# 不支持数据获取的指数黑名单（akshare + yfinance 均无对应数据源）
# 这些指数在 update_db() 中跳过拉取，在 order() 中从邮件 CSV 中过滤
# 避免无意义的请求与展示 "-"
unsupported_index_ids = {
    # 香港恒生指数公司主题指数（Sina API 仅支持 HSI 家族，不支持主题指数）
    'HSHKAT',   # 恒生港股通汽车主题指数
    'HSC',      # 恒生消费指数
    'HSHGDV',   # 恒生港股通高股息低波动指数
    'HSCPG',    # 恒生A股电网设备指数
    'HSHDY',    # 恒生港股通高股息率指数
    'HSHKCT',   # 恒生港股通中国科技指数
    'HSHKNE',   # 恒生港股通新经济指数
    # 海外指数（akshare 无对应数据源，yfinance 限流不可用）
    'SGXTECH',  # 新交所泛东南亚科技指数
    'FARAB',    # 富时阿拉伯指数
    'TPX',      # 东证指数
    # 其他无 API 支持的指数
    '716567',   # MSCI中国A股国际通指数
    'ICEA',     # 易盛能化A指数
}

class Pe(object):
    def __init__(self, work_path):
        df = ak.stock_zh_a_daily(symbol="sz000001", start_date="20240301", adjust="qfq")
        self._latest_trade_day = str(df['date'].iloc[-1])
        self._rewrite = False

        self._db_file = os.path.join(work_path, 'anetf.db')
        self._mail_path = os.path.join(work_path, 'mail')
        self._gz_df = ak.index_all_cni().set_index('指数代码')

        # 初始化 SQLite：WAL（读写不互斥）+ busy_timeout（锁冲突自动等）+ 建表
        # check_same_thread=False：连接在主线程创建，但写库由 worker 触发；
        #   靠 self._db_lock 保证同一时刻只有一个线程操作连接，故跨线程共享安全。
        self._conn = sqlite3.connect(self._db_file, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.execute(CREATE_INDEX_VALUATION_SQL)
        self._conn.commit()
        self._db_lock = threading.Lock()

    def _extend_pe_history(self, index_id, current_pe_s):
        """尝试扩展 PE 历史数据长度（仅使用 PE 数据源，绝不使用点位）。
        当前已有 PE 不足时，优先从中证历史行情（滚动市盈率列）扩展，
        再尝试通过韭圈儿获取更长的 PE 序列。达不到最小行数返回 None。
        """
        MIN_PE_ROWS = 20  # 至少需要 20 个 PE 数据点才计算百分位（5% 精度）
        current_pe_s = current_pe_s.dropna()
        if len(current_pe_s) >= MIN_PE_ROWS:
            return current_pe_s

        # 1. 尝试 stock_zh_index_hist_csindex 的"滚动市盈率"列（覆盖 CSI 全量指数，可能被WAF封）
        try:
            df = ak.stock_zh_index_hist_csindex(
                symbol=index_id,
                start_date='20180101',
                end_date=self._latest_trade_day.replace('-', '')
            )
            if not df.empty and '滚动市盈率' in df.columns:
                extra_pe = df['滚动市盈率'].dropna()
                extra_pe = extra_pe[extra_pe > 0]  # 过滤 0 值
                # 合并当前 PE 与扩展 PE（去重，避免重复日期）
                merged = pd.concat([current_pe_s, extra_pe]).drop_duplicates()
                merged = merged[~merged.index.duplicated(keep='last')] if isinstance(merged.index, pd.DatetimeIndex) else merged
                if len(merged) >= MIN_PE_ROWS:
                    return merged
        except Exception:
            pass

        # 2. 尝试韭圈儿 PE（更长历史，但需要能匹配名称）
        try:
            from ext import jq
            # 通过 index.csv 反查名称（这里不知道名称，只能直接用代码匹配 jq 的名称表，跳过）
            # 如需更彻底的扩展，应在 order() 里传入 index_name 参数——此处保持轻量
        except Exception:
            pass

        # 达不到最小要求
        extended = current_pe_s.dropna()
        return extended if len(extended) >= MIN_PE_ROWS else None

    def _extend_point_history(self, index_id, current_point_s):
        """尝试扩展点位历史长度（仅使用价格/行情数据源，绝不使用 PE）。
        当前点位不足时，从多种 akshare 接口回退获取。达不到最小行数返回 None。
        """
        MIN_POINT_ROWS = 20
        current_point_s = current_point_s.dropna()
        if len(current_point_s) >= MIN_POINT_ROWS:
            return current_point_s

        def _from_close_col(df, aliases=None):
            if df is None or df.empty:
                return None
            for alias in (aliases or ['close', '收盘', '收盘价', 'Close', '晚盘价']):
                if alias in df.columns:
                    s = pd.Series(df[alias]).dropna()
                    merged = pd.concat([current_point_s, s]).drop_duplicates()
                    return merged if len(merged) >= MIN_POINT_ROWS else None
            return None

        symbol_info = self._get_price_symbol(index_id)
        if symbol_info is None:
            ext = current_point_s.dropna()
            return ext if len(ext) >= MIN_POINT_ROWS else None
        source_type, symbol = symbol_info

        try:
            # ===== 中证 / 国证 / 沪深 =====
            if source_type in ('cn', 'cni'):
                # 国证历史行情 (980xxx/987xxx 必中)
                try:
                    df = ak.index_hist_cni(symbol=index_id)
                    res = _from_close_col(df)
                    if res is not None:
                        return res
                except Exception:
                    pass
                # 中证历史行情 (930xxx/931xxx/932xxx，WAF 可能间歇性封堵)
                try:
                    df = ak.stock_zh_index_hist_csindex(
                        symbol=index_id,
                        start_date='20180101',
                        end_date=self._latest_trade_day.replace('-', '')
                    )
                    res = _from_close_col(df)
                    if res is not None:
                        return res
                except Exception:
                    pass
                # 新浪行情：多种前缀组合
                if not index_id.startswith('98'):
                    for prefix in ['', 'csi', 'sh', 'sz']:
                        try:
                            df = ak.stock_zh_index_daily(symbol=prefix + index_id)
                            res = _from_close_col(df)
                            if res is not None:
                                return res
                        except Exception:
                            pass

            # ===== 港股 =====
            elif source_type == 'hk':
                try:
                    df = ak.stock_hk_index_daily_sina(symbol=symbol)
                    res = _from_close_col(df)
                    if res is not None:
                        return res
                except Exception:
                    pass

            # ===== 美股 =====
            elif source_type == 'us':
                try:
                    df = ak.index_us_stock_sina(symbol=symbol)
                    res = _from_close_col(df)
                    if res is not None:
                        return res
                except Exception:
                    pass

            # ===== 期货 =====
            elif source_type == 'futures':
                try:
                    df = ak.futures_zh_daily_sina(symbol=symbol)
                    res = _from_close_col(df)
                    if res is not None:
                        return res
                except Exception:
                    pass
            # ===== 黄金 =====
            elif source_type == 'gold':
                try:
                    df = ak.spot_golden_benchmark_sge()
                    res = _from_close_col(df)
                    if res is not None:
                        return res
                except Exception:
                    pass
        except Exception:
            pass

        ext = current_point_s.dropna()
        return ext if len(ext) >= MIN_POINT_ROWS else None

    def order(self):
        # 由于多只ETF跟踪相同指数，所以先进行去重操作，只保留成交量最高的ETF
        df = self._load_etf_mapping()
        drop_duplicate_df = df.sort_values(by=['avgamount']).drop_duplicates(subset=['index_id'], keep='last')

        # 过滤掉不支持数据获取的指数，不在邮件中展示
        before_filter = len(drop_duplicate_df)
        drop_duplicate_df = drop_duplicate_df[~drop_duplicate_df['index_id'].apply(
            lambda x: x.split('.')[0].upper() in unsupported_index_ids)]
        logger.info('ETF number: {}, drop to {} after remove duplicated ETF, '
                    'filtered {} unsupported.'.format(
                        len(df), len(drop_duplicate_df), before_filter - len(drop_duplicate_df)))        

        # 填充ETF的最新估值和百分位
        # 股票类ETF用市盈率(PE)，非股票类ETF用指数点位
        values, value_percentile, data_types = [], [], []
        for i in range(len(drop_duplicate_df)):
            index_id = drop_duplicate_df['index_id'].iloc[i].split('.')[0].upper()
            etf_df = self._load_index(index_id)

            if not etf_df.empty:
                # _load_index 总是返回 市盈率/点位 两列（缺值为 NaN），优先 PE，PE 全空降级用点位
                pe_valid = pd.notna(etf_df['市盈率'].iloc[-1])
                point_valid = pd.notna(etf_df['点位'].iloc[-1])

                if pe_valid:
                    # 估值类型=PE：只使用 PE 数据计算百分位，绝不使用点位
                    val = etf_df['市盈率'].iloc[-1]
                    values.append(val)
                    extended_pe = self._extend_pe_history(index_id, etf_df['市盈率'])
                    if extended_pe is not None:
                        value_percentile.append(calc_percentile(extended_pe))
                    else:
                        # PE 扩展后仍不足，保持 "-"，绝不混用点位数据
                        value_percentile.append(np.nan)
                    data_types.append('PE')
                elif point_valid:
                    # 估值类型=点位：只使用点位数据计算百分位，绝不使用PE
                    val = etf_df['点位'].iloc[-1]
                    values.append(val)
                    extended_pt = self._extend_point_history(index_id, etf_df['点位'])
                    if extended_pt is not None:
                        value_percentile.append(calc_percentile(extended_pt))
                    else:
                        # 点位扩展后仍不足，保持 "-"
                        value_percentile.append(np.nan)
                    data_types.append('指数点位')
                else:
                    # 既无PE也无点位有效数据
                    values.append(np.nan)
                    value_percentile.append(np.nan)
                    data_types.append('')
            else:
                values.append(np.nan)
                value_percentile.append(np.nan)
                data_types.append('')

        drop_duplicate_df.columns = ['ETF名称', 'ETF代码', '标签', '平均成交额', '指数名称', '指数代码']
        drop_duplicate_df['当前值'] = values
        drop_duplicate_df['历史百分位'] = value_percentile
        drop_duplicate_df['指标类型'] = data_types
                
        def sort_and_save(etf_subset, filename, label):
            etf_subset = etf_subset.sort_values(by=['当前值', '历史百分位']).reset_index(drop=True)
            etf_subset.to_csv(os.path.join(self._mail_path, filename))
            logger.info('{} ETF count: {}'.format(label, len(etf_subset)))

        # 按分类拆分并保存，分类规则见 classify()
        grouped = {key: [] for key, _ in categories}
        for i in range(len(drop_duplicate_df)):
            key = classify(drop_duplicate_df['标签'].iloc[i])
            if key is None:
                logger.warning('Unclassified ETF: {} (tag={})'.format(
                    drop_duplicate_df['ETF名称'].iloc[i], drop_duplicate_df['标签'].iloc[i]))
                continue
            grouped[key].append(i)

        for key, label in categories:
            etf_subset = drop_duplicate_df.iloc[grouped[key]]
            sort_and_save(etf_subset, 'etf_{}_sorted.csv'.format(key), label)

    def _load_index(self, index_id):
        """从数据库读取某指数的全部历史估值（按日期升序）。
        返回 DataFrame 以 date 为索引，列名与旧 CSV 兼容（市盈率/点位/数据类型/数据源…），
        便于 store_pe / order / _extend_*_history 等沿用原逻辑。
        """
        sql = ("SELECT date, index_id, index_name, tag, pe, point, data_type, source "
               "FROM index_valuation WHERE index_id=? ORDER BY date")
        df = pd.read_sql_query(sql, self._conn, params=(index_id,))
        df = df.rename(columns={
            'index_id': '指数代码', 'index_name': '指数名称', 'tag': '标签',
            'pe': '市盈率', 'point': '点位', 'data_type': '数据类型', 'source': '数据源'})
        return df.set_index('date')

    def _load_etf_mapping(self):
        """从数据库读取 ETF→指数映射（替代 tmp/index.csv）。
        列顺序与旧 CSV 的 usecols 一致：name, code, tag, avgamount, index_name, index_id，
        以保持 order() 末尾按位置重命名为中文列名的行为不变。
        """
        sql = "SELECT name, code, tag, avgamount, index_name, index_id FROM etf"
        try:
            return pd.read_sql_query(sql, self._conn)
        except sqlite3.OperationalError:
            # etf 表尚未创建（未跑过 etf.py 刷新）——返回空表，避免阻断每日流程
            logger.warning("etf table not found; run `python etf.py` to refresh the mapping")
            return pd.DataFrame(columns=['name', 'code', 'tag', 'avgamount', 'index_name', 'index_id'])

    def _to_db_records(self, index_id, diff):
        """把 update_* 产出的 DataFrame（PE 类或点位类）转为统一 DB schema 的元组列表。
        NaN 统一转 None，以便 SQLite 存为 NULL。
        """
        is_pe = '市盈率' in diff.columns
        rows = pd.DataFrame({
            'index_id':   index_id,
            'date':       diff.index.astype(str),
            'index_name': diff['指数名称'] if '指数名称' in diff.columns else None,
            'tag':        diff['标签'] if '标签' in diff.columns else None,
            'pe':         diff['市盈率'] if is_pe else np.nan,
            'point':      diff['点位'] if '点位' in diff.columns else np.nan,
            'data_type':  diff['数据类型'] if '数据类型' in diff.columns else ('PE' if is_pe else '点位'),
            'source':     diff['数据源'] if '数据源' in diff.columns else None,
        })
        cols = ['index_id', 'date', 'index_name', 'tag', 'pe', 'point', 'data_type', 'source']
        return [
            tuple(None if pd.isna(v) else v for v in row)
            for row in rows[cols].itertuples(index=False, name=None)
        ]

    def store_pe(self, index_id, old_df, new_df):
        """将新估值写入数据库 index_valuation 表。
        - 正常模式：只追加 old_df 最新日期之后的新行（INSERT OR IGNORE 防重复）
        - _rewrite 模式：先删该指数全部旧数据，再全量写入
        线程安全：写库段加 self._db_lock 串行化，保证并发 worker 共享连接安全。
        """
        try:
            if self._rewrite:
                diff = new_df
                with self._db_lock:
                    self._conn.execute(
                        "DELETE FROM index_valuation WHERE index_id=?", (index_id,))
                    self._conn.commit()
            elif old_df.empty:
                diff = new_df
            else:
                # 数据无更新（最新日期相同）
                if str(old_df.index[-1]) == str(new_df.index[-1]):
                    return
                diff = new_df[new_df.index > old_df.index[-1]] if len(new_df) > 1 else new_df
                if diff.empty:
                    return

            logger.debug(diff)
            records = self._to_db_records(index_id, diff)
            if not records:
                return
            sql = ("INSERT OR IGNORE INTO index_valuation "
                   "(index_id, date, index_name, tag, pe, point, data_type, source) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
            with self._db_lock:
                self._conn.executemany(sql, records)
                self._conn.commit()
        except Exception as e:
            logger.error('Store pe for {} failed because of {}'.format(index_id, str(e)))

    # 从韭圈儿获取市盈率并更新
    # 支持名称映射：如果本地名称在funddb中不存在，尝试使用映射名称
    # 同时支持多候选：先尝试映射名，再尝试原始名，确保不丢失已有功能
    def update_jq(self, index_id, index_nm, index_tag, old_df):
        # 构建候选名称列表
        jq_name = funddb_name_mapping.get(index_nm, index_nm)
        candidates = [jq_name]
        if jq_name != index_nm:
            candidates.append(index_nm)  # 回退：同时尝试原始名称

        for name in candidates:
            try:
                logger.info('JQ: Update PE index id({}), local_name({}), trying funddb_name({})'.format(
                    index_id, index_nm, name))
                new_df = jq.index_value_hist_funddb(symbol=name).astype({'日期':str})
                if new_df.empty:
                    logger.debug('JQ: funddb returned empty for {}, trying next candidate'.format(name))
                    continue
                new_df['指数代码'] = index_id
                new_df['指数名称'] = index_nm
                new_df['标签'] = index_tag
                new_df['数据源'] = '韭圈儿'
                new_df = new_df[['日期', '指数代码', '指数名称', '标签', '市盈率', '数据源']].set_index('日期')
                self.store_pe(index_id, old_df, new_df)
                return True
            except Exception as e:
                logger.debug('JQ: query {} failed: {}'.format(name, str(e)))
                continue

        logger.error('JQ: query failed for all candidates: {}'.format(candidates))
        return False

    # 更新中证指数的市盈率
    def update_zz(self, index_id, index_nm, index_tag, old_df):
        try:
            logger.info('ZZ: Update PE index id({})'.format(index_id))
            new_df = ak.stock_zh_index_value_csindex(symbol=index_id).astype({'日期':str})
            new_df['指数名称'] = index_nm
            new_df['标签'] = index_tag
            new_df['数据源'] = '中证指数'
            new_df = new_df.sort_values(by=['日期']).set_index('日期')[['指数代码', '指数名称', '标签', '市盈率1', '数据源']].rename(columns={'市盈率1':'市盈率'})
            #print(new_df)
            self.store_pe(index_id, old_df, new_df)
            return True
        except Exception as e:
            logger.error('ZZ: query {} failed because of {}'.format(index_id, str(e)))
        return False
    
    # 从国证网站获取市盈率并更新
    def update_gz(self, index_id, index_nm, index_tag, old_df):
        logger.info('GZ: Update PE index id({}), name({})'.format(index_id, index_nm))

        if index_id in self._gz_df.index:
            pe_val = self._gz_df.loc[index_id, 'PE滚动']
            if pd.isna(pe_val):
                logger.warning('GZ: Update {} skipped, PE is NaN in gz_df.'.format(index_id))
                return False
            record = [self._latest_trade_day, index_id, index_nm, index_tag, pe_val, '国证指数']
            new_df = pd.DataFrame([record], columns=['日期', '指数代码', '指数名称', '标签', '市盈率', '数据源'])
            new_df = new_df.set_index('日期')
            logger.debug(new_df)
            self.store_pe(index_id, old_df, new_df)
            return True
        else:
            logger.warning('Update {} failed, index not found in gz_df.'.format(index_id))
            return False

    # 从中证指数历史行情获取PE（覆盖中证系列全量指数）
    def update_csindex(self, index_id, index_nm, index_tag, old_df):
        try:
            logger.info('CSI: Update PE index id({}), name({})'.format(index_id, index_nm))
            new_df = ak.stock_zh_index_hist_csindex(
                symbol=index_id,
                start_date='20180101',
                end_date=self._latest_trade_day.replace('-', '')
            )
            if new_df.empty:
                return False
            new_df = new_df.astype({'日期': str})
            # 过滤掉PE为0或NaN的记录
            pe_df = new_df[new_df['滚动市盈率'].notna() & (new_df['滚动市盈率'] > 0)].copy()
            if pe_df.empty:
                return False
            pe_df['指数代码'] = index_id
            pe_df['指数名称'] = index_nm
            pe_df['标签'] = index_tag
            pe_df['数据源'] = '中证指数行情'
            pe_df = pe_df.rename(columns={'滚动市盈率': '市盈率'})
            pe_df = pe_df[['日期', '指数代码', '指数名称', '标签', '市盈率', '数据源']].set_index('日期')
            self.store_pe(index_id, old_df, pe_df)
            return True
        except Exception as e:
            logger.error('CSI: query {} failed because of {}'.format(index_id, str(e)))
            return False

    def _get_price_symbol(self, index_id):
        """根据指数代码推断行情数据获取方式
        注意: index_id 在传入前已经通过 split('.')[0] 去掉了后缀
        """
        # 港股指数代码: HSHKAT, HSC, HSHGDV, HSCPG, HSHDY, HSHKCT, HSHCI 等
        if index_id.startswith('HS') or index_id.startswith('HSC'):
            return ('hk', index_id)
        # 国证指数代码: 987xxx, 980xxx 开头的国证指数
        if index_id.startswith('987') or index_id.startswith('980'):
            return ('cni', index_id)
        # 中证指数代码: 931xxx 开头的中证指数
        if index_id.startswith('931'):
            return ('cn', 'csi' + index_id)
        # 商品/期货特殊处理
        if index_id in ('AU9999', 'SHAU'):
            return ('gold', None)
        if index_id == 'M9999':
            return ('futures', 'M0')
        if index_id == 'ICEA':
            return None
        # 美国指数: Sina API 要求代码以 . 开头
        us_index_map = {
            'SP500': ('us', '.INX'),
            'DJI': ('us', '.DJI'),
            'NDX': ('us', '.NDX'),
            'NBI': ('us', '.NBI'),
        }
        if index_id in us_index_map:
            return us_index_map[index_id]
        # 国内指数: 判断交易所前缀
        if index_id[0] in '05679':
            return ('cn', 'sh' + index_id)
        elif index_id[0] in '123':
            return ('cn', 'sz' + index_id)
        elif index_id.startswith('H') or index_id.startswith('CN'):
            return ('cn', 'csi' + index_id)
        return None

    # 价格降级：对没有PE的指数（商品、债券、海外等），用历史点位计算百分位
    def update_price(self, index_id, index_nm, index_tag, old_df):
        try:
            symbol_info = self._get_price_symbol(index_id)
            if symbol_info is None:
                logger.warning('PRICE: No price source for {}'.format(index_id))
                return False

            source_type, symbol = symbol_info
            logger.info('PRICE: Update index id({}), name({}), source={}'.format(index_id, index_nm, source_type))

            if source_type == 'cn':
                try:
                    price_df = ak.stock_zh_index_daily(symbol=symbol)
                    price_df = price_df[['date', 'close']].rename(columns={'date': '日期', 'close': '收盘'})
                except Exception:
                    # stock_zh_index_daily 不支持 csi 前缀代码，回退到中证指数历史行情
                    try:
                        logger.info('PRICE: primary API failed for {}, falling back to csindex'.format(symbol))
                        price_df = ak.stock_zh_index_hist_csindex(
                            symbol=index_id,
                            start_date='20180101',
                            end_date=self._latest_trade_day.replace('-', '')
                        )
                        if price_df.empty:
                            return False
                        price_df = price_df.rename(columns={'收盘': '点位'})
                        price_df = price_df[['日期', '点位']].copy()
                        # 后续会统一处理列名
                        price_df = price_df.rename(columns={'点位': '收盘'})
                    except Exception as e2:
                        logger.warning('PRICE: fallback also failed for {}: {}'.format(index_id, e2))
                        return False
            elif source_type == 'cni':
                # 国证指数历史行情: 987xxx/980xxx 代码
                try:
                    price_df = ak.index_hist_cni(symbol=symbol)
                    if price_df.empty:
                        logger.warning('PRICE: CNI index {} returned empty data'.format(symbol))
                        return False
                    price_df = price_df.rename(columns={'收盘价': '收盘'})
                    price_df = price_df[['日期', '收盘']].copy()
                    logger.info('PRICE: CNI index {} loaded {} rows from index_hist_cni'.format(symbol, len(price_df)))
                except Exception as e2:
                    logger.warning('PRICE: CNI index {} failed: {}'.format(symbol, str(e2)))
                    return False
            elif source_type == 'hk':
                price_df = ak.stock_hk_index_daily_sina(symbol=symbol)
                price_df = price_df[['date', 'close']].rename(columns={'date': '日期', 'close': '收盘'})
            elif source_type == 'us':
                try:
                    price_df = ak.index_us_stock_sina(symbol=symbol)
                    price_df = price_df[['date', 'close']].rename(columns={'date': '日期', 'close': '收盘'})
                except Exception:
                    logger.warning('PRICE: US index {} not supported by akshare, skipping'.format(symbol))
                    return False
            elif source_type == 'futures':
                price_df = ak.futures_zh_daily_sina(symbol=symbol)
                price_df = price_df[['date', 'close']].rename(columns={'date': '日期', 'close': '收盘'})
            elif source_type == 'gold':
                price_df = ak.spot_golden_benchmark_sge()
                price_df = price_df[['交易时间', '晚盘价']].rename(columns={'交易时间': '日期', '晚盘价': '收盘'})
            else:
                return False

            price_df['日期'] = pd.to_datetime(price_df['日期']).dt.strftime('%Y-%m-%d')
            price_df['指数代码'] = index_id
            price_df['指数名称'] = index_nm
            price_df['标签'] = index_tag
            price_df['数据类型'] = '点位'
            price_df['数据源'] = '指数行情'
            price_df = price_df[['日期', '指数代码', '指数名称', '标签', '收盘', '数据类型', '数据源']].set_index('日期')
            price_df = price_df.rename(columns={'收盘': '点位'})
            self.store_pe(index_id, old_df, price_df)
            return True
        except Exception as e:
            logger.error('PRICE: query {} failed because of {}'.format(index_id, str(e)))
            return False

    def _has_valid_data(self, df):
        """检查DB文件是否有有效数据（PE或点位至少一列有非空值）"""
        if df.empty:
            return False
        if '市盈率' in df.columns and df['市盈率'].notna().any():
            return True
        if '点位' in df.columns and df['点位'].notna().any():
            return True
        return False

    def update_db(self, max_workers=12):
        """更新指数数据库（PE/点位）。
        - 先对 index_id 去重，避免同一指数（被多只ETF复用）重复请求
        - 对需要真实请求的任务用线程池并发（HTTP IO 密集型，默认 12 线程提速 10x+）
        """
        df = self._load_etf_mapping()

        # —— Step 1: 按 index_id 去重（和 order() 一样按 avgamount 排序保留最大那行）
        #    834 个 ETF → ~274 个唯一指数，直接砍掉约 2/3 的循环迭代
        uniq = df.sort_values(by=['avgamount']).drop_duplicates(
            subset=['index_id'], keep='last', ignore_index=True)
        logger.info('update_db: total ETF {} rows -> dedup to {} unique indices'.format(len(df), len(uniq)))

        # —— Step 2: 逐个做"跳过/需要更新"判定（纯本地 IO，毫秒级）
        tasks = []   # 需要真实请求的条目列表: (i, index_id, index_name, index_tag, old_df)
        skipped = 0
        for i in range(len(uniq)):
            index_id = str(uniq['index_id'].iloc[i]).split('.')[0].upper()
            index_name = uniq['index_name'].iloc[i]
            index_tag = uniq['tag'].iloc[i]

            # 跳过不支持的指数
            if index_id in unsupported_index_ids:
                logger.info('{}: Skip unsupported index {}/{}'.format(i, index_id, index_name))
                skipped += 1
                continue

            old_df = self._load_index(index_id)
            need_update = True
            if not old_df.empty:
                if (str(old_df.index[-1]) >= self._latest_trade_day
                        and not self._rewrite
                        and self._has_valid_data(old_df)):
                    need_update = False
                    skipped += 1

            if need_update:
                tasks.append((i, index_id, index_name, index_tag, old_df))

        logger.info('update_db: {} skip (cached/unsupported), {} need fresh fetch'.format(skipped, len(tasks)))

        # —— Step 3: 快速路径：如果没有需要更新的，直接返回
        if not tasks:
            return

        # —— Step 4: 用线程池并发执行需要数据源请求的任务（IO 密集型）
        def _update_one(tup):
            i, index_id, index_name, index_tag, old_df = tup
            try:
                logger.info('{}: Update PE index for {}/{}'.format(i, index_id, index_name))

                is_cni = index_id.startswith('980') or index_id.startswith('987')
                first_tag = str(index_tag).split('，')[0] if pd.notna(index_tag) else ''
                is_non_equity = first_tag in ('商品', '债券')
                is_overseas_code = (
                    index_id.startswith('HS')
                    or index_id in ('SP500', 'DJI', 'NDX', 'NBI', 'SHAU', 'AU9999', 'M9999', 'ICEA')
                )
                skip_domestic_pe = is_non_equity or is_overseas_code

                pe_updated = self.update_jq(index_id, index_name, index_tag, old_df)

                if not pe_updated and not skip_domestic_pe and not is_cni:
                    pe_updated = self.update_zz(index_id, index_name, index_tag, old_df)

                if not pe_updated and not skip_domestic_pe:
                    pe_updated = self.update_gz(index_id, index_name, index_tag, old_df)

                if not pe_updated and not skip_domestic_pe and not is_cni:
                    pe_updated = self.update_csindex(index_id, index_name, index_tag, old_df)

                if not pe_updated:
                    self.update_price(index_id, index_name, index_tag, old_df)

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


if __name__ == "__main__":
    work_path = os.path.dirname(os.path.realpath(__file__))
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    logger.info('work_path: {}'.format(work_path))
    
    pe = Pe(work_path)
    pe.update_db()
    pe.order()
