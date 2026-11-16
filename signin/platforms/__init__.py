"""平台包：导入即注册，导入顺序决定执行顺序。

新增平台时在这一行后面加一个模块名即可（详见 docs/ADDING_A_PLATFORM.md）。
"""
from . import trae, qoder, workbuddy, doubao  # noqa: F401  （导入触发注册）
from .base import FieldSpec, PlatformSpec
from .registry import all_specs, get, keys, register

# 注册完成的平台键，供需要常量清单的地方直接使用
PLATFORMS = keys()

__all__ = ["PLATFORMS", "FieldSpec", "PlatformSpec", "all_specs", "get", "keys", "register"]
