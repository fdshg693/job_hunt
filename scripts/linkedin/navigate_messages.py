"""LinkedIn のメッセージ会話一覧（任意でスレッド本文）を取得・保存する CLI.

LinkedIn メッセージ（会話一覧・スレッド本文）自動取得スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
LinkedInのログイン状態確認・未ログイン時の通知待機ハンドオフ・メッセージ画面（/messaging/）からの
会話一覧抽出（ステータス・サブフィルタ対応、内部スクロールによる遅延読込対応）・任意でスレッド本文取得・
構造化フロントマター付きMarkdownおよびJSON形式での永続化を実行します。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/linkedin/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.browser_auth import run_code_snippet
from scripts.common.crawlers.message_pipeline import (
    MessageCrawlerConfig,
    MessagePipelineContext,
    generate_message_markdown,
    print_message_summary,
    run_message_pipeline,
    save_message_batch,
)
from scripts.common.models.message import MessageBatch, MessageItem

LINKEDIN_SCRIPTS_DIR = Path(__file__).resolve().parent
NAVIGATE_SCRIPT_PATH = LINKEDIN_SCRIPTS_DIR / "navigate_messages.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "linkedin" / "messages"
BASE_URL = "https://www.linkedin.com/messaging/"

STATUS_CHOICES = ["Focused", "Other", "Archived", "Spam"]
FILTER_CHOICES = ["all", "Jobs", "Unread", "Connections", "InMail", "Starred"]


def build_messaging_url(status: str = "Focused", filter_name: str = "all") -> str:
    """ステータスおよびサブフィルタから LinkedIn メッセージ URL を生成する."""
    st = status.strip().lower()
    ft = filter_name.strip().lower()

    if st == "archived":
        return f"{BASE_URL}?filter=archived"
    if st in ("spam", "blocked"):
        return f"{BASE_URL}?filter=blocked"

    filter_param_map = {
        "all": None,
        "jobs": "job",
        "job": "job",
        "unread": "unread",
        "connections": "connections",
        "inmail": "inmail",
        "starred": "starred",
    }

    query_parts: list[str] = []

    if ft in filter_param_map and filter_param_map[ft] is not None:
        query_parts.append(f"filter={filter_param_map[ft]}")
    elif ft not in ("all", ""):
        query_parts.append(f"filter={ft}")

    if st == "other":
        query_parts.append("inboxType=SECONDARY")

    if query_parts:
        return f"{BASE_URL}?{'&'.join(query_parts)}"
    return BASE_URL


def execute_navigate_messages(
    session: str,
    target_url: str,
    status: str = "Focused",
    filter_name: str = "all",
    limit: int = 0,
    fetch_threads: bool = False,
    timeout: float = 180.0,
) -> dict[str, Any]:
    """navigate_messages.mjs にパラメータを注入して実行する."""
    if not NAVIGATE_SCRIPT_PATH.exists():
        raise RuntimeError(f"メッセージスクリプトが見つかりません: {NAVIGATE_SCRIPT_PATH}")

    template_code = NAVIGATE_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = (
        template_code.replace("__TARGET_URL__", target_url)
        .replace("__LI_STATUS__", status)
        .replace("__LI_FILTER__", filter_name)
        .replace("__FETCH_THREADS__", "true" if fetch_threads else "false")
        .replace("__LIMIT__", str(limit))
    ).strip().rstrip(";")

    result = run_code_snippet(session, run_code, timeout=timeout)
    if not result:
        raise RuntimeError("Playwrightスクリプトの実行に失敗しました")
    return result


def _parse_item(item_dict: dict[str, Any]) -> MessageItem:
    sender = item_dict.get("name") or item_dict.get("sender") or ""
    unread = bool(item_dict.get("unread") or item_dict.get("is_unread") or False)
    scout_type = item_dict.get("label") or item_dict.get("scout_type") or "通常"
    return MessageItem.model_validate({
        **item_dict,
        "sender": sender,
        "is_unread": unread,
        "scout_type": scout_type,
    })


def _custom_fetch(ctx: MessagePipelineContext) -> dict[str, Any]:
    selected_status = getattr(ctx.args, "status", "Focused")
    selected_filter = getattr(ctx.args, "filter", "all")
    if ctx.args.tab and ctx.args.tab != "all" and ctx.args.tab in STATUS_CHOICES:
        selected_status = ctx.args.tab

    if selected_filter in STATUS_CHOICES:
        if selected_status == "Focused":
            selected_status = selected_filter
            selected_filter = "all"
        else:
            raise ValueError(f"--filter にステータス名 '{selected_filter}' が指定されています。--status を使用してください。")

    if selected_status in ("Archived", "Spam") and selected_filter != "all":
        raise ValueError(f"ステータス '{selected_status}' ではサブフィルタ (--filter) を指定できません。")

    target_url = build_messaging_url(selected_status, selected_filter)
    ctx.target_url = target_url
    slug = (
        f"{selected_status.lower()}_{selected_filter.lower()}"
        if selected_status in ("Focused", "Other") and selected_filter != "all"
        else selected_status.lower()
    )
    ctx.tab = slug
    filter_info = f"ステータス: {selected_status}"
    if selected_status in ("Focused", "Other") and selected_filter != "all":
        filter_info += f" / フィルタ: {selected_filter}"
    ctx.tab_label = filter_info

    fetch_threads = getattr(ctx.args, "threads", False)
    run_timeout = 180.0 + (ctx.args.limit or 30) * 8 if fetch_threads else 180.0

    return execute_navigate_messages(
        session=ctx.session,
        target_url=target_url,
        status=selected_status,
        filter_name=selected_filter,
        limit=ctx.args.limit or 0,
        fetch_threads=fetch_threads,
        timeout=run_timeout,
    )


def _format_summary_item(msg: MessageItem, idx: int) -> list[str]:
    flags = []
    if msg.is_unread:
        flags.append("未読")
    if msg.extra_metadata.get("starred"):
        flags.append("★")
    label = msg.extra_metadata.get("label") or (msg.scout_type if msg.scout_type != "通常" else "")
    if label:
        flags.append(label)
    flag_str = " ".join(f"[{f}]" for f in flags)
    name = msg.sender or msg.company or "名前不明"
    date_str = msg.date or "-"
    lines = [f"[{idx}] {flag_str} {name}  ({date_str})"]
    if msg.snippet:
        lines.append(f"    抜粋:     {msg.snippet[:120]}")
    if msg.url:
        lines.append(f"    スレッド: {msg.url}")
    thread = msg.extra_metadata.get("thread") or []
    if thread:
        lines.append(f"    本文:     {len(thread)} メッセージ取得")
    lines.append("-" * 56)
    return lines


def _markdown_table_row(msg: MessageItem, idx: int) -> list[str]:
    name = msg.sender or msg.company or "名前不明"
    snippet = (msg.snippet or "-")[:80]
    msg_label = msg.extra_metadata.get("label") or (msg.scout_type if msg.scout_type != "通常" else "-")
    unread = "●" if msg.is_unread else "-"
    starred = "★" if msg.extra_metadata.get("starred") else "-"
    date_str = msg.date or "-"
    return [str(idx), unread, starred, msg_label, name, date_str, snippet]


def _markdown_detail_item(msg: MessageItem, idx: int) -> list[str]:
    name = msg.sender or msg.company or "名前不明"
    lines = [
        f"### {idx}. {name}",
        "",
        f"- **日付**: {msg.date or '-'}",
    ]
    label = msg.extra_metadata.get("label") or msg.scout_type
    if label and label != "通常":
        lines.append(f"- **種別**: {label}")
    lines.append(f"- **未読**: {'はい' if msg.is_unread else 'いいえ'}")
    lines.append(f"- **スター**: {'はい' if msg.extra_metadata.get('starred') else 'いいえ'}")
    if msg.url:
        lines.append(f"- **スレッドURL**: {msg.url}")
    lines.append("")

    thread = msg.extra_metadata.get("thread") or []
    if thread:
        lines.append("#### スレッド本文")
        lines.append("")
        for t in thread:
            when = " ".join(x for x in [t.get("day"), t.get("time")] if x)
            lines.append(f"**{t.get('sender') or '不明'}** ({when or '-'})")
            lines.append("")
            lines.append("```text")
            lines.append(t.get("text", ""))
            lines.append("```")
            lines.append("")
    elif msg.snippet:
        lines.append(f"> **抜粋**: {msg.snippet}")
        lines.append("")
    return lines


def _setup_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--status",
        choices=STATUS_CHOICES,
        default="Focused",
        help="メッセージステータス (Focused[デフォルト], Other, Archived, Spam)",
    )
    parser.add_argument(
        "--filter",
        choices=FILTER_CHOICES + ["Focused", "Other", "Archived", "Spam"],
        default="all",
        help="サブフィルタ (all[デフォルト], Jobs, Unread, Connections, InMail, Starred) ※Focused / Other 時のみ有効",
    )
    parser.add_argument(
        "--threads",
        action="store_true",
        help="各会話を開いてスレッド本文も取得する（既読副作用あり・低速。-n で件数を絞ることを推奨）",
    )


CONFIG = MessageCrawlerConfig(
    site_id="linkedin",
    site_name="LinkedIn",
    auth_site="linkedin",
    default_output_dir=DEFAULT_OUTPUT_DIR,
    tab_url_map={"Focused": BASE_URL},
    default_tab="Focused",
    save_mode="latest_and_history",
    custom_fetch_fn=_custom_fetch,
    parse_item_fn=_parse_item,
    summary_item_formatter=_format_summary_item,
    markdown_table_columns=["#", "未読", "スター", "種別", "相手", "日付", "抜粋"],
    markdown_table_row_fn=_markdown_table_row,
    markdown_detail_item_fn=_markdown_detail_item,
    setup_args_fn=_setup_args,
    examples=[
        "uv run python scripts/linkedin/navigate_messages.py -n 5 --summary",
        "uv run python scripts/linkedin/navigate_messages.py --status Other --filter Jobs --summary",
        "uv run python scripts/linkedin/navigate_messages.py -n 3 --threads  # スレッド本文も取得（既読になる）",
    ],
    related=[
        "scripts/linkedin/evaluate_messages.py: 次に使う（Other の取得結果を事前仕分けする）",
        "scripts/linkedin/fetch_single_thread.py: 次に使う（特定スレッドだけ本文を取る）",
    ],
)


def print_formatted_summary(data: dict[str, Any] | MessageBatch, status: str = "Focused", filter_name: str = "all") -> None:
    """メッセージ一覧のサマリをコンソールに整形出力する（後方互換用）."""
    if isinstance(data, dict) and "source" not in data:
        data = {**data, "source": "linkedin"}
    batch = MessageBatch.model_validate(data) if not isinstance(data, MessageBatch) else data
    slug = f"{status.lower()}_{filter_name.lower()}" if status in ("Focused", "Other") and filter_name != "all" else status.lower()
    batch.tab = slug
    filter_info = f"ステータス: {status}"
    if status in ("Focused", "Other") and filter_name != "all":
        filter_info += f" / フィルタ: {filter_name}"
    batch.tab_label = filter_info
    print_message_summary(batch, CONFIG)


def generate_markdown(data: dict[str, Any] | MessageBatch, status: str, filter_name: str, now: datetime) -> str:
    """メッセージ一覧を構造化フロントマター付きMarkdownに整形する（後方互換用）."""
    if isinstance(data, dict) and "source" not in data:
        data = {**data, "source": "linkedin"}
    batch = MessageBatch.model_validate(data) if not isinstance(data, MessageBatch) else data
    slug = f"{status.lower()}_{filter_name.lower()}" if status in ("Focused", "Other") and filter_name != "all" else status.lower()
    batch.tab = slug
    filter_info = f"ステータス: {status}"
    if status in ("Focused", "Other") and filter_name != "all":
        filter_info += f" / フィルタ: {filter_name}"
    batch.tab_label = filter_info
    batch.source = "linkedin"
    return generate_message_markdown(batch, CONFIG, now)


def save_messages_result(
    data: dict[str, Any] | MessageBatch,
    status: str = "Focused",
    filter_name: str = "all",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    now: datetime | None = None,
) -> list[Path]:
    """メッセージデータを latest と履歴（Markdown / JSON）として保存する（後方互換用）."""
    if now is None:
        now = datetime.now()
    if isinstance(data, dict) and "source" not in data:
        data = {**data, "source": "linkedin"}
    batch = MessageBatch.model_validate(data) if not isinstance(data, MessageBatch) else data
    slug = f"{status.lower()}_{filter_name.lower()}" if status in ("Focused", "Other") and filter_name != "all" else status.lower()
    batch.tab = slug
    filter_info = f"ステータス: {status}"
    if status in ("Focused", "Other") and filter_name != "all":
        filter_info += f" / フィルタ: {filter_name}"
    batch.tab_label = filter_info
    batch.source = "linkedin"

    from types import SimpleNamespace
    ctx = MessagePipelineContext(
        config=CONFIG,
        args=SimpleNamespace(output_dir=output_dir, force=False, no_save=False),  # type: ignore
        entrypoint_ctx=None,  # type: ignore
        tab=slug,
        tab_label=batch.tab_label,
        target_url=batch.url or BASE_URL,
        session="job-hunt",
        profile_dir=output_dir,
        now=now,
    )
    return save_message_batch(batch, ctx)


def main() -> None:
    """CLIエントリポイント."""
    sys.exit(run_message_pipeline(CONFIG))


if __name__ == "__main__":
    main()
