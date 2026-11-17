r"""Trae CN：从本机 Trae 客户端登录态自动读令牌，再调接口签到。

令牌来源（按优先级，全部只读、不落盘）：
1. `%APPDATA%\<Trae 应用>\User\globalStorage\storage.json` 里的
   `iCubeAuthInfo://icube.cloudide`（加密信封，AES-128-CBC + sha512 派生密钥）
2. CLI 登录文件 `~/.trae-cn/trae-jwt-token`、`~/.trae/trae-jwt-token`

信封格式：header(6) + salt(32) + AES-CBC 密文；解密后是 sha512(前 64 字节校验) + JSON。
算法来自公开实现 G57651/dsh-dual-checkin（MIT），本仓库用纯 Python 复刻，不依赖第三方库。
"""
import base64
import hashlib
import json
import os
import uuid
from pathlib import Path

from .. import gui
from ..core.aesgcm import cbc_decrypt
from ..core.models import (CheckinResult, LoginState, QuotaSnapshot, Status, fmt_epoch,
                           fmt_number)
from .base import FieldSpec, PlatformSpec
from .registry import register

TRAE_STATUS_PATH = "/trae/api/v2/ug/checkin_credits/status"
TRAE_CLAIM_PATH = "/trae/api/v2/ug/checkin_credits/claim"
TRAE_USAGE_PATH = "/trae/api/v2/pay/ide_user_ent_usage"
TRAE_BAD_DEVICE_CODES = (9004, 9074)
DEFAULT_BASE_URL = "https://api.trae.cn"

AUTH_KEY = "iCubeAuthInfo://icube.cloudide"
DEVICE_PREFIX = "iCubeAuthInfo://icube-dc:"
APP_NAMES = ("TRAE SOLO CN", "Trae CN", "Trae", "TRAE SOLO")
CLI_DIRS = (".trae-cn", ".trae")
HEADER_AES = bytes([116, 99, 5, 16, 0, 0])          # tc 05 10 00 00
HEADER_AES_PRIVATE = bytes([18, 57, 32, 32, 2, 3])
SALT_A = bytes([82, 9, 106, 213, 48, 54, 165, 56, 191, 64, 163, 158, 129, 243, 215, 251,
                124, 227, 57, 130, 155, 47, 255, 135, 52, 142, 67, 68, 196, 222, 233, 203,
                84, 123, 148, 50, 166, 194, 35, 61, 238, 76, 149, 11, 66, 250, 195, 78,
                8, 46, 161, 102, 40, 217, 36, 178, 118, 91, 162, 73, 109, 139, 209, 37])
SALT_B = bytes([31, 221, 168, 51, 136, 7, 199, 49, 177, 18, 16, 89, 39, 128, 236, 95,
                96, 81, 127, 169, 25, 181, 74, 13, 45, 229, 122, 159, 147, 201, 156, 239,
                160, 224, 59, 77, 174, 42, 245, 176, 200, 235, 187, 60, 131, 83, 153, 97,
                23, 43, 4, 126, 186, 119, 214, 38, 225, 105, 20, 99, 85, 33, 12, 125])
SALT_C = bytes([191, 192, 216, 250, 122, 246, 220, 97, 31, 254, 98, 27, 8, 72, 71, 176,
                135, 99, 96, 18, 127, 101, 203, 104, 211, 102, 191, 125, 37, 72, 150, 156,
                51, 229, 121, 35, 17, 153, 141, 177, 110, 131, 150, 128, 172, 255, 254, 6,
                18, 140, 55, 62, 236, 249, 135, 64, 135, 12, 117, 4, 89, 149, 168, 209])
SALT_D = bytes([246, 204, 26, 232, 232, 70, 129, 109, 223, 146, 169, 242, 23, 241, 105, 145,
                50, 196, 165, 42, 254, 120, 3, 54, 244, 207, 209, 85, 53, 6, 138, 106,
                175, 148, 31, 204, 186, 186, 165, 182, 87, 142, 49, 10, 39, 110, 26, 154,
                86, 56, 173, 125, 18, 64, 198, 225, 99, 99, 83, 82, 191, 134, 76, 170])


