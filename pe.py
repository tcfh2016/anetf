# -*- coding:utf-8 -*-
"""
Date: 2024-05-02
Desc: 更新ETF对应的指数的市盈率
"""

import os
import pandas as pd
import numpy as np
import akshare as ak

gz_df = ak.index_all_cni().set_index('指数代码')

def calc_percentile(arr):
    lower = arr[arr < arr.iloc[-1]]
    return(lower.shape[0] / arr.shape[0])

class Pe(object):
    def __init__(self, work_path):
        df = ak.stock_zh_a_hist(symbol='000001', period='daily', start_date='20240301', adjust="")
        self._latest_trade_day = str(df['日期'].iloc[-1])
        self._rewrite = False
        
        self._db_path = os.path.join(work_path, 'db')
        self._mail_path = os.path.join(work_path, 'mail')  
        self._index_file_path = os.path.join(work_path, 'tmp', 'index.csv')
        #print('db path:{}, index:{}'.format(self._db_path, self._index_file_path))

    def order(self):
        # 由于多只ETF跟踪相同指数，所以先进行去重操作，只保留成交量最高的ETF
        df = pd.read_csv(self._index_file_path, usecols=['name', 'code', 'tag', 'avgamount', 'index_name', 'index_id'])
        drop_duplicate_df = df.sort_values(by=['avgamount']).drop_duplicates(subset=['index_id'], keep='last')
        print('ETF number: {}, drop to {} after remove duplicated ETF.'.format(len(df), len(drop_duplicate_df)))        

        # 填充ETF的最新市盈率，以及市盈率百分位（有至少500个交易日的数据）
        pe, pe_percentile = [], []
        for i in range(len(drop_duplicate_df)):
            index_id = drop_duplicate_df['index_id'].iloc[i].split('.')[0].upper()
            etf_pe = pd.read_csv(os.path.join(self._db_path, index_id + '.csv'))

            pe.append(etf_pe['市盈率'].iloc[-1])
            if len(etf_pe) > 500:
                pe_percentile.append(calc_percentile(etf_pe['市盈率']))
            else:
                pe_percentile.append(np.nan)

        drop_duplicate_df.columns = ['ETF名称', 'ETF代码', '标签', '平均成交额', '指数名称', '指数代码']
        drop_duplicate_df['市盈率'] = pe
        drop_duplicate_df['市盈率百分位'] = pe_percentile
        
        # 将ETF分割为“宽基”和“非宽基”两类
        broad_etf = drop_duplicate_df[drop_duplicate_df['标签'].str.find('宽基') != -1]
        broad_etf = broad_etf.sort_values(by=['市盈率', '市盈率百分位']).reset_index(drop=True)
        broad_etf.to_csv(os.path.join(self._mail_path, 'etf_broad_sorted.csv'))
        print(broad_etf)

        other_etf = drop_duplicate_df[drop_duplicate_df['标签'].str.find('宽基') == -1]
        other_etf = other_etf.sort_values(by=['市盈率', '市盈率百分位']).reset_index(drop=True)
        other_etf.to_csv(os.path.join(self._mail_path, 'etf_other_sorted.csv'))
        print(other_etf)

    def store_pe(self, index_id, old_df, new_df):
        db_file = os.path.join(self._db_path, index_id + '.csv')

        try:
            if self._rewrite:
                new_df.to_csv(db_file)
            else:
                # pe数据无更新
                if old_df.index[-1] == new_df.index[-1]:
                    return
                if len(new_df) > 1:
                    diff = new_df[old_df.index[-1]:][1:]
                else:
                    diff = new_df

                print(diff)
                pd.concat([old_df, diff]).to_csv(db_file)
        except Exception as e:
            print('Store pe for {} failed becuse of {}'.format(index_id, str(e)))

    # 从韭圈儿获取市盈率并更新
    def update_jq(self, index_id, index_nm, index_tag, old_df):
        try:
            print('JQ: Update PE index id({}), name({})'.format(index_id, index_nm))
            new_df = ak.index_value_hist_funddb(symbol=index_nm).astype({'日期':str})
            new_df['指数代码'] = index_id
            new_df['指数名称'] = index_nm
            new_df['标签'] = index_tag
            new_df['数据源'] = '韭圈儿'
            new_df = new_df[['日期', '指数代码', '指数名称', '标签', '市盈率', '数据源']].set_index('日期')
            #print(new_df)
            self.store_pe(index_id, old_df, new_df)
            return True
        except Exception as e:
            print('JQ: query {} failed becuse of {}'.format(index_id, str(e)))
            return False

    # 更新中证指数的市盈率
    def update_zz(self, index_id, index_nm, index_tag, old_df):
        try:
            print('ZZ: Update PE index id({})'.format(index_id))
            new_df = ak.stock_zh_index_value_csindex(symbol=index_id).astype({'日期':str})
            new_df['指数名称'] = index_nm
            new_df['标签'] = index_tag
            new_df['数据源'] = '中证指数'
            new_df = new_df.sort_values(by=['日期']).set_index('日期')[['指数代码', '指数名称', '标签', '市盈率1', '数据源']].rename(columns={'市盈率1':'市盈率'})
            #print(new_df)
            self.store_pe(index_id, old_df, new_df)
            return True
        except Exception as e:
            print('ZZ: query {} failed becuse of {}'.format(index_id, str(e)))
        return False
    
    # 从国证网站获取市盈率并更新
    def update_gz(self, index_id, index_nm, index_tag, old_df):
        print('GZ: Update PE index id({})'.format(index_id, index_nm))

        if index_id in gz_df.index:
            record = [self._latest_trade_day, index_id, index_nm, index_tag, gz_df.loc[index_id, 'PE滚动'], '国证指数']
            new_df = pd.DataFrame([record], columns=['日期', '指数代码', '指数名称', '标签', '市盈率', '数据源'])
            new_df = new_df.set_index('日期')
            #print(new_df)
            self.store_pe(index_id, old_df, new_df)
        else:
            print('Update {} failed.'.format(index_id))

    def update_db(self):
        df = pd.read_csv(self._index_file_path)

        for i in range(len(df)):
            index_id = df['index_id'].iloc[i].split('.')[0].upper()
            index_name = df['index_name'].iloc[i]
            index_tag = df['tag'].iloc[i]
            print('{}: Update PE index for {}/{}'.format(i, index_id, index_name))

            db_file = os.path.join(self._db_path, index_id + '.csv')
            if os.access(db_file, os.R_OK):
                old_df = pd.read_csv(db_file, index_col=0)
                if str(old_df.index[-1]) >= self._latest_trade_day and not self._rewrite:
                    print('No new data need to be updated')
                    continue
            else:
                old_df = pd.DataFrame(columns=['日期', '指数代码', '指数名称', '市盈率', '数据源'])
         
            # 首先查找韭圈儿的估值信息，因为最全，包括了国内、国外的主要指数多年的数据
            if not self.update_jq(index_id, index_name, index_tag, old_df):
                # 其次查找中证官网的估值信息，包括数天的估值信息
                if not self.update_zz(index_id, index_name, index_tag, old_df):
                    # 最后查找国证网站的估值信息，仅包含最近交易日的估值信息
                    self.update_gz(index_id, index_name, index_tag, old_df)


if __name__ == "__main__":
    work_path = os.getcwd()
    print('work_path: {}'.format(work_path))
    
    pe = Pe(work_path)
    pe.update_db()
    pe.order()
