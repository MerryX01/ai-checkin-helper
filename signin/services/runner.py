"""业务编排：按注册表逐个执行平台，汇总结果与退出码。

这里没有 if/elif：加平台后自动被调度。
"""
from .. import platforms
from ..core import http
from ..core.models import CheckinResult, Status, pad


def build_client(cfg: dict) -> http.Client:
    rt = cfg.get("runtime") or {}
    return http.Client(
        timeout=rt.get("timeout", 20),
        retries=rt.get("retries", 3),
        backoff=rt.get("backoff", 1.0),
    )


def run_all(cfg: dict, client=None, only=None, dry_run: bool = False, log=None, on_result=None) -> list[CheckinResult]:
    """按启用状态逐个执行，单个平台抛异常不影响其它平台。"""
    client = client or build_client(cfg)
    results: list[CheckinResult] = []

    for spec in platforms.all_specs():
        if only and spec.key not in only:
            continue
        section = cfg.get(spec.key) or {}
        if not section.get("enabled"):
            continue
        try:
            result = spec.run(client, section, dry_run=dry_run)
        except Exception as e:
            result = CheckinResult(spec.key, Status.FAILED, f"未预期异常：{type(e).__name__}: {e}")

        results.append(result)
        if log:
            log.info(result.line())
        if on_result:
            on_result(result)
    return results


def summary(results: list[CheckinResult]) -> str:
    if not results:
        return "没有启用的平台（先编辑 config.json，或在界面里勾选）"
    lines = [pad("平台", 12) + pad("结果", 6) + pad("积分", 8) + "说明"]
    lines.append("-" * 60)
    for r in results:
        lines.append(r.line())
    ok = sum(1 for r in results if r.is_ok)
    need = sum(1 for r in results if r.status == Status.NEED_SETUP)
    badge = sum(1 for r in results if r.status == Status.FAILED)
    lines.append("-" * 60)
    lines.append(f"合计 {len(results)} 个平台：成功/已签 {ok}，需配置 {need}，失败 {badge}")
    return "\n".join(lines)


def exit_code(results: list[CheckinResult]) -> int:
    return 1 if any(r.status == Status.FAILED for r in results) else 0
