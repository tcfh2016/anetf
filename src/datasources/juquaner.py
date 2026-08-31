# -*- coding:utf-8 -*-
"""韭圈儿（funddb）数据源。

阶段 2 重构：把原 ext/jq.py 的 funddb API 封装与 pe.py 的 update_jq 逻辑
合并到此处，对外提供：
- 模块级函数 index_value_name_funddb / index_value_hist_funddb（供 etf.py 等调用）
- JuquanerSource 类（供 ValuationService 编排）

ext/jq.py 现已改为 deprecated re-export，过渡期保留。
"""

import hashlib
import time
import logging
from typing import Optional

import requests
import pandas as pd

from src.datasources.base import DataSource
from src.constants import FUNDBB_NAME_MAPPING

logger = logging.getLogger(__name__)

# 缓存指数名称→代码映射，避免重复请求
_name_code_map_cache = None


def _request_with_retry(url, json=None, max_retries=3, delay=2, timeout=10):
    """带重试和超时的 HTTP 请求。默认 10s 超时 + 最多 3 次，
    韭圈儿服务端偶发 500（并发触发限流），加大重试间隔以度过瞬时故障。"""
    for attempt in range(max_retries):
        try:
            if json is not None:
                r = requests.post(url, json=json, timeout=timeout)
            else:
                r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:
            logger.warning('Request to %s failed (attempt %d/%d): %s',
                          url, attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                time.sleep(delay)
    raise RuntimeError('Request to %s failed after %d retries' % (url, max_retries))


def _get_current_timestamp_ms() -> int:
    """生成毫秒时间戳。"""
    return int(time.time() * 1000)


def _md5_hash(input_string) -> str:
    """生成 md5 加密后的值。"""
    md5 = hashlib.md5()
    md5.update(input_string.encode("utf-8"))
    return md5.hexdigest()


def _create_encode(
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
    hash_value = _md5_hash(input_string)
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
    _ = l[14:16]  # $ is not a valid variable name in Python, replaced with underscore
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


def _get_name_code_map():
    """获取并缓存指数名称→代码映射"""
    global _name_code_map_cache
    if _name_code_map_cache is None:
        df = index_value_name_funddb()
        _name_code_map_cache = dict(zip(df['指数名称'], df['指数代码']))
    return _name_code_map_cache


def index_value_name_funddb() -> pd.DataFrame:
    """
    funddb-指数估值-指数代码
    https://funddb.cn/site/index
    :return: pandas.DataFrame
    :rtype: 指数代码
    """
    url = "https://api.jiucaishuo.com/v2/guzhi/showcategory"
    get_current_timestamp_ms_str = _get_current_timestamp_ms()
    encode_params = _create_encode(
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
    r = _request_with_retry(url, json=payload)
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
    return temp_df


def index_value_hist_funddb(
    symbol: str = "大盘成长", indicator: str = "市盈率"
) -> pd.DataFrame:
    """
    funddb-指数估值-估值信息
    https://funddb.cn/site/index
    :param symbol: 指数名称; 通过调用 index_value_name_funddb() 来获取
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
    name_code_map = _get_name_code_map()
    url = "https://api.jiucaishuo.com/v2/guzhi/newtubiaolinedata"
    get_current_timestamp_ms_str = _get_current_timestamp_ms()
    encode_params = _create_encode(
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
    r = _request_with_retry(url, json=payload)
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


class JuquanerSource(DataSource):
    """韭圈儿（funddb）PE 数据源。

    支持名称映射：本地指数名称经 FUNDBB_NAME_MAPPING 转换为 funddb 中的名称。
    支持多候选：先尝试映射名，再尝试原始名，确保不丢失已有功能。
    """

    name = '韭圈儿'

    def fetch(self, index_id: str, index_name: str, index_tag: str) -> Optional[pd.DataFrame]:
        jq_name = FUNDBB_NAME_MAPPING.get(index_name, index_name)
        candidates = [jq_name]
        if jq_name != index_name:
            candidates.append(index_name)  # 回退：同时尝试原始名称

        for name in candidates:
            try:
                logger.info('JQ: Update PE index id(%s), local_name(%s), trying funddb_name(%s)',
                           index_id, index_name, name)
                new_df = index_value_hist_funddb(symbol=name).astype({'日期': str})
                if new_df.empty:
                    logger.debug('JQ: funddb returned empty for %s, trying next candidate', name)
                    continue
                new_df['指数代码'] = index_id
                new_df['指数名称'] = index_name
                new_df['标签'] = index_tag
                new_df['数据源'] = '韭圈儿'
                return new_df[['日期', '指数代码', '指数名称', '标签', '市盈率', '数据源']].set_index('日期')
            except Exception as e:
                logger.debug('JQ: query %s failed: %s', name, e)
                continue

        logger.error('JQ: query failed for all candidates: %s', candidates)
        return None
