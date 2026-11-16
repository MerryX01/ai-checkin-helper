"""结果推送。默认关闭，配置 notify.url 后启用。

注意：企业微信 / server酱 / 飞书机器人都有「HTTP 200 但业务码失败」的情况，
只看状态码会把消息静默丢掉，因此这里一律检查 body 里的业务码。
"""
from . import http

PROVIDERS = ("wecom", "feishu", "serverchan", "generic")


def _payload(provider: str, title: str, body: str) -> tuple[dict, str | None]:
    if provider == "wecom":
        return {"msgtype": "text", "text": {"content": f"{title}\n{body}"}}, "errcode"
    if provider == "feishu":
        return {"msg_type": "text", "content": {"text": f"{title}\n{body}"}}, "code"
    if provider == "serverchan":
        return {"title": title, "desp": body}, "code"
    return {"title": title, "body": body}, None


def send(section: dict | None, title: str, body: str, client: http.Client | None = None) -> tuple[bool, str]:
    """发送一条通知，返回 (是否送达, 说明)。"""
    section = section or {}
    if not section.get("enabled"):
        return False, "未配置通知通道（notify.enabled=false）"

    url = (section.get("url") or "").strip()
    if not url:
        return False, "通知缺少 url"

    provider = (section.get("type") or "generic").strip().lower()
    if provider not in PROVIDERS:
        return False, f"未知通知类型：{provider}（可选 {'/'.join(PROVIDERS)}）"

    payload, code_key = _payload(provider, title, body)
    client = client or http.Client(retries=2)
    try:
        resp = client.post(url, json_body=payload)
    except Exception as e:
        return False, f"推送异常：{type(e).__name__}: {e}"

    if not resp.ok:
        return False, f"推送失败：HTTP {resp.status} {resp.snippet()}"

    if code_key and isinstance(resp.json, dict):
        code = resp.json.get(code_key)
        if code not in (0, "0"):
            return False, f"推送失败：{code_key}={code} {resp.json.get('errmsg') or resp.json.get('message') or ''}".strip()

    return True, "已推送"
