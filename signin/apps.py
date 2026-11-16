"""Windows 客户端定位与启动（用于"打开即签到"类平台）。"""
import glob
import os
import subprocess
import sys

DOUBAO_DIRS = [
    r"D:\SoftWare\Doubao",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Doubao", "Application"),
    os.path.join(os.environ.get("ProgramFiles", ""), "Doubao"),
]

DOUBAO_EXE_HINTS = ("doubao.exe", "豆包.exe")


def resolve_doubao(app_path: str = "") -> str:
    """返回可执行文件的绝对路径；找不到返回空串。"""
    if app_path:
        expanded = os.path.expandvars(os.path.expanduser(app_path))
        return expanded if os.path.exists(expanded) else ""

    for base in DOUBAO_DIRS:
        if not base or not os.path.isdir(base):
            continue
        for name in DOUBAO_EXE_HINTS:
            hit = os.path.join(base, name)
            if os.path.exists(hit):
                return hit
        # 版本子目录 / 任意 doubao*.exe
        for pattern in (os.path.join(base, "*.exe"), os.path.join(base, "*", "*.exe")):
            for hit in sorted(glob.glob(pattern)):
                if "doubao" in os.path.basename(hit).lower():
                    return hit
    return ""


def launch(path: str) -> bool:
    """把客户端拉起来（不等待、不关闭）。"""
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen([path], close_fds=True,
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        else:
            subprocess.Popen([path])
        return True
    except Exception:
        return False
