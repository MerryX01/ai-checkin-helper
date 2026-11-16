# 加一个平台

新增平台只动两个地方：**写一个模块**、**注册它**。不需要改 config / settings / ui / cli。

## 1. 写模块

新建 `signin/platforms/yourname.py`：

```python
from ..core.models import CheckinResult, LoginState, Status
from .base import FieldSpec, PlatformSpec
from .registry import register

BASE_URL = "https://api.example.com"


def login_state() -> LoginState:
    """自动读本机客户端登录态。读不到就返回 ok=False + 一句人话提示。"""
    token = ...  # 用 signin.core.secrets 里的工具
    if not token:
        return LoginState(False, message="先在 Example 客户端登录一次")
    return LoginState(True, account="昵称", data={"token": token})


def check(section: dict) -> list[str]:
    """这个平台还缺什么（空列表 = 可以跑）。界面的「待配置」也用它。"""
    token = (section.get("token") or "").strip()
    if token:
        return []
    state = login_state()
    return [] if state.ok else [state.message]


def run(client, section, dry_run=False):
    token = (section.get("token") or "").strip()
    if not token:
        state = login_state()
        if not state.ok:
            return CheckinResult("yourname", Status.NEED_SETUP, state.message)
        token = (state.data or {}).get("token", "")
    if dry_run:
        return CheckinResult("yourname", Status.SKIPPED, f"dry-run：将 POST {BASE_URL}/checkin")
    resp = client.request("POST", f"{BASE_URL}/checkin",
                          headers={"Authorization": f"Bearer {token}"}, json_body={})
    if resp.status == 401:
        return CheckinResult("yourname", Status.NEED_SETUP, "登录已失效：重新打开客户端登录一次")
    ...
    return CheckinResult("yourname", Status.OK, "签到成功")


SPEC = PlatformSpec(
    key="yourname",                 # 配置段名 / --only 取值
    label="Example",
    summary="每日签到拿积分",
    description="只要在 Example 客户端登录一次，脚本就会自动读取登录态。",
    run=run,
    fields=(
        FieldSpec("base_url", "接口地址", default=BASE_URL),
        # FieldSpec("token", "令牌", kind="secret", credential=True, advanced=True, env="CHECKIN_YOURNAME_TOKEN")
    ),
    enabled_default=False,
    login_state=login_state,
    login_hint="在 Example 客户端里登录一次即可",
    check=check,
    actions=("open_client",),      # login / teach / probe / open_client
    login_url="https://example.com/login",
)
register(SPEC)
```

`CheckinResult(platform, status, message="", credits=None, detail={})`；状态用 `Status`：
`OK` 成功、`ALREADY` 今天已签、`NEED_SETUP` 缺配置/失效、`FAILED` 失败、`SKIPPED` dry-run。

## 2. 注册

在 `signin/platforms/__init__.py` 里加一行导入：

```python
from . import yourname  # noqa: F401  （导入即注册）
```

## 2.5 加额度看板（可选）

如果平台有余额/用量接口，再加一个只读函数，并把 `quota=` 传给 `PlatformSpec`：

```python
from ..core.models import QuotaSnapshot

def quota(client, section):
    token = ...
    resp = client.get(f"{BASE_URL}/usage", headers={"Authorization": f"Bearer {token}"})
    if resp.status == 401:
        return QuotaSnapshot("yourname", Status.NEED_SETUP, "登录已失效")
    data = resp.json or {}
    return QuotaSnapshot(
        "yourname", Status.OK, "已读取额度",
        balance=data.get("remaining"), total=data.get("total"), used=data.get("used"),
        unit="credits", details=[("套餐", data.get("plan", ""))],
        source="GET api.example.com /usage",
    )
```

没有额度接口的平台不用写 `quota`，看板会显示「未提供」，不会影响签到。

## 3. 自检

```bat
python run.py platforms                       :: 应该能看到 Example
python -m unittest discover -s tests -t .      :: 现有测试不应被破坏
py -3 gui_app.py --selftest                   :: panels 数量 +1
```

## 约定

- **凭证优先自动读**：`login_state()` 能读出来就不要让用户填。界面上的令牌类字段默认 `advanced=True`（折叠在「显示高级项」里），只作为兜底。
- **`check()` 要说人话**：面向用户，不写堆栈。
- **`run()` 必须幂等**：今天已签就返回 `ALREADY`，不要重复请求领取。
- **不要新增第三方依赖**：HTTP 用 `signin.core.http.Client`，点击用 `signin.gui`，加密用 `signin.core.aesgcm`。
