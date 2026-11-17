"""界面动效引擎：一个 after() 心跳驱动全窗口效果（≈30fps）。

tkinter 没有合成器，动效全靠逐帧改控件属性（颜色/坐标）。三条纪律：
- 每个窗口一个引擎、一个心跳循环；没有活动效果时不排帧，不空转占 CPU；
- 每帧只改颜色/坐标，不触发几何重排；
- 控件销毁引发的 TclError 一律吞掉并注销对应任务，关窗口动画绝不报错。

时钟经 `clock` 注入，纯逻辑（脉冲波形、过渡插值、互斥 key）可以在无显示
环境单测（tests.test_ui_fx 用 FakeRoot/FakeWidget 驱动真引擎）。
"""
import itertools
import time
import tkinter as tk

from . import theme

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
DOT_FRAMES = ("●", "● ●", "● ● ●", "● ●")


class FxEngine:
    TICK_MS = 33  # ≈30fps，人眼顺滑、CPU 占用可忽略

    def __init__(self, root, clock=None):
        self.root = root
        self._clock = clock or time.monotonic
        self._jobs = []
        self._keyed: dict = {}
        self._keys = itertools.count(1)
        self._alive = True
        self._scheduled = False

    # ------------------------------------------------------------ 心跳
    def add(self, job, key=None):
        """注册每帧回调 job(t)->bool；返回 False 或抛 TclError 即注销。

        同 key 互斥：后注册的顶掉先注册的（例如同一控件先后的过渡动画）。
        """
        if not self._alive:
            return None
        if key is not None and key in self._keyed:
            self._jobs.remove(self._keyed[key])
        if key is not None:
            self._keyed[key] = job
        self._jobs.append(job)
        self._schedule()
        return job

    def cancel(self, key) -> None:
        job = self._keyed.pop(key, None)
        if job is not None and job in self._jobs:
            self._jobs.remove(job)

    def stop(self) -> None:
        self._alive = False
        self._jobs = []
        self._keyed = {}

    def _schedule(self) -> None:
        if self._scheduled or not self._alive:
            return
        try:
            self.root.after(self.TICK_MS, self._tick)
            self._scheduled = True
        except tk.TclError:
            self._alive = False

    def _tick(self) -> None:
        if not self._alive:
            return
        self._scheduled = False
        t = self._clock()
        still = []
        for job in self._jobs:
            try:
                keep = bool(job(t))
            except tk.TclError:
                keep = False          # 控件已销毁：静默退场
            except Exception:
                keep = False          # 单个效果出错不能拖死整个心跳
            if keep:
                still.append(job)
        self._jobs = still
        self._keyed = {k: j for k, j in self._keyed.items() if j in still}
        if self._jobs:
            self._schedule()

    # ------------------------------------------------------------ 属性
    @staticmethod
    def _set(widget, attr: str, value) -> None:
        if attr == "border":  # Frame 的发光边框
            widget.configure(highlightbackground=value)
        else:
            widget.configure(**{attr: value})

    # ------------------------------------------------------------ 效果
    def pulse(self, widget, attr: str, c1: str, c2: str,
              period: float = 1.8, pause: float = 0.25, key=None):
        """呼吸：在 c1/c2 之间平滑往复。"""
        def job(t):
            self._set(widget, attr, theme.mix(c1, c2, theme.wave(t, period, pause)))
            return True
        return self.add(job, key)

    def transition(self, widget, attr: str, c_from: str, c_to: str,
                   ms: int = 160, key=None):
        """一次性过渡：ms 毫秒内从 c_from 渐变到 c_to。"""
        start = [None]

        def job(t):
            if start[0] is None:
                start[0] = t
            k = (t - start[0]) * 1000.0 / max(1, ms)
            if k >= 1.0:
                self._set(widget, attr, c_to)
                return False
            self._set(widget, attr, theme.mix(c_from, c_to, k * k * (3 - 2 * k)))
            return True
        return self.add(job, key or next(self._keys))

    def spinner(self, label, base: str = "", fg: str | None = None, key=None):
        """旋转字符指示器：⠋⠙⠹… 挂在文案尾部。"""
        if fg is not None:
            label.configure(fg=fg)
        step = 0.09

        def job(t):
            frame = SPINNER_FRAMES[int(t / step) % len(SPINNER_FRAMES)]
            label.configure(text=f"{base} {frame}")
            return True
        return self.add(job, key or next(self._keys))

    def dots(self, label, base: str, fg: str | None = None, key=None):
        """执行中指示：● → ● ● → ● ● ● 循环。"""
        if fg is not None:
            label.configure(fg=fg)
        step = 0.28

        def job(t):
            frame = DOT_FRAMES[int(t / step) % len(DOT_FRAMES)]
            label.configure(text=f"{base}{frame}")
            return True
        return self.add(job, key or next(self._keys))

    def sweep(self, canvas, item, x0: float, x1: float,
              y0: float, y1: float, period: float = 3.4, key=None):
        """扫光：canvas 矩形 item 在 x0..x1 间单向循环移动。"""
        def job(t):
            cx = x0 + (x1 - x0) * theme.loop(t, period)
            half = max(2.0, (y1 - y0) * 2.5)
            canvas.coords(item, cx - half, y0, cx + half, y1)
            return True
        return self.add(job, key or next(self._keys))

    def fade_in(self, window, ms: int = 280, key=None):
        """窗口渐显：tk 的 -alpha 在 Windows 上是真透明，可用。"""
        try:
            window.attributes("-alpha", 0.0)
        except tk.TclError:
            return None  # 平台不支持透明度：直接显示
        start = [None]

        def job(t):
            if start[0] is None:
                start[0] = t
            k = (t - start[0]) * 1000.0 / max(1, ms)
            if k >= 1.0:
                window.attributes("-alpha", 1.0)
                return False
            window.attributes("-alpha", 0.15 + 0.85 * k)
            return True
        return self.add(job, key or next(self._keys))
