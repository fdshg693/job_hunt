"""Gmail を JOB ラベル配下で検索し、ヒット一覧を保存する CLI（読み取り専用）.

Gmail 検索 CLI（読み取り専用）.

Gmail の検索構文（`from:` `subject:` `newer_than:` 等）でメールを検索し、ヒットしたスレッドの一覧を
data/gmail/searches/YYYY-MM-DD-HHmmss_{slug}.md（＋同名 .json）に保存する。
--download を付けると、ヒットしたスレッドの本文も data/gmail/threads/ に保存する。
検索範囲は常に JOB ラベル配下（--label で分類ラベル配下）に限る。ラベル規則の正本は scripts/gmail/labels.py。

- stdout: 検索結果ファイル（.md / .json）と、--download 時は各スレッドファイルのパス
- 終了コード: 0 正常 / 1 エラー（JOB ラベルが無い等） / 2 未認可・トークン失効（ユーザーの再認可が必要）
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

# プロジェクトルートパス (scripts/gmail/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import EntrypointContext, create_base_parser, entrypoint_guard, to_relative_path
from scripts.common.storage import sanitize_filename
from scripts.gmail.client import GoogleAuthError, build_service, execute
from scripts.gmail.fetch_thread import (
    DATA_DIR,
    OutOfScopeError,
    fetch_and_save_thread,
    internal_date_iso,
    thread_path,
    thread_url,
)
from scripts.gmail.labels import CATEGORIES, LabelSetupError, fetch_label_names, label_names_of, scope_query
from scripts.gmail.mime import decode_header_value

DEFAULT_LIMIT = 20
LIST_PAGE_MAX = 500  # messages.list の maxResults 上限
SLUG_MAX_LEN = 40
_SINCE_RE = re.compile(r"^\d+[dmy]$")


def build_query(query: str | None, since: str | None) -> str:
    """--query と --since（newer_than: の省略形）を 1 つの Gmail 検索クエリにする（どちらも無ければ空）."""
    parts = []
    if query and query.strip():
        parts.append(query.strip())
    if since:
        if not _SINCE_RE.match(since):
            raise ValueError(f"--since は 7d / 2m / 1y の形式で指定してください: {since}")
        parts.append(f"newer_than:{since}")
    return " ".join(parts)


def scoped_query(scope: str, query: str) -> str:
    """ラベルの範囲とユーザーのクエリを AND にする（クエリ内の OR で範囲から漏れないよう括弧で包む）."""
    return f"{scope} ({query})" if query else scope


def list_thread_hits(service: Any, query: str, limit: int) -> tuple[list[dict[str, Any]], int]:
    """messages.list をページングし、新しい順に最大 limit スレッド分の (最新ヒットの message id, 件数) を集める.

    戻り値: ([{thread_id, message_id, hit_count}], resultSizeEstimate)
    """
    hits: dict[str, dict[str, Any]] = {}
    page_token = None
    estimate = 0
    while True:
        resp = execute(
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=min(LIST_PAGE_MAX, max(limit, 100)), pageToken=page_token)
        )
        if page_token is None:
            estimate = int(resp.get("resultSizeEstimate", 0))
        for m in resp.get("messages", []):
            tid = m["threadId"]
            if tid in hits:
                hits[tid]["hit_count"] += 1
            elif len(hits) < limit:
                hits[tid] = {"thread_id": tid, "message_id": m["id"], "hit_count": 1}
        page_token = resp.get("nextPageToken")
        # limit スレッドに達したら打ち切る（以降のページは同じスレッドの古いメッセージかもしれないが追わない）
        if not page_token or len(hits) >= limit:
            break
    return list(hits.values()), estimate


def describe_hit(
    service: Any, hit: dict[str, Any], label_names: dict[str, str], data_dir: Path | None = None
) -> dict[str, Any]:
    """ヒットしたメッセージのヘッダ（format=metadata）から一覧の 1 行を作る."""
    msg = execute(
        service.users()
        .messages()
        .get(userId="me", id=hit["message_id"], format="metadata", metadataHeaders=["From", "Subject", "Date"])
    )
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    path = thread_path(hit["thread_id"], data_dir)
    return {
        "thread_id": hit["thread_id"],
        "message_id": hit["message_id"],
        "hit_count": hit["hit_count"],
        "subject": decode_header_value(headers.get("subject")) or "（件名なし）",
        "from": decode_header_value(headers.get("from")),
        "date": internal_date_iso(msg["internalDate"]) if msg.get("internalDate") else "",
        "snippet": msg.get("snippet", ""),
        "labels": label_names_of(msg.get("labelIds", []), label_names),
        "url": thread_url(hit["thread_id"]),
        "saved_path": to_relative_path(path) if path.exists() else "",
    }


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def save_search(
    query: str,
    label: str | None,
    gmail_query: str,
    rows: list[dict[str, Any]],
    estimate: int,
    data_dir: Path | None = None,
) -> tuple[Path, Path]:
    """検索結果一覧を Markdown と JSON で保存する."""
    now = datetime.now().astimezone()
    target = (data_dir or DATA_DIR) / "searches"
    target.mkdir(parents=True, exist_ok=True)
    slug = sanitize_filename(" ".join(filter(None, [label, query])))[:SLUG_MAX_LEN].strip("_") or "all"
    base = f"{now:%Y-%m-%d-%H%M%S}_{slug}"
    md_path = target / f"{base}.md"
    json_path = target / f"{base}.json"

    fm = {
        "source": "gmail",
        "type": "searches",
        "query": query,
        "label": label or "all",
        "gmail_query": gmail_query,
        "result_size_estimate": estimate,
        "thread_count": len(rows),
        "fetched_at": now.isoformat(timespec="seconds"),
    }
    lines = [
        f"# Gmail 検索結果: {query or '（条件なし）'}",
        "",
        f"- 取得日時: {now:%Y-%m-%d %H:%M:%S}",
        f"- ラベル範囲: {label or 'all'}（`{gmail_query}`）",
        f"- スレッド数: {len(rows)} 件（ヒットしたメッセージの概算: {estimate} 件）",
        "",
        "## スレッド一覧（新しい順）",
        "",
        "| No | 日時 | From | 件名 | ヒット数 | 保存先 |",
        "|---|---|---|---|---|---|",
    ]
    for idx, r in enumerate(rows, start=1):
        saved = f"[{Path(r['saved_path']).name}]({r['saved_path']})" if r["saved_path"] else "未保存"
        lines.append(
            f"| {idx} | {r['date']} | {_cell(r['from'])} | {_cell(r['subject'])} | {r['hit_count']} | {saved} |"
        )
    lines += ["", "## 詳細", ""]
    for idx, r in enumerate(rows, start=1):
        lines += [
            f"### {idx}. {r['subject']}",
            f"- **thread_id**: {r['thread_id']}",
            f"- **From**: {r['from']}",
            f"- **日時**: {r['date']}",
            f"- **ラベル**: {', '.join(r['labels'])}",
            f"- **snippet**: {r['snippet']}",
            f"- **Gmail**: {r['url']}",
            "",
        ]

    fm_yaml = yaml.dump(fm, allow_unicode=True, sort_keys=False).strip()
    md_path.write_text(f"---\n{fm_yaml}\n---\n\n" + "\n".join(lines).rstrip() + "\n", encoding="utf-8")
    json_path.write_text(json.dumps({**fm, "threads": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path, json_path


def run_search(
    service: Any,
    query: str,
    limit: int,
    label: str | None = None,
    download: bool = False,
    force: bool = False,
    ctx: EntrypointContext | None = None,
    data_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], list[Path]]:
    """JOB ラベル配下（label 指定時はその分類ラベル配下）を検索し、一覧（と --download 時はスレッド本文）を保存する.

    戻り値: (一覧の行, 保存したファイルパス)。
    """
    label_names = fetch_label_names(service)
    gmail_query = scoped_query(scope_query(label_names, label), query)
    hits, estimate = list_thread_hits(service, gmail_query, limit)
    if ctx:
        ctx.log(f"[検索] {gmail_query} → {len(hits)} スレッド（ヒット概算 {estimate} 件）")

    paths: list[Path] = []
    thread_paths: list[Path] = []
    if download:
        for hit in hits:
            try:
                path, _ = fetch_and_save_thread(
                    service, hit["thread_id"], force=force, ctx=ctx, data_dir=data_dir, label_names=label_names
                )
            except OutOfScopeError as e:
                if ctx:
                    ctx.log(f"[スキップ] {e}")
                continue
            thread_paths.append(path)

    # 保存先パスを一覧に載せるため、本文の保存後に一覧を作る
    rows = [describe_hit(service, hit, label_names, data_dir) for hit in hits]
    md_path, json_path = save_search(query, label, gmail_query, rows, estimate, data_dir)
    paths += [md_path, json_path, *thread_paths]
    return rows, paths


def main() -> int:
    parser = create_base_parser(
        description="Gmail を検索し、ヒットしたスレッド一覧を data/gmail/searches/ に保存する（読み取り専用）",
        default_limit=DEFAULT_LIMIT,
        examples=[
            "uv run python scripts/gmail/search_messages.py --since 14d --summary",
            "uv run python scripts/gmail/search_messages.py --label schedule --since 7d --download -n 5  # 本文も保存",
            'uv run python scripts/gmail/search_messages.py --label recruiter -q "from:example.co.jp" -n 10 --summary',
        ],
        related=[
            "scripts/google/auth.py: 前に使う（--check でトークンを確かめる）",
            "scripts/gmail/fetch_thread.py: 次に使う（個別スレッドの本文を取る）",
        ],
    )
    parser.add_argument("-q", "--query", help='Gmail の検索構文をそのまま渡す（例: "from:bizreach.jp 面談"）')
    parser.add_argument("--since", help="newer_than: の省略形（例: 7d / 2m / 1y）")
    parser.add_argument(
        "-l",
        "--label",
        choices=sorted(CATEGORIES),
        help="分類ラベル配下に絞る（"
        + " / ".join(f"{k}: {name}" for k, (name, _) in CATEGORIES.items())
        + "）。省略時は JOB 配下すべて",
    )
    parser.add_argument(
        "-d",
        "--download",
        action="store_true",
        help="ヒットしたスレッドの本文も data/gmail/threads/ に保存する",
    )
    args = parser.parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        rows: list[dict[str, Any]] = []
        query = build_query(args.query, args.since)
        try:
            service = build_service()
            rows, paths = run_search(
                service,
                query,
                args.limit or DEFAULT_LIMIT,
                label=args.label,
                download=args.download,
                force=args.force,
                ctx=ctx,
            )
            ctx.add_result_paths(paths)
        except GoogleAuthError as e:
            ctx.error(e.handoff_message())
            ctx.set_exit_code(2)
        except LabelSetupError as e:
            ctx.error(str(e))
            ctx.set_exit_code(1)

        def print_summary() -> None:
            for r in rows:
                saved = f" → {r['saved_path']}" if r["saved_path"] else ""
                print(f"- {r['date'][:16]} | {r['from']} | {r['subject']} [{r['thread_id']}]{saved}")
            for p in ctx.result_paths[:2]:
                print(f"保存: {p}")

        return ctx.flush_outputs(summary_fn=print_summary, json_data={"query": query, "label": args.label or "all", "threads": rows})


if __name__ == "__main__":
    sys.exit(main())
