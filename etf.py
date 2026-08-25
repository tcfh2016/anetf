# -*- coding:utf-8 -*-
"""
Date: 2024-05-01
Desc: 获取ETF列表
"""

import os
import logging
import requests
import pandas as pd
import akshare as ak
from pathlib import Path
from ext import jq

logger = logging.getLogger(__name__)

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
    logger.warning('Failed to fetch ETF info, status code: {}'.format(r.status_code))
    return None

def etf_info() -> pd.DataFrame:
    rows = info_rows()
    if not rows:
        logger.error('No valid data when calling info_rows()')
    
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

etf_index_mapping_table = {
    # ETF列表里面的“指数名称”，指数列表里面的“指数名称”，指数列表里面的“指数代码”
    '港股通内地金融港元指数':['中证香港银行投资指数', '930792']
}

def find_index_id(name, jq_df, gz_df, jk_df) -> tuple:
    # 先查手动定义的映射表
    if name in etf_index_mapping_table:
        values = etf_index_mapping_table[name]
        return (values[0], values[1])

    # 先从韭圈儿找，指数代码带后缀，如000994.CSI，399102.SZ，HSTECH.HI
    for _, row in jq_df.iterrows():
        if name.find(row['指数名称']) != -1:
            return (row['指数名称'], row['指数代码'])

    # 再从国证指数里找，不带后缀，如399606，980009，CN2312
    for _, row in gz_df.iterrows():
        if name.find(row['指数简称']) != -1:
            return (row['指数简称'], row['指数代码'])

    # 最后从聚宽指数里找，不带后缀，如000001，399335
    for _, row in jk_df.iterrows():
        if name.find(row['display_name']) != -1:
            return (row['display_name'], row['index_code'])

    logger.warning("Can't find index info for {}".format(name))
    return (None, None)


def etf_map2_index(jq_df, gz_df, jk_df):
    etfs = etf_info()

    names, ids = [], []
    for i in range(len(etfs)):
        (index_name, index_id) = find_index_id(etfs['index'][i], jq_df, gz_df, jk_df)
        names.append(index_name)
        ids.append(index_id)

    etfs['index_name'] = names
    etfs['index_id'] = ids
    etfs = etfs[pd.notnull(etfs['index_id'])].reset_index(drop=True)
    etfs.to_csv(os.path.join(tmp_path, 'index.csv'))
    logger.info('Mapped ETF to index, total: {}'.format(len(etfs)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')

    #,指数名称,最新PE,PE分位,最新PB,PB分位,股息率,股息率分位,指数代码,指数开始时间,更新时间
    jq_df = jq.index_value_name_funddb()

    #,指数代码,指数简称,样本数,收盘点位,涨跌幅,PE滚动,成交量,成交额,总市值,自由流通市值
    gz_df = ak.index_all_cni()

    #,index_code,display_name,publish_date
    jk_df = ak.index_stock_info().astype({'index_code':str})

    etf_map2_index(jq_df, gz_df, jk_df)