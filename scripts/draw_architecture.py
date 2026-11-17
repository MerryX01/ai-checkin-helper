"""生成 docs/architecture.png —— 四平台签到助手分层架构图（v2.2.2）。

只依赖 Pillow；用系统微软雅黑字体，保证中文标签清晰。
运行：py -3 scripts/draw_architecture.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "architecture.png"

W, H = 1600, 930
BG = "#F6F8FB"
INK = "#17233D"
MUTED = "#64748B"
BORDER = "#E2E8F0"
WHITE = "#FFFFFF"

BLUE = "#2F6BFF"
TEAL = "#0E9F9F"
AMBER = "#D97706"
SLATE = "#475569"
GREEN = "#059669"

FONT = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT, size)


def rounded(draw, box, radius=12, fill=WHITE, outline=BORDER, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def text(draw, xy, value, size=14, color=INK, bold=False, anchor="la"):
    draw.text(xy, value, font=font(size, bold), fill=color, anchor=anchor)


def wrap(draw, xy, value, width, size=12, color=MUTED, line_gap=4):
    """按像素宽度折行，返回结束 y。"""
    f = font(size)
    lines = []
    for raw in value.split("\n"):
        line = ""
        for ch in raw:
            if draw.textlength(line + ch, font=f) <= width:
                line += ch
            else:
                lines.append(line)
                line = ch
        lines.append(line)
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=f, fill=color, anchor="la")
        y += size + line_gap
    return y


def arrow(draw, x1, y1, x2, y2, color="#94A3B8", width=2, dashed=False, head=True):
    if dashed:
        # 手工虚线
        length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        if length:
            step = 10
            for i in range(0, int(length), step * 2):
                t1 = i / length
                t2 = min((i + step) / length, 1)
                draw.line((x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1,
                           x1 + (x2 - x1) * t2, y1 + (y2 - y1) * t2),
                          fill=color, width=width)
    else:
        draw.line((x1, y1, x2, y2), fill=color, width=width)
    if head:
        if abs(x2 - x1) >= abs(y2 - y1):
            # 水平箭头
            direction = 1 if x2 >= x1 else -1
            draw.polygon([(x2, y2), (x2 - 8 * direction, y2 - 5),
                          (x2 - 8 * direction, y2 + 5)], fill=color)
        else:
            draw.polygon([(x2, y2), (x2 - 5, y2 - 8), (x2 + 5, y2 - 8)], fill=color)


def card(draw, box, title, lines, accent, title_size=14, line_size=11):
    rounded(draw, box, radius=10, fill=WHITE, outline=BORDER)
    x0, y0, x1, y1 = box
    draw.rounded_rectangle((x0, y0, x0 + 6, y1), radius=3, fill=accent)
    text(draw, (x0 + 18, y0 + 12), title, title_size, INK, True)
    y = y0 + 12 + title_size + 8
    for line in lines:
        y = wrap(draw, (x0 + 18, y), line, x1 - x0 - 30, line_size, MUTED, 3)


def layer_band(draw, y, h, label, color, cards, desc=""):
    rounded(draw, (50, y, 1180, y + h), radius=14, fill="#FFFFFF", outline=BORDER)
    draw.rounded_rectangle((50, y, 202, y + h), radius=14, fill=color)
    # 左侧标签
    text(draw, (126, y + h / 2 - 10), label, 15, WHITE, True, anchor="ma")
    if desc:
        text(draw, (126, y + h / 2 + 12), desc, 9, "#EAF2FF", anchor="ma")
    # 卡片区域
    n = len(cards)
    gap = 14
    content_x0, content_x1 = 218, 1166
    width = (content_x1 - content_x0 - gap * (n - 1)) / n
    for i, item in enumerate(cards):
        x0 = content_x0 + i * (width + gap)
        card(draw, (x0, y + 12, x0 + width, y + h - 12), *item, color)


def main() -> None:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)

    # 标题
    text(draw, (50, 30), "四平台每日签到 · 分层架构", 30, INK, True)
    text(draw, (50, 74), "一次签到，从界面到平台官方接口的完整链路  ·  v2.2.2", 13, MUTED)
    text(draw, (1550, 40), "Windows 桌面 / 纯标准库 Python / 可打包 exe", 11, MUTED, anchor="ra")

    # 分层
    layer_band(draw, 112, 92, "展示层", BLUE, [
        ("主界面（Tkinter）", ["四张平台卡片、单独勾选", "立即签到 / 设置 / 日志"]),
        ("额度看板", ["余额 · 总量 · 已用 · 使用率", "今日签到 · 选中行用量明细"]),
        ("CLI / 定时任务", ["run.py run / quota / check", "Windows 任务计划每天触发"]),
    ])

    layer_band(draw, 236, 92, "应用服务层", TEAL, [
        ("Runner 签到编排", ["按注册顺序执行", "单平台失败不影响其他"]),
        ("Settings 配置表单", ["界面 / config.json", "单独勾选 / 校验登录态"]),
        ("Quota 额度聚合", ["真实接口 + 今日收益", "今日无积分时显示状态"]),
        ("History 历史", ["checkin_history.jsonl", "关掉界面也不丢今日收益"]),
    ])

    layer_band(draw, 360, 142, "平台适配层", AMBER, [
        ("Trae CN", ["读 storage.json / JWT", "status → claim → 回读确认", "额度：权益包用量"]),
        ("Qoder", ["读 auth.v1.dat", "活动列表 → 幂等领取", "额度：addOnQuota"]),
        ("WorkBuddy", ["读 state.vscdb accessToken", "签到状态 → 领取 → 回读", "今日积分 + 连续天数"]),
        ("豆包", ["读客户端 Cookies", "任务面板 / 气泡签到", "识别飞书/企业登录态"]),
    ])

    layer_band(draw, 534, 112, "基础设施层", SLATE, [
        ("本机凭证读取", ["Chromium v10 / DPAPI", "AES-GCM / VSCDB / JWT"]),
        ("HTTP 客户端", ["超时、重试、退避", "统一 JSON / 错误摘要"]),
        ("配置与开关", ["config.json + ENV", "旧配置自动补默认值"]),
        ("日志与通知", ["checkin.log / 历史 jsonl", "Windows 通知（可选）"]),
    ])

    layer_band(draw, 678, 112, "外部系统", GREEN, [
        ("四个平台客户端与官方接口", ["Trae / Qoder / WorkBuddy / 豆包", "只调用客户端自己用的接口"]),
        ("Windows 任务计划", ["每天指定时间", "无窗口运行 run_daily.ps1"]),
        ("GitHub Actions / Release", ["全量测试 + 编译 + 构建 exe", "tag v* 自动发布附件"]),
    ])

    # 层间箭头
    for y1, y2 in ((204, 236), (328, 360), (502, 534), (646, 678)):
        arrow(draw, 600, y1, 600, y2)

    # 右侧：本机数据 + 判定原则
    panel = (1210, 112, 1550, 790)
    rounded(draw, panel, radius=14, fill=WHITE, outline=BORDER)
    text(draw, (1232, 130), "本机数据 & 产物", 16, INK, True)
    y = 162
    for title, value in (
        ("config.json", "平台开关、签到时间、手动凭证（不进 git）"),
        ("logs/checkin_history.jsonl", "每天真实签到结果，回填「今日签到」"),
        ("dist/签到助手.exe", "PyInstaller 单文件，给别人直接运行"),
        ("docs/architecture.png", "就是这张图，随版本更新"),
    ):
        rounded(draw, (1230, y, 1530, y + 74), radius=9, fill="#F8FAFC", outline="#EDF2F7")
        text(draw, (1244, y + 10), title, 12, INK, True)
        wrap(draw, (1244, y + 34), value, 270, 10, MUTED, 3)
        y += 84

    # 判定原则
    text(draw, (1232, 520), "四条硬规则（不假报成功）", 15, INK, True)
    rules = [
        ("只有回读确认才报成功", "豆包确认任务面板；WorkBuddy 确认签到状态。"),
        ("读不到就明说", "显示「— / 无资格 / 需登录」，不拿 0 或估算值冒充。"),
        ("「已用 <1」给下限", "豆包余额显示 ≥199，保留「已用 <1」，不伪造精确值。"),
        ("单平台失败隔离", "一个平台报错不影响另外三个，错误写进日志。"),
    ]
    y = 550
    for i, (title, body) in enumerate(rules, 1):
        draw.ellipse((1232, y + 2, 1252, y + 22), fill=BLUE)
        text(draw, (1242, y + 4), str(i), 9, WHITE, True, anchor="ma")
        text(draw, (1262, y), title, 12, INK, True)
        y = wrap(draw, (1262, y + 20), body, 258, 10, MUTED, 3) + 12

    # 凭证虚线
    arrow(draw, 1206, 426, 1160, 426, color="#94A3B8", width=1, dashed=True)
    text(draw, (1184, 404), "本机登录态", 9, MUTED, anchor="ra")

    # 图例
    text(draw, (52, 820), "图例", 11, INK, True)
    draw.line((100, 827, 140, 827), fill="#94A3B8", width=2)
    text(draw, (148, 819), "调用 / 数据流", 10, MUTED)
    draw.line((250, 827, 290, 827), fill="#94A3B8", width=1)
    text(draw, (298, 819), "只读凭证 / 结果回填", 10, MUTED)
    text(draw, (52, 852), "依赖只向下：platforms 不 import ui，core 不 import platforms；"
                          "新增平台只要注册一个 PlatformSpec，界面、配置、CLI 自动生成。", 10, MUTED)

    image.save(OUT, optimize=True)
    print("SAVED", OUT, image.size)


if __name__ == "__main__":
    main()
