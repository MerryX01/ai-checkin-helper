"""科技感深色主题：色板 + 颜色插值工具。

tkinter 没有 alpha 通道，所有「渐变 / 呼吸 / 扫光」都靠在两个十六进制实色之间
逐帧插值实现；mix() 是唯一的插值入口，fx.py 与两个窗口都从这里取色。
"""

# 深空科技主题（Tk 无 alpha，全部实色；改这里即全局换肤）
COLORS = {
    "bg":         "#0A1120",  # 深空底色
    "bg_soft":    "#0E1830",  # 次级底色（登录框等）
    "card":       "#101B33",  # 卡片 / 面板
    "card_hi":    "#16233F",  # 卡片悬停
    "inset":      "#0B1426",  # 输入框 / 日志 / 明细等凹陷面
    "border":     "#1D2B4A",  # 常规描边
    "border_hi":  "#2E4470",  # 悬停描边
    "text":       "#D9E4FF",  # 主文本
    "muted":      "#7688AC",  # 次文本
    "accent":     "#35B5FF",  # 主色·电光青蓝
    "accent_dim": "#1D6FB0",  # 主色暗态（呼吸下沿 / 非选中强调）
    "accent2":    "#8B6CFF",  # 辅色·星云紫
    "ok":         "#3ED598",
    "warn":       "#FFB547",
    "err":        "#FF6E7D",
    "selection":  "#173565",  # 列表选中底
}


def _parse(color: str) -> tuple[int, int, int]:
    color = color.strip().lstrip("#")
    if len(color) != 6:
        raise ValueError(f"只支持 #RRGGBB，收到 {color!r}")
    return (int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % tuple(max(0, min(255, v)) for v in rgb)


def mix(c1: str, c2: str, t: float) -> str:
    """在两个颜色之间线性插值：t=0 → c1，t=1 → c2，越界自动截断。"""
    a, b = _parse(c1), _parse(c2)
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    return _hex(tuple(round(x + (y - x) * t) for x, y in zip(a, b)))


def shade(color: str, factor: float) -> str:
    """把颜色压向黑色（factor<1）或提亮（factor>1，最多溢出到白）。"""
    rgb = _parse(color)
    return _hex(tuple(round(v * factor) for v in rgb))


def wave(t: float, period: float, pause: float = 0.0) -> float:
    """0→1→0 的平滑往复：升/降各占一半，起点终点各停留 pause 秒。"""
    if period <= 0:
        return 0.0
    span = period - 2 * pause
    if span <= 0:
        return 0.0
    x = t % period
    if x < pause or x >= pause + span:
        return 0.0
    u = (x - pause) / span
    tri = 1 - abs(2 * u - 1)          # 0→1→0 三角
    return tri * tri * (3 - 2 * tri)  # smoothstep：两端速度为 0，不闪眼


def loop(t: float, period: float) -> float:
    """0→1 的循环波（扫光用，单向往复）。"""
    if period <= 0:
        return 0.0
    return (t % period) / period
