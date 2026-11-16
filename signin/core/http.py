"""极简 HTTP 客户端：标准库实现，带重试、超时、业务码识别。

设计要点（来自实践教训）：
- 4xx 不重试：凭据错/参数错，重试只会白等。
- 5xx 与网络错误才重试，退避带随机抖动。
- 「HTTP 200 + body 业务码失败」必须由 is_success 回调判定，不能只看状态码。
"""
import json
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


@dataclass
class RawResponse:
    status: int
    body: bytes


class HttpResult:
    """一次请求的最终结果（已合并重试）。"""

    def __init__(self, status: int, text: str, json_obj, ok: bool, error: str = "", attempts: int = 1):
        self.status = status
        self.text = text
        self.json = json_obj
        self.ok = ok
        self.error = error
        self.attempts = attempts

    def __repr__(self):
        return f"HttpResult(status={self.status}, ok={self.ok}, attempts={self.attempts})"

    def snippet(self, n: int = 160) -> str:
        return (self.text or self.error or "")[:n]


def _default_transport(method, url, headers, data, timeout):
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return RawResponse(getattr(resp, "status", 200), resp.read())
    except urllib.error.HTTPError as e:  # 4xx/5xx 也要拿到 body
        try:
            body = e.read()
        except Exception:
            body = b""
        return RawResponse(e.code, body or b"")


class Client:
    def __init__(self, timeout: int = 20, retries: int = 3, backoff: float = 1.0,
                 jitter: float = 0.3, transport=None, sleep=None, user_agent: str = USER_AGENT):
        self.timeout = timeout
        self.retries = max(1, int(retries))
        self.backoff = backoff
        self.jitter = jitter
        self.transport = transport or _default_transport
        self.sleep = sleep or time.sleep
        self.user_agent = user_agent

    def request(self, method: str, url: str, headers: dict | None = None,
                json_body=None, is_success=None, retries: int | None = None) -> HttpResult:
        hdrs = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if headers:
            hdrs.update(headers)

        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")

        limit = max(1, int(retries if retries is not None else self.retries))
        last_error = ""

        for attempt in range(1, limit + 1):
            try:
                raw = self.transport(method, url, hdrs, data, self.timeout)
            except Exception as e:  # 网络错误统一重试
                last_error = f"{type(e).__name__}: {e}"
                if attempt < limit:
                    self._wait(attempt)
                    continue
                return HttpResult(0, "", None, False, last_error, attempt)

            text = (raw.body or b"").decode("utf-8", "replace")
            parsed = None
            if text.strip():
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = None

            if raw.status >= 500:
                last_error = f"HTTP {raw.status}: {text[:120]}"
                if attempt < limit:
                    self._wait(attempt)
                    continue
                return HttpResult(raw.status, text, parsed, False, last_error, attempt)

            ok = 200 <= raw.status < 300
            if ok and is_success is not None:
                ok = bool(is_success(parsed if parsed is not None else {}))
            err = "" if ok else f"HTTP {raw.status}: {text[:160]}"
            return HttpResult(raw.status, text, parsed, ok, err, attempt)

        return HttpResult(0, "", None, False, last_error, limit)

    def _wait(self, attempt: int) -> None:
        self.sleep(self.backoff * attempt + random.uniform(0, self.jitter))

    def get(self, url: str, **kw) -> HttpResult:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw) -> HttpResult:
        return self.request("POST", url, **kw)
