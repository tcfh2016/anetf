import hashlib
import time
import requests
import pandas as pd

def __get_current_timestamp_ms() -> int:
    """
    生成时间戳
    :return: 时间戳
    :rtype: int
    """
    timestamp_seconds = time.time()
    timestamp_ms = int(timestamp_seconds * 1000)
    return timestamp_ms

def __md5_hash(input_string) -> str:
    """
    生成 md5 加密后的值
    :return: 生成 md5 加密后的值
    :rtype: str
    """
    md5 = hashlib.md5()
    md5.update(input_string.encode("utf-8"))
    return md5.hexdigest()

def __create_encode(
    act_time="1688635494326",
    authtoken="",
    gu_code="399808.SZ",
    pe_category="pb",
    type="pc",
    ver="new",
    version="2.2.7",
    year=-1,
) -> dict:
    """
    生成 post 密文，需要 JS 观察如下文件：
    https://funddb.cn/static/js/app.1c429c670c72542fb4fd.js
    :return: 生成 post 密文
    :rtype: str
    """
    input_string = f"{act_time}{authtoken}{gu_code}{pe_category}{type}{ver}{version}{year}EWf45rlv#kfsr@k#gfksgkr"
    hash_value = __md5_hash(input_string)
    l = hash_value
    c = l[29:31]
    d = l[2:4]
    f = l[5:6]
    h = l[26:27]
    m = l[6:8]
    v = l[1:2]
    y = l[0:2]
    k = l[6:8]
    w = l[8:9]
    x = l[30:31]
    P = l[11:14]
    z = l[11:12]
    j = l[2:5]
    q = l[9:11]
    H = l[23:25]
    O = l[31:32]
    C = l[25:27]
    E = l[9:11]
    A = l[27:29]
    T = l[17:19]
    F = l[26:27]
    U = l[12:14]
    S = l[25:26]
    R = l[16:19]
    K = l[17:21]
    I = l[18:19]
    D = l[21:23]
    _ = l[
        14:16
    ]  # $ is not a valid variable name in Python, so I replaced it with an underscore
    B = l[29:32]
    N = l[21:23]
    V = l[24:26]
    Y = l[16:17]

    def b(
        t,
        e,
        n,
        i,
        a,
        r,
        o,
        l,
        u,
        c,
        s,
        d,
        _,
        f,
        h,
        p,
        m,
        g,
        v,
        y,
        b,
        k,
        w,
        x,
        P,
        z,
        j,
        q,
        H,
        O,
        C,
        E,
        A,
    ):
        t["data"]["tirgkjfs"] = f
        t["data"]["abiokytke"] = _
        t["data"]["u54rg5d"] = e
        t["data"]["kf54ge7"] = q
        t["data"]["tiklsktr4"] = d
        t["data"]["lksytkjh"] = z
        t["data"]["sbnoywr"] = j
        t["data"]["bgd7h8tyu54"] = w
        t["data"]["y654b5fs3tr"] = C
        t["data"]["bioduytlw"] = n
        t["data"]["bd4uy742"] = P
        t["data"]["h67456y"] = o
        t["data"]["bvytikwqjk"] = s
        t["data"]["ngd4uy551"] = b
        t["data"]["bgiuytkw"] = v
        t["data"]["nd354uy4752"] = g
        t["data"]["ghtoiutkmlg"] = x
        t["data"]["bd24y6421f"] = i
        t["data"]["tbvdiuytk"] = l
        t["data"]["ibvytiqjek"] = p
        t["data"]["jnhf8u5231"] = A
        t["data"]["fjlkatj"] = E
        t["data"]["hy5641d321t"] = H
        t["data"]["iogojti"] = r
        t["data"]["ngd4yut78"] = a
        t["data"]["nkjhrew"] = c
        t["data"]["yt447e13f"] = O
        t["data"]["n3bf4uj7y7"] = k
        t["data"]["nbf4uj7y432"] = h
        t["data"]["yi854tew"] = u
        t["data"]["h13ey474"] = m
        t["data"]["quikgdky"] = y

    t = {"data": {}}

    b(
        t,
        d,
        f,
        V,
        U,
        S,
        R,
        Y,
        c,
        h,
        m,
        v,
        N,
        y,
        D,
        _,
        B,
        x,
        E,
        A,
        T,
        I,
        k,
        P,
        F,
        K,
        H,
        O,
        C,
        w,
        z,
        j,
        q,
    )
    return t["data"]

