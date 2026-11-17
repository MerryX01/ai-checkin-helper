"""签到结果模型与中文等宽对齐工具。"""
import unicodedata
from dataclasses import dataclass, field
from enum import Enum

# 平台内部键 -> 展示名。注册表在注册平台时写入，避免"新增平台要改多处文案"。
LABELS: dict[str, str] = {}

STATUS_CN = {
    "ok": "签到成功",
    "already": "今日已签",
    "need_setup": "需配置",
    "failed": "失败",
    "skipped": "跳过",
}


class Status(str, Enum):
    OK = "ok"                 # 本次签到成功
    ALREADY = "already"       # 今日已签，幂等跳过
    NEED_SETUP = "need_setup"  # 缺凭证/配置，需要人补
    FAILED = "failed"          # 请求失败
    SKIPPED = "skipped"        # 主动跳过（如 dry-run）
    # 说明：枚举值沿用 str 便于日志与 JSON 序列化


def display_width(text: str) -> int:
    """按显示宽度计算：中文/全角算 2，其余算 1（等宽表格对齐用）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in str(text))


def pad(text: str, width: int) -> str:
    s = str(text)
    return s + " " * max(0, width - display_width(s))


def fmt_number(value) -> str:
    """额度显示：整数不补小数，非整数最多两位；None 显示「—」。"""
    if value is None:
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(num - round(num)) < 1e-9:
        return f"{int(round(num)):,}"
    text = f"{num:,.2f}".rstrip("0").rstrip(".")
    return text or "0"


QUOTA_STATUS_CN = {
    "ok": "正常",
    "need_setup": "需登录",
    "failed": "读取失败",
    "skipped": "未提供",
}


def fmt_epoch(value, millis: bool = False) -> str:
    """把平台返回的秒/毫秒时间戳转成日期；9999 年这种「长期」直接说明。"""
    if value in (None, ""):
        return ""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if millis or num > 10_000_000_000:
        num /= 1000.0
    if num >= 4102444800:  # 2100-01-01：平台把「永久」写成 9999 年
        return "长期"
    try:
        import datetime
        dt = datetime.datetime.fromtimestamp(num)
    except (OverflowError, OSError, ValueError):
        return ""
    if dt.year >= 2100:
        return "长期"
    return f"{dt:%Y-%m-%d}"


@dataclass
class LoginState:
    """「这个平台现在是不是已经登录」的检测结果（不是签到结果）。

    ok=True 表示从本机客户端里已经取到可用凭证，用户不需要再填任何东西。
    """

    ok: bool
    account: str = ""
    message: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class QuotaSnapshot:
    """某个平台当前的额度/余额快照（只读，不是签到结果）。

    只保存接口真实返回的数值；缺失字段保持 None，界面显示「—」，不猜测。
    """

    platform: str
    status: Status = Status.OK
    message: str = ""
    balance: float | None = None
    total: float | None = None
    used: float | None = None
    unit: str = ""
    today_earned: float | None = None
    today_text: str = ""
    expire_at: str = ""
    balance_text: str = ""
    used_text: str = ""
    details: list[tuple[str, str]] = field(default_factory=list)
    source: str = ""
    raw: dict = field(default_factory=dict)
    percent_override: float | None = None

    @property
    def label(self) -> str:
        return LABELS.get(self.platform, self.platform)

    @property
    def percent(self) -> float | None:
        if self.percent_override is not None:
            return float(self.percent_override)
        if self.total is None or self.total == 0:
            return None
        if self.used is None:
            return None
        return float(self.used) / float(self.total)

    def fmt_balance(self) -> str:
        return self.balance_text or fmt_number(self.balance)

    def fmt_total(self) -> str:
        return fmt_number(self.total)

    def fmt_used(self) -> str:
        return self.used_text or fmt_number(self.used)

    def fmt_percent(self) -> str:
        percent = self.percent
        return "—" if percent is None else f"{percent:.1%}"

    def fmt_today(self) -> str:
        if self.today_earned is not None:
            return f"+{fmt_number(self.today_earned)}"
        return self.today_text or "—"

    def as_dict(self) -> dict:
        return {
            "platform": self.platform,
            "status": self.status.value,
            "message": self.message,
            "balance": self.balance,
            "total": self.total,
            "used": self.used,
            "unit": self.unit,
            "today_earned": self.today_earned,
            "today_text": self.today_text,
            "expire_at": self.expire_at,
            "details": self.details,
            "source": self.source,
        }


@dataclass
class CheckinResult:
    platform: str
    status: Status
    message: str = ""
    credits: int | None = None
    detail: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return LABELS.get(self.platform, self.platform)

    @property
    def is_ok(self) -> bool:
        return self.status in (Status.OK, Status.ALREADY)

    def line(self) -> str:
        credits = f"+{self.credits}" if self.credits else "-"
        msg = self.message or ""
        status = STATUS_CN.get(self.status.value, self.status.value)
        return (pad(self.label, 12) + pad(status, 6) + pad(credits, 8) + msg).rstrip()

    def as_dict(self) -> dict:
        return {
            "platform": self.platform,
            "status": self.status.value,
            "message": self.message,
            "credits": self.credits,
            "detail": self.detail,
        }
