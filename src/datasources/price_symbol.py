# -*- coding:utf-8 -*-
"""指数代码 → 行情数据获取方式的路由表。

拆自 pe.py 的 _get_price_symbol，便于阶段 2 各数据源类直接复用。
输入的 index_id 假定已通过 split('.')[0] 去掉后缀并大写。
"""

from typing import Optional, Tuple

# 美国指数：Sina API 要求代码以 . 开头
US_INDEX_MAP = {
    'SP500': ('us', '.INX'),
    'DJI':   ('us', '.DJI'),
    'NDX':   ('us', '.NDX'),
    'NBI':   ('us', '.NBI'),
}

# 海外/特殊代码集合（用于 update_db 跳过国内 PE 数据源）
OVERSEAS_SPECIAL_CODES = frozenset(
    {'SP500', 'DJI', 'NDX', 'NBI', 'SHAU', 'AU9999', 'M9999', 'ICEA'}
)


def get_price_symbol(index_id: str) -> Optional[Tuple[str, Optional[str]]]:
    """根据指数代码推断行情数据获取方式。

    返回 (source_type, symbol) 或 None（无可用数据源）。
    source_type 取值：'cn' / 'cni' / 'hk' / 'us' / 'futures' / 'gold'。
    """
    # 港股指数代码: HSHKAT, HSC, HSHGDV, HSCPG, HSHDY, HSHKCT, HSHCI 等
    if index_id.startswith('HS') or index_id.startswith('HSC'):
        return ('hk', index_id)
    # 国证指数代码: 987xxx/980xxx/970xxx 及 CN 开头的国证指数
    if index_id.startswith(('987', '980', '970')) or index_id.startswith('CN'):
        return ('cni', index_id)
    # 中证指数代码: 931xxx 开头的中证指数
    if index_id.startswith('931'):
        return ('cn', 'csi' + index_id)
    # 商品/期货特殊处理
    if index_id in ('AU9999', 'SHAU'):
        return ('gold', None)
    if index_id == 'M9999':
        return ('futures', 'M0')
    if index_id == 'ICEA':
        return None
    # 美国指数
    if index_id in US_INDEX_MAP:
        return US_INDEX_MAP[index_id]
    # 国内指数: 判断交易所前缀
    if index_id[0] in '05679':
        return ('cn', 'sh' + index_id)
    elif index_id[0] in '123':
        return ('cn', 'sz' + index_id)
    elif index_id.startswith('H'):
        return ('cn', 'csi' + index_id)
    return None
