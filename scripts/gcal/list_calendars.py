"""参照できる Google カレンダーの一覧を保存する CLI（読み取り専用）.

Google カレンダー一覧 CLI（読み取り専用）.

参照できるカレンダー（ID・表示名・primary か・権限）を data/gcal/calendars/YYYY-MM-DD-HHmmss.md（＋同名 .json）に保存する。
find_slots.py の --calendar に渡す ID を選ぶために使う。

- stdout: 保存したファイル（.md / .json）のパス
- 終了コード: 0 正常 / 1 エラー / 2 未認可・トークン失効（ユーザーの再認可が必要）
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/gcal/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import create_base_parser, entrypoint_guard
from scripts.gcal.client import GoogleAuthError, build_service, cell, execute, save_result


def list_calendars(service: Any) -> list[dict[str, Any]]:
    """calendarList.list をページングして全カレンダーを集める（primary を先頭に）."""
    rows: list[dict[str, Any]] = []
    page_token = None
    while True:
        resp = execute(service.calendarList().list(pageToken=page_token, maxResults=250))
        for c in resp.get("items", []):
            rows.append(
                {
                    "id": c["id"],
                    "summary": c.get("summaryOverride") or c.get("summary", ""),
                    "primary": bool(c.get("primary")),
                    "access_role": c.get("accessRole", ""),
                    "time_zone": c.get("timeZone", ""),
                    "selected": bool(c.get("selected")),
                }
            )
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    rows.sort(key=lambda r: (not r["primary"], r["access_role"] != "owner", r["summary"]))
    return rows


def save_calendars(rows: list[dict[str, Any]], data_dir: Path | None = None) -> tuple[Path, Path]:
    lines = [
        "# Google カレンダー一覧",
        "",
        "- 予定の作成・更新・削除ができるのは access_role が owner のカレンダーだけ（スコープ calendar.events.owned）",
        "",
        "| 表示名 | ID | primary | access_role | タイムゾーン | 表示中 |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {cell(r['summary'])} | `{r['id']}` | {'✓' if r['primary'] else ''} | {r['access_role']} "
            f"| {r['time_zone']} | {'✓' if r['selected'] else ''} |"
        )
    return save_result("calendars", {"calendar_count": len(rows)}, lines, {"calendars": rows}, data_dir)


def main() -> int:
    parser = create_base_parser(
        description="参照できる Google カレンダーの一覧を data/gcal/calendars/ に保存する（読み取り専用）",
        examples=[
            "uv run python scripts/gcal/list_calendars.py --summary",
            "uv run python scripts/gcal/list_calendars.py --json",
        ],
        related=[
            "scripts/gcal/find_slots.py: 次に使う（選んだ ID を --calendar に渡す）",
        ],
    )
    args = parser.parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        rows: list[dict[str, Any]] = []
        try:
            rows = list_calendars(build_service())
            ctx.add_result_paths(save_calendars(rows))
        except GoogleAuthError as e:
            ctx.error(e.handoff_message())
            ctx.set_exit_code(2)

        def print_summary() -> None:
            for r in rows:
                mark = " [primary]" if r["primary"] else ""
                print(f"- {r['summary']}{mark} | {r['access_role']} | {r['id']}")
            for p in ctx.result_paths[:1]:
                print(f"保存: {p}")

        return ctx.flush_outputs(summary_fn=print_summary, json_data={"calendars": rows})


if __name__ == "__main__":
    sys.exit(main())
