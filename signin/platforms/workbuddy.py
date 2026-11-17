"""WorkBuddy：登录一次客户端，之后自动读 accessToken，POST 每日签到。"""
from ..core import secrets
from ..core.models import CheckinResult, LoginState, QuotaSnapshot, Status, fmt_number
from .base import FieldSpec, PlatformSpec
from .registry import register

WORKBUDDY_CHECKIN_PATH = "/billing/meter/daily-checkin"
WORKBUDDY_STATUS_PATH = "/billing/meter/checkin-activity-status"
WORKBUDDY_USAGE_PATH = "/billing/meter/get-user-resource-summary"
DEFAULT_BASE_URL = "https://www.codebuddy.cn"
CLIENT_DIR_NAMES = ("CodeBuddy CN", "WorkBuddy")
TOKEN_NEEDLE = "accessTokencn"


def _result(status: Status, message: str = "",
            credits: int | None = None, detail: dict | None = None) -> CheckinResult:
    return CheckinResult("workbuddy", status, message, credits, detail or {})


def login_state() -> LoginState:
    """从 CodeBuddy 客户端的 secret 存储里读 accessToken（v10 密文，本机可解）。"""
    base = secrets.app_dir(CLIENT_DIR_NAMES)
    if base is None:
        return LoginState(False, message="没找到 WorkBuddy 客户端的数据目录：先安装并登录一次")
    doc = secrets.read_vscdb_secret(base, TOKEN_NEEDLE)
    if not doc:
        return LoginState(False, message="客户端里没有登录记录：打开 WorkBuddy 登录一次")
    auth = doc.get("auth") or {}
    account = doc.get("account") or {}
    token = str(auth.get("accessToken") or "").strip()
    if not token:
        return LoginState(False, message="登录记录里没有 accessToken：重新登录一次客户端")
    return LoginState(True, account=str(account.get("nickname") or account.get("uin") or ""), data={
        "token": token,
        "refresh_token": auth.get("refreshToken", ""),
        "token_type": auth.get("tokenType", "Bearer"),
        "expires_at": auth.get("expiresAt", ""),
        "uid": account.get("uid", ""),
    })


