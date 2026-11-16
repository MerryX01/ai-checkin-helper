"""配置加载：config.json + 环境变量覆盖，敏感值打码。

平台默认值由注册表生成（新增平台自动出现在配置里），环境变量映射也由字段声明推导。
"""
import copy
import json
import os
import sys
from pathlib import Path

from ..platforms import registry

CONFIG_NAME = "config.json"
DEFAULT_TIME = "10:10"

# 工程根目录：源码运行往上三级；打包成 exe 后就是 exe 所在目录（配置、日志都放它旁边）
if getattr(sys, "frozen", False):  # PyInstaller 等打包环境
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parents[2]

NOTIFY_DEFAULTS = {"enabled": False, "type": "wecom", "url": ""}
RUNTIME_DEFAULTS = {"timeout": 20, "retries": 3, "backoff": 1.0, "log_dir": "logs"}
UI_DEFAULTS = {"time": DEFAULT_TIME}


def _platform_defaults() -> dict:
    out = {}
    for spec in registry.all_specs():
        section = {"enabled": spec.enabled_default}
        for fld in spec.fields:
            section[fld.key] = copy.deepcopy(fld.default)
        for key, value in spec.defaults.items():
            section.setdefault(key, copy.deepcopy(value))
        out[spec.key] = section
    return out


DEFAULTS = {
    **_platform_defaults(),
    "notify": dict(NOTIFY_DEFAULTS),
    "runtime": dict(RUNTIME_DEFAULTS),
    "ui": dict(UI_DEFAULTS),
}


def _env_map() -> dict:
    """环境变量 -> (配置段, 字段, 是否凭证)。"""
    out = {}
    for spec in registry.all_specs():
        for fld in spec.fields:
            if fld.env:
                out[fld.env] = (spec.key, fld.key, fld.credential)
    out["CHECKIN_NOTIFY_URL"] = ("notify", "url", False)
    out["CHECKIN_NOTIFY_TYPE"] = ("notify", "type", False)
    return out


ENV_MAP = _env_map()

# 兼容旧名字，外部脚本可能引用过
CREDENTIAL_FIELDS = {"token", "cookie"}

# 打码规则：包含这些词的键，值会被打码
SENSITIVE_KEY_PARTS = ("token", "cookie", "secret", "password", "sendkey", "auth")


class ConfigError(Exception):
    """配置文件存在但无法解析。"""


def load(path: str | None = None) -> dict:
    """读取配置并与默认值深合并；文件不存在时只用默认值。"""
    cfg = copy.deepcopy(DEFAULTS)
    path = path or str(ROOT / CONFIG_NAME)

    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                user = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ConfigError(f"配置文件解析失败：{path}：{e}") from e
        if not isinstance(user, dict):
            raise ConfigError(f"配置文件顶层必须是对象：{path}")
        _deep_merge(cfg, user)

    _apply_env(cfg)
    cfg["_path"] = path
    return cfg


def _deep_merge(base: dict, extra: dict) -> None:
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _apply_env(cfg: dict) -> None:
    for env_name, (section, field, credential) in ENV_MAP.items():
        value = os.environ.get(env_name)
        if value is None or value == "":
            continue
        cfg.setdefault(section, {})[field] = value
        if credential:
            cfg[section]["enabled"] = True
        elif section == "notify":
            cfg["notify"]["enabled"] = True


def redact(value: str) -> str:
    """敏感值打码：保留前 3 位，8 位以内全打码。"""
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return value[:3] + "***"


def redact_dict(data: dict) -> dict:
    """递归复制并打码所有敏感键（用于日志/导出）。"""
    out = {}
    for k, v in data.items():
        if isinstance(v, dict):
            out[k] = redact_dict(v)
        elif isinstance(v, str) and any(p in k.lower() for p in SENSITIVE_KEY_PARTS):
            out[k] = redact(v)
        else:
            out[k] = v
    return out


def ensure_config(dir_path: str) -> str:
    """首次运行生成 config.json（内容为默认模板），返回路径。"""
    path = os.path.join(dir_path, CONFIG_NAME)
    if os.path.exists(path):
        return path
    with open(path, "w", encoding="utf-8") as f:
        json.dump(DEFAULTS, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


def enabled_platforms(cfg: dict) -> list[str]:
    return [p for p in registry.keys() if (cfg.get(p) or {}).get("enabled")]
