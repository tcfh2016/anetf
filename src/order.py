# -*- coding:utf-8 -*-
"""
Date: 2024-05-02
Desc: ETF按市盈率排序
"""

import os
import pandas as pd
import numpy as np
from pathlib import Path

index_file_path = os.path.join(os.getcwd(), 'index.csv')
db_path = os.path.join(Path(os.getcwd()).parent, 'db')

def calc_percentile(arr):
    lower = arr[arr < arr.iloc[-1]]
    return(lower.shape[0] / arr.shape[0])

def order():
    # 由于多只ETF跟踪相同指数，所以先进行去重操作，只保留成交量最高的ETF
    df = pd.read_csv(index_file_path, usecols=['name', 'code', 'tag', 'avgamount', 'index_name', 'index_id'])
    drop_duplicate_df = df.sort_values(by=['avgamount']).drop_duplicates(subset=['index_id'], keep='first')
    print('ETF number: {}, drop to {} after remove duplicated ETF.'.format(len(df), len(drop_duplicate_df)))
    

    # 填充ETF的最新市盈率，以及市盈率百分位（有至少500个交易日的数据）
    pe, pe_percentile = [], []
    for i in range(len(drop_duplicate_df)):
        index_id = drop_duplicate_df['index_id'].iloc[i].split('.')[0].upper()
        etf_pe = pd.read_csv(os.path.join(db_path, index_id + '.csv'))

        pe.append(etf_pe['市盈率'].iloc[-1])
        if len(etf_pe) > 500:
            pe_percentile.append(calc_percentile(etf_pe['市盈率']))
        else:
            pe_percentile.append(np.nan)

    drop_duplicate_df['市盈率'] = pe
    drop_duplicate_df['市盈率百分位'] = pe_percentile

    
    # 将ETF分割为“宽基”和“非宽基”两类
    broad_etf = drop_duplicate_df[drop_duplicate_df['tag'].str.find('宽基') != -1]
    broad_etf = broad_etf.sort_values(by=['市盈率', '市盈率百分位']).reset_index(drop=True)
    broad_etf.to_csv('etf_broad_sorted.csv')
    print(broad_etf)

    other_etf = drop_duplicate_df[drop_duplicate_df['tag'].str.find('宽基') == -1]
    other_etf = other_etf.sort_values(by=['市盈率百分位', '市盈率']).reset_index(drop=True)
    other_etf.to_csv('etf_other_sorted.csv')
    print(other_etf)


if __name__ == '__main__':
    order()