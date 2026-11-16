"""命令行入口：体检 / 执行 / 校准 / 注册定时任务 / 打开界面。"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import VERSION, apps, platforms
from .core import config, http, logging_setup, notify
from .core.models import LABELS, STATUS_CN, CheckinResult, Status, pad
from .services import history, runner, quota as quota_service

ROOT = Path(__file__).resolve().parent.parent


def build_client(cfg: dict) -> http.Client:
    return runner.build_client(cfg)


def run_all(cfg: dict, client=None, only=None, dry_run=False, log=None) -> list[CheckinResult]:
    return runner.run_all(cfg, client=client, only=only, dry_run=dry_run, log=log)


def summary(results: list[CheckinResult]) -> str:
    return runner.summary(results)


def exit_code(results: list[CheckinResult]) -> int:
    return runner.exit_code(results)


# ------------------------------------------------------------------ 体检
def _tkinter_ok() -> bool:
    """import tkinter 成功不代表能用：精简运行时缺 init.tcl 时要在建 Tcl 解释器时才报错。"""
    try:
        import tkinter
        tkinter.Tcl()
        return True
    except Exception:
        return False


def _python_info() -> str:
    info = f"Python {sys.version.split()[0]}（{sys.executable}）"
    info += "｜tkinter 可用" if _tkinter_ok() else "｜tkinter 不可用（界面需换 py -3 启动）"
    try:
        from . import gui as _gui
        _gui._require()
        info += "｜窗口点击可用（纯系统 API）"
    except Exception:
        info += "｜窗口点击不可用"
    return info


def cmd_check(cfg: dict, verbose: bool = False) -> int:
    print("配置体检（不发起任何网络请求）")
    print("-" * 60)
    print(f"工程目录：{ROOT}")
    print(f"配置文件：{cfg.get('_path')}")
    if verbose:
        print(_python_info())
    for spec in platforms.all_specs():
        section = cfg.get(spec.key) or {}
        enabled = "启用" if section.get("enabled") else "未启用"
        cred = spec.credential_field
        if cred:
            raw = str(section.get(cred.key) or "")
            if cred.kind == "path":
                shown = apps.resolve_doubao(raw) or "—（未找到客户端）"
            else:
                shown = config.redact(raw) if raw else "—（缺凭证）"
        elif spec.login_state is not None:
            state = spec.detect_login()
            if state.ok:
                shown = f"已登录 {state.account}" if state.account else "已登录（凭证自动读取）"
            else:
                shown = f"—（{state.message}）"
        else:
            shown = "—"
        issues = spec.problems(section) if section.get("enabled") else []
        tail = ("待补：" + "；".join(issues)) if issues else ""
        print(f"  {pad(spec.label, 12)} [{enabled}] {shown} {tail}".rstrip())

    n = cfg.get("notify") or {}
    print(f"  {pad('通知', 12)} [{'启用' if n.get('enabled') else '未启用'}] "
          f"type={n.get('type')} url={config.redact(n.get('url', '')) or '—'}")
    task = "未注册"
    try:
        from .services import settings as settings_mod
        task = settings_mod.task_state()
    except Exception:
        pass
    print(f"  {pad('定时任务', 12)} {task}")
    print("-" * 60)
    print("下一步：python run.py                  # 真正签到")
    print("        python run.py run --dry-run    # 只看会发哪些请求")
    print("        python run.py ui               # 打开图形界面")
    return 0


# ------------------------------------------------------------------ 执行
def cmd_run(cfg: dict, args) -> int:
    log = logging_setup.setup((cfg.get("runtime") or {}).get("log_dir", "logs"))
    only = [s.strip() for s in (args.only or "").split(",") if s.strip()] or None
    log.info("开始签到（dry_run=%s，only=%s）", args.dry_run, only or "全部")

    results = run_all(cfg, only=only, dry_run=args.dry_run, log=log)
    if not args.dry_run and results:
        try:
            history.append(results)
        except Exception as exc:
            log.info("写签到历史失败：%s", exc)
    text = summary(results)
    print()
    print(text)

    if not args.no_notify:
        n = cfg.get("notify") or {}
        if n.get("enabled"):
            failed = [r for r in results if r.status == Status.FAILED]
            title = f"签到结果｜失败 {len(failed)}" if failed else "签到结果｜全部完成"
            ok, msg = notify.send(n, title, text)
            log.info("推送：%s %s", "成功" if ok else "失败", msg)

    log.info("结束：退出码 %d", exit_code(results))
    return exit_code(results)


# ------------------------------------------------------------------ 额度看板
def cmd_quota(cfg: dict, args) -> int:
    only = [s.strip() for s in (getattr(args, "only", "") or "").split(",") if s.strip()] or None
    snapshots = quota_service.collect(cfg, only=only, results=history.today_results())
    print(quota_service.summary(snapshots))
    if getattr(args, "details", False):
        for snap in snapshots:
            print()
            print(f"## {snap.label}  {snap.message}")
            if snap.source:
                print(f"数据源：{snap.source}")
            for key, value in snap.details:
                print(f"  {pad(key, 12)} {value}")
    return 1 if any(s.status == Status.FAILED for s in snapshots) else 0


# ------------------------------------------------------------------ 校准点击坐标
def cmd_teach(cfg: dict, args) -> int:
    from . import gui

    path = cfg.get("_path") or os.path.join(str(ROOT), config.CONFIG_NAME)
    try:
        point = gui.record_point(args.platform)
    except gui.GuiUnavailable as e:
        print(f"无法校准：{e}")
        return 2

    data = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    data.setdefault(args.platform, {})["gui_click"] = point
    data[args.platform].setdefault("gui_fallback", True)
    data[args.platform].setdefault("enabled", True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"已写入 {path}：{args.platform}.gui_click = {point}")
    return 0


# ------------------------------------------------------------------ 定时任务
def _task_script() -> Path:
    return ROOT / "scripts" / "install_task.ps1"


TASK_NAME = "SignInDailyCheckin"


def _frozen_exe() -> str:
    return sys.executable if getattr(sys, "frozen", False) else ""


def cmd_install_task(args) -> int:
    # 打包成 exe 时没有 scripts 目录：直接让计划任务调用 exe 自己
    exe = _frozen_exe()
    if exe:
        command = f'"{exe}" run --no-notify'
        cmd = ["schtasks", "/Create", "/SC", "DAILY", "/ST", args.time,
               "/TN", TASK_NAME, "/TR", command, "/F"]
        if args.dry_run:
            print("将执行：", subprocess.list2cmdline(cmd))
            return 0
        code = subprocess.call(cmd)
        print("注册任务：%s 每天 %s 动作：%s" % (TASK_NAME, args.time, command))
        return code
    script = _task_script()
    if not script.exists():
        print(f"缺少脚本：{script}")
        return 2
    cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
           "-Time", args.time]
    if args.dry_run:
        print("将执行：", " ".join(cmd))
        return 0
    print("注册每日定时任务…")
    return subprocess.call(cmd)


def cmd_uninstall_task(args) -> int:
    if _frozen_exe():
        cmd = ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]
        if args.dry_run:
            print("将执行：", subprocess.list2cmdline(cmd))
            return 0
        return subprocess.call(cmd)
    script = _task_script()
    cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Remove"]
    if args.dry_run:
        print("将执行：", " ".join(cmd))
        return 0
    return subprocess.call(cmd)


# ------------------------------------------------------------------ 其它
def cmd_ui() -> int:
    from .ui import app as ui_app
    return ui_app.main([])


def cmd_platforms() -> int:
    print(f"{pad('键', 12)}{pad('名称', 12)}说明")
    print("-" * 60)
    for spec in platforms.all_specs():
        print(f"{pad(spec.key, 12)}{pad(spec.label, 12)}{spec.summary}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run.py", description="每日自动签到：WorkBuddy / Qoder / Trae CN / 豆包")
    parser.add_argument("--version", action="version", version=f"sign_in {VERSION}")
    parser.add_argument("--config", default=None, help="配置文件路径（默认 ./config.json）")
    sub = parser.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="执行签到")
    p_run.add_argument("--only", default="", help="只跑指定平台，如 trae,qoder")
    p_run.add_argument("--dry-run", action="store_true", help="只打印将要发出的请求")
    p_run.add_argument("--no-notify", action="store_true", help="跳过推送")

    sub.add_parser("check", help="配置体检（不发请求）")
    sub.add_parser("doctor", help="环境 + 配置全面体检")
    sub.add_parser("platforms", help="列出已注册的平台")
    sub.add_parser("ui", help="打开图形界面")
    p_quota = sub.add_parser("quota", help="查看每个平台的额度与用量")
    p_quota.add_argument("--only", default="", help="只看指定平台，如 trae,qoder")
    p_quota.add_argument("--details", action="store_true", help="同时打印额度构成/记录明细")

    p_teach = sub.add_parser("teach", help="校准客户端签到按钮坐标")
    p_teach.add_argument("platform", choices=list(platforms.keys()))

    p_task = sub.add_parser("install-task", help="注册 Windows 每日定时任务")
    p_task.add_argument("--time", default="10:10", help="每日执行时间 HH:MM")
    p_task.add_argument("--dry-run", action="store_true")
    sub.add_parser("uninstall-task", help="删除定时任务")

    args = parser.parse_args(argv)
    cmd = args.cmd or "run"
    if cmd == "run" and not hasattr(args, "only"):
        args.only, args.dry_run, args.no_notify = "", False, False

    if cmd == "platforms":
        return cmd_platforms()
    if cmd == "ui":
        return cmd_ui()

    cfg = config.load(args.config)

    if cmd == "quota":
        return cmd_quota(cfg, args)

    if cmd == "check":
        path = cfg.get("_path") or ""
        if path and not os.path.exists(path):
            created = config.ensure_config(os.path.dirname(os.path.abspath(path)))
            print(f"已生成默认配置：{created}（填好凭证后把 enabled 改成 true）")
            cfg = config.load(args.config)
        return cmd_check(cfg)
    if cmd == "doctor":
        print(f"sign_in {VERSION}")
        return cmd_check(cfg, verbose=True)
    if cmd == "run":
        return cmd_run(cfg, args)
    if cmd == "teach":
        return cmd_teach(cfg, args)
    if cmd == "install-task":
        return cmd_install_task(args)
    if cmd == "uninstall-task":
        return cmd_uninstall_task(args)
    parser.print_help()
    return 2
