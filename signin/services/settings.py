"""界面/命令行与配置之间的纯逻辑：表单映射、校验、命令拼装。

全部由平台注册表驱动：加一个平台不需要改这里。
"""
import copy
import json
import os
import re
from pathlib import Path

from .. import apps, platforms
from ..core import config
from ..core.models import LABELS

DEFAULT_TIME = config.DEFAULT_TIME
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# ------------------------------------------------------------------ 表单
def form_from_config(cfg: dict) -> dict:
    """config.json -> 界面表单（值全部转成可直接绑定控件的类型）。"""
    form: dict = {"enabled": {}}
    for spec in platforms.all_specs():
        section = cfg.get(spec.key) or {}
        form["enabled"][spec.key] = bool(section.get("enabled"))
        values = {}
        for fld in spec.fields:
            raw = section.get(fld.key, fld.default)
            if fld.kind == "bool":
                values[fld.key] = bool(raw)
            elif fld.kind == "int":
                try:
                    values[fld.key] = int(raw or 0)
                except (TypeError, ValueError):
                    values[fld.key] = int(fld.default or 0)
            else:
                values[fld.key] = "" if raw is None else str(raw)
        # 只读状态：点击坐标是否已校准（不写回配置）
        values["gui_click_ready"] = bool(section.get("gui_click"))
        form[spec.key] = values
    return form


def apply_form(existing: dict, form: dict) -> dict:
    """表单 -> 新配置。只改平台段，notify/runtime/gui_click 等其它键原样保留。"""
    out = copy.deepcopy(existing or config.DEFAULTS)
    for spec in platforms.all_specs():
        out.setdefault(spec.key, {})
        section = out[spec.key]
        section["enabled"] = bool((form.get("enabled") or {}).get(spec.key))
        src = form.get(spec.key) or {}
        for fld in spec.fields:
            if fld.kind == "bool":
                section[fld.key] = bool(src.get(fld.key, fld.default))
            elif fld.kind == "int":
                try:
                    section[fld.key] = max(0, int(src.get(fld.key) or 0))
                except (TypeError, ValueError):
                    section[fld.key] = int(fld.default or 0)
            else:
                text = str(src.get(fld.key) or "").strip()
                if not text:
                    text = str(fld.default or "")
                if fld.key.endswith("_url"):
                    text = text.rstrip("/")
                section[fld.key] = text
    return out


def enabled_platforms(form: dict) -> list[str]:
    return [p for p in platforms.keys() if (form.get("enabled") or {}).get(p)]


def toggle_platform(form: dict, key: str) -> bool:
    """单独切换一个平台的勾选状态；返回切换后的值。"""
    enabled = form.setdefault("enabled", {})
    enabled[key] = not bool(enabled.get(key))
    return enabled[key]


# ------------------------------------------------------------------ 校验
def validate_time(text: str) -> bool:
    """每日执行时间必须是 HH:MM（00:00–23:59）。"""
    return bool(_TIME_RE.match((text or "").strip()))


def platform_problems(spec, section: dict) -> list[str]:
    """某个平台自己的问题清单（读表单或读配置都适用）。"""
    return spec.problems(section)


def problems(form: dict) -> list[tuple[str, str]]:
    """返回 [(平台名或 '*', 人话说明)]；空列表表示可以放心跑。"""
    names = enabled_platforms(form)
    if not names:
        return [("*", "还没有勾选任何平台，点一下左侧平台名即可勾选")]
    out: list[tuple[str, str]] = []
    for spec in platforms.all_specs():
        if not form.get("enabled", {}).get(spec.key):
            continue
        section = form.get(spec.key) or {}
        for text in spec.problems(section):
            out.append((spec.key, f"{sp_label(spec.key)}：{text}"))
    return out


def sp_label(key: str) -> str:
    return LABELS.get(key, key)


def ready(form: dict, key: str) -> bool:
    """该平台勾选且没有待补项。"""
    spec = platforms.get(key)
    return bool(form.get("enabled", {}).get(key)) and not spec.problems(form.get(key) or {})


def credential_text(value: str) -> str:
    """凭证状态展示：只给打码后的形态，不回显全文。"""
    value = (value or "").strip()
    if not value:
        return "未填写"
    return f"已填写（{config.redact(value)}）"


def login_urls() -> dict[str, str]:
    return {spec.key: spec.login_url for spec in platforms.all_specs() if spec.login_url}


LOGIN_URLS = login_urls()


# ------------------------------------------------------------------ 读写
def save_config(path: str, cfg: dict) -> str:
    """写 config.json（丢掉内部键 _path），返回写入路径。"""
    data = {k: v for k, v in (cfg or {}).items() if not k.startswith("_")}
    path = str(path)
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


# ------------------------------------------------------------------ 定时任务
def task_command(root: str, time_text: str) -> list[str]:
    script = str(Path(root) / "scripts" / "install_task.ps1")
    return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", script, "-Time", (time_text or "").strip()]


def remove_task_command(root: str) -> list[str]:
    script = str(Path(root) / "scripts" / "install_task.ps1")
    return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", script, "-Remove"]


def task_state() -> str:
    """返回计划任务状态的简短描述（Windows 用 schtasks 查询）。"""
    import subprocess
    try:
        out = subprocess.run(["schtasks", "/Query", "/TN", "SignInDailyCheckin", "/FO", "LIST"],
                             capture_output=True, text=True, timeout=10)
    except Exception as e:
        return f"查询失败：{type(e).__name__}"
    # pythonw 下没有控制台，stdout/stderr 可能是 None，不能直接 splitlines
    text = "".join(part for part in (out.stdout, out.stderr) if part)
    if out.returncode != 0:
        return "未注册"
    for line in text.splitlines():
        if "Next Run Time" in line or "下次运行时间" in line:
            return line.split(":", 1)[-1].strip()
    return "已注册"
