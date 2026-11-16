"""签到历史落盘：只记结果摘要，不记令牌/Cookie。

看板用它补齐「今天已经签到多少」，避免关掉界面后今天的收益变成「—」。
"""
import json
from datetime import date, datetime
from pathlib import Path

from ..core import config
from ..core.models import CheckinResult, Status

FILE_NAME = "checkin_history.jsonl"


def default_path() -> Path:
    return config.ROOT / "logs" / FILE_NAME


def append(results: list[CheckinResult], when: datetime | None = None,
           path: str | Path | None = None) -> Path:
    target = Path(path) if path else default_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    when = when or datetime.now()
    with open(target, "a", encoding="utf-8") as f:
        for result in results:
            record = {
                "at": when.strftime("%Y-%m-%d %H:%M:%S"),
                "date": when.strftime("%Y-%m-%d"),
                "platform": result.platform,
                "status": result.status.value,
                "credits": result.credits,
                "message": result.message,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return target


def today_results(path: str | Path | None = None, today: date | None = None) -> dict[str, CheckinResult]:
    target = Path(path) if path else default_path()
    wanted = (today or date.today()).strftime("%Y-%m-%d")
    out: dict[str, CheckinResult] = {}
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return out
    for line in lines:
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(row, dict) or row.get("date") != wanted:
            continue
        platform = str(row.get("platform") or "").strip()
        if not platform:
            continue
        try:
            status = Status(str(row.get("status") or "skipped"))
        except ValueError:
            status = Status.SKIPPED
        credits = row.get("credits")
        try:
            credits = int(credits) if credits is not None else None
        except (TypeError, ValueError):
            credits = None
        out[platform] = CheckinResult(platform, status, str(row.get("message") or ""), credits)
    return out
