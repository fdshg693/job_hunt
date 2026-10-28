"""Google カレンダーの期間内の予定一覧を保存する CLI（読み取り専用）.

Google カレンダー予定一覧 CLI（読み取り専用）.

期間内の予定（繰り返しは展開）を data/gcal/events/YYYY-MM-DD-HHmmss.md（＋同名 .json）に保存する。
--job-only でこのツールが作った予定（extendedProperties.private の job_hunt_managed=1）だけに絞る。
読めるのは自分所有のカレンダーの予定だけ（スコープ calendar.events.owned）。空き時間だけなら find_slots.py を使う。

- stdout: 保存したファイル（.md / .json）のパス
- 終了コード: 0 正常 / 1 エラー / 2 未認可・トークン失効（ユーザーの再認可が必要）
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# プロジェクトルートパス (scripts/gcal/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import create_base_parser, entrypoint_guard
from scripts.gcal.client import (
    DEFAULT_TZ,
    MANAGED_PROPERTY_KEY,
    MANAGED_PROPERTY_VALUE,
    GoogleAuthError,
    build_service,
    cell,
    execute,
    load_tz,
    resolve_range,
    save_result,
)

DEFAULT_LIMIT = 100
LIST_PAGE_MAX = 250


def _when(value: dict[str, Any], tz: ZoneInfo) -> tuple[str, bool]:
    """start / end を (表示用の文字列, 終日か) にする."""
    if "dateTime" in value:
        return datetime.fromisoformat(value["dateTime"]).astimezone(tz).isoformat(timespec="minutes"), False
    return date.fromisoformat(value["date"]).isoformat(), True


def event_row(e: dict[str, Any], tz: ZoneInfo) -> dict[str, Any]:
    start, all_day = _when(e.get("start", {}), tz)
    end, _ = _when(e.get("end", {}), tz)
    private = e.get("extendedProperties", {}).get("private", {})
    return {
        "id": e["id"],
        "summary": e.get("summary", "（タイトルなし）"),
        "start": start,
        "end": end,
        "all_day": all_day,
        "status": e.get("status", ""),
        "transparency": e.get("transparency", "opaque"),
        "event_type": e.get("eventType", "default"),
        "managed": private.get(MANAGED_PROPERTY_KEY) == MANAGED_PROPERTY_VALUE,
        "private_properties": private,
        "html_link": e.get("htmlLink", ""),
    }


def list_events(
    service: Any, calendar_id: str, time_min: datetime, time_max: datetime, limit: int, tz: ZoneInfo, job_only: bool = False
) -> list[dict[str, Any]]:
    """events.list をページングし、開始順に最大 limit 件を集める."""
    params: dict[str, Any] = {
        "calendarId": calendar_id,
        "timeMin": time_min.isoformat(),
        "timeMax": time_max.isoformat(),
        "singleEvents": True,
        "orderBy": "startTime",
        "maxResults": min(LIST_PAGE_MAX, limit),
    }
    if job_only:
        # 複数条件の意味がドキュメント間で食い違うので 1 条件だけで使う
        params["privateExtendedProperty"] = f"{MANAGED_PROPERTY_KEY}={MANAGED_PROPERTY_VALUE}"
    rows: list[dict[str, Any]] = []
    page_token = None
    while len(rows) < limit:
        resp = execute(service.events().list(pageToken=page_token, **params))
        rows += [event_row(e, tz) for e in resp.get("items", [])]
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return rows[:limit]


def save_events(
    calendar_id: str, time_min: datetime, time_max: datetime, job_only: bool, rows: list[dict[str, Any]], data_dir: Path | None = None
) -> tuple[Path, Path]:
    fm = {
        "calendar": calendar_id,
        "time_min": time_min.isoformat(),
        "time_max": time_max.isoformat(),
        "job_only": job_only,
        "event_count": len(rows),
    }
    lines = [
        f"# Google カレンダー予定一覧: {time_min:%Y-%m-%d} 〜 {time_max:%Y-%m-%d}（終了日は含まない）",
        "",
        f"- カレンダー: `{calendar_id}`",
        f"- 絞り込み: {'このツールが作った予定のみ' if job_only else 'なし'}",
        f"- 件数: {len(rows)} 件",
        "",
        "| 開始 | 終了 | タイトル | 状態 | 予定なし表示 | ツール作成 | ID |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['start']} | {r['end']} | {cell(r['summary'])} | {r['status']} "
            f"| {'✓' if r['transparency'] == 'transparent' else ''} | {'✓' if r['managed'] else ''} | `{r['id']}` |"
        )
    return save_result("events", fm, lines, {"events": rows}, data_dir)


def main() -> int:
    parser = create_base_parser(
        description="Google カレンダーの予定一覧を data/gcal/events/ に保存する（読み取り専用）",
        default_limit=DEFAULT_LIMIT,
        examples=[
            "uv run python scripts/gcal/list_events.py --summary",
            "uv run python scripts/gcal/list_events.py --since 2026-11-01 --until 2026-11-30 --calendar <calendar-id>",
            "uv run python scripts/gcal/list_events.py --job-only --summary  # このツールが作った予定だけ",
        ],
        related=[
            "scripts/gcal/manage_events.py: 次に使う（予定 ID を指定して更新・削除する）",
        ],
    )
    parser.add_argument("--since", help="開始日 YYYY-MM-DD（省略時は今日）")
    parser.add_argument("--until", help="終了日 YYYY-MM-DD（当日を含む。省略時は開始日から 14 日分）")
    parser.add_argument("--calendar", default="primary", help="カレンダー ID（既定: primary。一覧は list_calendars.py）")
    parser.add_argument("--job-only", action="store_true", help="このツールが作った予定だけに絞る")
    parser.add_argument("--tz", default=DEFAULT_TZ, help=f"日付の区切りと表示のタイムゾーン（既定: {DEFAULT_TZ}）")
    args = parser.parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        rows: list[dict[str, Any]] = []
        tz = load_tz(args.tz)
        time_min, time_max = resolve_range(args.since, args.until, tz)
        try:
            rows = list_events(build_service(), args.calendar, time_min, time_max, args.limit or DEFAULT_LIMIT, tz, args.job_only)
            ctx.add_result_paths(save_events(args.calendar, time_min, time_max, args.job_only, rows))
        except GoogleAuthError as e:
            ctx.error(e.handoff_message())
            ctx.set_exit_code(2)

        def print_summary() -> None:
            for r in rows:
                when = r["start"] if r["all_day"] else f"{r['start'][:16]}〜{r['end'][11:16]}"
                mark = " [tool]" if r["managed"] else ""
                print(f"- {when} | {r['summary']}{mark} [{r['id']}]")
            for p in ctx.result_paths[:1]:
                print(f"保存: {p}")

        return ctx.flush_outputs(summary_fn=print_summary, json_data={"calendar": args.calendar, "events": rows})


if __name__ == "__main__":
    sys.exit(main())
