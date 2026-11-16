"""Qoder：登录一次客户端，之后自动读令牌 → 查活动 → 领取每天 100 Credits。

真实活动接口在 gateway.qoder.com.cn，且必须带 Cosy-ClientType 头，否则会返回空活动列表
（这就是之前把"接口空壳"误判成"今日已签"的原因）。
"""
from ..core import secrets
from ..core.models import CheckinResult, LoginState, QuotaSnapshot, Status, fmt_epoch, fmt_number
from .base import FieldSpec, PlatformSpec
from .registry import register

CAMPAIGNS_PATH = "/sash/api/v1/me/campaigns"
USAGE_PATH = "/sash/api/v2/me/usage"
DEFAULT_BASE_URL = "https://gateway.qoder.com.cn"
COSY_CLIENT_TYPE = "10"          # Qoder CN 桌面端的客户端类型；缺这个头接口返回空列表
CLIENT_DIR_NAMES = ("com.qodercn.app.stable", "Qoder CN")
LOGIN_FILES = ("auth.v1.dat",)


def _result(status: Status, message: str = "",
            credits: int | None = None, detail: dict | None = None) -> CheckinResult:
    return CheckinResult("qoder", status, message, credits, detail or {})


def login_state() -> LoginState:
    """从 Qoder 客户端的数据目录里读登录令牌（DPAPI + v10 解密）。"""
    base = secrets.app_dir(CLIENT_DIR_NAMES)
    if base is None:
        return LoginState(False, message="没找到 Qoder 客户端的数据目录：先安装并登录一次客户端")
    login_file = next((base / name for name in LOGIN_FILES if (base / name).exists()), None)
    if login_file is None:
        return LoginState(False, message="客户端里还没有登录记录：打开 Qoder 登录一次")
    key = secrets.master_key(base)
    try:
        doc = secrets.read_encrypted_json(login_file, key)
    except Exception as exc:
        return LoginState(False, message=f"登录记录解不开（可能换过机器或账号）：{exc}")
    token = str(doc.get("token") or "").strip()
    if not token:
        return LoginState(False, message="登录记录里没有令牌：重新在客户端登录一次")
    user = doc.get("user") or {}
    account = str(user.get("nickname") or user.get("email") or user.get("id") or "")
    return LoginState(True, account=account, data={
        "token": token,
        "refresh_token": doc.get("refreshToken", ""),
        "expires_at": doc.get("expiresAt", ""),
    })


def _campaigns(payload) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    items = payload.get("campaigns")
    return [c for c in items if isinstance(c, dict)] if isinstance(items, list) else []


def _amount(campaign) -> int | None:
    benefit = campaign.get("benefit") if isinstance(campaign, dict) else None
    if not isinstance(benefit, dict):
        return None
    if str(benefit.get("kind") or "").upper() != "CREDITS":
        return None
    try:
        return int(benefit.get("amount"))
    except (TypeError, ValueError):
        return None


def _find_claimable(payload) -> tuple[str, int | None] | None:
    """在活动列表里找「可领取」的签到奖励，返回 (campaignId, 积分)。

    真实响应字段是 claimStatus / actionType（不是 status / type）。
    """
    for campaign in _campaigns(payload):
        if str(campaign.get("claimStatus") or "").upper() != "CLAIMABLE":
            continue
        action = str(campaign.get("actionType") or "").upper()
        if action and action != "CLAIM_BENEFIT":
            continue
        cid = campaign.get("campaignId") or campaign.get("id")
        if cid:
            return str(cid), _amount(campaign)
    return None


def _claimed_amount(payload) -> int | None:
    """今天这条 100 Credits 活动是否已经领过；返回积分。"""
    for campaign in _campaigns(payload):
        if str(campaign.get("claimStatus") or "").upper() != "CLAIMED":
            continue
        action = str(campaign.get("actionType") or "").upper()
        if action and action != "CLAIM_BENEFIT":
            continue
        amount = _amount(campaign)
        if amount:
            return amount
    return None


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Cosy-ClientType": COSY_CLIENT_TYPE,
        "Origin": "https://gateway.qoder.com.cn",
        "Referer": "https://gateway.qoder.com.cn/growth-page/activity-iframe",
    }


