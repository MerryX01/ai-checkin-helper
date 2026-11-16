"""平台插件协议。

新增一个平台 = 新建 `signin/platforms/<名字>.py`，在里面定义 SPEC 并用 `register()` 注册。
配置默认值、界面输入框、校验提示、执行顺序、命令行选项全部由这份 SPEC 推导出来，
不需要再改 config / settings / ui / cli 里的任何一处。
"""
from dataclasses import dataclass, field
from typing import Callable

from ..core.models import LoginState

FIELD_KINDS = ("text", "secret", "path", "int", "bool")
ACTION_KINDS = ("login", "teach", "probe", "open_client")


@dataclass(frozen=True)
class FieldSpec:
    """界面上的一个输入项（同时决定 config.json 的字段与默认值）。"""

    key: str
    label: str
    kind: str = "text"          # text | secret | path | int | bool
    default: object = ""
    required: bool = False
    hint: str = ""              # 输入框下方的小字说明
    env: str = ""               # 对应的环境变量名（可选）
    credential: bool = False    # 是否凭证：环境变量命中时自动启用该平台
    advanced: bool = False      # 高级项：界面默认隐藏，需要时可展开

    def __post_init__(self):
        if self.kind not in FIELD_KINDS:
            raise ValueError(f"未知字段类型：{self.kind}（可选 {'/'.join(FIELD_KINDS)}）")


@dataclass
class PlatformSpec:
    """一个平台的完整描述。"""

    key: str                    # 配置段名，同时是命令行 --only 的取值
    label: str                  # 展示名
    summary: str                # 一句话说明（README / check 输出）
    description: str            # 界面右侧的详细说明
    run: Callable               # (client, section, dry_run=False) -> CheckinResult
    fields: tuple = ()          # 界面字段（含 base_url 这类可编辑项）
    enabled_default: bool = False
    defaults: dict = field(default_factory=dict)   # 不在界面上、但配置里要有的键
    actions: tuple = ()         # 面板上的附加按钮：login / teach / probe / open_client
    login_url: str = ""         # 「打开登录页」跳转地址
    check: Callable | None = None                  # (section) -> [问题说明]，空列表表示可跑
    login_state: Callable | None = None            # () -> LoginState，自动读本机登录态
    login_hint: str = ""        # 「登录一次」要用户去哪儿登录
    quota: Callable | None = None                  # (client, section) -> QuotaSnapshot，额度看板

    def __post_init__(self):
        for action in self.actions:
            if action not in ACTION_KINDS:
                raise ValueError(f"未知面板动作：{action}（可选 {'/'.join(ACTION_KINDS)}）")

    def detect_login(self) -> LoginState:
        """安全地调一次登录态探测：任何异常都转成「未登录 + 原因」。"""
        if self.login_state is None:
            return LoginState(False, message=self.login_hint or "该平台不支持自动读取登录态")
        try:
            state = self.login_state()
        except Exception as exc:  # 探测失败不该让整个界面崩
            return LoginState(False, message=f"读取登录态失败：{type(exc).__name__}: {exc}")
        return state if isinstance(state, LoginState) else LoginState(bool(state))

    def problems(self, section: dict) -> list[str]:
        """该平台当前配置还缺什么。"""
        section = section or {}
        if self.check is not None:
            return list(self.check(section) or [])
        missing = [f.label for f in self.fields
                   if f.required and not str(section.get(f.key) or "").strip()]
        return [f"缺少 {', '.join(missing)}"] if missing else []

    @property
    def credential_field(self) -> FieldSpec | None:
        for f in self.fields:
            if f.credential:
                return f
        return None
