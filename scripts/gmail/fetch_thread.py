"""Gmail のスレッド本文を ID 指定で取得して保存する CLI（読み取り専用）.

Gmail スレッド取得 CLI.

スレッド ID を指定して、スレッド内の全メッセージの本文を data/gmail/threads/{thread_id}.md に保存する。
保存済みのスレッドはメッセージ数が増えていなければ取り直さない（--force で強制）。
JOB ラベル（scripts/gmail/labels.py）が付いていないスレッドは取得しない。

- stdout: 保存した（または最新のまま残した）スレッドファイルのパス
- 終了コード: 0 正常 / 1 エラー / 2 未認可・トークン失効（ユーザーの再認可が必要）
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

# プロジェクトルートパス (scripts/gmail/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import EntrypointContext, create_base_parser, entrypoint_guard, to_relative_path
from scripts.gmail.client import GoogleAuthError, build_service, execute
from scripts.gmail.labels import fetch_label_names, has_job_label, label_names_of
from scripts.gmail.mime import ParsedMessage, parse_raw

DATA_DIR = PROJECT_ROOT / "data" / "gmail"
METADATA_HEADERS = ["From", "To", "Cc", "Subject", "Date"]


class OutOfScopeError(Exception):
    """JOB ラベルが付いていないスレッド（このリポジトリでは読まない）."""


def threads_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / "threads"


def thread_path(thread_id: str, data_dir: Path | None = None) -> Path:
    return threads_dir(data_dir) / f"{thread_id}.md"


def thread_url(thread_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#all/{thread_id}"


def internal_date_iso(internal_date: Any) -> str:
    """internalDate（エポックミリ秒の文字列）をローカルタイムの ISO 8601 にする."""
    return datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC).astimezone().isoformat(timespec="seconds")


def read_saved_message_count(path: Path) -> int | None:
    """保存済みスレッドファイルのフロントマターから message_count を読む."""
    try:
        text = path.read_text(encoding="utf-8")
        _, fm, _ = text.split("---", 2)
        return int(yaml.safe_load(fm)["message_count"])
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
        return None


def _unique(values: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for v in values:
        if v and v not in seen:
            seen[v] = None
    return list(seen)


def render_thread(
    thread_id: str,
    messages: list[dict[str, Any]],
    parsed: list[ParsedMessage],
    label_names: dict[str, str] | None = None,
) -> str:
    """スレッドを Markdown にする. messages は threads.get(metadata) の各メッセージ、parsed は同順の本文."""
    dates = [internal_date_iso(m["internalDate"]) for m in messages]
    subject = next((p.subject for p in parsed if p.subject), "") or "（件名なし）"
    labels = label_names_of([label for m in messages for label in m.get("labelIds", [])], label_names or {})
    participants = _unique([addr for p in parsed for addr in [p.from_, *p.to, *p.cc]])

    fm = {
        "id": thread_id,
        "source": "gmail",
        "type": "thread",
        "subject": subject,
        "participants": participants,
        "first_date": dates[0] if dates else "",
        "last_date": dates[-1] if dates else "",
        "message_count": len(messages),
        "labels": labels,
        "url": thread_url(thread_id),
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    fm_yaml = yaml.dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False).strip()

    lines = [f"# {subject}", ""]
    for idx, (meta, date, p) in enumerate(zip(messages, dates, parsed, strict=True), start=1):
        lines.append(f"## {idx}. {date} — {p.from_ or '（差出人不明）'}")
        lines.append("")
        lines.append(f"- **Message-ID (Gmail)**: {meta['id']}")
        if p.to:
            lines.append(f"- **To**: {', '.join(p.to)}")
        if p.cc:
            lines.append(f"- **Cc**: {', '.join(p.cc)}")
        if p.subject and p.subject != subject:
            lines.append(f"- **件名**: {p.subject}")
        if p.attachments:
            files = ", ".join(f"{a.filename} ({a.content_type}, {a.size:,} bytes)" for a in p.attachments)
            lines.append(f"- **添付（未保存）**: {files}")
        if p.body_type == "text/html":
            lines.append("- **本文形式**: HTML をテキスト化")
        lines.append("")
        lines.append(p.body or "（本文なし）")
        lines.append("")

    return f"---\n{fm_yaml}\n---\n\n" + "\n".join(lines).rstrip() + "\n"


def fetch_and_save_thread(
    service: Any,
    thread_id: str,
    force: bool = False,
    ctx: EntrypointContext | None = None,
    data_dir: Path | None = None,
    label_names: dict[str, str] | None = None,
) -> tuple[Path, bool]:
    """スレッドを取得して保存する. 戻り値: (パス, 取得・書き込みを行ったか).

    JOB ラベルの付いたメッセージが 1 通も無いスレッドは OutOfScopeError にする（本文は取らない）。
    """
    if label_names is None:
        label_names = fetch_label_names(service)
    meta = execute(
        service.users().threads().get(userId="me", id=thread_id, format="metadata", metadataHeaders=METADATA_HEADERS)
    )
    messages = sorted(meta.get("messages", []), key=lambda m: int(m.get("internalDate", 0)))
    if not has_job_label([label for m in messages for label in m.get("labelIds", [])], label_names):
        raise OutOfScopeError(f"{thread_id}: JOB ラベルが付いていないため取得しません（Gmail でラベルを付けてください）。")
    path = thread_path(thread_id, data_dir)

    if path.exists() and not force and read_saved_message_count(path) == len(messages):
        if ctx:
            ctx.log(f"[スキップ] {thread_id}: 保存済み（{len(messages)} 通、増加なし）")
        return path, False

    parsed = []
    for m in messages:
        raw = execute(service.users().messages().get(userId="me", id=m["id"], format="raw"))
        parsed.append(parse_raw(raw["raw"]))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_thread(thread_id, messages, parsed, label_names), encoding="utf-8")
    if ctx:
        ctx.log(f"[保存] {thread_id}: {len(messages)} 通 → {to_relative_path(path)}")
    return path, True


def main() -> int:
    parser = create_base_parser(
        description="Gmail のスレッドを取得して data/gmail/threads/ に保存する（読み取り専用）",
        examples=[
            "uv run python scripts/gmail/fetch_thread.py --thread-id <thread-id>",
            "uv run python scripts/gmail/fetch_thread.py --thread-id <thread-id-1> <thread-id-2> --force  # 保存済みでも取り直す",
        ],
        related=[
            "scripts/gmail/search_messages.py: 前に使う（スレッド ID を探す）",
        ],
    )
    parser.add_argument(
        "--thread-id",
        dest="thread_ids",
        nargs="+",
        action="extend",
        required=True,
        help="取得するスレッド ID（複数可。search_messages.py の結果や Gmail の URL 末尾の ID）",
    )
    args = parser.parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        results: list[dict[str, Any]] = []
        try:
            service = build_service()
            label_names = fetch_label_names(service)
            for thread_id in _unique(args.thread_ids)[: args.limit or None]:
                try:
                    path, updated = fetch_and_save_thread(
                        service, thread_id, force=args.force, ctx=ctx, label_names=label_names
                    )
                except OutOfScopeError as e:
                    ctx.error(str(e))
                    ctx.set_exit_code(1)
                    continue
                ctx.add_result_path(path)
                results.append({"thread_id": thread_id, "path": to_relative_path(path), "updated": updated})
        except GoogleAuthError as e:
            ctx.error(e.handoff_message())
            ctx.set_exit_code(2)

        def print_summary() -> None:
            for r in results:
                print(f"- {r['path']}（{'更新' if r['updated'] else '変更なし'}）")

        return ctx.flush_outputs(summary_fn=print_summary, json_data={"threads": results})


if __name__ == "__main__":
    sys.exit(main())
