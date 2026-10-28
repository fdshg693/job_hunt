"""Google Calendar API クライアント.

認証（token.json の読込・refresh・スコープ検証）と再試行は Google 共通層 scripts/google/client.py が担い、
ここは Calendar API service の生成と、CLI 共通の期間解決・保存を持ちます。
スコープは calendar.events.owned / calendar.events.freebusy / calendar.calendarlist.readonly（定義は共通層の CALENDAR_SCOPES）。
仕様は docs/gcal/README.md、認証は docs/google/README.md を参照。
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from scripts.common.cli import PROJECT_ROOT
from scripts.google.client import GoogleAuthError
from scripts.google.client import build_service as _build_service
from scripts.google.client import execute as _execute

__all__ = ["GoogleAuthError", "build_service", "execute"]

DATA_DIR = PROJECT_ROOT / "data" / "gcal"

# 稼働時間帯・日付の判定に使う既定のタイムゾーン（--tz 等で上書き）
DEFAULT_TZ = "Asia/Tokyo"
# 期間の既定日数（--until 省略時、--since から数えて何日分か）
DEFAULT_DAYS = 14

# このツールが作った予定の目印（extendedProperties.private。キーは 44 文字以内）
MANAGED_PROPERTY_KEY = "job_hunt_managed"
MANAGED_PROPERTY_VALUE = "1"
# 予定と vault の企業ログを結ぶキー（値は company_key。予定 ID は vault のスキーマに持たせず、これで逆引きする）
COMPANY_PROPERTY_KEY = "job_hunt_company_key"


def build_service(creds: Any | None = None) -> Any:
    """Calendar API v3 の service を生成する."""
    return _build_service("calendar", "v3", creds)


def execute(request: Any) -> Any:
    """Calendar API リクエストを再試行付きで実行する（429・rateLimitExceeded・5xx は指数バックオフ）."""
    return _execute(request, api_name="Calendar API")


def load_tz(name: str) -> ZoneInfo:
    from zoneinfo import ZoneInfoNotFoundError

    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"タイムゾーンが不正です（IANA 名で指定。例: Asia/Tokyo）: {name}") from None


def resolve_range(since: str | None, until: str | None, tz: ZoneInfo, now: datetime | None = None) -> tuple[datetime, datetime]:
    """--since / --until（YYYY-MM-DD、until は当日を含む）を [開始, 終了) にする。since 省略時は今日、until 省略時は 14 日分."""
    today = (now or datetime.now(tz)).astimezone(tz).date()
    first = date.fromisoformat(since) if since else today
    last = date.fromisoformat(until) if until else first + timedelta(days=DEFAULT_DAYS - 1)
    if last < first:
        raise ValueError(f"--until は --since 以降の日付にしてください: {first} 〜 {last}")
    return datetime.combine(first, time(0), tz), datetime.combine(last + timedelta(days=1), time(0), tz)


def save_result(kind: str, fm: dict[str, Any], lines: list[str], payload: dict[str, Any], data_dir: Path | None = None) -> tuple[Path, Path]:
    """data/gcal/{kind}/YYYY-MM-DD-HHmmss.md（＋同名 .json）に保存する."""
    now = datetime.now().astimezone()
    target = (data_dir or DATA_DIR) / kind
    target.mkdir(parents=True, exist_ok=True)
    base = f"{now:%Y-%m-%d-%H%M%S}"
    md_path, json_path = target / f"{base}.md", target / f"{base}.json"
    fm = {"source": "gcal", "type": kind, **fm, "fetched_at": now.isoformat(timespec="seconds")}
    fm_yaml = yaml.dump(fm, allow_unicode=True, sort_keys=False).strip()
    md_path.write_text(f"---\n{fm_yaml}\n---\n\n" + "\n".join(lines).rstrip() + "\n", encoding="utf-8")
    json_path.write_text(json.dumps({**fm, **payload}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return md_path, json_path


def cell(value: Any) -> str:
    """Markdown 表のセル用にエスケープする."""
    return str(value or "").replace("|", "\\|").replace("\n", " ")
