"""tkinter 界面。

面板完全由平台注册表生成：注册一个新平台，界面自动多出一张卡片和一个设置面板，
这里不需要任何改动。
"""
import os
import queue
import subprocess
import sys
import threading
import traceback
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from .. import VERSION, apps, gui as gui_mod, platforms
from ..core import config
from ..core.models import STATUS_CN, Status
from ..services import history, runner, settings

COLORS = {
    "bg": "#F3F4F6",
    "card": "#FFFFFF",
    "border": "#E5E7EB",
    "text": "#111827",
    "muted": "#6B7280",
    "accent": "#2563EB",
    "ok": "#16A34A",
    "warn": "#B45309",
    "err": "#DC2626",
}

TITLE_PREFIX = "每日自动签到"
TASK_NAME_NOTE = "Windows 计划任务（任务名 SignInDailyCheckin）"


def _enable_dpi_awareness() -> None:
    """让窗口按真实像素绘制，否则 200% 缩放下控件会被裁切。"""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class SignInApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(TITLE_PREFIX + " · " + " / ".join(spec.label for spec in platforms.all_specs()))
        self.root.configure(bg=COLORS["bg"])

        self.scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        self._setup_geometry()
        self._setup_styles()

        self.path = str(config.ROOT / config.CONFIG_NAME)
        self.cfg = config.load(self.path)
        self.form = settings.form_from_config(self.cfg)
        self.vars: dict[str, dict] = {}
        self.panel_cards: dict[str, dict] = {}
        self.results: dict[str, object] = {}
        self.login_cache: dict[str, object] = {}
        self.show_advanced = False
        self.queue: queue.Queue = queue.Queue()
        self.current = platforms.all_specs()[0].key if platforms.all_specs() else ""
        self.running = False
        self.quota_window = None
        self.time_var = tk.StringVar(value=(self.cfg.get("ui") or {}).get("time", settings.DEFAULT_TIME))
        self.dry_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="")

        for spec in platforms.all_specs():
            self.vars[spec.key] = {}
            for fld in spec.fields:
                self.vars[spec.key][fld.key] = (
                    tk.BooleanVar(value=bool(self.form[spec.key][fld.key]))
                    if fld.kind == "bool"
                    else tk.StringVar(value=str(self.form[spec.key][fld.key]))
                )

        self._build_layout()
        self._refresh_cards()
        self._select(self.current)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._bring_to_front()
        self._write_launch_mark()

    # ------------------------------------------------------------ 基础
    def P(self, value) -> int:
        return int(round(value * self.scale))

    def font(self, size_pt: int, bold: bool = False):
        px = int(round(size_pt * self.scale * 96 / 72))
        return ("Microsoft YaHei UI", -px, "bold" if bold else "normal")

    def _setup_geometry(self) -> None:
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = min(self.P(1120), sw - self.P(24))
        h = min(self.P(760), sh - self.P(88))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2 - self.P(10))
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(min(self.P(900), sw), min(self.P(620), sh))

    def _setup_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Card.TCheckbutton", background=COLORS["card"], foreground=COLORS["text"],
                        font=self.font(10), padding=self.P(2))
        style.configure("Bg.TCheckbutton", background=COLORS["bg"], foreground=COLORS["text"],
                        font=self.font(10), padding=self.P(2))
        style.map("Card.TCheckbutton", background=[("active", COLORS["card"])])
        style.map("Bg.TCheckbutton", background=[("active", COLORS["bg"])])
        style.configure("TScrollbar", background=COLORS["border"], troughcolor=COLORS["bg"])

    def _bring_to_front(self) -> None:
        """全屏浏览器会盖住新窗口：先置顶，再把焦点抢过来，1.2 秒后取消置顶。"""
        try:
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.focus_force()
            self.root.after(1200, lambda: self.root.attributes("-topmost", False))
        except tk.TclError:
            pass

    def _write_launch_mark(self) -> None:
        """记录一次成功启动，便于排查"双击没反应"。"""
        try:
            log_dir = config.ROOT / "logs"
            log_dir.mkdir(exist_ok=True)
            with open(log_dir / "ui_launch.log", "a", encoding="utf-8") as f:
                import datetime
                f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} 窗口已打开 "
                        f"(scale={self.scale:.2f}, python={sys.executable})\n")
        except Exception:
            pass

    # ------------------------------------------------------------ 布局
    def _build_layout(self) -> None:
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=3)
        self.root.grid_rowconfigure(4, weight=1, minsize=self.P(96))

        header = tk.Frame(self.root, bg=COLORS["bg"])
        header.grid(row=0, column=0, sticky="ew", padx=self.P(20), pady=(self.P(16), self.P(6)))
        header.grid_columnconfigure(0, weight=1)

        title = tk.Label(header, text=TITLE_PREFIX, font=self.font(18, True),
                         bg=COLORS["bg"], fg=COLORS["text"], anchor="w")
        title.grid(row=0, column=0, sticky="w")
        subtitle = tk.Label(header, text="勾选要挂的平台，填好凭证，一键签到；也可以设成每天定点自动跑",
                            font=self.font(9), bg=COLORS["bg"], fg=COLORS["muted"], anchor="w")
        subtitle.grid(row=1, column=0, sticky="w", pady=(self.P(2), 0))

        right = tk.Frame(header, bg=COLORS["bg"])
        right.grid(row=0, column=1, rowspan=2, sticky="e")
        path_label = tk.Label(right, text="配置：" + self.path, font=self.font(8),
                              bg=COLORS["bg"], fg=COLORS["muted"])
        path_label.pack(anchor="e")
        open_btn = tk.Button(right, text="打开项目文件夹", font=self.font(8), bd=0,
                             bg=COLORS["bg"], fg=COLORS["accent"], activebackground=COLORS["bg"],
                             cursor="hand2", command=self._open_project_dir)
        open_btn.pack(anchor="e", pady=(self.P(2), 0))
        tk.Label(right, text=f"v{VERSION}", font=self.font(8),
                 bg=COLORS["bg"], fg=COLORS["muted"]).pack(anchor="e")

        body = tk.Frame(self.root, bg=COLORS["bg"])
        body.grid(row=1, column=0, sticky="nsew", padx=self.P(20))
        body.grid_columnconfigure(0, weight=0, minsize=self.P(300))
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # 左侧：平台卡片
        left = tk.Frame(body, bg=COLORS["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, self.P(16)))
        head = tk.Frame(left, bg=COLORS["bg"])
        head.pack(fill="x", pady=(0, self.P(6)))
        tk.Label(head, text="① 选择平台", font=self.font(11, True),
                 bg=COLORS["bg"], fg=COLORS["text"], anchor="w").pack(side="left")
        for text, state in (("全不选", False), ("全选", True)):
            link = tk.Label(head, text=text, font=self.font(8), bg=COLORS["bg"],
                            fg=COLORS["accent"], cursor="hand2")
            link.pack(side="right", padx=(self.P(8), 0))
            link.bind("<Button-1>", lambda _e, s=state: self._set_all(s))
        self.cards_holder = tk.Frame(left, bg=COLORS["bg"])
        self.cards_holder.pack(fill="x", anchor="n")
        tk.Label(left, text="勾选框 = 是否参与签到；点卡片查看右边设置",
                 font=self.font(8), bg=COLORS["bg"], fg=COLORS["muted"],
                 wraplength=self.P(280), justify="left").pack(fill="x", pady=(self.P(4), 0))

        for spec in platforms.all_specs():
            self._build_card(spec)

        # 右侧：设置详情
        right_col = tk.Frame(body, bg=COLORS["bg"])
        right_col.grid(row=0, column=1, sticky="nsew")
        tk.Label(right_col, text="② 平台设置", font=self.font(11, True), bg=COLORS["bg"],
                 fg=COLORS["text"], anchor="w").pack(fill="x", pady=(0, self.P(6)))
        self.detail = tk.Frame(right_col, bg=COLORS["card"], highlightthickness=1,
                               highlightbackground=COLORS["border"])
        self.detail.pack(fill="both", expand=True)

        # ③ 每天自动
        schedule = tk.Frame(self.root, bg=COLORS["card"], highlightthickness=1,
                            highlightbackground=COLORS["border"])
        schedule.grid(row=2, column=0, sticky="ew", padx=self.P(20), pady=(self.P(12), 0))
        tk.Label(schedule, text="③ 每天自动", font=self.font(11, True), bg=COLORS["card"],
                 fg=COLORS["text"]).pack(side="left", padx=(self.P(14), self.P(10)), pady=self.P(10))
        tk.Entry(schedule, textvariable=self.time_var, font=self.font(10), width=6,
                 justify="center", relief="flat", bg="#FFFFFF", highlightthickness=1,
                 highlightbackground=COLORS["border"]).pack(side="left", ipady=self.P(3))
        tk.Label(schedule, text="(HH:MM，" + TASK_NAME_NOTE + ")", font=self.font(8),
                 bg=COLORS["card"], fg=COLORS["muted"]).pack(side="left", padx=(self.P(8), self.P(12)))
        self._button(schedule, "注册定时任务", self._install_task, primary=False).pack(side="left")
        self._button(schedule, "移除", self._remove_task, primary=False).pack(side="left", padx=self.P(6))
        self.task_label = tk.Label(schedule, text="定时任务：" + settings.task_state(),
                                   font=self.font(8), bg=COLORS["card"], fg=COLORS["muted"])
        self.task_label.pack(side="right", padx=(0, self.P(14)))

        # 操作行
        actions = tk.Frame(self.root, bg=COLORS["bg"])
        actions.grid(row=3, column=0, sticky="ew", padx=self.P(20), pady=(self.P(10), self.P(6)))
        ttk.Checkbutton(actions, text="试运行（只打印将要发出的请求，不真签到）",
                        variable=self.dry_var, style="Bg.TCheckbutton").pack(side="left")
        self._button(actions, "保存配置", self._save_clicked, primary=False).pack(side="left", padx=self.P(12))
        self._button(actions, "额度看板", self._open_quota, primary=False).pack(side="left", padx=(0, self.P(12)))
        self.ready_label = tk.Label(actions, text="", font=self.font(9), bg=COLORS["bg"],
                                    fg=COLORS["muted"])
        self.ready_label.pack(side="left", padx=self.P(8))
        self.run_button = self._button(actions, "立即签到", self._run_clicked, primary=True)
        self.run_button.pack(side="right")

        # 日志
        log_wrap = tk.Frame(self.root, bg=COLORS["bg"])
        log_wrap.grid(row=4, column=0, sticky="nsew", padx=self.P(20), pady=(0, self.P(14)))
        log_wrap.grid_columnconfigure(0, weight=1)
        log_wrap.grid_rowconfigure(0, weight=1)
        self.log = tk.Text(log_wrap, font=self.font(9), bg="#FFFFFF", fg=COLORS["text"],
                           relief="flat", highlightthickness=1, highlightbackground=COLORS["border"],
                           wrap="word", height=4, padx=self.P(10), pady=self.P(8))
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_wrap, orient="vertical", command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)
        self.log.tag_configure("muted", foreground=COLORS["muted"])
        self.log.tag_configure("ok", foreground=COLORS["ok"])
        self.log.tag_configure("err", foreground=COLORS["err"])
        self.log.tag_configure("title", foreground=COLORS["text"], font=self.font(9, True))
        self.log.configure(state="disabled")

    def _button(self, parent, text, command, primary: bool):
        return tk.Button(parent, text=text, command=command, font=self.font(9),
                         bd=0, cursor="hand2",
                         bg=COLORS["accent"] if primary else "#FFFFFF",
                         fg="#FFFFFF" if primary else COLORS["text"],
                         activebackground=COLORS["accent"] if primary else "#F9FAFB",
                         activeforeground="#FFFFFF" if primary else COLORS["text"],
                         highlightthickness=0 if primary else 1,
                         highlightbackground=COLORS["border"],
                         padx=self.P(14), pady=self.P(5))

    def _build_card(self, spec) -> None:
        card = tk.Frame(self.cards_holder, bg=COLORS["card"], highlightthickness=1,
                        highlightbackground=COLORS["border"], cursor="hand2")
        card.pack(fill="x", pady=(0, self.P(8)))
        card.grid_columnconfigure(1, weight=1)

        chk_var = tk.BooleanVar(value=bool(self.form["enabled"][spec.key]))
        mark = tk.Label(card, text="☑" if chk_var.get() else "☐",
                        font=self.font(13), bg=COLORS["card"],
                        fg=COLORS["accent"] if chk_var.get() else COLORS["muted"], cursor="hand2")
        mark.grid(row=0, column=0, padx=(self.P(12), 0), pady=self.P(8), sticky="w")
        mark.bind("<Button-1>", lambda _e, k=spec.key: self._toggle_enabled(k))

        name = tk.Label(card, text=spec.label, font=self.font(10, True), bg=COLORS["card"],
                        fg=COLORS["text"], anchor="w", cursor="hand2")
        name.grid(row=0, column=1, sticky="w")
        status = tk.Label(card, text="", font=self.font(8), bg=COLORS["card"], fg=COLORS["muted"])
        status.grid(row=0, column=2, padx=(self.P(6), self.P(12)), sticky="e")

        for widget in (card, name, status):
            widget.bind("<Button-1>", lambda _e, k=spec.key: self._select(k))

        self.panel_cards[spec.key] = {"card": card, "check": chk_var, "mark": mark,
                                       "status": status, "name": name}

    # ------------------------------------------------------------ 卡片交互
    def _refresh_cards(self) -> None:
        for spec in platforms.all_specs():
            entry = self.panel_cards[spec.key]
            entry["check"].set(bool(self.form["enabled"][spec.key]))
            on = entry["check"].get()
            entry["mark"].configure(text="☑" if on else "☐",
                                    fg=COLORS["accent"] if on else COLORS["muted"])
            text, color = self._card_status(spec.key)
            entry["status"].configure(text=text, fg=color)
            entry["card"].configure(highlightbackground=(
                COLORS["accent"] if spec.key == self.current else COLORS["border"]))

        enabled = settings.enabled_platforms(self.form)
        ready = [p for p in enabled if settings.ready(self.form, p)]
        self.ready_label.configure(
            text=f"已勾选 {len(enabled)} 个平台，其中 {len(ready)} 个可以直接跑",
            fg=COLORS["err"] if enabled and not ready else COLORS["muted"])

    def _card_status(self, key: str) -> tuple[str, str]:
        result = self.results.get(key)
        if result is not None:
            return STATUS_CN.get(result.status.value, result.status.value), {
                Status.OK: COLORS["ok"], Status.ALREADY: COLORS["muted"],
                Status.NEED_SETUP: COLORS["warn"], Status.SKIPPED: COLORS["muted"],
            }.get(result.status, COLORS["err"])
        if not self.form["enabled"][key]:
            return "未启用", COLORS["muted"]
        if settings.ready(self.form, key):
            return "已就绪", COLORS["ok"]
        return "待配置", COLORS["warn"]

    def _toggle_enabled(self, key: str) -> None:
        # 单独切换：先翻转状态，再同步到配置；不能只读取当前值。
        value = settings.toggle_platform(self.form, key)
        self.panel_cards[key]["check"].set(value)
        self.results.pop(key, None)
        self._refresh_cards()
        self._save(silent=True)

    def _set_all(self, enabled: bool) -> None:
        """全选 / 全不选：一次勾选多个平台（签到时会按勾选批量跑）。"""
        for spec in platforms.all_specs():
            self.form["enabled"][spec.key] = bool(enabled)
            self.results.pop(spec.key, None)
        self._refresh_cards()
        self._render_detail()
        self._save(silent=True)

    def _select(self, key: str) -> None:
        self.current = key
        self._refresh_cards()
        self._render_detail()

    # ------------------------------------------------------------ 详情面板
    def _render_detail(self) -> None:
        for child in self.detail.winfo_children():
            child.destroy()
        spec = platforms.get(self.current)

        head = tk.Frame(self.detail, bg=COLORS["card"])
        head.pack(fill="x", padx=self.P(20), pady=(self.P(20), 0))
        tk.Label(head, text=spec.label, font=self.font(15, True), bg=COLORS["card"],
                 fg=COLORS["text"], anchor="w").pack(fill="x")
        tk.Label(head, text=spec.description, font=self.font(9), bg=COLORS["card"],
                 fg=COLORS["muted"], anchor="w", justify="left",
                 wraplength=self.P(680)).pack(fill="x", pady=(self.P(6), 0))

        if spec.login_state is not None or spec.login_hint:
            self._build_login_box(spec)

        fields = tk.Frame(self.detail, bg=COLORS["card"])
        fields.pack(fill="x", padx=self.P(20), pady=(self.P(14), 0))
        fields.grid_columnconfigure(1, weight=1)

        row = 0
        for fld in spec.fields:
            if fld.advanced and not self.show_advanced:
                continue
            row = self._build_field(fields, spec, fld, row)

        self._build_actions(fields, spec, row + 1)

        result_box = tk.Frame(self.detail, bg="#F9FAFB", highlightthickness=1,
                              highlightbackground=COLORS["border"])
        result_box.pack(side="bottom", fill="x", padx=self.P(20), pady=(self.P(10), self.P(18)))
        tk.Label(result_box, text="最近一次结果", font=self.font(8), bg="#F9FAFB",
                 fg=COLORS["muted"], anchor="w").pack(fill="x", padx=self.P(12), pady=(self.P(8), 0))
        result = self.results.get(spec.key)
        text = "还没跑过" if result is None else f"{STATUS_CN.get(result.status.value, '')} · {result.message}"
        tk.Label(result_box, text=text, font=self.font(9), bg="#F9FAFB",
                 fg=COLORS["text"] if result else COLORS["muted"], anchor="w", justify="left",
                 wraplength=self.P(660)).pack(fill="x", padx=self.P(12), pady=(self.P(2), self.P(10)))

    def _build_field(self, parent, spec, fld, row: int) -> int:
        tk.Label(parent, text=fld.label, font=self.font(9), bg=COLORS["card"],
                 fg=COLORS["text"], anchor="w").grid(row=row, column=0, sticky="w",
                                                     padx=(0, self.P(12)), pady=(self.P(8), 0))
        var = self.vars[spec.key][fld.key]

        if fld.kind == "bool":
            holder = tk.Frame(parent, bg=COLORS["card"])
            holder.grid(row=row, column=1, sticky="w", pady=(self.P(8), 0))
            mark = tk.Label(holder, text="☑" if var.get() else "☐", font=self.font(12),
                            bg=COLORS["card"],
                            fg=COLORS["accent"] if var.get() else COLORS["muted"], cursor="hand2")
            mark.pack(side="left")
            tk.Label(holder, text="开启", font=self.font(9), bg=COLORS["card"],
                     fg=COLORS["text"], cursor="hand2").pack(side="left", padx=(self.P(4), 0))
            holder.bind("<Button-1>", lambda _e, v=var, m=mark: self._toggle_bool(v, m))
            mark.bind("<Button-1>", lambda _e, v=var, m=mark: self._toggle_bool(v, m))
            return row + 1

        entry = tk.Entry(parent, textvariable=var, font=self.font(9), bg="#FFFFFF", relief="flat",
                         highlightthickness=1, highlightbackground=COLORS["border"],
                         highlightcolor=COLORS["accent"],
                         show="*" if fld.kind == "secret" else "")
        entry.grid(row=row, column=1, sticky="ew", pady=(self.P(8), 0), ipady=self.P(3))

        buttons = tk.Frame(parent, bg=COLORS["card"])
        buttons.grid(row=row, column=2, sticky="w", padx=(self.P(8), 0), pady=(self.P(8), 0))
        if fld.kind == "secret":
            self._button(buttons, "粘贴剪贴板", lambda k=spec.key, f=fld: self._paste(k, f),
                         primary=False).pack(side="left")
        if fld.kind == "path":
            self._button(buttons, "选择 exe", lambda k=spec.key, f=fld: self._browse_path(k, f),
                         primary=False).pack(side="left")

        if fld.hint:
            tk.Label(parent, text=fld.hint, font=self.font(8), bg=COLORS["card"], fg=COLORS["muted"],
                     anchor="w", justify="left", wraplength=self.P(560)).grid(
                row=row + 1, column=1, columnspan=2, sticky="w", pady=(self.P(2), 0))
            return row + 2
        return row + 1

    def _build_actions(self, parent, spec, row: int) -> None:
        if not spec.actions:
            return
        bar = tk.Frame(parent, bg=COLORS["card"])
        bar.grid(row=row, column=0, columnspan=3, sticky="w", pady=(self.P(14), 0))
        for action in spec.actions:
            if action == "login" and spec.login_url:
                b = self._button(bar, "打开登录页", lambda u=spec.login_url: webbrowser.open(u),
                                 primary=False)
            elif action == "teach":
                b = self._button(bar, "校准点击位置", lambda k=spec.key: self._teach(k), primary=False)
            elif action == "probe":
                b = self._button(bar, "自动探测路径", lambda k=spec.key: self._probe(k), primary=False)
            elif action == "open_client":
                b = self._button(bar, "现在打开", lambda k=spec.key: self._open_client(k), primary=False)
            else:
                continue
            b.pack(side="left", padx=(0, self.P(8)))

    def _login_state_for(self, key: str):
        if key not in self.login_cache:
            self.login_cache[key] = platforms.get(key).detect_login()
        return self.login_cache[key]

    def _refresh_login(self) -> None:
        self.login_cache.clear()
        self._render_detail()
        self._refresh_cards()

    def _toggle_advanced(self) -> None:
        self.show_advanced = not self.show_advanced
        self._render_detail()

    def _build_login_box(self, spec) -> None:
        """「登录一次就行」这一区的界面：显示当前是不是已经读到登录态。"""
        box = tk.Frame(self.detail, bg="#F6F8F7", highlightthickness=1,
                       highlightbackground=COLORS["border"])
        box.pack(fill="x", padx=self.P(20), pady=(self.P(12), 0))
        state = self._login_state_for(spec.key) if spec.login_state is not None else None
        if state is None:
            text, color = (spec.login_hint or "该平台不需要登录"), COLORS["muted"]
        elif state.ok:
            who = ""
            if state.account:
                acct = state.account if len(state.account) <= 20 else state.account[:8] + "…"
                who = f" · {acct}"
            text, color = f"已登录{who}（凭证自动读取，不用填任何东西）", COLORS["ok"]
        else:
            text, color = f"未登录：{state.message or spec.login_hint}", COLORS["warn"]

        row = tk.Frame(box, bg="#F6F8F7")
        row.pack(fill="x", padx=self.P(12), pady=self.P(8))
        tk.Label(row, text="登录状态", font=self.font(8), bg="#F6F8F7",
                 fg=COLORS["muted"]).pack(side="left")
        tk.Label(row, text=text, font=self.font(9), bg="#F6F8F7", fg=color, anchor="w",
                 justify="left", wraplength=self.P(400)).pack(side="left", padx=(self.P(10), 0), fill="x")

        if spec.login_state is not None:
            self._button(row, "刷新", self._refresh_login, primary=False).pack(side="right")
        if any(fld.advanced for fld in spec.fields):
            toggle = tk.Label(row, text=("收起高级项" if self.show_advanced else "显示高级项"),
                              font=self.font(8), bg="#F6F8F7", fg=COLORS["accent"], cursor="hand2")
            toggle.pack(side="right", padx=(0, self.P(10)))
            toggle.bind("<Button-1>", lambda _e: self._toggle_advanced())

    def _toggle_bool(self, var, mark) -> None:
        var.set(not bool(var.get()))
        mark.configure(text="☑" if var.get() else "☐",
                       fg=COLORS["accent"] if var.get() else COLORS["muted"])

    # ------------------------------------------------------------ 字段动作
    def _paste(self, key: str, fld) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            self._log("剪贴板是空的，先复制凭证再点粘贴", "err")
            return
        self.vars[key][fld.key].set(text.strip())
        self._log(f"已粘贴到 {platforms.get(key).label} · {fld.label}（长度 {len(text.strip())}）", "muted")

    def _browse_path(self, key: str, fld) -> None:
        path = filedialog.askopenfilename(title="选择客户端可执行文件",
                                          filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")])
        if path:
            self.vars[key][fld.key].set(path)

    def _probe(self, key: str) -> None:
        path = apps.resolve_doubao("")
        if not path:
            self._log("没探测到豆包客户端，请手动选择 exe", "err")
            return
        for fld in platforms.get(key).fields:
            if fld.kind == "path":
                self.vars[key][fld.key].set(path)
        self._log(f"已探测到：{path}", "ok")

    def _open_client(self, key: str) -> None:
        spec = platforms.get(key)
        path = ""
        for fld in spec.fields:
            if fld.kind == "path":
                path = apps.resolve_doubao(self.vars[key][fld.key].get())
        if not path:
            self._log("还没有可用路径，先探测或手填", "err")
            return
        ok = apps.launch(path)
        self._log(("已打开：" if ok else "打开失败：") + path, "ok" if ok else "err")

    def _teach(self, key: str) -> None:
        spec = platforms.get(key)
        messagebox.showinfo("校准点击位置",
                            "点确定后 5 秒内，把鼠标移到客户端的「签到 / 领取」按钮上，别动鼠标。")
        try:
            self.root.iconify()
        except tk.TclError:
            pass
        threading.Thread(target=self._teach_worker, args=(key,), daemon=True).start()

    def _teach_worker(self, key: str) -> None:
        try:
            point = gui_mod.record_point(key)
        except gui_mod.GuiUnavailable as e:
            self.queue.put(("log", f"无法校准：{e}", "err"))
            return
        except Exception as e:
            self.queue.put(("log", f"校准失败：{type(e).__name__}: {e}", "err"))
            return
        self.queue.put(("teach", (key, point)))

    def _apply_teach(self, key: str, point: dict) -> None:
        if not point.get("window"):
            self._log("没抓到窗口，校准失败", "err")
            return
        self.cfg.setdefault(key, {})["gui_click"] = point
        self.form[key]["gui_click_ready"] = True
        self._save(silent=True)
        self._log(f"已校准：窗口「{point['window']}」 位置 {point['x_ratio']:.2f}/{point['y_ratio']:.2f}", "ok")
        self._render_detail()
        self._refresh_cards()
        try:
            self.root.deiconify()
            self.root.lift()
        except tk.TclError:
            pass

    # ------------------------------------------------------------ 保存
    def _collect(self) -> dict:
        self.form["enabled"] = {k: bool(self.panel_cards[k]["check"].get()) for k in self.form["enabled"]}
        for spec in platforms.all_specs():
            for fld in spec.fields:
                self.form[spec.key][fld.key] = self.vars[spec.key][fld.key].get()
        return self.form

    def _save(self, silent: bool = False) -> bool:
        time_text = (self.time_var.get() or "").strip()
        if not settings.validate_time(time_text):
            if not silent:
                messagebox.showwarning("时间格式不对", "每日执行时间要写成 HH:MM，例如 10:10。")
            return False
        self.cfg = settings.apply_form(self.cfg, self._collect())
        self.cfg.setdefault("ui", {})["time"] = time_text
        settings.save_config(self.path, self.cfg)
        self.form = settings.form_from_config(self.cfg)
        self._refresh_cards()
        if not silent:
            self._log(f"配置已保存：{self.path}", "muted")
        return True

    def _save_clicked(self) -> None:
        if self._save():
            self._render_detail()

    def _open_project_dir(self) -> None:
        try:
            os.startfile(str(config.ROOT))  # noqa: S606 - Windows 打开资源管理器
        except Exception as e:
            self._log(f"打不开文件夹：{e}", "err")

    def _open_quota(self) -> None:
        """打开只读的额度看板；重复点击只把已有窗口提到前面。"""
        from .quota import QuotaDashboard
        if self.quota_window is not None and getattr(self.quota_window, "alive", False):
            self.quota_window.lift()
            return
        self.quota_window = QuotaDashboard(self)

    # ------------------------------------------------------------ 定时任务
    def _install_task(self) -> None:
        if not self._save():
            return
        cmd = settings.task_command(str(config.ROOT), self.time_var.get())
        self._run_task_command(cmd, "已注册定时任务：" + self.time_var.get())

    def _remove_task(self) -> None:
        self._run_task_command(settings.remove_task_command(str(config.ROOT)), "已移除定时任务")

    def _run_task_command(self, cmd: list[str], ok_text: str) -> None:
        self._log("执行：" + " ".join(cmd), "muted")
        try:
            code = subprocess.call(cmd, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            self._log(f"命令启动失败：{type(e).__name__}: {e}", "err")
            return
        if code == 0:
            self._log(ok_text, "ok")
        else:
            self._log(f"计划任务脚本返回 {code}，看 scripts 目录里的输出", "err")
        try:
            self.task_label.configure(text="定时任务：" + settings.task_state())
        except tk.TclError:
            pass

    # ------------------------------------------------------------ 执行
    def _run_clicked(self) -> None:
        if self.running:
            return
        if not self._save():
            return
        problems = settings.problems(self.form)
        if problems:
            for key, text in problems:
                self._log("待补：" + text, "muted" if key != "*" else "err")
            if not settings.enabled_platforms(self.form):
                messagebox.showwarning("没有可跑的平台", "先勾选至少一个平台，并把凭证补齐。")
                return
        self._start_run(bool(self.dry_var.get()))

    def _start_run(self, dry_run: bool) -> None:
        self.running = True
        self.last_dry_run = bool(dry_run)
        self.run_button.configure(state="disabled", text="执行中…")
        self.status_var.set("")
        self._clear_log()
        self._log(("开始试运行" if dry_run else "开始签到") + f"（{len(settings.enabled_platforms(self.form))} 个平台）", "title")
        cfg = self.cfg
        threading.Thread(target=self._run_worker, args=(cfg, dry_run), daemon=True).start()
        self._poll()

    def _run_worker(self, cfg: dict, dry_run: bool) -> None:
        try:
            client = runner.build_client(cfg)
            results = runner.run_all(
                cfg, client=client, dry_run=dry_run,
                log=_QueueLogger(self.queue),
                on_result=lambda r: self.queue.put(("result", r)),
            )
            self.queue.put(("done", results))
        except Exception as e:
            self.queue.put(("log", f"执行异常：{type(e).__name__}: {e}", "err"))
            self.queue.put(("done", []))

    def _poll(self) -> None:
        try:
            while True:
                item = self.queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._log(item[1], item[2])
                elif kind == "result":
                    result = item[1]
                    self.results[result.platform] = result
                    self._refresh_cards()
                    if result.platform == self.current:
                        self._render_detail()
                elif kind == "done":
                    self._finish_run(item[1])
                    return
                elif kind == "teach":
                    self._apply_teach(*item[1])
        except queue.Empty:
            pass
        if self.running:
            self.root.after(100, self._poll)

    def _finish_run(self, results: list) -> None:
        if results and not getattr(self, "last_dry_run", False):
            try:
                history.append(results)
            except Exception as exc:
                self._log(f"写签到历史失败：{type(exc).__name__}: {exc}", "err")
        if results:
            for line in runner.summary(results).splitlines():
                self._log(line, "muted")
        else:
            self._log("没有平台被执行（可能都没勾选，或都缺配置）", "muted")
        self.running = False
        self.run_button.configure(state="normal", text="立即签到")
        self._refresh_cards()

    # ------------------------------------------------------------ 日志
    def _log(self, text: str, tag: str = "muted") -> None:
        import datetime
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"[{stamp}] {text}\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # ------------------------------------------------------------ 收尾
    def _on_close(self) -> None:
        try:
            if not self.running:
                self._save(silent=True)
        except Exception:
            pass
        self.root.destroy()


class _QueueLogger:
    """把 run_all 的日志塞进界面队列。"""

    def __init__(self, q: queue.Queue):
        self.q = q

    def info(self, msg: str, *args) -> None:
        text = msg % args if args else msg
        self.q.put(("log", text, "muted"))


def _write_error_log(exc: BaseException) -> str:
    try:
        log_dir = config.ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        path = log_dir / "ui_error.log"
        with open(path, "a", encoding="utf-8") as f:
            import datetime
            f.write(f"\n=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
            f.write("".join(traceback.format_exception(exc)))
        return str(path)
    except Exception:
        return ""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    selftest = "--selftest" in argv

    _enable_dpi_awareness()
    try:
        app = SignInApp()
    except Exception as e:  # 无可用显示 / Tcl 初始化失败
        msg = str(e)
        log_path = _write_error_log(e)
        if "init.tcl" in msg or "Tcl" in msg:
            print("当前 Python 缺少 Tcl/Tk 运行文件（tkinter 用不了），开不了窗口。")
            print("换一个带 tkinter 的解释器，例如：py -3 gui_app.py")
        else:
            print(f"无法创建窗口（{type(e).__name__}: {msg.splitlines()[0] if msg else ''}）")
        if log_path:
            print(f"详细信息已写入：{log_path}")
        return 2

    if selftest:
        app.root.update_idletasks()
        app.root.update()
        specs = platforms.all_specs()
        ok = len(app.panel_cards) == len(specs) and all(k in app.panel_cards for k in platforms.keys())
        print(f"UI-{'OK' if ok else 'BAD'} panels={len(specs)} cards={len(app.panel_cards)} "
              f"scale={app.scale:.1f} fields={sum(len(s.fields) for s in specs)}")
        try:
            from .quota import QuotaDashboard
            dash = QuotaDashboard(app, autorun=False)
            app.root.update_idletasks()
            dash_ok = len(dash.rows) == len(specs)
            print(f"DASH-{'OK' if dash_ok else 'BAD'} rows={len(dash.rows)}")
            dash.close()
        except Exception as exc:
            dash_ok = False
            print(f"DASH-BAD {type(exc).__name__}: {exc}")
        app.root.destroy()
        return 0 if (ok and dash_ok) else 3

    app.root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
