"""额度看板业务层：逐个平台读取真实余额/用量，并合成今天的签到收益。

数据只来自各平台客户端登录态对应的接口；任何平台失败都只影响自己那一行。
"""
from .. import platforms
from ..core.models import (CheckinResult, QUOTA_STATUS_CN, QuotaSnapshot, Status, pad)
from . import runner


def collect(cfg: dict, client=None, specs=None, results: dict | None = None,
            only=None) -> list[QuotaSnapshot]:
    client = client or runner.build_client(cfg)
    specs = list(specs if specs is not None else platforms.all_specs())
    if only:
        wanted = {str(k).strip() for k in only if str(k).strip()}
        specs = [s for s in specs if s.key in wanted]

    snapshots: list[QuotaSnapshot] = []
    for spec in specs:
        section = cfg.get(spec.key) or {}
        fn = getattr(spec, "quota", None)
        if not callable(fn):
            snap = QuotaSnapshot(spec.key, Status.SKIPPED,
                                 "该平台还没有额度查询适配器（新增平台时补 quota() 即可）")
        else:
            try:
                snap = fn(client, section)
            except Exception as exc:  # 一个平台读不到不影响其它平台
                snap = QuotaSnapshot(spec.key, Status.FAILED,
                                     f"读取额度异常：{type(exc).__name__}: {exc}")
        if not isinstance(snap, QuotaSnapshot):
            snap = QuotaSnapshot(spec.key, Status.FAILED, "额度适配器没有返回 QuotaSnapshot")

        result = (results or {}).get(spec.key)
        if (isinstance(result, CheckinResult) and result.is_ok
                and result.credits is not None):
            snap.today_earned = result.credits
        snapshots.append(snap)
    return snapshots


def summary(snapshots: list[QuotaSnapshot]) -> str:
    """CLI 用等宽表格；明细字段由 UI 展示。"""
    if not snapshots:
        return "没有可查询的平台"
    lines = [pad("平台", 12) + pad("余额", 10) + pad("总量", 10) + pad("已用", 10)
             + pad("使用率", 8) + pad("今日签到", 10) + "状态"]
    lines.append("-" * 78)
    for snap in snapshots:
        lines.append(pad(snap.label, 12) + pad(snap.fmt_balance(), 10)
                     + pad(snap.fmt_total(), 10) + pad(snap.fmt_used(), 10)
                     + pad(snap.fmt_percent(), 8) + pad(snap.fmt_today(), 10)
                     + QUOTA_STATUS_CN.get(snap.status.value, snap.status.value))
    lines.append("-" * 78)
    ok = sum(1 for s in snapshots if s.status == Status.OK)
    lines.append(f"共 {len(snapshots)} 个平台：正常 {ok}，其余 {len(snapshots) - ok} 个需登录或读取失败")
    return "\n".join(lines)
