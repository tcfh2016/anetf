# -*- coding:utf-8 -*-
"""DEPRECATED: 韭圈儿 funddb 封装已迁移到 anetf.datasources.juquaner。

本模块仅为过渡期保留的 re-export，新代码请直接：
    from anetf.datasources import juquaner
    juquaner.index_value_name_funddb()
    juquaner.JuquanerSource()
"""

import warnings

warnings.warn(
    "ext.jq is deprecated; use anetf.datasources.juquaner instead.",
    DeprecationWarning,
    stacklevel=2,
)

# re-export 公开 API
from anetf.datasources.juquaner import (  # noqa: F401  E402
    index_value_name_funddb,
    index_value_hist_funddb,
    JuquanerSource,
)

__all__ = [
    'index_value_name_funddb',
    'index_value_hist_funddb',
    'JuquanerSource',
]

