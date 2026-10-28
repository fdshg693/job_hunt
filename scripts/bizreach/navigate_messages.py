"""ビズリーチのメッセージ・スカウト一覧を取得して保存する CLI.

ビズリーチ メッセージ自動取得スクリプト.
リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
ビズリーチのログイン状態確認・未ログイン時の通知待機ハンドオフ・メッセージ一覧画面からのスカウト/メッセージ抽出を実行します。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/bizreach/ の2階層上)
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

BIZREACH_SCRIPTS_DIR = Path(__file__).resolve().parent
NAVIGATE_SCRIPT_PATH = BIZREACH_SCRIPTS_DIR / "navigate_messages.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "bizreach" / "messages"

TAB_URL_MAP = {
    "all": "https://www.bizreach.jp/messages/",
    "direct": "https://www.bizreach.jp/messages/?recruitmentTypeCodes=DIRECT_RECRUITMENT",
    "headhunter": "https://www.bizreach.jp/messages/?recruitmentTypeCodes=HEADHUNTER",
}

TAB_LABEL_MAP = {
    "all": "すべて",
    "direct": "企業（直接コンタクト）",
    "headhunter": "ヘッドハンター",
}


def _format_summary_item(msg: MessageItem, idx: int) -> list[str]:
    type_badge = f"[{msg.scout_type or '通常'}]"
    unread_badge = "[未読] " if msg.is_unread else ""
    sender = msg.sender or msg.company or "送信者名不明"
    lines = [
        f"[{idx}] {unread_badge}{type_badge} {sender}",
        f"    件名:     {msg.subject or '（件名なし）'}",
    ]
    if msg.date:
        lines.append(f"    日時:     {msg.date}")
    if msg.url:
        lines.append(f"    URL:      {msg.url}")
    attached_jobs = msg.extra_metadata.get("attachedJobs") or []
    if attached_jobs:
        lines.append(f"    添付求人: {len(attached_jobs)} 件")
        for j_idx, job in enumerate(attached_jobs, start=1):
            j_title = job.get("title", "")
            j_company = job.get("company", "")
            j_salary = job.get("salary", "")
            j_url = job.get("url", "")
            sal_disp = f" ({j_salary})" if j_salary else ""
            lines.append(f"      - [{j_idx}] {j_company} | {j_title}{sal_disp}")
            if j_url:
                lines.append(f"           {j_url}")
    if msg.snippet:
        lines.append(f"    抜粋:     {msg.snippet[:100]}...")
    lines.append("-" * 56)
    return lines


def _markdown_table_row(msg: MessageItem, idx: int) -> list[str]:
    status = "未読" if msg.is_unread else "既読"
    scout_type = msg.scout_type or "通常"
    sender = msg.sender or msg.company or "送信者不明"
    subject = msg.subject or "（件名なし）"
    date_str = msg.date or "-"
    attached_jobs = msg.extra_metadata.get("attachedJobs") or []
    attached_count = f"{len(attached_jobs)} 件" if attached_jobs else "-"
    link = f"[詳細]({msg.url})" if msg.url else "-"
    return [str(idx), status, scout_type, sender, subject, date_str, attached_count, link]


def _markdown_detail_item(msg: MessageItem, idx: int) -> list[str]:
    status = "未読" if msg.is_unread else "既読"
    sender = msg.sender or msg.company or "送信者不明"
    subject = msg.subject or "（件名なし）"
    lines = [
        f"### {idx}. [{status}] {sender} - {subject}",
    ]
    if msg.url:
        lines.append(f"- **スレッドURL**: {msg.url}")
    if msg.date:
        lines.append(f"- **受信日時**: {msg.date}")
    if msg.scout_type:
        lines.append(f"- **スカウト種別**: {msg.scout_type}")
    if msg.snippet:
        lines.append(f"- **本文抜粋**: {msg.snippet}")
    attached_jobs = msg.extra_metadata.get("attachedJobs") or []
    if attached_jobs:
        lines.append("- **添付求人一覧**:")
        for j_idx, job in enumerate(attached_jobs, start=1):
            j_title = job.get("title", "")
            j_comp = job.get("company", "")
            j_sal = job.get("salary", "")
            j_url = job.get("url", "")
            sal_part = f" ({j_sal})" if j_sal else ""
            url_part = f" [リンク]({j_url})" if j_url else ""
            lines.append(f"  - [{j_idx}] {j_comp} | {j_title}{sal_part}{url_part}")
    lines.append("")
    return lines


CONFIG = MessageCrawlerConfig(
    examples=[
        "uv run python scripts/bizreach/navigate_messages.py --summary",
        "uv run python scripts/bizreach/navigate_messages.py --tab direct --limit 10 --summary",
    ],
    related=[
        "scripts/bizreach/fetch_message_jobs.py: 次に使う（スレッドの添付求人を保存）",
    ],
    site_id="bizreach",
    site_name="ビズリーチ",
    auth_site="bizreach",
    default_output_dir=DEFAULT_OUTPUT_DIR,
    tab_url_map=TAB_URL_MAP,
    tab_label_map=TAB_LABEL_MAP,
    default_tab="all",
    tab_choices=["all", "direct", "headhunter"],
    script_path=NAVIGATE_SCRIPT_PATH,
    save_mode="hourly",
    summary_item_formatter=_format_summary_item,
    markdown_table_columns=["#", "状態", "種別", "送信者", "件名", "日時", "添付求人", "スレッドURL"],
    markdown_table_row_fn=_markdown_table_row,
    markdown_detail_item_fn=_markdown_detail_item,
)


def print_formatted_summary(data: dict[str, Any] | MessageBatch, tab: str = "all") -> None:
    """メッセージ一覧のサマリをコンソールに整形出力する（後方互換用）."""
    if isinstance(data, dict) and "source" not in data:
        data = {**data, "source": "bizreach"}
    batch = MessageBatch.model_validate(data) if not isinstance(data, MessageBatch) else data
    if tab:
        batch.tab = tab
        batch.tab_label = TAB_LABEL_MAP.get(tab, tab)
    print_message_summary(batch, CONFIG)


def generate_markdown(data: dict[str, Any] | MessageBatch, tab: str, now: datetime) -> str:
    """メッセージ一覧を構造化フロントマター付きMarkdownに整形する（後方互換用）."""
    if isinstance(data, dict) and "source" not in data:
        data = {**data, "source": "bizreach"}
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
        data = {**data, "source": "bizreach"}
    batch = MessageBatch.model_validate(data) if not isinstance(data, MessageBatch) else data
    batch.tab = tab
    batch.tab_label = TAB_LABEL_MAP.get(tab, tab)
    batch.source = "bizreach"

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
    paths = save_message_batch(batch, ctx)
    md_path = next((p for p in paths if p.suffix == ".md"), output_dir / f"{now.strftime('%Y-%m-%d-%H')}_{tab}.md")
    json_path = next((p for p in paths if p.suffix == ".json"), output_dir / f"{now.strftime('%Y-%m-%d-%H')}_{tab}.json")
    return md_path, json_path


def main() -> None:
    """CLIエントリポイント."""
    sys.exit(run_message_pipeline(CONFIG))


if __name__ == "__main__":
    main()