def _result(status: Status, message: str = "",
            credits: int | None = None, detail: dict | None = None) -> CheckinResult:
    return CheckinResult("trae", status, message, credits, detail or {})


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def decrypt_storage_value(encoded: str) -> str:
    """解开 storage.json 里的加密信封，返回明文 JSON 字符串。"""
    data = base64.b64decode(encoded)
    if len(data) <= 102:
        raise ValueError("Trae 登录信息太短")
    header = data[:6]
    if header == HEADER_AES:
        salt = _xor(SALT_A, SALT_B)
    elif header == HEADER_AES_PRIVATE:
        salt = _xor(SALT_C, SALT_D)
    else:
        raise ValueError("Trae 登录信息的加密格式不认识（客户端可能又改版了）")
    digest = hashlib.sha512(data[6:38]).digest()
    derived = hashlib.sha512(digest + salt).digest()
    plain_all = cbc_decrypt(derived[:16], derived[16:32], data[38:])
    # 明文尾部是 PKCS#7 填充（随内容长度在 1~16 字节之间变化），先去填充再校验
    pad = plain_all[-1] if plain_all else 0
    if 1 <= pad <= 16 and plain_all[-pad:] == bytes([pad]) * pad:
        plain_all = plain_all[:-pad]
    if len(plain_all) < 64:
        raise ValueError("Trae 登录信息解开后太短")
    body = plain_all[64:]
    if hashlib.sha512(body).digest() != plain_all[:64]:
        raise ValueError("Trae 登录信息校验不通过")
    return body.decode("utf-8", "replace")


def _jwt_claim(token: str, key: str = "sub") -> str:
    """读 JWT 里的字段（不校验签名，只用来显示账号）。"""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        value = data.get(key)
        if value in (None, ""):
            value = (data.get("data") or {}).get("id") if isinstance(data.get("data"), dict) else None
        return "" if value is None else str(value)
    except Exception:
        return ""


def _storage_paths() -> list[Path]:
    roots = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata))
    if os.environ.get("USERPROFILE"):
        roots.append(Path(os.environ["USERPROFILE"]) / "AppData" / "Roaming")
    out = []
    seen = set()
    for root in roots:
        for app in APP_NAMES:
            path = root / app / "User" / "globalStorage" / "storage.json"
            if path.exists() and str(path) not in seen:
                out.append(path)
                seen.add(str(path))
    return out


def _from_storage() -> list[dict]:
    """从桌面客户端的 storage.json 里读出所有可用登录。"""
    found = []
    for path in _storage_paths():
        try:
            storage = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        raw = storage.get(AUTH_KEY)
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            text = raw.strip() if raw.strip().startswith("{") else decrypt_storage_value(raw.strip())
            auth = json.loads(text)
        except Exception:
            continue
        token = str(auth.get("token") or auth.get("accessToken") or "").strip()
        if not token:
            continue
        device_key = next((k for k in storage if k.startswith(DEVICE_PREFIX)), "")
        device_id = device_key[len(DEVICE_PREFIX):] if device_key else str(storage.get("telemetry.devDeviceId") or "")
        account = str(auth.get("userId") or _jwt_claim(token) or "")
        found.append({"token": token, "device_id": device_id, "account": account,
                      "source": path.parents[2].name})
    return found


def _from_cli() -> list[dict]:
    """从 CLI 的 trae-jwt-token 文件里读出登录。"""
    found = []
    home = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    for name in CLI_DIRS:
        path = home / name / "trae-jwt-token"
        try:
            text = path.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if not text:
            continue
        token = text
        if text.startswith("{"):
            try:
                token = str(json.loads(text).get("token") or "")
            except Exception:
                token = ""
        if len(token.split(".")) != 3:
            continue
        found.append({"token": token, "device_id": "", "account": _jwt_claim(token), "source": f"~/{name}"})
    return found


def find_credentials() -> list[dict]:
    """本机所有 Trae 登录：有设备号（桌面端）优先，没过的期优先。"""
    items = _from_storage() + _from_cli()
    items.sort(key=lambda c: (bool(c.get("device_id")), bool(_jwt_claim(c["token"])), len(c.get("token") or "")),
               reverse=True)
    return items


def login_state() -> LoginState:
    items = find_credentials()
    if not items:
        return LoginState(False, message="没找到 Trae 登录记录：先启动 Trae CN 客户端登录一次")
    best = items[0]
    account = best.get("account") or ""
    label = f"…{account[-4:]}" if account else best.get("source", "Trae")
    return LoginState(True, account=label, data={
        "token": best["token"],
        "device_id": best.get("device_id", ""),
        "accounts": len(items),
        "source": best.get("source", ""),
    })


def _headers(token: str, device_id: str) -> dict:
    headers = {
        "Authorization": f"Cloud-IDE-JWT {token}",
        "Content-Type": "application/json",
        "User-Agent": "VSCode 1.107.1 (TRAE SOLO CN)",
        "x-user-region": "CN",
        "package-type": "stable_cn",
        "x-lscbd-aid": "787976",
        "x-lscbd-platform": "windows",
        "app-version": "0.1.51",
        "Accept": "*/*",
        "x-request-id": uuid.uuid4().hex,
        "x-device-brand": "To be filled by O.E.M.",
        "x-device-type": "windows",
        "x-lgw-req-sdk-type": "3",
    }
    if device_id:
        headers["x-device-id"] = device_id
    return headers