def _headers(section: dict, token: str) -> dict:
    base = (section.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    headers = {"Origin": base, "Referer": f"{base}/profile/usage"}
    cookie = (section.get("cookie") or "").strip()
    if cookie:
        headers["Cookie"] = cookie
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _int(value) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def activity_status(client, section: dict, token: str) -> dict | None:
    """读「Buddy加油站」签到状态：今天签没签、今日积分、连续天数。

    非 200 / 非 JSON / code 非 0 都返回 None（调用方按「状态不可用」处理）。
    """
    base = (section.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    resp = client.post(base + WORKBUDDY_STATUS_PATH, headers=_headers(section, token), json_body={})
    if not resp.ok or not isinstance(resp.json, dict):
        return None
    if resp.json.get("code") not in (None, 0):
        return None
    data = resp.json.get("data")
    return data if isinstance(data, dict) else None


def _status_credit(status: dict | None) -> int | None:
    if not status or status.get("today_checked_in") is not True:
        return None
    return _int(status.get("today_credit")) or _int(status.get("daily_credit"))


def _status_line(status: dict | None) -> str:
    if not status:
        return ""
    streak = _int(status.get("streak_days"))
    credit = _status_credit(status)
    parts = []
    if credit:
        parts.append(f"今天 +{credit} 积分已到账")
    if streak:
        parts.append(f"连续 {streak} 天")
    return "，".join(parts)


def _safe_status(client, section: dict, token: str) -> dict | None:
    """状态接口是加分项：读不到不能让签到本身崩掉。"""
    try:
        return activity_status(client, section, token)
    except Exception:
        return None


def run(client, section: dict, dry_run: bool = False) -> CheckinResult:
    token = (section.get("token") or "").strip()
    if not token:
        token = str(login_state().data.get("token") or "")
    cookie = (section.get("cookie") or "").strip()
    if not token and not cookie:
        return _result(Status.NEED_SETUP,
                       "还没拿到 WorkBuddy 登录凭证：打开 WorkBuddy 客户端登录一次，再点「刷新登录状态」")

    base = (section.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    headers = _headers(section, token)

    if dry_run:
        return _result(Status.SKIPPED, f"dry-run：将 POST {base}{WORKBUDDY_CHECKIN_PATH}")

    resp = client.post(base + WORKBUDDY_CHECKIN_PATH, headers=headers, json_body={})
    if resp.status in (401, 403):
        return _result(Status.NEED_SETUP,
                       f"登录已失效（HTTP {resp.status}）：重新打开 WorkBuddy 客户端登录一次")

    text = resp.text or ""
    # 服务端把"今天已签到"当作错误返回（HTTP 400 / code 10001），这属于幂等成功，不算失败
    if "已签到" in text or "already" in text.lower() or '"code":10001' in text.replace(" ", ""):
        status = _safe_status(client, section, token)
        credit = _status_credit(status)
        line = _status_line(status) if credit else ""
        return _result(Status.ALREADY,
                       "今日已签到" + (f"（{line}）" if line else "，跳过"),
                       credit, {"body": text[:300], "status": status})
    if not resp.ok:
        return _result(Status.FAILED, f"签到接口失败：HTTP {resp.status} {resp.snippet()}")

    # 领取成功后回读状态，确认「今天已签 + 今天到账多少积分」，不把未确认写成成功。
    status = _safe_status(client, section, token)
    if status is not None:
        if status.get("today_checked_in") is not True:
            return _result(Status.FAILED,
                           "领取接口返回成功，但签到状态仍显示今天未签（未确认到账）",
                           None, {"body": text[:300], "status": status})
        credit = _status_credit(status)
        line = _status_line(status)
        return _result(Status.OK,
                       "签到成功" + (f"（{line}）" if line else "，已确认到账"),
                       credit, {"body": text[:300], "status": status})
    # 状态接口读不到时，不把「接口 200」包装成已到账。
    return _result(Status.SKIPPED,
                   "签到接口返回成功，但没能回读签到状态确认到账；稍后刷新额度看板确认",
                   None, {"body": text[:300], "status": None})


def quota(client, section: dict) -> QuotaSnapshot:
    """读取 WorkBuddy 的资源汇总（套餐/奖励积分余额）。"""
    token = (section.get("token") or "").strip()
    if not token:
        token = str(login_state().data.get("token") or "")
    cookie = (section.get("cookie") or "").strip()
    if not token and not cookie:
        return QuotaSnapshot("workbuddy", Status.NEED_SETUP,
                             "还没读到 WorkBuddy 登录态：先在客户端登录一次")
    base = (section.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    resp = client.post(base + WORKBUDDY_USAGE_PATH, headers=_headers(section, token), json_body={})
    if resp.status in (401, 403):
        return QuotaSnapshot("workbuddy", Status.NEED_SETUP,
                             f"登录已失效（HTTP {resp.status}）：重新打开 WorkBuddy 客户端登录")
    if not resp.ok or not isinstance(resp.json, dict):
        return QuotaSnapshot("workbuddy", Status.FAILED, f"额度接口返回异常：{resp.snippet()}")

    body = resp.json
    if body.get("code") not in (None, 0):
        return QuotaSnapshot("workbuddy", Status.FAILED,
                             f"额度接口业务失败（code={body.get('code')}）：{body.get('msg', '')}")
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    groups = [g for g in (data.get("CreditGroups") or []) if isinstance(g, dict)]

    total = sum(_num(g.get("CycleTotalCapacity")) or 0 for g in groups)
    balance = sum(_num(g.get("CycleRemainCapacity")) or 0 for g in groups)
    used = sum(_num(g.get("CycleUsedCapacity")) or 0 for g in groups)
    if not groups:
        balance = _num(data.get("TotalCredits"))
        total = None
        used = None
    unit = "credits"
    details = []
    if data.get("SubscriptionPackageName"):
        details.append(("套餐", str(data["SubscriptionPackageName"])))
    details.append(("是否付费", "是" if data.get("IsPaidUser") else "否"))
    if total:
        details.append(("总额度", f"{fmt_number(total)} {unit}"))
    for group in groups:
        details.append((str(group.get("Name") or group.get("Kind") or "积分"),
                        f"剩余 {fmt_number(group.get('CycleRemainCapacity'))} / "
                        f"总量 {fmt_number(group.get('CycleTotalCapacity'))}，"
                        f"已用 {fmt_number(group.get('CycleUsedCapacity'))}"))
    # 签到活动状态：今日真实到账积分、连续天数（只读，不影响余额）。
    status = _safe_status(client, section, token)
    today_earned = _status_credit(status)
    if status:
        if status.get("activity_name"):
            details.append(("签到活动", str(status["activity_name"])))
        streak = _int(status.get("streak_days"))
        if streak:
            details.append(("连续签到", f"{streak} 天"))
        week = _int(status.get("week_checkin_days"))
        if week is not None:
            details.append(("本周签到", f"{week} 天"))
        if status.get("end_time"):
            details.append(("活动截止", str(status["end_time"])))
        if today_earned:
            details.append(("今日签到", f"+{today_earned} credits（已到账）"))
    message = (f"余额 {fmt_number(balance)} / 总量 {fmt_number(total)} {unit}"
               if balance is not None else "已读取额度，但没有返回余额数字")
    if today_earned:
        message += f"；今日签到 +{today_earned} credits 已到账"
    return QuotaSnapshot("workbuddy", Status.OK, message, balance, total, used, unit,
                         today_earned=today_earned,
                         details=details, source="POST codebuddy.cn /billing/meter/get-user-resource-summary",
                         raw={"usage": body, "status": status})


def _num(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def check(section: dict) -> list[str]:
    if (section.get("token") or "").strip() or (section.get("cookie") or "").strip():
        return []
    if login_state().ok:
        return []
    return ["还没读到 WorkBuddy 登录态：先在客户端登录一次（只做一次，之后自动）"]


SPEC = register(PlatformSpec(
    key="workbuddy",
    label="WorkBuddy",
    summary="自动读取客户端 accessToken → POST daily-checkin",
    description=("只要在 WorkBuddy 客户端登录过一次，脚本就能从本机加密存储里读出 accessToken，"
                 "每天自动调用签到接口。登录过期时，重新在客户端登录一次即可。"),
    enabled_default=False,
    login_url="https://www.codebuddy.cn/",
    actions=("login",),
    login_state=login_state,
    login_hint="在 WorkBuddy 客户端里登录一次即可",
    fields=(
        FieldSpec("base_url", "接口地址", "text", default=DEFAULT_BASE_URL),
    ),
    check=check,
    run=run,
    quota=quota,
))
