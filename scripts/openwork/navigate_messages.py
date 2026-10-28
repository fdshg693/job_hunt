"""OpenWork のメッセージ・スカウト一覧を取得して保存する CLI.

OpenWork メッセージ・スカウト自動取得スクリプト.
リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
OpenWorkのログイン状態確認・未ログイン時の通知待機ハンドオフ・メッセージ一覧画面（/job_apply_list）からの
スカウト・メッセージ抽出・永続化を実行します。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/openwork/ の2階層上)
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

OPENWORK_SCRIPTS_DIR = Path(__file__).resolve().parent
NAVIGATE_SCRIPT_PATH = OPENWORK_SCRIPTS_DIR / "navigate_messages.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "openwork" / "messages"
TARGET_URL = "https://www.openwork.jp/job_apply_list"

TAB_URL_MAP = {
    "all": "https://www.openwork.jp/job_apply_list",
    "company": "https://www.openwork.jp/job_apply_list?type=1",
    "agent": "https://www.openwork.jp/job_apply_list?type=2",
}

TAB_LABEL_MAP = {
    "all": "すべて",
    "company": "企業",
    "agent": "エージェント",
}


def _format_summary_item(msg: MessageItem, idx: int) -> list[str]:
    type_badge = f"[{msg.scout_type or '通常'}]"
    unread_badge = "[未読] " if msg.is_unread else ""
    deadline_str = f" ({msg.deadline})" if msg.deadline else ""
    company = msg.company or msg.sender or "送信者不明"
    lines = [
        f"[{idx}] {unread_badge}{type_badge} {company}{deadline_str}",
        f"    件名: {msg.subject or '（件名なし）'}",
    ]
    if msg.date:
        lines.append(f"    日時: {msg.date}")
    if msg.url:
        lines.append(f"    URL:  {msg.url}")
    if msg.snippet:
        lines.append(f"    抜粋: {msg.snippet[:100]}...")
    lines.append("-" * 56)
    return lines


def _markdown_table_row(msg: MessageItem, idx: int) -> list[str]:
    status = "未読" if msg.is_unread else "既読"
    scout_type = msg.scout_type or "通常"
    company = msg.company or msg.sender or "不明"
    subject = msg.subject or "（件名なし）"
    date_str = msg.date or "-"
    deadline = msg.deadline or "-"
    link = f"[詳細]({msg.url})" if msg.url else "-"
    return [str(idx), status, scout_type, company, subject, date_str, deadline, link]


def _markdown_detail_item(msg: MessageItem, idx: int) -> list[str]:
    status = "未読" if msg.is_unread else "既読"
    company = msg.company or msg.sender or "不明"
    subject = msg.subject or "（件名なし）"
    lines = [
        f"### {idx}. [{status}] {company} - {subject}",
    ]
    if msg.url:
        lines.append(f"- **スレッドURL**: {msg.url}")
    if msg.date:
        lines.append(f"- **受信日時**: {msg.date}")
    if msg.deadline:
        lines.append(f"- **返信期限**: {msg.deadline}")
    if msg.scout_type:
        lines.append(f"- **種別**: {msg.scout_type}")
    if msg.snippet:
        lines.append(f"- **抜粋**: {msg.snippet}")
    lines.append("")
    return lines


CONFIG = MessageCrawlerConfig(
    examples=[
        "uv run python scripts/openwork/navigate_messages.py --summary",
        "uv run python scripts/openwork/navigate_messages.py --tab company --limit 10 --summary",
    ],
    related=[
        "scripts/openwork/fetch_job.py: 次に使う（スカウト求人の詳細を取得）",
    ],
    site_id="openwork",
    site_name="OpenWork",
    auth_site="openwork",
    default_output_dir=DEFAULT_OUTPUT_DIR,
    tab_url_map=TAB_URL_MAP,
    tab_label_map=TAB_LABEL_MAP,
    default_tab="all",
    tab_choices=["all", "company", "agent"],
    script_path=NAVIGATE_SCRIPT_PATH,
    save_mode="hourly",
    summary_item_formatter=_format_summary_item,
    markdown_table_columns=["#", "状態", "種別", "企業名", "件名", "日時", "返信期限", "スレッドURL"],
    markdown_table_row_fn=_markdown_table_row,
    markdown_detail_item_fn=_markdown_detail_item,
)


def print_formatted_summary(data: dict[str, Any] | MessageBatch, tab: str = "all") -> None:
    """メッセージ一覧のサマリをコンソールに整形出力する（後方互換用）."""
    if isinstance(data, dict) and "source" not in data:
        data = {**data, "source": "openwork"}
    batch = MessageBatch.model_validate(data) if not isinstance(data, MessageBatch) else data
    if tab:
        batch.tab = tab
        batch.tab_label = TAB_LABEL_MAP.get(tab, tab)
    print_message_summary(batch, CONFIG)


def generate_markdown(data: dict[str, Any] | MessageBatch, tab: str, now: datetime) -> str:
    """メッセージ一覧を構造化フロントマター付きMarkdownに整形する（後方互換用）."""
    if isinstance(data, dict) and "source" not in data:
        data = {**data, "source": "openwork"}
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
) -> tuple[Path, Path]:
    """メッセージデータをMarkdownとJSONでファイル保存する（後方互換用）."""
    if now is None:
        now = datetime.now()
    if isinstance(data, dict) and "source" not in data:
        data = {**data, "source": "openwork"}
    batch = MessageBatch.model_validate(data) if not isinstance(data, MessageBatch) else data
    batch.tab = tab
    batch.tab_label = TAB_LABEL_MAP.get(tab, tab)
    batch.source = "openwork"

    from types import SimpleNamespace
    ctx = MessagePipelineContext(
        config=CONFIG,
        args=SimpleNamespace(output_dir=output_dir, force=False, no_save=False),  # type: ignore
        entrypoint_ctx=None,  # type: ignore
        tab=tab,
        tab_label=batch.tab_label,
        target_url=batch.url or TAB_URL_MAP.get(tab, TARGET_URL),
        session="job-hunt",
        profile_dir=output_dir,
        now=now,
    )
    paths = save_message_batch(batch, ctx)
    md_path = next((p for p in paths if p.suffix == ".md"), output_dir / f"{now.strftime('%Y-%m-%d-%H')}_{tab}.md")
    json_path = next((p for p in paths if p.suffix == ".json"), output_dir / f"{now.strftime('%Y-%m-%d-%H')}_{tab}.json")
    return md_path, json_path


def main() -> None:
    """CLIエントリポイント."""
    sys.exit(run_message_pipeline(CONFIG))


if __name__ == "__main__":
    main()
