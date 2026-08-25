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
    lower = arr[arr < arr.iloc[-1]]
    return(lower.shape[0] / arr.shape[0])

class Pe(object):
    def __init__(self, work_path):
        df = ak.stock_zh_a_daily(symbol="sz000001", start_date="20240301", adjust="qfq")
        self._latest_trade_day = str(df['date'].iloc[-1])
        self._rewrite = False
        
        self._db_path = os.path.join(work_path, 'db')
        self._mail_path = os.path.join(work_path, 'mail')  
        self._index_file_path = os.path.join(work_path, 'tmp', 'index.csv')
        self._gz_df = ak.index_all_cni().set_index('指数代码')

    def order(self):
        # 由于多只ETF跟踪相同指数，所以先进行去重操作，只保留成交量最高的ETF
        df = pd.read_csv(self._index_file_path, usecols=['name', 'code', 'tag', 'avgamount', 'index_name', 'index_id'])
        drop_duplicate_df = df.sort_values(by=['avgamount']).drop_duplicates(subset=['index_id'], keep='last')
        logger.info('ETF number: {}, drop to {} after remove duplicated ETF.'.format(len(df), len(drop_duplicate_df)))        

        # 填充ETF的最新估值和百分位
        # 股票类ETF用市盈率(PE)，非股票类ETF用指数点位
        values, value_percentile, data_types = [], [], []
        for i in range(len(drop_duplicate_df)):
            index_id = drop_duplicate_df['index_id'].iloc[i].split('.')[0].upper()            
            index_file = os.path.join(self._db_path, index_id + '.csv')

            if os.access(index_file, os.R_OK):
                etf_df = pd.read_csv(index_file, dtype={'指数代码':'object'})
                has_pe_col = '市盈率' in etf_df.columns
                data_type = etf_df['数据类型'].iloc[-1] if '数据类型' in etf_df.columns else 'PE'

                if data_type == 'PE' and has_pe_col:
                    val = etf_df['市盈率'].iloc[-1]
                    values.append(val)
                    if len(etf_df) > 500:
                        value_percentile.append(calc_percentile(etf_df['市盈率']))
                    else:
                        value_percentile.append(np.nan)
                    data_types.append('PE')
                else:
                    # 点位百分位
                    val = etf_df['点位'].iloc[-1] if '点位' in etf_df.columns else np.nan
                    values.append(val)
                    if '点位' in etf_df.columns and len(etf_df) > 500:
                        value_percentile.append(calc_percentile(etf_df['点位']))
                    else:
                        value_percentile.append(np.nan)
                    data_types.append('点位')
            else:
                values.append(np.nan)
                value_percentile.append(np.nan)
                data_types.append('')

        drop_duplicate_df.columns = ['ETF名称', 'ETF代码', '标签', '平均成交额', '指数名称', '指数代码']
        drop_duplicate_df['市盈率'] = values
        drop_duplicate_df['市盈率百分位'] = value_percentile
        drop_duplicate_df['数据类型'] = data_types
                
        def sort_and_save(etf_subset, filename, label):
            etf_subset = etf_subset.sort_values(by=['市盈率', '市盈率百分位']).reset_index(drop=True)
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
    def update_jq(self, index_id, index_nm, index_tag, old_df):
        try:
            logger.info('JQ: Update PE index id({}), name({})'.format(index_id, index_nm))
            new_df = jq.index_value_hist_funddb(symbol=index_nm).astype({'日期':str})
            new_df['指数代码'] = index_id
            new_df['指数名称'] = index_nm
            new_df['标签'] = index_tag
            new_df['数据源'] = '韭圈儿'
            new_df = new_df[['日期', '指数代码', '指数名称', '标签', '市盈率', '数据源']].set_index('日期')
            
            self.store_pe(index_id, old_df, new_df)
            return True
        except Exception as e:
            logger.error('JQ: query {} failed because of {}'.format(index_id, str(e)))
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
            record = [self._latest_trade_day, index_id, index_nm, index_tag, self._gz_df.loc[index_id, 'PE滚动'], '国证指数']
            new_df = pd.DataFrame([record], columns=['日期', '指数代码', '指数名称', '标签', '市盈率', '数据源'])
            new_df = new_df.set_index('日期')
            logger.debug(new_df)
            self.store_pe(index_id, old_df, new_df)
        else:
            logger.warning('Update {} failed, index not found in gz_df.'.format(index_id))

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
        """根据指数代码推断行情数据获取方式"""
        if index_id.startswith('HS') or index_id.startswith('HSC'):
            return ('hk', index_id)
        if index_id in ('AU9999', 'SHAU'):
            return ('gold', None)
        if index_id == 'M9999':
            return ('futures', 'M0')
        if index_id == 'ICEA':
            return None
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
                price_df = ak.stock_zh_index_daily(symbol=symbol)
                price_df = price_df[['date', 'close']].rename(columns={'date': '日期', 'close': '收盘'})
            elif source_type == 'hk':
                price_df = ak.stock_hk_index_daily_sina(symbol=symbol)
                price_df = price_df[['date', 'close']].rename(columns={'date': '日期', 'close': '收盘'})
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

    def update_db(self):
        df = pd.read_csv(self._index_file_path)

        for i in range(len(df)):
            index_id = df['index_id'].iloc[i].split('.')[0].upper()
            index_name = df['index_name'].iloc[i]
            index_tag = df['tag'].iloc[i]
            logger.info('{}: Update PE index for {}/{}'.format(i, index_id, index_name))

            db_file = os.path.join(self._db_path, index_id + '.csv')
            if os.access(db_file, os.R_OK):
                old_df = pd.read_csv(db_file, index_col=0, dtype={'指数代码':'object'})                
                if str(old_df.index[-1]) >= self._latest_trade_day and not self._rewrite:
                    logger.info('No new data need to be updated')
                    continue
            else:
                old_df = pd.DataFrame(columns=['日期', '指数代码', '指数名称', '市盈率', '数据源'])
         
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
