"""额度看板窗口：四平台余额、总量、已用、使用率、今日签到和用量明细。

数据由 `signin.services.quota` 在后台线程实时读取；窗口只负责展示，
不签到、不改平台数据。没有返回的字段显示「—」，不猜。
"""
import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk

from .. import platforms
from ..core.models import QUOTA_STATUS_CN, QuotaSnapshot, Status, pad
from ..services import history
from ..services import quota as quota_service
from ..services import runner
from . import fx, theme
from .theme import COLORS

COLUMNS = ("platform", "balance", "total", "used", "percent", "today", "status")
HEADINGS = {
    "platform": "平台",
    "balance": "余额",
    "total": "总量",
    "used": "已用",
    "percent": "使用率",
    "today": "今日签到",
    "status": "状态",
}
WIDTHS = {"platform": 150, "balance": 110, "total": 110, "used": 110,
          "percent": 90, "today": 110, "status": 100}


class QuotaDashboard:
    def __init__(self, app, autorun: bool = True):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.title("额度看板 · Trae CN / Qoder / WorkBuddy / 豆包")
        self.win.configure(bg=COLORS["bg"])
        self.win.transient(app.root)
        self.win.minsize(app.P(880), app.P(600))
        self._center(app.P(1120), app.P(760))

        self.snapshots: dict[str, QuotaSnapshot] = {}
        self.rows: dict[str, str] = {}
        self.queue: queue.Queue = queue.Queue()
        self.busy = False
        self.selected_key = platforms.all_specs()[0].key if platforms.all_specs() else ""
        self.updated_at = ""
        self.last_error = ""
        self.alive = True
        self.fx = fx.FxEngine(self.win)
        self.pending_keys: set[str] = set()
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self._build_styles()
        self._build_layout()
        self.fx.fade_in(self.win, ms=240)
        if autorun:
            self.refresh()

    # ------------------------------------------------------------ 基础
    def _center(self, width: int, height: int) -> None:
        self.win.update_idletasks()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        width = min(width, sw - self.app.P(24))
        height = min(height, sh - self.app.P(64))
        x = max(0, (sw - width) // 2)
        y = max(0, (sh - height) // 2 - self.app.P(8))
        self.win.geometry(f"{width}x{height}+{x}+{y}")

    def _build_styles(self) -> None:
        style = ttk.Style(self.win)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Quota.Treeview", background=COLORS["card"], fieldbackground=COLORS["card"],
                        foreground=COLORS["text"], rowheight=self.app.P(34), font=self.app.font(10),
                        borderwidth=0)
        style.configure("Quota.Treeview.Heading", background=COLORS["bg_soft"], foreground=COLORS["muted"],
                        font=self.app.font(9, True), relief="flat")
        style.map("Quota.Treeview", background=[("selected", COLORS["selection"])],
                  foreground=[("selected", COLORS["text"])])
        style.configure("TScrollbar", background=COLORS["border"], troughcolor=COLORS["bg"],
                        arrowcolor=COLORS["muted"])
        style.map("TScrollbar", background=[("active", COLORS["border_hi"])])

    def _button(self, parent, text, command, primary: bool = False):
        return self.app._button(parent, text, command, primary)

    # ------------------------------------------------------------ 布局
    def _build_layout(self) -> None:
        self.win.grid_columnconfigure(0, weight=1)
        self.win.grid_rowconfigure(1, weight=0)
        self.win.grid_rowconfigure(2, weight=1)

        header = tk.Frame(self.win, bg=COLORS["bg"])
        header.grid(row=0, column=0, sticky="ew", padx=self.app.P(20), pady=(self.app.P(16), self.app.P(8)))
        header.grid_columnconfigure(0, weight=1)
        tk.Label(header, text="额度看板", font=self.app.font(18, True), bg=COLORS["bg"],
                 fg=COLORS["text"], anchor="w").grid(row=0, column=0, sticky="w")
        tk.Label(header, text="实时读取客户端登录态对应的额度接口；只读查询，不会触发签到",
                 font=self.app.font(9), bg=COLORS["bg"], fg=COLORS["muted"], anchor="w").grid(
            row=1, column=0, sticky="w", pady=(self.app.P(2), 0))
        right = tk.Frame(header, bg=COLORS["bg"])
        right.grid(row=0, column=1, rowspan=2, sticky="e")
        self.refresh_btn = self._button(right, "刷新全部", self.refresh, primary=True)
        self.refresh_btn.pack(side="left", padx=(0, self.app.P(8)))
        self._button(right, "关闭", self.close, primary=False).pack(side="left")

        table_wrap = tk.Frame(self.win, bg=COLORS["card"], highlightthickness=1,
                              highlightbackground=COLORS["border"])
        table_wrap.grid(row=1, column=0, sticky="ew", padx=self.app.P(20))
        table_wrap.grid_columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(table_wrap, columns=COLUMNS, show="headings",
                                 style="Quota.Treeview", height=4)
        for col in COLUMNS:
            self.tree.heading(col, text=HEADINGS[col])
            self.tree.column(col, width=self.app.P(WIDTHS[col]), anchor="center" if col != "platform" else "w",
                             stretch=(col in ("platform", "balance", "total", "used")))
        self.tree.grid(row=0, column=0, sticky="ew", padx=(self.app.P(2), 0), pady=self.app.P(2))
        tree_scroll = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.tag_configure("ok", foreground=COLORS["text"])
        self.tree.tag_configure("need", foreground=COLORS["warn"])
        self.tree.tag_configure("bad", foreground=COLORS["err"])
        # 快照到达时的整行高亮：亮底色闪一下再沉回
        self.tree.tag_configure("fresh", background=theme.mix(COLORS["accent"], COLORS["card"], 0.30))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        for spec in platforms.all_specs():
            iid = self.tree.insert("", "end", values=(
                spec.label, "读取中…", "—", "—", "—", "—", "读取中"), tags=("ok",))
            self.rows[spec.key] = iid
        if self.rows and self.selected_key in self.rows:
            self.tree.selection_set(self.rows[self.selected_key])
            self.tree.focus(self.rows[self.selected_key])

        detail_wrap = tk.Frame(self.win, bg=COLORS["card"], highlightthickness=1,
                               highlightbackground=COLORS["border"])
        detail_wrap.grid(row=2, column=0, sticky="nsew", padx=self.app.P(20), pady=(self.app.P(10), 0))
        detail_wrap.grid_columnconfigure(0, weight=1)
        detail_wrap.grid_rowconfigure(1, weight=1)
        self.detail_title = tk.Label(detail_wrap, text="用量明细", font=self.app.font(11, True),
                                     bg=COLORS["card"], fg=COLORS["text"], anchor="w")
        self.detail_title.grid(row=0, column=0, sticky="w", padx=self.app.P(14), pady=(self.app.P(8), self.app.P(4)))
        self.detail = tk.Text(detail_wrap, font=self.app.font(9), bg=COLORS["inset"], fg=COLORS["text"],
                              relief="flat", wrap="word", height=12, padx=self.app.P(10),
                              pady=self.app.P(8), highlightthickness=0, insertbackground=COLORS["accent"])
        self.detail.grid(row=1, column=0, sticky="nsew", padx=(self.app.P(8), 0), pady=(0, self.app.P(8)))
        detail_scroll = ttk.Scrollbar(detail_wrap, orient="vertical", command=self.detail.yview)
        detail_scroll.grid(row=1, column=1, sticky="ns", pady=(0, self.app.P(8)))
        self.detail.configure(yscrollcommand=detail_scroll.set, state="disabled")
        self.detail.tag_configure("title", foreground=COLORS["text"], font=self.app.font(14, True))
        self.detail.tag_configure("section", foreground=COLORS["accent"], font=self.app.font(10, True))
        self.detail.tag_configure("body", foreground=COLORS["text"], font=self.app.font(9))
        self.detail.tag_configure("muted", foreground=COLORS["muted"], font=self.app.font(8))
        self.detail.tag_configure("ok", foreground=COLORS["ok"], font=self.app.font(9))
        self.detail.tag_configure("warn", foreground=COLORS["warn"], font=self.app.font(9))

        footer = tk.Frame(self.win, bg=COLORS["bg"])
        footer.grid(row=3, column=0, sticky="ew", padx=self.app.P(20), pady=(self.app.P(6), self.app.P(12)))
        self.footer = tk.Label(footer, text="额度来自各平台真实接口；显示「—」表示平台没有返回该字段。",
                               font=self.app.font(8), bg=COLORS["bg"], fg=COLORS["muted"], anchor="w")
        self.footer.pack(fill="x")

    # ------------------------------------------------------------ 刷新
    def refresh(self) -> None:
        if self.busy:
            return
        self.busy = True
        self.last_error = ""
        self.refresh_btn.configure(state="disabled")
        self.fx.dots(self.refresh_btn, "刷新中", fg="#FFFFFF", key="btn-dots")
        self.fx.spinner(self.footer, base="正在读取各平台额度", fg=COLORS["muted"], key="foot-spin")
        self.pending_keys = set(self.rows)
        for key, iid in self.rows.items():
            try:
                self.tree.item(iid, values=(platforms.get(key).label, "读取中", "—", "—", "—", "—", "读取中"))
            except tk.TclError:
                pass
        self._animate_pending()
        cfg = self.app.cfg
        results = history.today_results()
        results.update(dict(self.app.results))
        threading.Thread(target=self._worker, args=(cfg, results), daemon=True).start()
        self._poll()

    def _animate_pending(self) -> None:
        """读取中的行：状态列跟着旋转字符走。"""
        def job(t):
            if not self.pending_keys:
                return False
            frame = fx.SPINNER_FRAMES[int(t / 0.09) % len(fx.SPINNER_FRAMES)]
            for key in list(self.pending_keys):
                iid = self.rows.get(key)
                if not iid:
                    continue
                try:
                    vals = list(self.tree.item(iid, "values"))
                    vals[-1] = f"读取中 {frame}"
                    self.tree.item(iid, values=vals)
                except tk.TclError:
                    return False
            return True
        self.fx.add(job, key="row-spin")

    def _worker(self, cfg: dict, results: dict) -> None:
        try:
            client = runner.build_client(cfg)
            for spec in platforms.all_specs():
                snap = quota_service.collect(cfg, client=client, specs=[spec], results=results)[0]
                self.queue.put(("snap", snap))
        except Exception as exc:
            self.queue.put(("error", f"{type(exc).__name__}: {exc}"))
        finally:
            self.queue.put(("done", None))

    def _poll(self) -> None:
        if not self.alive:
            return
        try:
            while True:
                item = self.queue.get_nowait()
                kind = item[0]
                if kind == "snap":
                    self._apply_snapshot(item[1])
                elif kind == "error":
                    self.last_error = str(item[1])
                    self.fx.cancel("foot-spin")
                    self.footer.configure(text=f"读取失败：{item[1]}", fg=COLORS["err"])
                elif kind == "done":
                    self._finish_refresh()
                    return
        except queue.Empty:
            pass
        if self.busy:
            try:
                self.win.after(100, self._poll)
            except tk.TclError:
                self.alive = False

    def _apply_snapshot(self, snap: QuotaSnapshot) -> None:
        self.snapshots[snap.platform] = snap
        self.pending_keys.discard(snap.platform)
        iid = self.rows.get(snap.platform)
        if iid:
            tag = {Status.OK: "ok", Status.NEED_SETUP: "need", Status.FAILED: "bad"}.get(snap.status, "need")
            values = (
                snap.label, snap.fmt_balance(), snap.fmt_total(), snap.fmt_used(),
                snap.fmt_percent(), snap.fmt_today(),
                QUOTA_STATUS_CN.get(snap.status.value, snap.status.value),
            )
            try:
                self.tree.item(iid, values=values, tags=("fresh",))
            except tk.TclError:
                return
            self.win.after(340, lambda: self._settle_row(iid, tag))
        if snap.platform == self.selected_key:
            self._render_detail()

    def _settle_row(self, iid: str, tag: str) -> None:
        """高亮过后把行沉回语义色。"""
        if not self.alive:
            return
        try:
            self.tree.item(iid, tags=(tag,))
        except tk.TclError:
            pass

    def _finish_refresh(self) -> None:
        self.busy = False
        self.pending_keys.clear()
        self.fx.cancel("row-spin")
        self.fx.cancel("foot-spin")
        self.fx.cancel("btn-dots")
        self.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.refresh_btn.configure(state="normal", text="刷新全部", bg=COLORS["accent"])
        except tk.TclError:
            pass
        ok = sum(1 for s in self.snapshots.values() if s.status == Status.OK)
        total = len(self.snapshots)
        if self.last_error:
            self.footer.configure(text=f"读取失败：{self.last_error}", fg=COLORS["err"])
        else:
            self.footer.configure(
                text=f"更新于 {self.updated_at} · 正常 {ok}/{total} 个平台 · 显示「—」表示平台没有返回该字段",
                fg=COLORS["muted"])
        self._render_detail()

    # ------------------------------------------------------------ 明细
    def _on_select(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        for key, iid in self.rows.items():
            if iid == selected[0]:
                self.selected_key = key
                break
        self._render_detail()

    def _render_detail(self) -> None:
        snap = self.snapshots.get(self.selected_key)
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        if snap is None:
            self.detail_title.configure(text="用量明细")
            self._insert("点一行平台查看额度与用量明细。\n", "muted")
            self._insert("刷新全部后会从客户端登录态读取真实数据。\n", "muted")
            self.detail.configure(state="disabled")
            return

        self.detail_title.configure(text=f"{snap.label} · 用量明细")
        line = f"{QUOTA_STATUS_CN.get(snap.status.value, snap.status.value)}"
        if self.updated_at:
            line += f" · 更新于 {self.updated_at}"
        self._insert(line + "\n", "muted")
        if snap.message:
            self._insert(snap.message + "\n", "ok" if snap.status == Status.OK else "warn")
        self._insert("\n")

        self._insert("额度概览\n", "section")
        unit = f" {snap.unit}" if snap.unit else ""
        self._insert(f"  当前余额    {snap.fmt_balance()}{unit}\n", "body")
        self._insert(f"  总量        {snap.fmt_total()}{unit}\n", "body")
        self._insert(f"  已用        {snap.fmt_used()}{unit}\n", "body")
        self._insert(f"  使用率      {snap.fmt_percent()}\n", "body")
        today = snap.fmt_today()
        today_tag = "ok" if snap.today_earned is not None else "muted"
        self._insert(f"  今日签到    {today}\n", today_tag)
        if snap.today_text and snap.today_earned is None:
            self._insert(f"              {self._today_hint(snap.today_text)}\n", "muted")
        if snap.expire_at:
            self._insert(f"  到期        {snap.expire_at}\n", "body")

        if snap.details:
            self._insert("\n额度构成 / 记录\n", "section")
            for label, value in snap.details:
                self._insert(f"  {pad(label, 14)}{value}\n", "body")
        if snap.source:
            self._insert("\n数据源\n", "section")
            self._insert(f"  {snap.source}\n", "muted")
        self.detail.configure(state="disabled")

    def _insert(self, text: str, tag: str = "body") -> None:
        self.detail.insert("end", text, tag)

    @staticmethod
    def _today_hint(text: str) -> str:
        """把「今日签到」列里的短状态翻译成明细里的人话。"""
        return {
            "无资格": "这个账号没有个人版每日签到活动（工作版/飞书企业号）",
            "已签": "今天已签到；平台没有返回本次具体积分，不猜数字",
            "需登录": "登录态失效，需要重新登录一次客户端",
            "失败": "本次签到失败，鼠标悬停主界面可看具体原因",
        }.get(str(text), "")

    # ------------------------------------------------------------ 收尾
    def lift(self) -> None:
        try:
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
        except tk.TclError:
            pass

    def close(self) -> None:
        self.alive = False
        self.fx.stop()
        try:
            self.win.destroy()
        except tk.TclError:
            pass
