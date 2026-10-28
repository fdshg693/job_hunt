"""Google カレンダーの空きから面談候補枠を算出・保存する CLI（読み取り専用）.

面談候補日 CLI（読み取り専用）.

freebusy.query で指定カレンダーの busy 区間を取り、稼働時間帯・曜日・祝日・前後バッファ・所要時間の条件で空き枠を出して
data/gcal/slots/YYYY-MM-DD-HHmmss.md（＋同名 .json）に保存する。予定の本文（タイトル等）は取らない。
--summary で返信にそのまま貼れる表記（例: `10/28(水) 13:00〜19:00`）を出す。空き枠は連続した空きをそのまま返すので、
どの枠を相手に出すかは呼び出し側（AI）が状況を見て選ぶ。算出ロジックは scripts/gcal/slots.py。

- stdout: 保存したファイル（.md / .json）のパス
- 終了コード: 0 正常 / 1 エラー（カレンダーが見つからない等） / 2 未認可・トークン失効（ユーザーの再認可が必要）
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# プロジェクトルートパス (scripts/gcal/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import create_base_parser, entrypoint_guard
from scripts.gcal import slots
from scripts.gcal.client import DEFAULT_TZ, GoogleAuthError, build_service, execute, load_tz, resolve_range, save_result

DEFAULT_LIMIT = 30
FREEBUSY_MAX_CALENDARS = 50  # calendarExpansionMax の上限


class FreeBusyError(Exception):
    """freeBusy がカレンダー単位のエラーを返した（HTTP 200 でも calendars[id].errors に入る）."""


def query_busy(service: Any, calendar_ids: list[str], time_min: datetime, time_max: datetime) -> list[slots.Interval]:
    """freebusy.query で busy 区間を集める。どれかのカレンダーにエラーがあれば FreeBusyError."""
    if len(calendar_ids) > FREEBUSY_MAX_CALENDARS:
        raise ValueError(f"--calendar は {FREEBUSY_MAX_CALENDARS} 個までです")
    body = {
        "timeMin": time_min.isoformat(),
        "timeMax": time_max.isoformat(),
        "items": [{"id": cid} for cid in calendar_ids],
    }
    resp = execute(service.freebusy().query(body=body))
    calendars = resp.get("calendars", {})
    errors = [f"{cid}: {', '.join(e.get('reason', '?') for e in cal['errors'])}" for cid, cal in calendars.items() if cal.get("errors")]
    missing = [cid for cid in calendar_ids if cid not in calendars]
    if errors or missing:
        raise FreeBusyError(
            "空き時間を取得できないカレンダーがあります（ID の誤り、または共有されていない可能性）: "
            + "; ".join(errors + [f"{cid}: 応答なし" for cid in missing])
        )
    return slots.parse_freebusy(calendars)


def build_rules(args: Any, tz: ZoneInfo, time_min: datetime, time_max: datetime) -> slots.SlotRules:
    day_start, day_end = slots.parse_hours(args.hours)
    holidays = slots.country_holidays(
        None if args.holidays.lower() == "none" else args.holidays, time_min.date(), (time_max - timedelta(days=1)).date()
    )
    return slots.SlotRules(
        tz=tz,
        day_start=day_start,
        day_end=day_end,
        weekdays=slots.parse_weekdays(args.weekdays),
        holidays=holidays,
        buffer=timedelta(minutes=args.buffer),
        min_duration=timedelta(minutes=args.duration),
        align=timedelta(minutes=args.align),
    )


def find(
    busy: list[slots.Interval], time_min: datetime, time_max: datetime, rules: slots.SlotRules, limit: int, now: datetime
) -> list[slots.Interval]:
    """過去の時刻を除いて空き枠を出し、先頭から limit 件に絞る."""
    return slots.free_slots(busy, max(time_min, now), time_max, rules)[:limit]


def save_slots(
    args: Any,
    calendar_ids: list[str],
    time_min: datetime,
    time_max: datetime,
    rules: slots.SlotRules,
    extra_busy: list[slots.Interval],
    found: list[slots.Interval],
    texts: list[str],
    display_tz: ZoneInfo,
    data_dir: Path | None = None,
) -> tuple[Path, Path]:
    holidays = sorted(rules.holidays)
    fm = {
        "calendars": calendar_ids,
        "time_min": time_min.isoformat(),
        "time_max": time_max.isoformat(),
        "tz": rules.tz.key,
        "display_tz": display_tz.key,
        "hours": args.hours,
        "weekdays": args.weekdays,
        "holidays_country": args.holidays,
        "duration_minutes": args.duration,
        "buffer_minutes": args.buffer,
        "align_minutes": args.align,
        "extra_busy": [f"{s.isoformat()}/{e.isoformat()}" for s, e in extra_busy],
        "slot_count": len(found),
    }
    lines = [
        f"# 面談候補（空き枠）: {time_min:%Y-%m-%d} 〜 {(time_max - timedelta(days=1)):%Y-%m-%d}",
        "",
        f"- 対象カレンダー: {', '.join(f'`{c}`' for c in calendar_ids)}",
        f"- 条件: {args.weekdays} {args.hours}（{rules.tz.key}）/ 所要 {args.duration} 分以上 / 前後バッファ {args.buffer} 分 / {args.align} 分刻み",
        f"- 除外した祝日（{args.holidays}）: {', '.join(d.isoformat() for d in holidays) or 'なし'}",
        f"- 手動で足した busy: {len(extra_busy)} 件",
        f"- 表示タイムゾーン: {display_tz.key}",
        "",
        "## 返信用（連続した空き。相手・状況に合わせて間引く）",
        "",
        *[f"- {t}" for t in texts],
    ]
    if not texts:
        lines.append("- 条件に合う空き枠はありません")
    payload = {
        "slots": [
            {"start": s.isoformat(), "end": e.isoformat(), "minutes": int((e - s).total_seconds() // 60), "text": t}
            for (s, e), t in zip(found, texts, strict=True)
        ]
    }
    return save_result("slots", fm, lines, payload, data_dir)


def main() -> int:
    parser = create_base_parser(
        description="Google カレンダーの空き時間から面談候補日を出し、data/gcal/slots/ に保存する（読み取り専用）",
        default_limit=DEFAULT_LIMIT,
        examples=[
            "uv run python scripts/gcal/find_slots.py --summary",
            "uv run python scripts/gcal/find_slots.py --since 2026-11-02 --until 2026-11-13 --hours 13-18 --duration 45 --summary",
            'uv run python scripts/gcal/find_slots.py --busy "2026-11-04 15:00-16:00" --summary  # カレンダー外の予定を除く',
        ],
        related=[
            "scripts/gcal/list_calendars.py: 前に使う（--calendar に渡す ID を調べる）",
            "scripts/gcal/manage_events.py: 次に使う（確定した日時で予定を登録する）",
        ],
    )
    parser.add_argument("--since", help="開始日 YYYY-MM-DD（省略時は今日。今日なら現在時刻以降）")
    parser.add_argument("--until", help="終了日 YYYY-MM-DD（当日を含む。省略時は開始日から 14 日分）")
    parser.add_argument("--duration", type=int, default=60, help="必要な所要時間（分。これ未満の空きは出さない。既定: 60）")
    parser.add_argument("--hours", default="10-19", help="候補にする時間帯（例: 10-19, 9:30-18:00。既定: 10-19）")
    parser.add_argument("--weekdays", default="mon-fri", help="候補にする曜日（例: mon-fri, mon,wed,fri。既定: mon-fri）")
    parser.add_argument("--buffer", type=int, default=15, help="既存予定の前後に空ける時間（分。既定: 15）")
    parser.add_argument("--align", type=int, default=30, help="枠の開始・終了を揃える刻み（分。既定: 30）")
    parser.add_argument("--holidays", default="JP", help="除外する祝日の国コード（ISO 3166-1。none で除外しない。既定: JP）")
    parser.add_argument(
        "--calendar",
        action="append",
        dest="calendars",
        help="busy に含めるカレンダー ID（複数回指定可。既定: primary。一覧は list_calendars.py）",
    )
    parser.add_argument(
        "--busy",
        action="append",
        default=[],
        help="カレンダー未登録の予定を busy に足す（'YYYY-MM-DD HH:MM-HH:MM'、--tz の現地時刻。複数回指定可）",
    )
    parser.add_argument("--tz", default=DEFAULT_TZ, help=f"時間帯・曜日・祝日を判定するタイムゾーン（既定: {DEFAULT_TZ}）")
    parser.add_argument("--display-tz", help="候補の表示タイムゾーン（相手の現地時刻で見せたいとき。既定: --tz と同じ）")
    parser.add_argument("--lang", choices=["ja", "en"], default="ja", help="表記（ja: 10/28(水) 13:00〜15:00 / en: Wed, Oct 28 13:00-15:00）")
    args = parser.parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        found: list[slots.Interval] = []
        texts: list[str] = []
        tz = load_tz(args.tz)
        display_tz = load_tz(args.display_tz) if args.display_tz else tz
        calendar_ids = args.calendars or ["primary"]
        time_min, time_max = resolve_range(args.since, args.until, tz)
        rules = build_rules(args, tz, time_min, time_max)
        extra_busy = [slots.parse_busy_arg(b, tz) for b in args.busy]
        try:
            busy = query_busy(build_service(), calendar_ids, time_min, time_max)
            found = find(busy + extra_busy, time_min, time_max, rules, args.limit or DEFAULT_LIMIT, datetime.now(tz))
            ctx.log(f"[空き枠] busy {len(busy)} 件（+手動 {len(extra_busy)} 件）→ 候補 {len(found)} 件")
            # 判定と別のタイムゾーンで見せるとき・英語表記のときは TZ 略号を付ける
            show_tz = display_tz.key != tz.key or args.lang == "en"
            texts = [slots.format_slot(s, e, display_tz, args.lang, show_tz) for s, e in found]
            ctx.add_result_paths(save_slots(args, calendar_ids, time_min, time_max, rules, extra_busy, found, texts, display_tz))
        except GoogleAuthError as e:
            ctx.error(e.handoff_message())
            ctx.set_exit_code(2)
        except FreeBusyError as e:
            ctx.error(str(e))
            ctx.set_exit_code(1)

        def print_summary() -> None:
            for t in texts:
                print(f"- {t}")
            if not texts:
                print("（条件に合う空き枠はありません）")
            for p in ctx.result_paths[:1]:
                print(f"保存: {p}")

        return ctx.flush_outputs(
            summary_fn=print_summary,
            json_data={"slots": [{"start": s.isoformat(), "end": e.isoformat(), "text": t} for (s, e), t in zip(found, texts, strict=True)]},
        )


if __name__ == "__main__":
    sys.exit(main())
