"""Findy のメッセージ・スカウト一覧を取得して保存する CLI.

Findy メッセージ・スカウト自動取得スクリプト.
リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
Findyのログイン状態確認・未ログイン時の通知待機ハンドオフ・メッセージ一覧画面からのスカウト/メッセージ抽出を実行します。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/findy/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.crawlers.message_pipeline import (
    MessageCrawlerConfig,
    MessagePipelineContext,
    generate_message_markdown,
    print_message_summary,
    run_message_pipeline,
    save_message_batch,
)
from scripts.common.models.message import MessageBatch, MessageItem

FINDY_SCRIPTS_DIR = Path(__file__).resolve().parent
NAVIGATE_SCRIPT_PATH = FINDY_SCRIPTS_DIR / "navigate_messages.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "findy" / "messages"

TAB_URL_MAP = {
    "all": "https://findy-code.io/matches",
    "unread": "https://findy-code.io/matches?tab=unread",
    "unreplied": "https://findy-code.io/matches?tab=unreplied",
    "archived": "https://findy-code.io/matches?tab=archived",
}

TAB_LABEL_MAP = {
    "all": "すべて",
    "unread": "未読",
    "unreplied": "未返信",
    "archived": "非表示（アーカイブ）",
}


def _format_summary_item(msg: MessageItem, idx: int) -> list[str]:
    type_badge = f"[{msg.scout_type or '通常'}]"
    unread_badge = "[未読] " if msg.is_unread else ""
    is_replied = msg.extra_metadata.get("isReplied", False)
    replied_badge = "[返信済] " if is_replied else "[未返信] "
    lines = [
        f"[{idx}] {unread_badge}{replied_badge}{type_badge} {msg.company or '企業名不明'}",
        f"    件名:     {msg.subject or '（件名なし）'}",
    ]
    if msg.date:
        lines.append(f"    日時:     {msg.date}")
    if msg.url:
        lines.append(f"    スレッド: {msg.url}")
    if msg.job_url:
        lines.append(f"    求人URL:  {msg.job_url}")
    if msg.snippet:
        lines.append(f"    抜粋:     {msg.snippet[:100]}...")
    lines.append("-" * 56)
    return lines


def _markdown_table_row(msg: MessageItem, idx: int) -> list[str]:
    status = "未読" if msg.is_unread else "既読"
    is_replied = msg.extra_metadata.get("isReplied", False)
    replied = "返信済" if is_replied else "未返信"
    scout_type = msg.scout_type or "通常"
    company = msg.company or "企業名不明"
    subject = msg.subject or "（件名なし）"
    date_str = msg.date or "-"
    link = f"[スレッド]({msg.url})" if msg.url else "-"
    return [str(idx), status, replied, scout_type, company, subject, date_str, link]


def _markdown_detail_item(msg: MessageItem, idx: int) -> list[str]:
    status = "未読" if msg.is_unread else "既読"
    is_replied = msg.extra_metadata.get("isReplied", False)
    replied = "返信済" if is_replied else "未返信"
    company = msg.company or "企業名不明"
    subject = msg.subject or "（件名なし）"
    lines = [
        f"### {idx}. [{status} / {replied}] {company} - {subject}",
    ]
    if msg.url:
        lines.append(f"- **スレッドURL**: {msg.url}")
    if msg.job_url:
        lines.append(f"- **求人URL**: {msg.job_url}")
    if msg.date:
        lines.append(f"- **送受信日時**: {msg.date}")
    if msg.scout_type:
        lines.append(f"- **スカウト種別**: {msg.scout_type}")
    if msg.snippet:
        lines.append(f"- **本文抜粋**: {msg.snippet}")
    latest_msg = msg.body or msg.extra_metadata.get("latestMessage", "")
    if latest_msg and len(latest_msg) > len(msg.snippet or ""):
        lines.append("- **最新メッセージ全文**:")
        lines.append("  ```")
        for m_line in latest_msg.splitlines():
            lines.append(f"  {m_line}")
        lines.append("  ```")
    lines.append("")
    return lines


CONFIG = MessageCrawlerConfig(
    examples=[
        "uv run python scripts/findy/navigate_messages.py --summary",
        "uv run python scripts/findy/navigate_messages.py --tab unreplied --summary",
    ],
    related=[
        "scripts/findy/fetch_job.py: 次に使う（スカウト求人の詳細を取得）",
    ],
    site_id="findy",
    site_name="Findy",
    auth_site="findy",
    default_output_dir=DEFAULT_OUTPUT_DIR,
    tab_url_map=TAB_URL_MAP,
    tab_label_map=TAB_LABEL_MAP,
    default_tab="all",
    tab_choices=["all", "unread", "unreplied", "archived"],
    script_path=NAVIGATE_SCRIPT_PATH,
    save_mode="latest_and_history",
    summary_item_formatter=_format_summary_item,
    markdown_table_columns=["#", "状態", "返信", "種別", "企業名", "件名・内容", "日時", "スレッドURL"],
    markdown_table_row_fn=_markdown_table_row,
    markdown_detail_item_fn=_markdown_detail_item,
)


def print_formatted_summary(data: dict[str, Any] | MessageBatch, tab: str = "all") -> None:
    """メッセージ一覧のサマリをコンソールに整形出力する（後方互換用）."""
    if isinstance(data, dict) and "source" not in data:
        data = {**data, "source": "findy"}
    batch = MessageBatch.model_validate(data) if not isinstance(data, MessageBatch) else data
    if tab:
        batch.tab = tab
        batch.tab_label = TAB_LABEL_MAP.get(tab, tab)
    print_message_summary(batch, CONFIG)


def generate_markdown(data: dict[str, Any] | MessageBatch, tab: str, now: datetime) -> str:
    """メッセージ一覧を構造化フロントマター付きMarkdownに整形する（後方互換用）."""
    if isinstance(data, dict) and "source" not in data:
        data = {**data, "source": "findy"}
    batch = MessageBatch.model_validate(data) if not isinstance(data, MessageBatch) else data
    if tab:
        batch.tab = tab
        batch.tab_label = TAB_LABEL_MAP.get(tab, tab)
    return generate_message_markdown(batch, CONFIG, now)


def save_messages_result(
    data: dict[str, Any] | MessageBatch,
    tab: str = "all",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    now: datetime | None = None,
) -> list[Path]:
    """メッセージデータを最新スナップショットと履歴ファイルとしてMarkdown/JSON保存する（後方互換用）."""
    if now is None:
        now = datetime.now()
    if isinstance(data, dict) and "source" not in data:
        data = {**data, "source": "findy"}
    batch = MessageBatch.model_validate(data) if not isinstance(data, MessageBatch) else data
    batch.tab = tab
    batch.tab_label = TAB_LABEL_MAP.get(tab, tab)
    batch.source = "findy"

    from types import SimpleNamespace
    ctx = MessagePipelineContext(
        config=CONFIG,
        args=SimpleNamespace(output_dir=output_dir, force=False, no_save=False),  # type: ignore
        entrypoint_ctx=None,  # type: ignore
        tab=tab,
        tab_label=batch.tab_label,
        target_url=batch.url or TAB_URL_MAP.get(tab, ""),
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
