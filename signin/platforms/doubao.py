"""豆包：自动读取客户端登录 Cookie，调用任务面板 / 领取接口。

和「拉起客户端」不是一回事：这里真的会 POST 领取，并回读任务面板确认
`checked_in_today` 已变 true；确认不了就按失败上报，绝不假报成功。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile
import time
import urllib.parse
from pathlib import Path

from ..core import secrets
from ..core.models import (CheckinResult, LoginState, QuotaSnapshot, Status, fmt_epoch,
                           fmt_number)
from .base import FieldSpec, PlatformSpec
from .registry import register

GROUP = "pc_incentive_task_mvp_v3"
DETAIL_PATH = "/alice/ug/campaign/v3/detail/"
CHECKIN_PATH = "/alice/ug/campaign/landing/checkin"
REWARD_PATH = "/alice/ug/campaign/item/reward/claim/"
QUOTA_SUMMARY_PATH = "/alice/commerce/sale/subscription/quota/summary/"
QUOTA_RECORDS_PATH = "/alice/ug/campaign/quota/records/"
BASE_URL = "https://www.doubao.com"
REFERER = "https://www.doubao.com/pc/agent-explore"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) DoubaoDesktop/2.32.6 Chrome/147.0.7727.149 Safari/537.36")
COMMON_PARAMS = {
    "version_code": "20800", "language": "zh", "device_platform": "web",
    "doubao_device_platform": "web", "aid": "497858", "real_aid": "497858",
    "pkg_type": "release_version", "pc_version": "2.32.6",
    "doubao_pc_version": "5.72.66", "samantha_web": "1", "web_platform": "desktop",
    "use-olympus-account": "1", "web_tab_id": "0",
}
NO_ACTIVITY_CODES = (710010702,)


def _result(status: Status, message: str = "",
            credits: int | None = None, detail: dict | None = None) -> CheckinResult:
    return CheckinResult("doubao", status, message, credits, detail or {})


# ---------------------------------------------------------------- Cookie 读取

def _user_data_dir() -> Path | None:
    """豆包数据固定在 %LOCALAPPDATA%\\Doubao\\User Data（Roaming 下同名目录不是数据）。"""
    for var in ("LOCALAPPDATA", "APPDATA"):
        base = os.environ.get(var)
        if not base:
            continue
        data = Path(base) / "Doubao" / "User Data"
        if data.is_dir():
            return data
    return None


def _profiles(root: Path) -> list[Path]:
    """所有带 Cookies 的 profile，优先通常是登录态所在的 Profile 3。"""
    found = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and (entry / "Network" / "Cookies").exists():
            found.append(entry)
    order = {"Profile 3": 0, "Default": 1}
    return sorted(found, key=lambda p: (order.get(p.name, 2), p.name))


def _cookie_value(key: bytes | None, value: str, encrypted: bytes) -> str:
    """明文值优先；v10 密文则解密并剥掉 Chromium 的 32 字节域哈希前缀。"""
    if value:
        return value
    plain = secrets.decrypt_blob(key, encrypted)
    if len(plain) > 32 and not all(32 <= b < 127 for b in plain):
        plain = plain[32:]
    return plain.decode("utf-8", "ignore")


def build_cookie(pairs) -> str:
    """把 (name, value) 组合成合法的 Cookie 头；二进制/中文值一律丢弃。"""
    out = []
    for name, value in pairs:
        name = str(name or "").strip()
        value = str(value or "").strip()
        if not name or not value:
            continue
        if not all(32 <= ord(ch) < 127 for ch in name + value):
            continue
        if any(ch in name for ch in ";=, \r\n") or any(ch in value for ch in ";\r\n"):
            continue
        out.append(f"{name}={value}")
    return "; ".join(out)


def _chrome_now() -> float:
    """当前时间换算成 Chrome Cookie 的纪元（1601-01-01 起的微秒 → 秒）。"""
    return time.time() + 11644473600


def _expired(expires_utc: int, now: float | None = None) -> bool:
    """会话 Cookie（expires_utc=0）永不过期；其余按 Chrome 纪元微秒判断。"""
    if not expires_utc:
        return False
    return expires_utc / 1_000_000 < (now if now is not None else _chrome_now())


def _read_profile_cookie(profile: Path, key: bytes | None) -> tuple[str, str, str]:
    """读一个 profile 的豆包登录 Cookie。

    返回 ("ok", cookie, uid) / ("locked", "", "") / ("empty", "", "")。
    locked：客户端正在运行、独占 Cookies 库；empty：库能读但没有登录态。
    """
    db = profile / "Network" / "Cookies"
    tmp = Path(tempfile.gettempdir()) / f"signin_doubao_{abs(hash(str(db)))}.db"
    rows = None
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            shutil.copy2(db, tmp)
            for suffix in ("-wal", "-shm"):
                side = Path(str(db) + suffix)
                if side.exists():
                    shutil.copy2(side, Path(str(tmp) + suffix))
            con = sqlite3.connect(tmp)
            try:
                rows = con.execute(
                    "select host_key, name, value, encrypted_value, expires_utc from cookies "
                    "where host_key like '%doubao.com%' order by name"
                ).fetchall()
            finally:
                con.close()
            break
        except (OSError, sqlite3.Error) as exc:
            last_error = exc
            time.sleep(0.4 * (attempt + 1))
    if rows is None:
        locked = isinstance(last_error, PermissionError) or getattr(
            last_error, "errno", None) in (13, 32, 5)
        return ("locked" if locked else "empty", "", "")
    try:
        pairs = []
        uid = ""
        for _host, name, value, encrypted, expires_utc in rows:
            # 浏览器不会发送已过期的 Cookie；豆包工作试用留下的 LARK 残留
            # （LARK_SUITE_* / msToken 等）过期后留在库里，照单全收会污染请求头，
            # 还会让 is_work_account 把个人号误判成企业号。
            if _expired(expires_utc):
                continue
            try:
                val = _cookie_value(key, value, encrypted or b"")
            except (RuntimeError, ValueError):
                continue
            pairs.append((name, val))
            if name in ("uid_tt", "uid_tt_ss") and val:
                uid = urllib.parse.unquote(val)
        cookie = build_cookie(pairs)
        if not cookie or "sessionid=" not in cookie:
            return ("empty", "", "")
        return ("ok", cookie, uid)
    finally:
        for path in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
            try:
                path.unlink()
            except OSError:
                pass


def _mask(uid: str) -> str:
    return f"…{uid[-6:]}" if len(uid) > 6 else uid


def login_state(profile_name: str = "") -> LoginState:
    root = _user_data_dir()
    if root is None:
        return LoginState(False, message="没找到豆包客户端的数据目录：先安装并登录一次")
    key = secrets.master_key(root)
    profiles = _profiles(root)
    if profile_name:
        profiles = [p for p in profiles if p.name.lower() == profile_name.strip().lower()]
    locked: list[str] = []
    for profile in profiles:
        state, cookie, uid = _read_profile_cookie(profile, key)
        if state == "ok":
            return LoginState(True, account=_mask(uid) if uid else profile.name, data={
                "cookie": cookie, "profile": profile.name, "seed": uid or cookie,
            })
        if state == "locked":
            locked.append(profile.name)
    if locked:
        return LoginState(False, message=(
            f"豆包客户端正在运行，{'、'.join(locked)} 的登录数据被占用读不了："
            "完全退出豆包客户端（包括右下角托盘图标）后重试；"
            "定时签到请在豆包客户端没在运行的时间段执行"))
    if profile_name:
        return LoginState(False, message=f"指定的 {profile_name} 里没有可读的豆包登录 Cookie")
    return LoginState(False, message="没读到豆包登录 Cookie：打开豆包客户端登录一次（Profile 3 / Default 任一即可）")


# ---------------------------------------------------------------- 协议

def _url(path: str, seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    web_id = "76" + "".join(str(b % 10) for b in digest[:8])
    tea = "".join(str(b % 10) for b in digest[8:16]).ljust(16, "7")
    query = urllib.parse.urlencode({**COMMON_PARAMS, "web_id": web_id, "tea_uuid": tea,
                                    "device_id": "", "region": "", "sys_region": ""})
    return BASE_URL + path + "?" + query


def _headers(cookie: str) -> dict:
    return {
        "Cookie": cookie,
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": BASE_URL,
        "Referer": REFERER,
        "User-Agent": UA,
    }


def _post(client, path: str, seed: str, cookie: str, body: dict):
    return client.post(_url(path, seed), headers=_headers(cookie), json_body=body)


def _payload(resp) -> dict:
    return resp.json if isinstance(resp.json, dict) else {}


def _detail(client, cookie: str, seed: str) -> dict:
    return _payload(_post(client, DETAIL_PATH, seed, cookie,
                          {"campaign_group_code": GROUP}))


def _daily_signin(payload: dict) -> dict | None:
    for task in ((payload.get("data") or {}).get("tasks") or []):
        if isinstance(task, dict) and task.get("task_kind") == "daily_signin":
            return task.get("daily_checkin") or {}
    return None


def _reward(task: dict) -> int | None:
    reward = task.get("reward") or {}
    amount = reward.get("reward_amount")
    try:
        return int(amount) if amount is not None else None
    except (TypeError, ValueError):
        return None


def _days(task: dict) -> int:
    try:
        return int(task.get("continuous_days") or 0)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------- 签到

def _pending(claim: dict) -> bool:
    """奖励接口受理了，但平台还在异步发放（biz_error.code=3）。"""
    biz = (claim.get("data") or {}).get("biz_error") or {}
    try:
        return int(biz.get("code") or 0) == 3
    except (TypeError, ValueError):
        return False


def is_work_account(cookie: str) -> bool:
    """飞书/企业登录态（豆包工作版、飞书 SSO）。

    这类登录态带有效的 LARK 会话凭证，个人版「天天领额度」领不了：
    气泡签到接口会回 710010702「系统错误」，不是登录失效、也不是脚本出错。
    注意 feishu_dpop_keypair 不算依据：个人号点过「免费用豆包工作」后
    这枚密钥残留会一直留在库里（实测 2026-11），不能当企业登录的证据。
    """
    for part in str(cookie or "").split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip().lower()
        if name in ("lark_suite_access_token", "lark_suite_dpop"):
            return True
        if name == "has_biz_token" and value.strip().lower() == "true":
            return True
    return False


def _run_work_account(client, cookie: str, seed: str, task: dict) -> CheckinResult:
    """飞书/企业登录态：只走气泡签到一次，领不到就说清原因，不再空转重试。"""
    claim = _payload(_post(client, CHECKIN_PATH, seed, cookie, {"scene": GROUP}))
    code = claim.get("code")
    detail = {"claim": claim, "work_account": True}
    if code == 710012001:
        return _result(Status.NEED_SETUP, "豆包登录已失效：打开豆包客户端重新登录一次",
                       None, detail)
    if code == 0:
        verified = _confirm(client, cookie, seed, attempts=2)
        if verified:
            amount = _reward(verified) or _reward(task)
            return _result(Status.OK, f"已领取 {amount} 体验额度（连续 {_days(verified)} 天）",
                           amount, detail)
        return _result(Status.FAILED, "领取接口返回成功，但任务面板仍显示未签到（未确认到账）",
                       None, detail)
    if code in NO_ACTIVITY_CODES:
        detail["no_activity"] = True
        last = str(task.get("last_checkin_date") or "").strip()
        message = ("这个豆包账号是飞书/企业登录态：服务端明确回「没有可领取的签到活动」"
                   f"（code {code}），今天没有额度可领。")
        if last:
            message += f"上次成功签到是 {last}。"
        message += ("要每天领 200 额度，请换个人豆包账号：在 doubao.com 网页版登录后，"
                    "再用这个账号登录一次豆包客户端。")
        return _result(Status.SKIPPED, message, None, detail)
    return _result(Status.FAILED,
                   f"领取失败：code={code} {claim.get('msg') or claim.get('message') or ''}".strip(),
                   None, detail)


def _confirm(client, cookie: str, seed: str, attempts: int = 3) -> dict | None:
    """领取后回读任务面板，只有 checked_in_today=true 才算到账。"""
    for index in range(attempts):
        if index:
            time.sleep(1.0)
        detail = _detail(client, cookie, seed)
        task = _daily_signin(detail)
        if task and task.get("checked_in_today"):
            return task
    return None


def _claim_via_checkin(client, cookie: str, seed: str, task: dict) -> CheckinResult | None:
    """气泡签到路径；返回 None 表示「活动没开放」，交给上层报跳过。"""
    claim = _payload(_post(client, CHECKIN_PATH, seed, cookie, {"scene": GROUP}))
    code = claim.get("code")
    if code == 710012001:
        return _result(Status.NEED_SETUP, "豆包登录已失效：打开豆包客户端重新登录一次")
    if code in NO_ACTIVITY_CODES:
        return None
    data = claim.get("data") or {}
    if code not in (0, None) or not (data.get("checked_in") or data.get("idempotent")):
        return _result(Status.FAILED,
                       f"领取失败：code={code} {claim.get('msg') or claim.get('message') or ''}".strip(),
                       None, {"claim": claim})
    verified = _confirm(client, cookie, seed, attempts=2)
    if not verified:
        return _result(Status.FAILED,
                       "领取接口返回成功，但任务面板仍显示未签到（未确认到账）",
                       None, {"claim": claim})
    amount = _reward(verified) or _reward(task)
    return _result(Status.OK, f"已领取 {amount} 体验额度（连续 {_days(verified)} 天）",
                   amount, {"claim": claim, "verify": verified})


def run(client, section: dict, dry_run: bool = False) -> CheckinResult:
    cookie = (section.get("cookie") or "").strip()
    seed = str(section.get("seed") or "").strip()
    if not cookie:
        state = login_state(str(section.get("profile") or ""))
        if not state.ok:
            return _result(Status.NEED_SETUP, state.message)
        cookie = str(state.data.get("cookie") or "")
        seed = str(state.data.get("seed") or cookie)
    seed = seed or cookie

    if dry_run:
        return _result(Status.SKIPPED, "dry-run：将读取任务面板并调用领取接口")

    detail = _detail(client, cookie, seed)
    if detail.get("code") == 710012001:
        return _result(Status.NEED_SETUP,
                       "豆包登录已失效：打开豆包客户端重新登录一次")
    if detail.get("code") not in (0, None):
        return _result(Status.FAILED,
                       f"任务面板返回 {detail.get('code')}：{detail.get('msg') or '未知错误'}")

    task = _daily_signin(detail)
    if task is None:
        return _result(Status.SKIPPED,
                       "这个豆包账号没有每日签到任务（工作版/飞书账号通常没有）")

    reward = _reward(task)
    if task.get("checked_in_today"):
        return _result(Status.ALREADY,
                       f"今日已签（连续 {_days(task)} 天，今天 {reward} 额度已到账）",
                       reward, {"task": task})

    # 飞书/企业登录态：个人版签到领不了，只探一次气泡签到，给明确原因。
    if is_work_account(cookie):
        return _run_work_account(client, cookie, seed, task)

    # 任务面板里 daily_signin 是 DirectClaim：先走 item/reward/claim（真实按钮路径）
    item_code = str(task.get("campaign_code") or "daily_signin")
    direct = _payload(_post(client, REWARD_PATH, seed, cookie, {
        "campaign_group_code": GROUP, "campaign_item_code": item_code,
    }))
    code = direct.get("code")
    pending = False
    if code == 710012001:
        return _result(Status.NEED_SETUP, "豆包登录已失效：打开豆包客户端重新登录一次")
    if code in NO_ACTIVITY_CODES:
        code = None
    elif code in (0, None):
        verified = _confirm(client, cookie, seed, attempts=3)
        if verified:
            amount = _reward(verified) or reward
            return _result(Status.OK, f"已领取 {amount} 体验额度（连续 {_days(verified)} 天）",
                           amount, {"claim": direct, "verify": verified})
        pending = _pending(direct)
        if not pending:
            return _result(Status.FAILED,
                           f"领取接口返回 code={code}，但任务面板仍未显示已签（未确认到账）",
                           None, {"claim": direct})
    else:
        return _result(Status.FAILED,
                       f"领取失败：code={code} {direct.get('msg') or direct.get('message') or ''}".strip(),
                       None, {"claim": direct})

    # 兜底：气泡签到接口（有些账号/版本只开放这一条）
    fallback = _claim_via_checkin(client, cookie, seed, task)
    if fallback is not None:
        return fallback
    if pending:
        return _result(Status.SKIPPED,
                       "豆包领取接口受理了，但额度一直没发放（平台反复回「领取结果确认中」，"
                       "已实测重试多次均不到账）。请在豆包客户端里用这个账号打开签到面板手动点一次："
                       "客户端能领，说明这类奖励只在客户端发放；客户端也领不了，"
                       "说明该账号的签到活动已停止发放。今天按未到账处理",
                       None, {"claim": direct})
    return _result(Status.SKIPPED,
                   "豆包当前没有可领取的签到活动（活动未开放/已下线），今天不补领；"
                   "这台机器的登录态已经读到了，不是脚本出错",
                   None, {"claim": direct})


def _quota_num(value) -> float | None:
    """额度数字；豆包会用「<1」表示不足 1，按 0 计算但明细保留原文。"""
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.startswith("<"):
        return 0.0
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def quota(client, section: dict) -> QuotaSnapshot:
    """读取豆包账户的额度汇总与额度记录（只读，不触发领取）。"""
    cookie = (section.get("cookie") or "").strip()
    seed = str(section.get("seed") or "").strip()
    if not cookie:
        state = login_state(str(section.get("profile") or ""))
        if not state.ok:
            return QuotaSnapshot("doubao", Status.NEED_SETUP, state.message)
        cookie = str(state.data.get("cookie") or "")
        seed = str(state.data.get("seed") or cookie)
    seed = seed or cookie
    work_account = is_work_account(cookie)

    summary_resp = _post(client, QUOTA_SUMMARY_PATH, seed, cookie, {})
    summary = _payload(summary_resp)
    code = summary.get("code")
    if code == 710012001:
        return QuotaSnapshot("doubao", Status.NEED_SETUP,
                             "豆包登录已失效：打开豆包客户端重新登录一次")
    if code not in (0, None):
        return QuotaSnapshot("doubao", Status.FAILED,
                             f"额度汇总返回 code={code}：{summary.get('msg') or '未知错误'}")
    data = summary.get("data") if isinstance(summary.get("data"), dict) else {}
    section_data = data.get("incentive_quota_section") if isinstance(
        data.get("incentive_quota_section"), dict) else {}
    groups = [g for g in (section_data.get("window_limit_groups") or []) if isinstance(g, dict)]

    total = 0.0
    used = 0.0
    found = False
    limits = []
    for group in groups:
        for limit in group.get("window_limits") or []:
            if not isinstance(limit, dict):
                continue
            limit_total = _quota_num(limit.get("total_amount"))
            limit_used = _quota_num(limit.get("used_amount"))
            if limit_total is None and limit_used is None:
                continue
            found = True
            total += limit_total or 0
            used += limit_used or 0
            limits.append((group.get("feature_group_name") or group.get("feature_group") or "额度",
                           limit))
    less_than_one = any(str(limit.get("used_amount", "")).strip().startswith("<")
                        for _, limit in limits)
    # 平台只返回「已用 <1」时没有精确剩余，不能拿 total-0 冒充余额。
    # 但「已用 <1」意味着余额 > total-1，可以给一个明确标注的下限，而不是显示「—」。
    balance = None if less_than_one or not found else max(0.0, total - used)
    balance_text = ""
    if less_than_one:
        unknown = sum(1 for _, limit in limits
                      if str(limit.get("used_amount") or "").strip().startswith("<"))
        floor = total - unknown
        if floor > 0:
            balance_text = f"≥{fmt_number(floor)}"
    unit = "额度"
    today_earned = None
    today_key = time.strftime("%Y-%m-%d")
    details = []
    subscription = data.get("current_subscription") if isinstance(
        data.get("current_subscription"), dict) else {}
    display = subscription.get("display") if isinstance(subscription.get("display"), dict) else {}
    if display.get("product_name") or display.get("short_name"):
        details.append(("当前套餐", f"{display.get('product_name', '')} / {display.get('short_name', '')}".strip(" /")))
    for name, limit in limits:
        raw_used = limit.get("used_amount")
        if str(raw_used or "").strip().startswith("<"):
            remaining = balance_text or "—"
        else:
            remaining = fmt_number(max(0.0, (_quota_num(limit.get("total_amount")) or 0) - (_quota_num(raw_used) or 0)))
        details.append((str(name),
                        f"剩余 {remaining} / "
                        f"总量 {fmt_number(limit.get('total_amount'))}，已用 {raw_used if raw_used not in (None, '') else '—'}"))
        expire = fmt_epoch(limit.get("end_time"), millis=True)
        if expire:
            details.append(("额度到期", expire))
    if not found:
        details.append(("说明", "当前账号没有返回活动赠送额度"))
    if work_account:
        details.append(("账号类型", "飞书/企业登录态：没有个人版「每日签到」领取资格"))

    record_error = ""
    records_resp = _post(client, QUOTA_RECORDS_PATH, seed, cookie, {})
    records = _payload(records_resp)
    if records.get("code") not in (0, None):
        record_error = f"额度记录返回 code={records.get('code')}"
    else:
        for record in ((records.get("data") or {}).get("records") or [])[:8]:
            if not isinstance(record, dict):
                continue
            day = fmt_epoch(record.get("create_time_ms"), millis=True)
            details.append(("额度记录",
                            f"{day} {record.get('task_name', record.get('task_code', '记录'))} "
                            f"+{record.get('amount')} {record.get('unit', '')}"))
            if day == today_key:
                amount = _quota_num(record.get("amount"))
                if amount:
                    today_earned = (today_earned or 0) + amount
    if less_than_one:
        message = (f"活动赠送额度总量 {fmt_number(total)}；平台只返回已用 <1（不足 1），"
                   f"因此余额明确为 {balance_text or '不足 ' + fmt_number(total)}，不是精确值")
    elif balance is not None:
        message = f"活动赠送额度剩余 {fmt_number(balance)} / {fmt_number(total)} {unit}"
    else:
        message = "已读取额度汇总，但没有返回额度数字"
    if work_account:
        message = "飞书/企业（工作版）登录态：只能查看活动额度，没有个人版每日签到领取资格"
    if record_error:
        message += f"（{record_error}）"
    return QuotaSnapshot("doubao", Status.OK, message, balance, total, used, unit,
                         today_earned=today_earned,
                         used_text="<1" if less_than_one else "",
                         balance_text=balance_text,
                         today_text="无资格" if work_account else "",
                         details=details,
                         source="POST doubao.com /alice/commerce/sale/subscription/quota/summary/ + quota/records",
                         raw={"summary": summary, "records": records})


def check(section: dict) -> list[str]:
    if (section.get("cookie") or "").strip():
        return []
    if login_state(str(section.get("profile") or "")).ok:
        return []
    return ["还没读到豆包登录态：先在豆包客户端登录一次（只做一次，之后自动）"]


SPEC = register(PlatformSpec(
    key="doubao",
    label="豆包",
    summary="自动读取客户端 Cookie → 每日签到（真实领取 + 回读确认）",
    description=("在豆包客户端登录过一次后，脚本会从本机 Cookies 库（v10 密文）读出登录态，"
                 "调用任务面板与领取接口，并在领取后回读 checked_in_today 确认到账。"
                 "如果活动本身没开放，会明确报「没有可领取的活动」，不会假报成功。"),
    enabled_default=True,
    actions=("probe", "open_client"),
    login_state=login_state,
    login_hint="在豆包客户端登录一次即可",
    fields=(
        FieldSpec("app_path", "客户端路径", "path", advanced=True,
                  hint="仅「现在打开」使用；登录态自动读取，不需要填"),
        FieldSpec("profile", "指定 Profile", "text", advanced=True,
                  hint="留空自动（优先 Profile 3 / Default）"),
    ),
    check=check,
    run=run,
    quota=quota,
))