def index_value_name_funddb() -> pd.DataFrame:
    """
    funddb-指数估值-指数代码
    https://funddb.cn/site/index
    :return: pandas.DataFrame
    :rtype: 指数代码
    """
    url = "https://api.jiucaishuo.com/v2/guzhi/showcategory"
    get_current_timestamp_ms_str = __get_current_timestamp_ms()
    encode_params = __create_encode(
        act_time=str(get_current_timestamp_ms_str),
        authtoken="",
        gu_code="",
        pe_category="",
        type="pc",
        ver="",
        version="2.2.7",
        year="",
    )
    payload = {
        "type": "pc",
        "version": "2.2.7",
        "authtoken": "",
        "act_time": str(get_current_timestamp_ms_str)
    }
    payload.update(encode_params)
    r = requests.post(url, json=payload)
    data_json = r.json()
    temp_df = pd.DataFrame(data_json["data"]["right_list"])
    
    temp_df.columns = [
        "指数开始时间",
        "-",
        "指数名称",
        "指数代码",
        "最新PE",
        "最新PB",
        "PE分位",
        "PB分位",
        "股息率",
        "-",
        "-",
        "-",
        "更新时间",
        "股息率分位",
        "-",
        "-",
        "-",
        "-",
        "-",
        "-",
        "-",
        "-",
        "-",
        "-",
        "-",
        "-",
        "-",
        "-",
        "-",
        "-",
    ]
    temp_df = temp_df[
        [
            "指数名称",
            "最新PE",
            "PE分位",
            "最新PB",
            "PB分位",
            "股息率",
            "股息率分位",
            "指数代码",
            "指数开始时间",
            "更新时间",
        ]
    ]
    '''
    temp_df["指数开始时间"] = pd.to_datetime(temp_df["指数开始时间"]).dt.date
    temp_df["最新PE"] = pd.to_numeric(temp_df["最新PE"], errors="coerce")
    temp_df["PE分位"] = pd.to_numeric(temp_df["PE分位"], errors="coerce")
    temp_df["最新PB"] = pd.to_numeric(temp_df["最新PB"], errors="coerce")
    temp_df["PB分位"] = pd.to_numeric(temp_df["PB分位"], errors="coerce")
    temp_df["股息率"] = pd.to_numeric(temp_df["股息率"], errors="coerce")
    temp_df["股息率分位"] = pd.to_numeric(temp_df["股息率分位"], errors="coerce")
    '''
    return temp_df


def index_value_hist_funddb(
    symbol: str = "大盘成长", indicator: str = "市盈率"
) -> pd.DataFrame:
    """
    funddb-指数估值-估值信息
    https://funddb.cn/site/index
    :param symbol: 指数名称; 通过调用 ak.index_value_name_funddb() 来获取
    :type symbol: str
    :param indicator: choice of {'市盈率', '市净率', '股息率', '风险溢价'}
    :type indicator: str
    :return: 估值信息
    :rtype: pandas.DataFrame
    """
    indicator_map = {
        "市盈率": "pe",
        "市净率": "pb",
        "股息率": "xilv",
        "风险溢价": "fed",
    }
    index_value_name_funddb_df = index_value_name_funddb()
    name_code_map = dict(
        zip(
            index_value_name_funddb_df["指数名称"],
            index_value_name_funddb_df["指数代码"],
        )
    )
    url = "https://api.jiucaishuo.com/v2/guzhi/newtubiaolinedata"
    get_current_timestamp_ms_str = __get_current_timestamp_ms()
    encode_params = __create_encode(
        act_time=str(get_current_timestamp_ms_str),
        authtoken="",
        gu_code=name_code_map[symbol],
        pe_category=indicator_map[indicator],
        type="pc",
        ver="new",
        version="2.2.7",
        year=-1,
    )
    payload = {
        "gu_code": name_code_map[symbol],
        "pe_category": indicator_map[indicator],
        "year": -1,
        "ver": "new",
        "type": "pc",
        "version": "2.2.7",
        "authtoken": "",
        "act_time": str(get_current_timestamp_ms_str)
    }
    payload.update(encode_params)
    r = requests.post(url, json=payload)
    data_json = r.json()
    big_df = pd.DataFrame()
    temp_df = pd.DataFrame(
        data_json["data"]["tubiao"]["series"][0]["data"],
        columns=["timestamp", "value"],
    )
    big_df["日期"] = (
        pd.to_datetime(temp_df["timestamp"], unit="ms", utc=True)
        .dt.tz_convert("Asia/Shanghai")
        .dt.date
    )
    big_df["平均值"] = pd.to_numeric(temp_df["value"])
    big_df[indicator] = pd.to_numeric(
        [item[1] for item in data_json["data"]["tubiao"]["series"][1]["data"]]
    )
    big_df["最低30"] = pd.to_numeric(
        [item[1] for item in data_json["data"]["tubiao"]["series"][2]["data"]]
    )
    big_df["最低10"] = pd.to_numeric(
        [item[1] for item in data_json["data"]["tubiao"]["series"][3]["data"]]
    )
    big_df["最高30"] = pd.to_numeric(
        [item[1] for item in data_json["data"]["tubiao"]["series"][4]["data"]]
    )
    big_df["最高10"] = pd.to_numeric(
        [item[1] for item in data_json["data"]["tubiao"]["series"][5]["data"]]
    )
    return big_df


if __name__ == "__main__":
    df = index_value_hist_funddb(symbol='纳斯达克100')
    print(df)