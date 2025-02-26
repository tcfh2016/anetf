# -*- coding:utf-8 -*-
"""
Date: 2024-05-01
Desc: 获取ETF列表
"""

import os
import requests
import pandas as pd
import akshare as ak
from pathlib import Path
from ext import jq

tmp_path = os.path.join(Path(os.getcwd()), 'tmp')

def info_rows() -> list:
    # 集思录: https://www.jisilu.cn/data/etf/#index
    # 不足之处：没有中概互联网513050
    #url = 'https://www.jisilu.cn/data/etf/etf_list/'
    #params = {
    #        "___jsl": "LST___t=1714532238732",
    #        "rp": "25",
    #        "page": "1 HTTP/1.1",
    #    }
    #
    #r = requests.get(url, params=params)
    #if r.status_code == 200:
    #    return r.json()['rows']
    #return None

    # 备选数据源，ETF组合宝：http://www.etf.group/data/list1.html
    url = 'http://www.etf.group/data/api1.php'
    r = requests.get(url)
    if r.status_code == 200:
        return r.json()['rows']['item']
    return None

def etf_info() -> pd.DataFrame:
    rows = info_rows()
    if not rows:
        print('no valid data when calling info_rows()')
    
    #集思录数据处理 
    #cells = [row['cell'] for row in rows] 
    #df = pd.DataFrame(cells).astype({'volume':float})
    ## 过滤成交额大于1000万，过滤债券ETF
    #df = df[(df['volume'] > 1000) & (df['fund_nm'].str.find('债') == -1)]
    
    #组合宝数据处理，获取日均交易额大于1亿的ETF
    df = pd.DataFrame(rows)
    df = df[(df['avgamount'] > 1000) & (df['name'].str.find('债') == -1)].reset_index(drop=True)
    df.to_csv(os.path.join(tmp_path, 'etf.csv'))

    return df

def find_index_id(name) -> tuple:
    # 先从韭圈儿找，指数代码带后缀，如000994.CSI，399102.SZ，HSTECH.HI
    for i in range(len(jq_df)):
        if name.find(jq_df['指数名称'][i]) != -1:
            return (jq_df['指数名称'][i], jq_df['指数代码'][i])

    # 再从国证指数里找，不带后缀，如399606，980009，CN2312
    for i in range(len(gz_df)):
        if name.find(gz_df['指数简称'][i]) != -1:
            return (gz_df['指数简称'][i], gz_df['指数代码'][i])

    # 最后从聚宽指数里找，不带后缀，如000001，399335
    for i in range(len(jk_df)):
        if name.find(jk_df['display_name'][i]) != -1:
            return (jk_df['display_name'][i], jk_df['index_code'][i])

    print("Can't find index info for {}".format(name))
    return (None, None)


def etf_map2_index():
    etfs = etf_info()

    names, ids = [], []
    for i in range(len(etfs)):
        #print('{}: start to query:{}'.format(i, etfs['index'][i]))
        (index_name, index_id) = find_index_id(etfs['index'][i])
        names.append(index_name)
        ids.append(index_id)

    etfs['index_name'] = names
    etfs['index_id'] = ids
    etfs = etfs[pd.notnull(etfs['index_id'])].reset_index(drop=True)
    etfs.to_csv(os.path.join(tmp_path, 'index.csv'))
    print(etfs)


if __name__ == "__main__":
    #,指数名称,最新PE,PE分位,最新PB,PB分位,股息率,股息率分位,指数代码,指数开始时间,更新时间
    #0,道琼斯美国石油开发与生产,8.29,0.77,2.72,82.61,3.88,81.96,DJSOEP.GI,2013-03-26,2024-04-30
    jq_df = jq.index_value_name_funddb()

    #,指数代码,指数简称,样本数,收盘点位,涨跌幅,PE滚动,成交量,成交额,总市值,自由流通市值
    #0,399001,深证成指,500,9587.1245,-0.009,19.0429,181681.14304,2578.7084342458998,191649.0203326368,98553.23325393882
    gz_df = ak.index_all_cni()

    #,index_code,display_name,publish_date
    #0,000001,上证指数,1991-07-15
    jk_df = ak.index_stock_info().astype({'index_code':str})

    etf_map2_index()