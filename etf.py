# -*- coding:utf-8 -*-
"""
Date: 2024-05-01
Desc: 获取ETF列表
"""

import os
import logging
import sqlite3
from datetime import datetime
import requests
import pandas as pd
import akshare as ak
from ext import jq

logger = logging.getLogger(__name__)

# 工程根目录（脚本所在目录）
project_dir = os.path.dirname(os.path.realpath(__file__))

# ETF→指数映射数据库（与 pe.py 共用同一个 anetf.db）
db_file = os.path.join(project_dir, 'anetf.db')

CREATE_ETF_SQL = """
CREATE TABLE IF NOT EXISTS etf (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    tag         TEXT,
    avgamount   REAL,
    index_name  TEXT,
    index_id    TEXT,
    updated_at  TEXT
);
"""

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
    df.to_csv(os.path.join(project_dir, 'etf.csv'))

    return df

etf_index_mapping_table = {
    # ETF列表里面的"指数名称" -> (指数列表里面的"指数名称", 指数列表里面的"指数代码")
    # 港股通/恒生系列（恒生指数公司编制，其他数据源未覆盖）
    '恒生生物科技指数': ('恒生生物科技指数', 'HSHKBIO.HI'),
    '恒生消费指数': ('恒生消费指数', 'HSC.HI'),
    '恒生港股通高股息低波动指数': ('恒生港股通高股息低波动指数', 'HSHGDV.HI'),
    '恒生港股通高股息率指数': ('恒生港股通高股息率指数', 'HSHDY.HI'),
    '恒生港股通中国科技指数': ('恒生港股通中国科技指数', 'HSHKCT.HI'),
    '恒生港股通新经济指数': ('恒生港股通新经济指数', 'HSHKNE.HI'),
    '恒生港股通汽车主题指数': ('恒生港股通汽车主题指数', 'HSHKAT.HI'),
    '恒生A股电网设备指数': ('恒生A股电网设备指数', 'HSCPG.HI'),
    '港股通高股息港元指数': ('中证港股通高股息投资指数', '930914'),
    '港股通信息C港元指数': ('中证港股通信息指数', '930909'),
    '港股通信息C人民币指数': ('中证港股通信息指数', '930909'),
    '港股通医疗主题指数': ('中证港股通医药卫生综合指数', '930965'),
    '港股通非银人民币指数': ('中证港股通非银行金融指数', '931024'),
    '港股通内地金融港元指数': ('中证香港银行投资指数', '930792'),
    '银行AH人民币指数': ('中证银行AH股指数', '931039'),
    '内地国有港元指数': ('中证内地国有主题指数', '930997'),
    '香港证券港元指数': ('中证香港证券投资指数', '930793'),
    'HKC科技人民币指数': ('HKC科技(CNY)', '931573'),
    'HKC科技港币指数': ('HKC科技(CNY)', '931573'),
    'HKC科技港币全收益指数': ('HKC科技(CNY)', '931573'),
    # TODO: HKC医药和HKC消费的正确指数代码待确认，原映射931643/931582指向错误指数
    'HKC医药C港元指数': ('HKC医药', '931643'),
    'HKC医药C人民币指数': ('HKC医药', '931643'),
    'HKC消费港元指数': ('HKC消费', '931582'),
    'HK高股息港元指数': ('中证港股通高股息投资指数', '930914'),
    # 海外指数
    '标准普尔500指数': ('标准普尔500指数', 'SP500'),
    '道琼斯工业平均指数': ('道琼斯工业平均指数', 'DJI'),
    '纳斯达克生物科技指数': ('纳斯达克生物科技指数', 'NBI'),
    'MSCI中国A股国际通指数': ('MSCI中国A股国际通指数', '716567'),
    '富时阿拉伯指数': ('富时阿拉伯指数', 'FARAB'),
    '东证指数': ('东证指数', 'TPX'),
    # 商品/期货
    '黄金9999指数': ('黄金9999指数', 'AU9999'),
    '上海金': ('上海金', 'SHAU'),
    '大商所豆粕期货价格指数': ('大商所豆粕期货价格指数', 'M9999'),
    '易盛能化A': ('易盛能化A', 'ICEA'),
    # 其他特殊指数
    '半导体指数': ('半导体', 'H30184'),
    '科创AI指数': ('科创AI指数', '000695'),
    '科创创业AI指数': ('科创创业AI指数', '000696'),
    '科创半导体材料设备指数': ('科创半导体材料设备指数', '000697'),
    '5G50指数': ('5G50', '931406'),
    'TMT150指数': ('中证TMT', '000998'),
    '新交所泛东南亚科技指数': ('新交所泛东南亚科技指数', 'SGXTECH'),
    '全球中国互联网人民币指数': ('全球中国互联网', '930796'),
    '中国互联网30人民币指数': ('中国互联网30', '930604'),
    '中华半导体人民币指数': ('中华半导体人民币指数', 'H30184'),
    '智选高股息指数': ('智选高股息', '932305'),
    '智选船舶产业指数': ('智选船舶产业', '932420'),
    '国信价值指数': ('国信价值', '931052'),
    # 修正模糊匹配容易错配的指数
    '中证A500指数': ('中证A500', '000510'),
    '沪深300指数': ('沪深300', '000300'),
    '红利指数': ('红利指数', '000015'),
    '证券公司30指数': ('证券公司30', '931412'),
    '半导体材料设备指数': ('半导体材料设备', '931743'),
    '科创芯片设计指数': ('科创芯片设计', '950162'),
    '中国教育人民币指数': ('中国教育', '931456'),
}

