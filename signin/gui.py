"""GUI 兜底：平台没有可复用令牌时，激活客户端窗口并点击校准好的坐标。

只依赖 Windows 自带的 user32（ctypes），不需要 pyautogui / pygetwindow，
所以「双击就能用」不会因为少装包而断掉。
"""
import time
from typing import Any

from .core.models import LABELS


class GuiUnavailable(Exception):
    """GUI 能力不可用（非 Windows 或 user32 调用失败）。"""


try:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
except Exception:  # pragma: no cover - 非 Windows 环境
    _user32 = None

_MOUSE_EVENT_LEFTDOWN = 0x0002
_MOUSE_EVENT_LEFTUP = 0x0004
_SW_RESTORE = 9


def _require():
    if _user32 is None:
        raise GuiUnavailable("当前系统不支持窗口点击（仅 Windows 可用）")
    return _user32


def _rect(hwnd) -> tuple[int, int, int, int] | None:
    r = wintypes.RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def _title(hwnd) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def find_window(title_part: str):
    """按标题片段找可见窗口，返回 hwnd（找不到返回 0）。"""
    if not title_part:
        return 0
    _require()
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _callback(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd):
            return True
        text = _title(hwnd)
        if text and title_part.lower() in text.lower():
            found.append(hwnd)
            return False
        return True

    _user32.EnumWindows(_callback, 0)
    return found[0] if found else 0


def click_at_ratio(window_title: str, x_ratio: float, y_ratio: float) -> bool:
    """在标题包含 window_title 的窗口内，按相对比例点击一次。"""
    if not (0.0 <= x_ratio <= 1.0 and 0.0 <= y_ratio <= 1.0):
        return False
    try:
        hwnd = find_window(window_title)
        if not hwnd:
            return False
        if _user32.IsIconic(hwnd):
            _user32.ShowWindow(hwnd, _SW_RESTORE)
        _user32.SetForegroundWindow(hwnd)
        time.sleep(0.4)
        geo = _rect(hwnd)
        if geo is None:
            return False
        left, top, width, height = geo
        x = left + int(width * x_ratio)
        y = top + int(height * y_ratio)
        _user32.SetCursorPos(x, y)
        time.sleep(0.1)
        _user32.mouse_event(_MOUSE_EVENT_LEFTDOWN, 0, 0, 0, 0)
        _user32.mouse_event(_MOUSE_EVENT_LEFTUP, 0, 0, 0, 0)
        return True
    except Exception:
        return False


def _say(text: str, end: str = "\n") -> None:
    """pythonw 下 stdout 是 None，打印必须容错，否则会打断校准。"""
    try:
        print(text, end=end, flush=True)
    except Exception:
        pass


def record_point(platform: str | None = None, countdown: int = 5) -> dict[str, Any]:
    """引导用户把鼠标移到签到按钮上，返回相对窗口的比例坐标（不依赖第三方包）。"""
    _require()
    _say(f"请在 {countdown} 秒内把鼠标移到「签到 / 领取」按钮上，不要移动…")
    for i in range(countdown, 0, -1):
        _say(f"  {i}…", end="\r")
        time.sleep(1)
    _say(" 已记录！")

    point = wintypes.POINT()
    if not _user32.GetCursorPos(ctypes.byref(point)):
        raise GuiUnavailable("读不到鼠标位置")
    hwnd = _user32.GetForegroundWindow()
    geo = _rect(hwnd) if hwnd else None
    if geo is None:
        return {"window": "", "x_ratio": 0.0, "y_ratio": 0.0}
    left, top, width, height = geo
    return {
        "window": LABELS.get(platform or "", _title(hwnd)),
        "x_ratio": round((point.x - left) / max(1, width), 4),
        "y_ratio": round((point.y - top) / max(1, height), 4),
    }
