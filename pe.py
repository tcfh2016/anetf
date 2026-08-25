# -*- coding:utf-8 -*-
"""
Date: 2024-05-02
Desc: 更新ETF对应的指数的市盈率
"""

import os
import logging
import pandas as pd
import numpy as np
import akshare as ak

from ext import jq

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
        
        self._db_path = os.path.join(work_path, 'db')
        self._mail_path = os.path.join(work_path, 'mail')  
        self._index_file_path = os.path.join(work_path, 'tmp', 'index.csv')
        self._gz_df = ak.index_all_cni().set_index('指数代码')

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
        df = pd.read_csv(self._index_file_path, usecols=['name', 'code', 'tag', 'avgamount', 'index_name', 'index_id'])
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
            index_file = os.path.join(self._db_path, index_id + '.csv')

            if os.access(index_file, os.R_OK):
                etf_df = pd.read_csv(index_file, dtype={'指数代码':'object'})
                has_pe_col = '市盈率' in etf_df.columns
                has_point_col = '点位' in etf_df.columns

                # 确定有效数据列：优先PE，PE全为空时降级用点位
                pe_valid = has_pe_col and pd.notna(etf_df['市盈率'].iloc[-1])
                point_valid = has_point_col and pd.notna(etf_df['点位'].iloc[-1])

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
                    data_types.append('点位')
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
        drop_duplicate_df['估值'] = values
        drop_duplicate_df['估值百分位'] = value_percentile
        drop_duplicate_df['估值类型'] = data_types
                
        def sort_and_save(etf_subset, filename, label):
            etf_subset = etf_subset.sort_values(by=['估值', '估值百分位']).reset_index(drop=True)
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

    def store_pe(self, index_id, old_df, new_df):
        db_file = os.path.join(self._db_path, index_id + '.csv')

        try:
            if self._rewrite or old_df.empty:
                new_df.to_csv(db_file)
            else:
                # pe数据无更新
                if old_df.index[-1] == new_df.index[-1]:
                    return
                if len(new_df) > 1:
                    diff = new_df[new_df.index > old_df.index[-1]]
                else:
                    diff = new_df

                if diff.empty:
                    return
                logger.debug(diff)
                pd.concat([old_df, diff]).to_csv(db_file)
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

    def update_db(self):
        df = pd.read_csv(self._index_file_path)

        for i in range(len(df)):
            index_id = df['index_id'].iloc[i].split('.')[0].upper()
            index_name = df['index_name'].iloc[i]
            index_tag = df['tag'].iloc[i]

            # 跳过不支持数据获取的指数，避免无意义请求
            if index_id in unsupported_index_ids:
                logger.info('{}: Skip unsupported index {}/{}'.format(i, index_id, index_name))
                continue

            logger.info('{}: Update PE index for {}/{}'.format(i, index_id, index_name))

            db_file = os.path.join(self._db_path, index_id + '.csv')
            need_update = True
            if os.access(db_file, os.R_OK):
                old_df = pd.read_csv(db_file, index_col=0, dtype={'指数代码':'object'})
                # 只有当数据有有效内容 且 日期是最新的 才跳过更新
                if str(old_df.index[-1]) >= self._latest_trade_day and not self._rewrite and self._has_valid_data(old_df):
                    logger.info('No new data need to be updated')
                    need_update = False
            else:
                old_df = pd.DataFrame(columns=['日期', '指数代码', '指数名称', '市盈率', '数据源'])
            
            if not need_update:
                continue
         
            # 首先查找韭圈儿的估值信息，因为最全，包括了国内、国外的主要指数多年的数据
            if not self.update_jq(index_id, index_name, index_tag, old_df):
                # 其次查找中证官网的估值信息，包括数天的估值信息
                if not self.update_zz(index_id, index_name, index_tag, old_df):
                    # 再查找国证网站的估值信息，仅包含最近交易日的估值信息
                    if not self.update_gz(index_id, index_name, index_tag, old_df):
                        # 再从中证指数历史行情获取PE（覆盖中证系列全量指数）
                        if not self.update_csindex(index_id, index_name, index_tag, old_df):
                            # 最后降级为获取指数点位，用于没有PE的指数（商品、债券、海外等）
                            self.update_price(index_id, index_name, index_tag, old_df)


if __name__ == "__main__":
    work_path = os.path.dirname(os.path.realpath(__file__))
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    logger.info('work_path: {}'.format(work_path))
    
    pe = Pe(work_path)
    pe.update_db()
    pe.order()
