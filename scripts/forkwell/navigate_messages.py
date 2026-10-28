"""Forkwell のスカウト・メッセージ一覧と詳細を取得して保存する CLI.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
Forkwell Jobsのログイン状態確認・未ログイン時の通知待機ハンドオフ・インボックス画面（/inbox）からの
スカウト・メッセージ一覧抽出・右ペイン詳細取得・構造化フロントマター付きMarkdownおよびJSON形式での永続化を実行します。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/forkwell/ の2階層上)
FORKWELL_SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = FORKWELL_SCRIPTS_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.browser_auth import run_code_script
from scripts.common.crawlers.message_pipeline import (
    MessageCrawlerConfig,
    MessagePipelineContext,
    generate_message_markdown,
    print_message_summary,
    run_message_pipeline,
)
from scripts.common.models.message import MessageBatch, MessageItem

NAVIGATE_SCRIPT_PATH = FORKWELL_SCRIPTS_DIR / "navigate_messages.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "forkwell" / "messages"
TARGET_URL = "https://jobs.forkwell.com/inbox"

TAB_LABEL_MAP = {
    "active": "スカウト・やりとり",
    "archive": "アーカイブ",
    "archived": "アーカイブ",
    "all": "すべて（やりとり＋アーカイブ）",
}


def execute_navigate_messages(
    session: str,
    tab: str = "active",
    limit: int = 0,
    no_details: bool = False,
    timeout: int = 120,
) -> dict[str, Any]:
    """navigate_messages.mjs にパラメータを注入して実行する."""
    if not NAVIGATE_SCRIPT_PATH.exists():
        raise RuntimeError(f"メッセージスクリプトが見つかりません: {NAVIGATE_SCRIPT_PATH}")

    template_code = NAVIGATE_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = (
        template_code.replace("'__FORKWELL_TAB__'", json.dumps(tab))
        .replace("__FETCH_DETAILS__", "false" if no_details else "true")
        .replace("__LIMIT__", str(limit))
    ).strip().rstrip(";")

    tmp_script_path = FORKWELL_SCRIPTS_DIR / f".tmp_nav_messages_{tab}.mjs"
    tmp_script_path.write_text(run_code, encoding="utf-8")

    try:
        result = run_code_script(session, tmp_script_path, timeout=timeout)
        if not result:
            raise RuntimeError("Playwrightスクリプトの実行に失敗しました")
        return result
    finally:
        if tmp_script_path.exists():
            try:
                tmp_script_path.unlink()
            except Exception:
                pass


def _custom_fetch(ctx: MessagePipelineContext) -> dict[str, Any]:
    tab = "archive" if ctx.tab == "archived" else ctx.tab
    ctx.tab = tab
    limit = ctx.args.limit or 0
    no_details = getattr(ctx.args, "no_details", False)
    return execute_navigate_messages(
        session=ctx.session,
        tab=tab,
        limit=limit,
        no_details=no_details,
        timeout=ctx.args.timeout,
    )


def _format_summary_item(msg: MessageItem, idx: int) -> list[str]:
    badges = msg.extra_metadata.get("badges", [])
    badges_str = " ".join(f"[{b}]" for b in badges)
    if not badges_str and msg.scout_type:
        badges_str = f"[{msg.scout_type}]"

    status_info = msg.extra_metadata.get("statusText") or ""
    if status_info:
        status_info = f" | {status_info}"

    lines = [
        f"[{idx}] {badges_str} {msg.company or '企業名不明'}{status_info}",
        f"    件名:     {msg.subject or '（件名なし）'}",
    ]
    job_title = msg.job_title or msg.extra_metadata.get("jobTitle")
    if job_title and job_title != msg.subject:
        lines.append(f"    求人名:   {job_title}")
    job_salary = msg.extra_metadata.get("jobSalary")
    if job_salary:
        lines.append(f"    提示年収: {job_salary}")
    if msg.url:
        lines.append(f"    スレッド: {msg.url}")
    if msg.job_url:
        lines.append(f"    求人URL:  {msg.job_url}")
    if msg.snippet:
        lines.append(f"    抜粋:     {msg.snippet[:120]}...")
    lines.append("-" * 56)
    return lines


def _markdown_table_row(msg: MessageItem, idx: int) -> list[str]:
    badges_list = msg.extra_metadata.get("badges", [])
    badges = " / ".join(badges_list) if badges_list else (msg.scout_type or "スカウト")
    company = msg.company or "企業名不明"
    subject = msg.subject or "（件名なし）"
    status_text = msg.extra_metadata.get("statusText") or "-"
    job_link = f"[求人詳細]({msg.job_url})" if msg.job_url else "-"
    thread_link = f"[スレッド]({msg.url})" if msg.url else "-"
    return [str(idx), badges, company, subject, status_text, job_link, thread_link]


def _markdown_detail_item(msg: MessageItem, idx: int) -> list[str]:
    comp = msg.company or "企業名不明"
    subj = msg.subject or "（件名なし）"
    lines = [
        f"### {idx}. {comp} - {subj}",
        "",
    ]
    badges = msg.extra_metadata.get("badges")
    if badges:
        lines.append(f"- **バッジ**: {', '.join(badges)}")
    status_text = msg.extra_metadata.get("statusText")
    if status_text:
        lines.append(f"- **状況**: {status_text}")
    if msg.deadline:
        lines.append(f"- **有効期限**: {msg.deadline}")
    job_title = msg.job_title or msg.extra_metadata.get("jobTitle")
    if job_title:
        lines.append(f"- **求人タイトル**: {job_title}")
    job_salary = msg.extra_metadata.get("jobSalary")
    if job_salary:
        lines.append(f"- **想定年収**: {job_salary}")
    job_role = msg.extra_metadata.get("jobRole")
    if job_role:
        lines.append(f"- **職種**: {job_role}")
    if msg.job_url:
        lines.append(f"- **求人URL**: {msg.job_url}")
    if msg.url:
        lines.append(f"- **スレッドURL**: {msg.url}")
    lines.append("")

    body = (msg.body or "").strip()
    if body:
        lines.extend([
            "#### メッセージ本文",
            "",
            "```text",
            body,
            "```",
            "",
        ])
    elif msg.snippet:
        lines.extend([
            f"> **抜粋**: {msg.snippet}",
            "",
        ])
    return lines


def _setup_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--no-details",
        action="store_true",
        help="カードクリックによる右ペイン詳細本文の取得をスキップする（高速一覧取得）",
    )


CONFIG = MessageCrawlerConfig(
    site_id="forkwell",
    site_name="Forkwell",
    auth_site="forkwell",
    default_output_dir=DEFAULT_OUTPUT_DIR,
    tab_url_map={
        "active": TARGET_URL,
        "archive": TARGET_URL,
        "archived": TARGET_URL,
        "all": TARGET_URL,
    },
    tab_label_map=TAB_LABEL_MAP,
    default_tab="active",
    tab_choices=["active", "archive", "archived", "all"],
    save_mode="latest_and_history",
    custom_fetch_fn=_custom_fetch,
    summary_item_formatter=_format_summary_item,
    markdown_table_columns=["#", "種別/バッジ", "企業名", "件名", "ステータス/期限", "求人URL", "スレッドURL"],
    markdown_table_row_fn=_markdown_table_row,
    markdown_detail_item_fn=_markdown_detail_item,
    setup_args_fn=_setup_args,
    examples=[
        "uv run python scripts/forkwell/navigate_messages.py --summary",
        "uv run python scripts/forkwell/navigate_messages.py --tab all --limit 5 --summary",
        "uv run python scripts/forkwell/navigate_messages.py --no-details --summary  # 一覧のみ（詳細ペインを開かない）",
    ],
    related=[
        "scripts/forkwell/fetch_job.py: 次に使う（スカウトの求人詳細を取得）",
    ],
)


def print_formatted_summary(data: dict[str, Any] | MessageBatch, tab: str = "active") -> None:
    """メッセージ一覧のサマリをコンソールに整形出力する（後方互換用）."""
    batch = MessageBatch.model_validate(data) if not isinstance(data, MessageBatch) else data
    if tab:
        batch.tab = "archive" if tab == "archived" else tab
        batch.tab_label = TAB_LABEL_MAP.get(tab, tab)
    print_message_summary(batch, CONFIG)


def generate_markdown(data: dict[str, Any] | MessageBatch, tab: str, now: datetime) -> str:
    """メッセージ一覧を構造化フロントマター付きMarkdownに整形する（後方互換用）."""
    batch = MessageBatch.model_validate(data) if not isinstance(data, MessageBatch) else data
    return generate_message_markdown(batch, CONFIG, now)


def main() -> None:
    """CLIエントリポイント."""
    sys.exit(run_message_pipeline(CONFIG))


if __name__ == "__main__":
    main()
