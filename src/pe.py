import os
import pandas as pd
import akshare as ak
from pathlib import Path

import index

gz_df = ak.index_all_cni().set_index('指数代码')
db_path = os.path.join(Path(os.getcwd()).parent, 'db')
index_file_path = os.path.join(os.getcwd(), 'index.csv')


class Pe(object):
    def __init__(self):
        df = ak.stock_zh_a_hist(symbol='000001', period='daily', start_date='20240301', adjust="")
        self._latest_trade_day = df['日期'].iloc[-1]
        self._rewrite = True

    def store_pe(self, index_id, new_df):
        db_file = os.path.join(db_path, index_id + '.csv')

        try:
            if self._rewrite or not os.access(db_file, os.R_OK):
                new_df.to_csv(db_file)
            else:
                old_df = pd.read_csv(db_file, index_col=0)
                if old_df.index[-1] < self._latest_trade_day:
                    diff = new_df[old_df.index[-1]:]
                    print(diff)
                    pd.concat([old_df, diff]).to_csv(db_file)
                else:
                    print('No new data need to be updated')
        except Exception as e:
            print('Store pe for {} failed becuse of {}'.format(index_id, str(e)))

    # 从韭圈儿获取市盈率并更新
    def update_jq(self, index_id, index_nm):
        try:
            print('JQ: Update PE index id({}), name({})'.format(index_id, index_nm))
            new_df = ak.index_value_hist_funddb(symbol=index_nm)
            new_df['指数代码'] = index_id
            new_df['指数名称'] = index_nm
            new_df['数据源'] = '韭圈儿'
            new_df = new_df[['日期', '指数代码', '指数名称', '市盈率', '数据源']].set_index('日期')
            #print(new_df)
            self.store_pe(index_id, new_df)
            return True
        except Exception as e:
            print('JQ: query {} failed becuse of {}'.format(index_id, str(e)))
            return False

    # 更新中证指数的市盈率
    def update_zz(self, index_id, index_nm):
        try:
            print('ZZ: Update PE index id({})'.format(index_id))
            new_df = ak.stock_zh_index_value_csindex(symbol=index_id)
            new_df['指数名称'] = index_nm
            new_df['数据源'] = '中证指数'
            new_df = new_df.sort_values(by=['日期']).set_index('日期')[['指数代码', '指数名称', '市盈率1', '数据源']].rename(columns={'市盈率1':'市盈率'})
            #print(new_df)
            self.store_pe(index_id, new_df)
            return True
        except Exception as e:
            print('ZZ: query {} failed becuse of {}'.format(index_id, str(e)))
        return False
    
    # 从国证网站获取市盈率并更新
    def update_gz(self, index_id, index_nm):
        print('GZ: Update PE index id({})'.format(index_id, index_nm))

        if index_id in gz_df.index:
            record = [self._latest_trade_day, index_id, index_nm, gz_df.loc[index_id, 'PE滚动'], '国证指数']
            new_df = pd.DataFrame([record], columns=['日期', '指数代码', '指数名称', '市盈率', '数据源'])
            #print(new_df)
            self.store_pe(index_id, new_df)
        else:
            print('Update {} failed.'.format(index_id))

    def update_db(self):
        df = pd.read_csv(index_file_path)

        for i in range(len(df)):
            index_id = df['index_id'].iloc[i].split('.')[0].upper()
            index_name = df['index_name'].iloc[i]

            # 首先查找韭圈儿的估值信息，因为最全，包括了国内、国外的主要指数多年的数据
            if not self.update_jq(index_id, index_name):
                # 其次查找中证官网的估值信息，包括数天的估值信息
                if not self.update_zz(index_id, index_name):
                    # 最后查找国证网站的估值信息，仅包含最近交易日的估值信息
                    self.update_gz(index_id, index_name)


if __name__ == "__main__":
    pe = Pe()
    pe.update_db()