def run(client, section: dict, dry_run: bool = False) -> CheckinResult:
    token = (section.get("token") or "").strip()
    if not token:
        state = login_state()
        token = str(state.data.get("token") or "")
    if not token:
        return _result(Status.NEED_SETUP,
                       "还没拿到 Qoder 令牌：打开 Qoder 客户端登录一次，再点「刷新登录状态」")

    base = (section.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    headers = _headers(token)

    if dry_run:
        return _result(Status.SKIPPED,
                       f"dry-run：将 GET {base}{CAMPAIGNS_PATH}（Cosy-ClientType={COSY_CLIENT_TYPE}）"
                       " → 领取 CLAIMABLE 的 100 Credits")

    resp = client.get(base + CAMPAIGNS_PATH, headers=headers)
    if resp.status in (401, 403):
        return _result(Status.NEED_SETUP,
                       f"登录令牌已过期（HTTP {resp.status}）：重新打开 Qoder 客户端登录一次")
    if not isinstance(resp.json, (dict, list)):
        return _result(Status.FAILED, f"活动列表返回异常：{resp.snippet()}")

    found = _find_claimable(resp.json)
    if not found:
        amount = _claimed_amount(resp.json)
        if amount:
            return _result(Status.ALREADY, f"今日已领 {amount} Credits（已到账，30 天有效）", amount)
        return _result(Status.SKIPPED,
                       "活动列表里没有 100 Credits 活动（可能今天还没放出，10:00 后再试）")

    campaign_id, amount = found
    claim = client.post(f"{base}{CAMPAIGNS_PATH}/{campaign_id}/claim", headers=headers, json_body={})
    if claim.status in (401, 403):
        return _result(Status.NEED_SETUP, f"领取时鉴权失败（HTTP {claim.status}）：重新登录客户端")
    if not claim.ok:
        return _result(Status.FAILED, f"领取失败：{claim.snippet()}",
                       None, {"campaign_id": campaign_id})
    body = claim.json if isinstance(claim.json, dict) else {}
    granted = _amount(body) or amount or 0
    if str(body.get("status") or "").upper() != "CLAIMED":
        return _result(Status.FAILED, f"领取没有返回 CLAIMED：{claim.snippet()}",
                       None, {"campaign_id": campaign_id})
    if body.get("replayed"):
        return _result(Status.ALREADY, f"今日已领 {granted} Credits（重复请求，服务端判定已领）", granted)
    return _result(Status.OK, f"已领取 {granted} Credits（已到账，30 天有效）", granted,
                   {"campaign_id": campaign_id, "grant_id": body.get("grantId", "")})


def quota(client, section: dict) -> QuotaSnapshot:
    """读取 Qoder 的真实余额/用量（只读，不领取）。"""
    token = (section.get("token") or "").strip()
    if not token:
        token = str(login_state().data.get("token") or "")
    if not token:
        return QuotaSnapshot("qoder", Status.NEED_SETUP,
                             "还没读到 Qoder 登录态：先在客户端登录一次")
    base = (section.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    resp = client.get(base + USAGE_PATH, headers=_headers(token))
    if resp.status in (401, 403):
        return QuotaSnapshot("qoder", Status.NEED_SETUP,
                             f"登录已失效（HTTP {resp.status}）：重新打开 Qoder 客户端登录")
    if not resp.ok or not isinstance(resp.json, dict):
        return QuotaSnapshot("qoder", Status.FAILED, f"用量接口返回异常：{resp.snippet()}")

    body = resp.json
    usage = body.get("qoderUsage")
    if not isinstance(usage, dict):
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        usage = data.get("qoderUsage") if isinstance(data.get("qoderUsage"), dict) else body
    addon = usage.get("addOnQuota") if isinstance(usage.get("addOnQuota"), dict) else {}
    plan = usage.get("userQuota") if isinstance(usage.get("userQuota"), dict) else {}

    def pick(key):
        for source in (addon, plan):
            value = source.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        return None

    balance, total, used = pick("remaining"), pick("total"), pick("used")
    unit = str(addon.get("unit") or plan.get("unit") or "credits")
    percent = usage.get("totalUsagePercentage")
    details = []
    if usage.get("userType"):
        details.append(("账号类型", str(usage["userType"])))
    details.append(("套餐额度", f"{fmt_number(plan.get('remaining'))} / {fmt_number(plan.get('total'))} {unit}"))
    details.append(("附加额度", f"{fmt_number(addon.get('remaining'))} / {fmt_number(addon.get('total'))} {unit}"))
    if percent is not None:
        details.append(("总使用率", f"{float(percent):.1%}"))
    if usage.get("expiresAt"):
        details.append(("额度到期", fmt_epoch(usage["expiresAt"], millis=True)))
    if addon.get("detailUrl"):
        details.append(("用量页", str(addon["detailUrl"])))
    message = (f"附加额度剩余 {fmt_number(balance)} / {fmt_number(total)} {unit}"
               if balance is not None else "已读取用量，但没有返回余额数字")
    return QuotaSnapshot("qoder", Status.OK, message, balance, total, used, unit,
                         details=details, source="GET gateway.qoder.com.cn /sash/api/v2/me/usage",
                         raw=body, percent_override=float(percent) if percent is not None else None)


def check(section: dict) -> list[str]:
    if login_state().ok:
        return []
    return ["还没读到 Qoder 登录态：先在 Qoder 客户端里登录一次（只做一次，之后自动）"]


SPEC = register(PlatformSpec(
    key="qoder",
    label="Qoder",
    summary="自动读取客户端登录态 → 查活动 → 领取每天 100 Credits",
    description=("只要在 Qoder 客户端登录过一次，脚本就能从本机登录记录里自动读出令牌，"
                 "不需要你复制任何东西。每天 10:00（UTC+8）后放出当天资格，自动任务建议设在 10:10 之后。"),
    enabled_default=False,
    login_url="https://qoder.cn/",
    actions=("login",),
    login_state=login_state,
    login_hint="在 Qoder 客户端里登录一次即可",
    fields=(
        FieldSpec("base_url", "接口地址", "text", default=DEFAULT_BASE_URL, env="CHECKIN_QODER_BASE_URL"),
    ),
    check=check,
    run=run,
    quota=quota,
))
