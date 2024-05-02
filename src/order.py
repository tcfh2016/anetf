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
    df = pd.read_csv(index_file_path, usecols=['name', 'code', 'index_name', 'index_id'])

    pe, pe_percentile = [], []
    for i in range(len(df)):
        index_id = df['index_id'].iloc[i].split('.')[0].upper()
        etf_df = pd.read_csv(os.path.join(db_path, index_id + '.csv'))

        pe.append(etf_df['市盈率'].iloc[-1])
        if len(etf_df) > 500:
            pe_percentile.append(calc_percentile(etf_df['市盈率']))
        else:
            pe_percentile.append(np.nan)

    df['市盈率'] = pe
    df['市盈率百分位'] = pe_percentile
    df = df.sort_values(by=['市盈率百分位']).reset_index(drop=True)
    df.to_csv('etf_sorted.csv')
    print(df)


if __name__ == '__main__':
    order()