# 数据源缺失或错误的标签修正（ETF代码 -> 标签）
etf_tag_overrides = {
    # 港股通信息技术系列，数据源未提供标签，实际为跨境港股科技类；159131原标签"跨境，通信"有误
    '159196': '跨境，香港，科技',
    '526000': '跨境，香港，科技',
    '159185': '跨境，香港，科技',
    '159198': '跨境，香港，科技',
    '513240': '跨境，香港，科技',
    '526050': '跨境，香港，科技',
    '520710': '跨境，香港，科技',
    '526030': '跨境，香港，科技',
    '520750': '跨境，香港，科技',
    '159131': '跨境，香港，科技',
    # 数据源未提供标签的A股ETF
    '159007': '行业，农业',
    # MSCI中国A50/A股系列本质是A股宽基，原标签"MSCI"不属于任何分类维度
    '159601': '宽基，大盘股',
    '560050': '宽基，大盘股',
    '563000': '宽基，大盘股',
    '512090': '宽基，大盘股',
}


def fix_etf_tags(df) -> pd.DataFrame:
    """修正数据源缺失或错误的ETF标签"""
    codes = df['code'].astype(str)
    for code, tag in etf_tag_overrides.items():
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
    if name in etf_index_mapping_table:
        values = etf_index_mapping_table[name]
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
    rows = etfs[['name', 'code', 'tag', 'avgamount', 'index_name', 'index_id']].copy()
    rows['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(CREATE_ETF_SQL)
    conn.execute("DELETE FROM etf")
    rows.to_sql('etf', conn, if_exists='append', index=False, method='multi')
    conn.commit()
    conn.close()
    logger.info('Mapped ETF to index, total: {}, written to {}'.format(len(etfs), db_file))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')

    #,指数名称,最新PE,PE分位,最新PB,PB分位,股息率,股息率分位,指数代码,指数开始时间,更新时间
    jq_df = jq.index_value_name_funddb()

    #,指数代码,指数简称,样本数,收盘点位,涨跌幅,PE滚动,成交量,成交额,总市值,自由流通市值
    gz_df = ak.index_all_cni()

    #,index_code,display_name,publish_date
    jk_df = ak.index_stock_info().astype({'index_code':str})

    #,指数代码,指数简称,指数全称,基日,基点,指数系列,样本数量,最新收盘,近一个月收益率,资产类别,指数热点,指数币种,合作指数,跟踪产品,指数合规,指数类别,发布时间
    cs_df = ak.index_csindex_all()

    etf_map2_index(jq_df, gz_df, jk_df, cs_df)