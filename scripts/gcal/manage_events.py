"""Google カレンダーの面談予定を作成・参照・更新・削除する CLI（安全ガード付き）.

Google カレンダー予定の作成・参照・更新・削除 CLI（安全ガード・バックアップ付き）.

面談確定時の予定登録（create）、内容確認（get）、リスケ（update）、辞退時の削除（delete）を行う。

安全ガード:
- 作成した予定には extendedProperties.private に job_hunt_managed=1（＋ --company-key があれば job_hunt_company_key）を付ける。
- update / delete は既定でこの目印のある予定だけ。それ以外は --force が必要。
- 自分が organizer でない予定（企業から届いた招待）と、ゲストのいる予定は --force でも変更・削除しない
  （相手側に反映されない／相手のカレンダーを変えてしまうため。リスケは相手に依頼する）。
- 招待メールは送らない（sendUpdates=none 固定。attendees は扱わない）。
- create は同じ日に同じ company_key（無ければ同じタイトル）の予定があれば --force 無しでは作らない。
- update / delete の前に予定 JSON を data/gcal/backups/ に保存し、etag（If-Match）で他所での変更を検知する。
- --dry-run は API を書き換えず、反映内容を stderr に出す。

- stdout: 保存したファイル（.md / .json、バックアップ）のパス
- 終了コード: 0 正常 / 1 エラー・ガードによる拒否 / 2 未認可・トークン失効（ユーザーの再認可が必要）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# プロジェクトルートパス (scripts/gcal/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import EntrypointContext, build_epilog, entrypoint_guard, to_relative_path
from scripts.gcal.client import (
    COMPANY_PROPERTY_KEY,
    DATA_DIR,
    DEFAULT_TZ,
    MANAGED_PROPERTY_KEY,
    MANAGED_PROPERTY_VALUE,
    GoogleAuthError,
    build_service,
    cell,
    execute,
    load_tz,
    save_result,
)
from scripts.gcal.list_events import event_row

DEFAULT_DURATION = 60
SEND_UPDATES = "none"  # 招待・変更通知のメールを送らない（固定）


class GuardError(Exception):
    """安全ガードで操作を拒否した."""


def parse_local_datetime(value: str, tz: ZoneInfo) -> datetime:
    """`2026-10-28 15:00`（tz の現地時刻）を datetime にする."""
    try:
        dt = datetime.fromisoformat(value.strip().replace("T", " "))
    except ValueError:
        raise ValueError(f"日時は 'YYYY-MM-DD HH:MM' の形式で指定してください: {value}") from None
    if dt.tzinfo is not None:
        raise ValueError(f"日時にオフセットを付けず、--tz の現地時刻で指定してください: {value}")
    return dt.replace(tzinfo=tz)


def resolve_end(start: datetime, end: str | None, duration: int | None, tz: ZoneInfo) -> datetime:
    """--end（日時）か --duration（分）から終了時刻を決める."""
    if end and duration:
        raise ValueError("--end と --duration は同時に指定できません")
    result = parse_local_datetime(end, tz) if end else start + timedelta(minutes=duration or DEFAULT_DURATION)
    if result <= start:
        raise ValueError(f"終了は開始より後にしてください: {start:%Y-%m-%d %H:%M} 〜 {result:%Y-%m-%d %H:%M}")
    return result


def _when(dt: datetime, tz: ZoneInfo) -> dict[str, str]:
    return {"dateTime": dt.isoformat(), "timeZone": tz.key}


def build_event_body(
    title: str,
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    location: str | None = None,
    description: str | None = None,
    company_key: str | None = None,
) -> dict[str, Any]:
    """events.insert の body。目印の extendedProperties を必ず付け、attendees は付けない."""
    private = {MANAGED_PROPERTY_KEY: MANAGED_PROPERTY_VALUE}
    if company_key:
        private[COMPANY_PROPERTY_KEY] = company_key
    body: dict[str, Any] = {
        "summary": title,
        "start": _when(start, tz),
        "end": _when(end, tz),
        "extendedProperties": {"private": private},
    }
    if location:
        body["location"] = location
    if description:
        body["description"] = description
    return body


def is_managed(event: dict[str, Any]) -> bool:
    private = event.get("extendedProperties", {}).get("private", {})
    return private.get(MANAGED_PROPERTY_KEY) == MANAGED_PROPERTY_VALUE


def check_writable(event: dict[str, Any], force: bool) -> None:
    """update / delete してよい予定かを確かめる。だめなら GuardError."""
    if event.get("status") == "cancelled":
        # 削除済みの予定も get では 404 にならず status=cancelled で返る
        raise GuardError("予定は既に削除されています（status=cancelled）。")
    organizer = event.get("organizer", {})
    if organizer and not organizer.get("self"):
        raise GuardError(
            f"自分が主催者でない予定です（主催者: {organizer.get('email') or organizer.get('displayName') or '不明'}）。"
            "企業から届いた招待予定は、ここで変えても相手側に反映されません。リスケ・辞退は相手に連絡してください。"
        )
    guests = [a for a in event.get("attendees", []) if not a.get("self")]
    if guests:
        raise GuardError(f"ゲストのいる予定です（{len(guests)} 人）。変更・削除が相手のカレンダーに及ぶため扱いません。")
    if not is_managed(event) and not force:
        raise GuardError(
            "このツールが作った予定ではありません（extendedProperties.private の目印なし）。"
            "私用予定の誤操作を防ぐため、ユーザーの明示確認を取ってから --force を付けてください。"
        )


def find_duplicates(service: Any, calendar_id: str, body: dict[str, Any], tz: ZoneInfo) -> list[dict[str, Any]]:
    """同じ日（tz の現地日付）に同じ company_key（無ければ同じタイトル）のツール作成予定を探す."""
    day = datetime.fromisoformat(body["start"]["dateTime"]).astimezone(tz).date()
    private = body["extendedProperties"]["private"]
    company_key = private.get(COMPANY_PROPERTY_KEY)
    # privateExtendedProperty は 1 条件だけで使う（複数条件の意味がドキュメント間で食い違う）
    prop = f"{COMPANY_PROPERTY_KEY}={company_key}" if company_key else f"{MANAGED_PROPERTY_KEY}={MANAGED_PROPERTY_VALUE}"
    resp = execute(
        service.events().list(
            calendarId=calendar_id,
            timeMin=datetime.combine(day, time(0), tz).isoformat(),
            timeMax=datetime.combine(day + timedelta(days=1), time(0), tz).isoformat(),
            singleEvents=True,
            privateExtendedProperty=prop,
            maxResults=50,
        )
    )
    items = [e for e in resp.get("items", []) if is_managed(e) and e.get("status") != "cancelled"]
    if company_key:
        return items
    return [e for e in items if e.get("summary") == body["summary"]]


def get_event(service: Any, calendar_id: str, event_id: str) -> dict[str, Any]:
    if not event_id.strip():
        # 空の ID だと events.get が一覧扱いになり、予定でない応答が返る
        raise ValueError("--id に予定 ID を指定してください")
    return execute(service.events().get(calendarId=calendar_id, eventId=event_id))


def build_patch(
    event: dict[str, Any],
    tz: ZoneInfo,
    title: str | None = None,
    start: str | None = None,
    end: str | None = None,
    duration: int | None = None,
    location: str | None = None,
    description: str | None = None,
    company_key: str | None = None,
) -> dict[str, Any]:
    """events.patch の body（指定したフィールドだけ）。開始だけ変えたときは元の所要時間を保つ."""
    patch: dict[str, Any] = {}
    if title is not None:
        patch["summary"] = title
    if location is not None:
        patch["location"] = location
    if description is not None:
        patch["description"] = description
    if start or end or duration:
        if "dateTime" not in event.get("start", {}):
            raise GuardError("終日予定の日時変更には対応していません。カレンダーアプリで変更してください。")
        old_start = datetime.fromisoformat(event["start"]["dateTime"]).astimezone(tz)
        old_end = datetime.fromisoformat(event["end"]["dateTime"]).astimezone(tz)
        new_start = parse_local_datetime(start, tz) if start else old_start
        if end or duration:
            new_end = resolve_end(new_start, end, duration, tz)
        else:
            new_end = new_start + (old_end - old_start)
            if new_end <= new_start:
                raise ValueError("終了は開始より後にしてください")
        patch["start"] = _when(new_start, tz)
        patch["end"] = _when(new_end, tz)
    if company_key is not None:
        # patch はネストしたオブジェクトをマージするが、目印を落とさないよう既存ごと送る
        private = dict(event.get("extendedProperties", {}).get("private", {}))
        private[COMPANY_PROPERTY_KEY] = company_key
        patch["extendedProperties"] = {"private": private}
    return patch


def _with_if_match(request: Any, etag: str | None) -> Any:
    """他所（カレンダーアプリ等）で変更されていたら 412 で止める."""
    if etag:
        request.headers["If-Match"] = etag
    return request


def backup_event(event: dict[str, Any], action: str, data_dir: Path | None = None) -> Path:
    """変更前の予定 JSON を data/gcal/backups/ に保存する."""
    target = (data_dir or DATA_DIR) / "backups"
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{datetime.now():%Y-%m-%d-%H%M%S}_{action}_{event['id']}.json"
    path.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[安全ガード] 変更前バックアップを保存しました: {to_relative_path(path)}", file=sys.stderr)
    return path


def detail_row(event: dict[str, Any], tz: ZoneInfo) -> dict[str, Any]:
    """list_events.event_row ＋ 書き込み判定に使う項目."""
    row = event_row(event, tz)
    organizer = event.get("organizer", {})
    row.update(
        {
            "location": event.get("location", ""),
            "description": event.get("description", ""),
            "organizer_self": bool(organizer.get("self", not organizer)),
            "guest_count": len([a for a in event.get("attendees", []) if not a.get("self")]),
            "etag": event.get("etag", ""),
        }
    )
    return row


def save_event(action: str, calendar_id: str, row: dict[str, Any], extra: dict[str, Any] | None = None, data_dir: Path | None = None) -> tuple[Path, Path]:
    """操作結果を data/gcal/event/（get）または data/gcal/changes/（create/update/delete）に保存する."""
    kind = "event" if action == "get" else "changes"
    fm = {"action": action, "calendar": calendar_id, "event_id": row["id"], **(extra or {})}
    lines = [
        f"# Google カレンダー予定: {action}",
        "",
        "| 項目 | 値 |",
        "|---|---|",
        f"| タイトル | {cell(row['summary'])} |",
        f"| 開始 | {row['start']} |",
        f"| 終了 | {row['end']} |",
        f"| 場所 | {cell(row['location'])} |",
        f"| 状態 | {row['status']} |",
        f"| ツール作成 | {'✓' if row['managed'] else ''} |",
        f"| 主催者が自分 | {'✓' if row['organizer_self'] else ''} |",
        f"| ゲスト数 | {row['guest_count']} |",
        f"| ID | `{row['id']}` |",
        f"| リンク | {row['html_link']} |",
    ]
    if row["description"]:
        lines += ["", "## 説明", "", row["description"]]
    return save_result(kind, fm, lines, {"event": row}, data_dir)


def _preview(label: str, data: dict[str, Any]) -> None:
    print(f"[DRY-RUN] {label}", file=sys.stderr)
    print(json.dumps(data, ensure_ascii=False, indent=2), file=sys.stderr)


def _diff(before: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    return {k: {"before": before.get(k), "after": v} for k, v in patch.items()}


# ----------------------------------------------------------------------
# サブコマンド
# ----------------------------------------------------------------------


def cmd_create(args: argparse.Namespace, service: Any, ctx: EntrypointContext, tz: ZoneInfo) -> dict[str, Any] | None:
    start = parse_local_datetime(args.start, tz)
    end = resolve_end(start, args.end, args.duration, tz)
    body = build_event_body(args.title, start, end, tz, args.location, args.description, args.company_key)
    duplicates = find_duplicates(service, args.calendar, body, tz)
    if duplicates:
        listed = "; ".join(f"{e.get('summary', '')} [{e['id']}]" for e in duplicates)
        if not args.force:
            raise GuardError(f"同じ日に同じ面談らしい予定が既にあります: {listed}。重複でなければ --force を付けてください。")
        ctx.warn(f"同じ日の既存予定を承知のうえで作成します（--force）: {listed}")
    if args.dry_run:
        _preview("予定を作成します（sendUpdates=none）", body)
        return {"dry_run": True, "action": "create", "body": body}
    created = execute(service.events().insert(calendarId=args.calendar, body=body, sendUpdates=SEND_UPDATES))
    row = detail_row(created, tz)
    ctx.add_result_paths(save_event("create", args.calendar, row))
    return {"action": "create", "event": row}


def cmd_get(args: argparse.Namespace, service: Any, ctx: EntrypointContext, tz: ZoneInfo) -> dict[str, Any] | None:
    row = detail_row(get_event(service, args.calendar, args.id), tz)
    ctx.add_result_paths(save_event("get", args.calendar, row))
    return {"action": "get", "event": row}


def cmd_update(args: argparse.Namespace, service: Any, ctx: EntrypointContext, tz: ZoneInfo) -> dict[str, Any] | None:
    event = get_event(service, args.calendar, args.id)
    check_writable(event, args.force)
    patch = build_patch(
        event, tz, args.title, args.start, args.end, args.duration, args.location, args.description, args.company_key
    )
    if not patch:
        raise ValueError("変更する項目を 1 つ以上指定してください（--title / --start / --end / --duration / --location / --description / --company-key）")
    diff = _diff(event, patch)
    if args.dry_run:
        _preview(f"予定 {args.id} を更新します（sendUpdates=none）", diff)
        return {"dry_run": True, "action": "update", "diff": diff}
    ctx.add_result_path(backup_event(event, "update"))
    request = service.events().patch(calendarId=args.calendar, eventId=args.id, body=patch, sendUpdates=SEND_UPDATES)
    updated = execute(_with_if_match(request, event.get("etag")))
    row = detail_row(updated, tz)
    ctx.add_result_paths(save_event("update", args.calendar, row, {"changed": sorted(patch)}))
    return {"action": "update", "event": row, "diff": diff}


def cmd_delete(args: argparse.Namespace, service: Any, ctx: EntrypointContext, tz: ZoneInfo) -> dict[str, Any] | None:
    event = get_event(service, args.calendar, args.id)
    check_writable(event, args.force)
    row = detail_row(event, tz)
    if args.dry_run:
        _preview(f"予定 {args.id} を削除します（sendUpdates=none）", {k: row[k] for k in ("summary", "start", "end", "managed")})
        return {"dry_run": True, "action": "delete", "event": row}
    ctx.add_result_path(backup_event(event, "delete"))
    request = service.events().delete(calendarId=args.calendar, eventId=args.id, sendUpdates=SEND_UPDATES)
    execute(_with_if_match(request, event.get("etag")))
    ctx.add_result_paths(save_event("delete", args.calendar, row))
    return {"action": "delete", "event": row}


COMMANDS = {"create": cmd_create, "get": cmd_get, "update": cmd_update, "delete": cmd_delete}


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-s", "--summary", action="store_true", help="コンソール向け整形サマリ表示（指定しない場合は保存ファイルパスのみ出力）")
    common.add_argument("--json", action="store_true", help="結果をJSON形式で標準出力に出力")
    common.add_argument("--calendar", default="primary", help="カレンダー ID（既定: primary。自分所有のカレンダーだけ書き込める）")
    common.add_argument("--tz", default=DEFAULT_TZ, help=f"日時の解釈と表示のタイムゾーン（既定: {DEFAULT_TZ}）")

    write = argparse.ArgumentParser(add_help=False)
    write.add_argument("--dry-run", action="store_true", help="書き換えず、反映内容を stderr に出すだけ")
    write.add_argument("--force", action="store_true", help="保護解除（create: 同日の重複を承知で作る / update・delete: ツール作成でない予定を扱う）")

    fields = argparse.ArgumentParser(add_help=False)
    fields.add_argument("--location", help="場所・会議 URL（相手から届いた URL を書く。Meet は自動生成しない）")
    fields.add_argument("--description", help="説明（選考の内部情報・本音メモは書かない）")
    fields.add_argument("--company-key", help="vault の company_key（予定から企業ログを逆引きする目印）")
    fields.add_argument("--end", help="終了日時 'YYYY-MM-DD HH:MM'（--duration と排他）")
    fields.add_argument("--duration", type=int, help=f"所要時間（分。--end と排他。create の既定: {DEFAULT_DURATION}）")

    parser = argparse.ArgumentParser(
        description="Google カレンダーの予定を作成・参照・更新・削除する（招待メールは送らない。変更前バックアップ付き）",
        epilog=build_epilog(
            examples=[
                'uv run python scripts/gcal/manage_events.py create --title "【面談】<会社名> カジュアル面談" --start "2026-11-04 15:00" --duration 45 --company-key <company-key> --dry-run',
                'uv run python scripts/gcal/manage_events.py update --id <event-id> --start "2026-11-05 11:00" --summary  # リスケ',
                "uv run python scripts/gcal/manage_events.py delete --id <event-id> --summary",
            ],
            related=[
                "scripts/gcal/find_slots.py: 前に使う（候補日を出す）",
                "scripts/gcal/list_events.py: 前に使う（--job-only で更新・削除する予定 ID を調べる）",
            ],
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create", parents=[common, write, fields], help="予定を作成（目印付き）")
    p.add_argument("--title", required=True, help="タイトル（例: 【面談】株式会社〇〇 カジュアル面談）")
    p.add_argument("--start", required=True, help="開始日時 'YYYY-MM-DD HH:MM'（--tz の現地時刻）")

    p = sub.add_parser("get", parents=[common], help="予定を 1 件取得して保存")
    p.add_argument("--id", required=True, help="予定 ID")

    p = sub.add_parser("update", parents=[common, write, fields], help="指定した項目だけ更新（リスケ等）")
    p.add_argument("--id", required=True, help="予定 ID")
    p.add_argument("--title", help="新しいタイトル")
    p.add_argument("--start", help="新しい開始日時 'YYYY-MM-DD HH:MM'（終了を指定しなければ元の所要時間を保つ）")

    p = sub.add_parser("delete", parents=[common, write], help="予定を削除")
    p.add_argument("--id", required=True, help="予定 ID")
    return parser


def main() -> int:
    from googleapiclient.errors import HttpError

    args = build_parser().parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        result: dict[str, Any] | None = None
        tz = load_tz(args.tz)
        try:
            result = COMMANDS[args.command](args, build_service(), ctx, tz)
        except GoogleAuthError as e:
            ctx.error(e.handoff_message())
            ctx.set_exit_code(2)
        except GuardError as e:
            ctx.error(f"[安全ガード] {e}")
            ctx.set_exit_code(1)
        except HttpError as e:
            status = e.resp.status
            if status == 412:
                ctx.error("予定が取得後に他所で変更されました（412 conditionNotMet）。get で最新を確認してからやり直してください。")
            elif status == 404:
                ctx.error(f"予定が見つかりません（404）。ID と --calendar を確認してください: {getattr(args, 'id', '')}")
            elif status == 410:
                ctx.error("予定は既に削除されています（410）。")
            elif status == 403:
                ctx.error("このカレンダーには書き込めません（403）。書き込めるのは access_role が owner のカレンダーだけです。")
            else:
                raise
            ctx.set_exit_code(1)

        def print_summary() -> None:
            if not result:
                return
            if result.get("dry_run"):
                print(f"[DRY-RUN] {result['action']}: 書き換えていません（内容は stderr）")
                return
            r = result["event"]
            verb = {"create": "作成", "get": "取得", "update": "更新", "delete": "削除"}[result["action"]]
            print(f"{verb}: {r['start'][:16]}〜{r['end'][11:16]} | {r['summary']} [{r['id']}]")
            if r["html_link"] and result["action"] != "delete":
                print(f"リンク: {r['html_link']}")
            for p in ctx.result_paths:
                print(f"保存: {p}")

        return ctx.flush_outputs(summary_fn=print_summary, json_data=result)


if __name__ == "__main__":
    sys.exit(main())
