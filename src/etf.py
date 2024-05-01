import requests
import pandas as pd


def etf_info() -> pd.DataFrame:
    cols = [
        'fund_id', #基金代码
        'fund_nm', #基金名称
        'index_id', #指数代码
        'fee', #管托费
        'm_fee', #
        't_fee', #
        'creation_unit', #最小申赎（万份）
        'issuer_nm', #基金公司
        'urls', #基金地址
        'eval_flg', #
        't0', #
        'ex_dt', #
        'ex_info', #
        'amount', #份额（万份）
        'amount_notes', #
        'unit_total', #规模（亿元）
        'unit_incr', #规模变化（亿元）
        'price', #现价
        'volume', #成交额（万元）
        'last_dt', #日期
        'last_time', #时间
        'increase_rt', #涨幅
        'estimate_value', #估值
        'last_est_time', #估值时间
        'discount_rt', #
        'fund_nav', #净值
        'nav_dt', #
        'index_nm', #指数名称
        'index_increase_rt', #
        'idx_price_dt', #
        'owned', #
        'holded', #
        'pe', #
        'pb' #
    ]

    rows = info_rows()
    if not rows:
        print('no valid data when calling info_rows()')

    cells = [row['cell'] for row in rows] 
    df = pd.DataFrame(cells)
    df.to_csv('etf_info.csv')
    return df


def info_rows() -> list:
    # 集思录: https://www.jisilu.cn/data/etf/#index
    url = 'https://www.jisilu.cn/data/etf/etf_list/'
    params = {
            "___jsl": "LST___t=1714532238732",
            "rp": "25",
            "page": "1 HTTP/1.1",
        }

    r = requests.get(url, params=params)
    if r.status_code == 200:
        return r.json()['rows']
    return None

    # 备选数据源，ETF组合宝：http://www.etf.group/data/list1.html
    #url = 'http://www.etf.group/data/api1.php'
    #r = requests.get(url)
    #if r.status_code == 200:
    #    print('for zuhebao')
    #    data_rows = r.json()['rows']['item']
    #    print(len(data_rows))


if __name__ == "__main__":
    etf_info()