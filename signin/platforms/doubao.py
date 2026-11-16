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


def _read_profile_cookie(profile: Path, key: bytes | None) -> tuple[str, str] | None:
    db = profile / "Network" / "Cookies"
    tmp = Path(tempfile.gettempdir()) / f"signin_doubao_{abs(hash(str(db)))}.db"
    try:
        shutil.copy2(db, tmp)
        for suffix in ("-wal", "-shm"):
            side = Path(str(db) + suffix)
            if side.exists():
                shutil.copy2(side, Path(str(tmp) + suffix))
        con = sqlite3.connect(tmp)
        try:
            rows = con.execute(
                "select host_key, name, value, encrypted_value from cookies "
                "where host_key like '%doubao.com%' order by name"
            ).fetchall()
        finally:
            con.close()
    except (OSError, sqlite3.Error):
        return None
    finally:
        for path in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
            try:
                path.unlink()
            except OSError:
                pass

    pairs = []
    uid = ""
    for _host, name, value, encrypted in rows:
        try:
            val = _cookie_value(key, value, encrypted or b"")
        except (RuntimeError, ValueError):
            continue
        pairs.append((name, val))
        if name in ("uid_tt", "uid_tt_ss") and val:
            uid = urllib.parse.unquote(val)
    cookie = build_cookie(pairs)
    if not cookie or "sessionid=" not in cookie:
        return None
    return cookie, uid


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
    for profile in profiles:
        found = _read_profile_cookie(profile, key)
        if found:
            cookie, uid = found
            return LoginState(True, account=_mask(uid) if uid else profile.name, data={
                "cookie": cookie, "profile": profile.name, "seed": uid or cookie,
            })
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
                       "豆包已受理领取，但平台一直显示「领取结果确认中」，没有确认到账；"
                       "过几分钟可再点一次「立即签到」查看是否到账，今天先按未到账处理",
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
    balance = None if less_than_one or not found else max(0.0, total - used)
    unit = "额度"
    details = []
    subscription = data.get("current_subscription") if isinstance(
        data.get("current_subscription"), dict) else {}
    display = subscription.get("display") if isinstance(subscription.get("display"), dict) else {}
    if display.get("product_name") or display.get("short_name"):
        details.append(("当前套餐", f"{display.get('product_name', '')} / {display.get('short_name', '')}".strip(" /")))
    for name, limit in limits:
        raw_used = limit.get("used_amount")
        if str(raw_used or "").strip().startswith("<"):
            remaining = "—"
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

    record_error = ""
    records_resp = _post(client, QUOTA_RECORDS_PATH, seed, cookie, {})
    records = _payload(records_resp)
    if records.get("code") not in (0, None):
        record_error = f"额度记录返回 code={records.get('code')}"
    else:
        for record in ((records.get("data") or {}).get("records") or [])[:8]:
            if isinstance(record, dict):
                details.append(("额度记录",
                                f"{fmt_epoch(record.get('create_time_ms'), millis=True)} "
                                f"{record.get('task_name', record.get('task_code', '记录'))} "
                                f"+{record.get('amount')} {record.get('unit', '')}"))
    if less_than_one:
        message = f"活动赠送额度总量 {fmt_number(total)}；平台只返回已用 <1，未返回精确剩余"
    elif balance is not None:
        message = f"活动赠送额度剩余 {fmt_number(balance)} / {fmt_number(total)} {unit}"
    else:
        message = "已读取额度汇总，但没有返回额度数字"
    if record_error:
        message += f"（{record_error}）"
    return QuotaSnapshot("doubao", Status.OK, message, balance, total, used, unit,
                         used_text="<1" if less_than_one else "",
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
