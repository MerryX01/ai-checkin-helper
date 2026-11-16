"""平台注册表。

平台模块导入时调用 `register()`，注册表就多一项。CLI、配置默认值、界面面板都读这里，
所以「加一个平台」不需要再去别的地方补 if/elif。
"""
from ..core import models
from .base import PlatformSpec

_REGISTRY: dict[str, PlatformSpec] = {}


def register(spec: PlatformSpec) -> PlatformSpec:
    if not spec.key:
        raise ValueError("平台 key 不能为空")
    if spec.key in _REGISTRY:
        raise ValueError(f"平台重复注册：{spec.key}")
    if not callable(spec.run):
        raise ValueError(f"平台 {spec.key} 缺少 run 函数")
    _REGISTRY[spec.key] = spec
    models.LABELS[spec.key] = spec.label
    return spec


def all_specs() -> list[PlatformSpec]:
    """按注册顺序返回（顺序即执行顺序、界面面板顺序）。"""
    return list(_REGISTRY.values())


def keys() -> tuple[str, ...]:
    return tuple(_REGISTRY.keys())


def get(key: str) -> PlatformSpec:
    try:
        return _REGISTRY[key]
    except KeyError as e:
        raise KeyError(f"未注册的平台：{key}") from e


def clear() -> None:
    """仅供测试：清空注册表与文案表。"""
    _REGISTRY.clear()
    models.LABELS.clear()
