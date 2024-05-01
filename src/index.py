import numpy as np
import pandas as pd
import akshare as ak
import etf

#,指数名称,最新PE,PE分位,最新PB,PB分位,股息率,股息率分位,指数代码,指数开始时间,更新时间
#0,道琼斯美国石油开发与生产,8.29,0.77,2.72,82.61,3.88,81.96,DJSOEP.GI,2013-03-26,2024-04-30
jq_df = ak.index_value_name_funddb()

#,指数代码,指数简称,样本数,收盘点位,涨跌幅,PE滚动,成交量,成交额,总市值,自由流通市值
#0,399001,深证成指,500,9587.1245,-0.009,19.0429,181681.14304,2578.7084342458998,191649.0203326368,98553.23325393882
gz_df = ak.index_all_cni()

#,index_code,display_name,publish_date
#0,000001,上证指数,1991-07-15
jk_df = ak.index_stock_info().astype({'index_code':str})


def find_index_id(name) -> tuple:
    # 先从韭圈儿找
    for i in range(len(jq_df)):
        if name.find(jq_df['指数名称'][i]) != -1:
            return (jq_df['指数名称'][i], jq_df['指数代码'][i])

    # 再从国证指数里找
    for i in range(len(gz_df)):
        if name.find(gz_df['指数简称'][i]) != -1:
            return (gz_df['指数简称'][i], gz_df['指数代码'][i])

    # 最后从聚宽指数里找
    for i in range(len(jk_df)):
        if name.find(jk_df['display_name'][i]) != -1:
            return (jk_df['display_name'][i], jk_df['index_code'][i])

    print("Can't find index info for {}".format(name))
    return (None, None)


def index():
    etfs = etf.etf_info().copy()

    names, ids = [], []
    for i in range(len(etfs)):
        #print('{}: start to query:{}'.format(i, etfs['index'][i]))
        (index_name, index_id) = find_index_id(etfs['index'][i])
        names.append(index_name)
        ids.append(index_id)

    etfs['index_name'] = names
    etfs['index_id'] = ids
    etfs = etfs[pd.notnull(etfs['index_id'])].reset_index(drop=True)
    etfs.to_csv('index.csv')
    print(etfs)


if __name__ == "__main__":
    index()
