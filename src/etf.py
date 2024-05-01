import requests
import pandas as pd


def etf_info() -> pd.DataFrame:
    rows = info_rows()
    if not rows:
        print('no valid data when calling info_rows()')
    
    #集思录数据处理 
    #cells = [row['cell'] for row in rows] 
    #df = pd.DataFrame(cells).astype({'volume':float})
    ## 过滤成交额大于1000万，过滤债券ETF
    #df = df[(df['volume'] > 1000) & (df['fund_nm'].str.find('债') == -1)]
    
    #组合宝数据处理
    df = pd.DataFrame(rows)
    df = df[(df['avgamount'] > 1000) & (df['name'].str.find('债') == -1)].reset_index(drop=True)
    df.to_csv('etf.csv')
    return df


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


if __name__ == "__main__":
    etf_info()