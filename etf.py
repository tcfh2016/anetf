# -*- coding:utf-8 -*-
"""
Date: 2024-05-01
Desc: 获取ETF列表

阶段 1 重构：常量与 DB 访问下沉到 anetf 包，业务逻辑不变。
"""

import logging
import requests
import pandas as pd
import akshare as ak

from anetf.constants import ETF_INDEX_MAPPING_TABLE, ETF_TAG_OVERRIDES
from anetf.db.connection import Database
from anetf.db.etf_repo import EtfRepository
from anetf.datasources import juquaner as jq

logger = logging.getLogger(__name__)


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

    #组合宝数据处理，获取日均交易额大于1亿的ETF，并修正标签
    df = pd.DataFrame(rows)
    df = df[(df['avgamount'] > 1000) & (df['name'].str.find('债') == -1)].reset_index(drop=True)
    df = fix_etf_tags(df)

    return df


def fix_etf_tags(df) -> pd.DataFrame:
    """修正数据源缺失或错误的ETF标签"""
    codes = df['code'].astype(str)
    for code, tag in ETF_TAG_OVERRIDES.items():
        df.loc[codes == code, 'tag'] = tag
    return df

def _match_name(etf_index_name, ref_name) -> bool:
    """双向子串匹配：检查ETF指数名称与参考指数名称是否相关"""
    # 正向：参考名称是ETF指数名称的子串
    if ref_name in etf_index_name:
        return True
    # 反向：ETF指数名称去掉"指数"后缀后，是参考名称的子串
    stripped = etf_index_name.replace('指数', '')
    if len(stripped) >= 2 and stripped in ref_name:
        return True
    return False


def _normalize(name) -> str:
    """去掉指数名称中的币种、后缀等修饰词，用于精确匹配"""
    for suffix in ('人民币', '港元', '港币'):
        name = name.replace(suffix, '')
    name = name.replace('指数', '')
    return name.strip()


def find_index_id(name, jq_df, gz_df, jk_df, cs_df) -> tuple:
    # 先查手动定义的映射表
    if name in ETF_INDEX_MAPPING_TABLE:
        values = ETF_INDEX_MAPPING_TABLE[name]
        return (values[0], values[1])

    # 第一遍：精确匹配（归一化后相等），避免模糊匹配因遍历顺序命中近似指数，
    # 例如"沪深300"错配到"沪深300周期"、"中证A500"错配到"中证A50"
    norm_name = _normalize(name)
    ref_sources = [
        (jq_df, '指数名称', '指数代码'), (gz_df, '指数简称', '指数代码'),
        (jk_df, 'display_name', 'index_code'), (cs_df, '指数简称', '指数代码'),
    ]
    for ref_df, name_col, code_col in ref_sources:
        for _, row in ref_df.iterrows():
            if norm_name and _normalize(row[name_col]) == norm_name:
                if ref_df is cs_df:
                    return (row['指数简称'], row[code_col])
                return (row[name_col], row[code_col])
    # 中证指数全量列表还需要用全称做一次精确匹配
    for _, row in cs_df.iterrows():
        if norm_name and _normalize(row['指数全称']) == norm_name:
            return (row['指数简称'], row['指数代码'])

    # 第二遍：模糊匹配（双向子串）
    # 再从韭圈儿找，指数代码带后缀，如000994.CSI，399102.SZ，HSTECH.HI
    for _, row in jq_df.iterrows():
        if _match_name(name, row['指数名称']):
            return (row['指数名称'], row['指数代码'])

    # 再从国证指数里找，不带后缀，如399606，980009，CN2312
    for _, row in gz_df.iterrows():
        if _match_name(name, row['指数简称']):
            return (row['指数简称'], row['指数代码'])

    # 再从聚宽指数里找，不带后缀，如000001，399335
    for _, row in jk_df.iterrows():
        if _match_name(name, row['display_name']):
            return (row['display_name'], row['index_code'])

    # 最后从中证指数全量列表找，2356个指数，同时匹配简称和全称
    for _, row in cs_df.iterrows():
        if _match_name(name, row['指数简称']) or _match_name(name, row['指数全称']):
            return (row['指数简称'], row['指数代码'])

    logger.warning("Can't find index info for {}".format(name))
    return (None, None)


def etf_map2_index(jq_df, gz_df, jk_df, cs_df):
    etfs = etf_info()

    names, ids = [], []
    for i in range(len(etfs)):
        (index_name, index_id) = find_index_id(etfs['index'][i], jq_df, gz_df, jk_df, cs_df)
        names.append(index_name)
        ids.append(index_id)

    etfs['index_name'] = names
    etfs['index_id'] = ids
    etfs = etfs[pd.notnull(etfs['index_id'])].reset_index(drop=True)

    # 全量刷新写入数据库（替代 tmp/index.csv）
    db = Database()
    repo = EtfRepository(db)
    repo.replace_all(etfs)
    logger.info('Mapped ETF to index, total: {}'.format(len(etfs)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')

    #,指数名称,最新PE,PE分位,最新PB,PB分位,股息率,股息率分位,指数代码,指数开始时间,更新时间
    jq_df = jq.index_value_name_funddb()

    #,指数代码,指数简称,样本数,收盘点位,涨跌幅,PE滚动,成交量,成交额,总市值,自由流通市值
    gz_df = ak.index_all_cni()

    #,index_code,display_name,publish_date
    jk_df = ak.index_stock_info().astype({'index_code': str})

    #,指数代码,指数简称,指数全称,基日,基点,指数系列,样本数量,最新收盘,近一个月收益率,资产类别,指数热点,指数币种,合作指数,跟踪产品,指数合规,指数类别,发布时间
    cs_df = ak.index_csindex_all()

    etf_map2_index(jq_df, gz_df, jk_df, cs_df)