def run(client, section: dict, dry_run: bool = False, clicker=None) -> CheckinResult:
    token = (section.get("token") or "").strip()
    device_id = (section.get("device_id") or "").strip()
    if not token:
        state = login_state()
        if state.ok:
            token = str(state.data.get("token") or "")
            device_id = device_id or str(state.data.get("device_id") or "")

    if not token:
        # 真的读不到登录态时，才退回到点击客户端（默认不开）
        if not section.get("gui_fallback"):
            return _result(Status.NEED_SETUP, "还没读到 Trae 登录态：打开 Trae CN 客户端登录一次，再点「刷新」")
        gui_click = section.get("gui_click") or {}
        if not gui_click.get("window"):
            return _result(Status.NEED_SETUP, "没读到 Trae 登录态，也没校准点击位置：先在客户端登录一次")
        if dry_run:
            return _result(Status.SKIPPED, f"dry-run：将点击窗口「{gui_click['window']}」的签到按钮")
        click = clicker or gui.click_at_ratio
        try:
            ok = bool(click(gui_click["window"], float(gui_click.get("x_ratio", 0.5)),
                            float(gui_click.get("y_ratio", 0.5))))
        except Exception as e:
            return _result(Status.FAILED, f"点击异常：{type(e).__name__}: {e}")
        return _result(Status.OK if ok else Status.FAILED,
                       "已点击客户端签到按钮" if ok else "点击失败：窗口没找到")

    base = (section.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    headers = _headers(token, device_id)

    if dry_run:
        return _result(Status.SKIPPED,
                       f"dry-run：将 POST {base}{TRAE_STATUS_PATH} → 必要时 POST {base}{TRAE_CLAIM_PATH}")

    status_resp = client.post(base + TRAE_STATUS_PATH, headers=headers, json_body={"req_source": 1},
                              is_success=lambda b: isinstance(b, dict) and b.get("code") == 0)
    if status_resp.status in (401, 403):
        return _result(Status.NEED_SETUP, f"登录已失效（HTTP {status_resp.status}）：重新打开 Trae 客户端登录一次")
    if not isinstance(status_resp.json, dict):
        return _result(Status.FAILED, f"状态接口返回异常：{status_resp.snippet()}")

    body = status_resp.json
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    credits = None
    if isinstance(data, dict) and isinstance(data.get("credits"), int):
        credits = int(data["credits"]) + (int(data.get("extra_credits") or 0))
    elif isinstance(body.get("credits"), int):
        credits = int(body["credits"])
    checked_in = bool(body.get("checked_in")) or bool(isinstance(data, dict) and data.get("checked_in"))
    if checked_in:
        return _result(Status.ALREADY, "今日已签到，跳过", credits, {"raw": body})
    code = body.get("code")
    if code not in (None, 0):
        return _result(Status.FAILED, f"查询签到状态失败（code={code}）：{body.get('message', '')}", None, {"raw": body})

    claim_resp = client.post(base + TRAE_CLAIM_PATH, headers=headers, json_body={"req_source": 1},
                             is_success=lambda b: isinstance(b, dict) and b.get("code") == 0)
    if claim_resp.status in (401, 403):
        return _result(Status.NEED_SETUP, f"登录已失效（HTTP {claim_resp.status}）：重新打开 Trae 客户端登录一次")

    claim = claim_resp.json if isinstance(claim_resp.json, dict) else {}
    code = claim.get("code")
    if code == 0:
        return _result(Status.OK, "签到成功", credits, {"raw": claim})
    if code in TRAE_BAD_DEVICE_CODES:
        return _result(Status.FAILED,
                       f"领取失败（code={code}）：设备号不匹配，用客户端自动读到的登录态重试", None, {"raw": claim})
    return _result(Status.FAILED,
                   f"领取失败：code={code} message={claim.get('message', claim_resp.snippet())}",
                   None, {"raw": claim})


def quota(client, section: dict) -> QuotaSnapshot:
    """读取 Trae 的真实额度用量（只读）。"""
    token = (section.get("token") or "").strip()
    device_id = (section.get("device_id") or "").strip()
    if not token:
        state = login_state()
        if state.ok:
            token = str(state.data.get("token") or "")
            device_id = device_id or str(state.data.get("device_id") or "")
    if not token:
        return QuotaSnapshot("trae", Status.NEED_SETUP,
                             "还没读到 Trae 登录态：先在 Trae CN 客户端登录一次")
    base = (section.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    headers = _headers(token, device_id)
    resp = client.post(base + TRAE_USAGE_PATH, headers=headers,
                       json_body={"require_usage": True, "req_source": 1})
    if resp.status in (401, 403):
        return QuotaSnapshot("trae", Status.NEED_SETUP,
                             f"登录已失效（HTTP {resp.status}）：重新打开 Trae 客户端登录")
    if not resp.ok or not isinstance(resp.json, dict):
        return QuotaSnapshot("trae", Status.FAILED, f"用量接口返回异常：{resp.snippet()}")

    body = resp.json
    if body.get("code") not in (None, 0):
        return QuotaSnapshot("trae", Status.FAILED,
                             f"用量接口业务失败（code={body.get('code')}）：{body.get('message', '')}")
    usage = body.get("usage_summary") if isinstance(body.get("usage_summary"), dict) else {}
    balance = _num(body.get("total_balance"))
    total = _num(usage.get("total_amount"))
    used = _num(usage.get("consumed_amount"))
    unit = "credits"
    details = []
    if usage.get("consumption_ratio") is not None:
        details.append(("已用比例", f"{float(usage['consumption_ratio']):.1%}"))
    if body.get("is_credits_billing") is not None:
        details.append(("计费方式", "Credits 额度" if body.get("is_credits_billing") else "美元用量"))
    for item in body.get("balance_summary") or []:
        if isinstance(item, dict):
            details.append((f"余额来源 {item.get('source', '')}",
                            f"{fmt_number(item.get('total_balance'))} credits"))
    for pack in body.get("user_entitlement_pack_list") or []:
        if not isinstance(pack, dict):
            continue
        quota_info = ((pack.get("entitlement_base_info") or {}).get("quota") or {})
        limit = quota_info.get("credits_limit")
        if limit is None:
            extra = (pack.get("entitlement_base_info") or {}).get("product_extra") or {}
            limit = ((extra.get("package_extra") or {}).get("quota") or {}).get("credits_limit")
        line = f"{pack.get('display_desc', '权益包')}：" + (
            f"额度 {fmt_number(limit)}" if limit is not None else "平台权益包（未标额度）"
        )
        expire = fmt_epoch(pack.get("expire_time"))
        if expire:
            line += f"，到期 {expire}"
        details.append(("权益包", line))
    message = (f"余额 {fmt_number(balance)} / 总量 {fmt_number(total)} {unit}"
               if balance is not None else "已读取用量，但没有返回余额数字")
    return QuotaSnapshot("trae", Status.OK, message, balance, total, used, unit,
                         details=details, source="POST api.trae.cn /trae/api/v2/pay/ide_user_ent_usage",
                         raw=body)


def _num(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _gui_click_ready(section: dict) -> bool:
    """是否已校准「点客户端按钮」兜底：窗口名 + 两个相对坐标都在才算数。"""
    click = section.get("gui_click") or {}
    if not click.get("window"):
        return False
    try:
        return 0 <= float(click.get("x_ratio", -1)) <= 1 and 0 <= float(click.get("y_ratio", -1)) <= 1
    except (TypeError, ValueError):
        return False


def check(section: dict) -> list[str]:
    if (section.get("token") or "").strip():
        return []
    # 读不到客户端登录态时，「开启兜底 + 已校准点击位置」也算已配置，和 run() 的兜底分支对齐
    if section.get("gui_fallback") and _gui_click_ready(section):
        return []
    state = login_state()
    if state.ok:
        return []
    if section.get("gui_fallback") and not _gui_click_ready(section):
        return ["已开启点击兜底，但还没校准签到按钮位置：运行 teach trae 或在界面上点「校准点击位置」"]
    return [state.message or "先在 Trae CN 客户端登录一次"]


SPEC = register(PlatformSpec(
    key="trae",
    label="Trae CN",
    summary="自动读客户端登录态 → checkin_credits 接口签到",
    description=("只要在 Trae CN 客户端登录过一次，脚本就能解开客户端存储里的加密登录信息，"
                 "拿到 Cloud-IDE-JWT 和真实设备号，每天直接调用签到接口。"
                 "不需要填令牌；读不到才考虑高级项。"),
    enabled_default=False,
    login_url="https://www.trae.cn/",
    actions=("login",),
    login_state=login_state,
    login_hint="在 Trae CN 客户端里登录一次即可",
    fields=(
        FieldSpec("token", "令牌", "secret", env="CHECKIN_TRAE_TOKEN", credential=True, advanced=True,
                  hint="高级项：Cloud-IDE-JWT 令牌，留空就用客户端登录态"),
        FieldSpec("device_id", "设备号", "text", env="CHECKIN_TRAE_DEVICE_ID", advanced=True,
                  hint="高级项：客户端真实 x-device-id，留空自动读取"),
        FieldSpec("base_url", "接口地址", "text", default=DEFAULT_BASE_URL, env="CHECKIN_TRAE_BASE_URL",
                  advanced=True),
        FieldSpec("gui_fallback", "读不到登录态时点客户端", "bool", default=False, advanced=True),
    ),
    defaults={"gui_click": None},
    check=check,
    run=run,
    quota=quota,
))
