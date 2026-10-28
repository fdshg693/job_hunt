"""レバテックダイレクトのスカウト・メッセージ一覧と詳細を取得して保存する CLI.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
レバテックダイレクトのログイン状態確認・未ログイン時の通知待機ハンドオフ・マイページメッセージ画面からの
スカウト・メッセージ一覧抽出・スレッド詳細取得・構造化フロントマター付きMarkdownおよびJSON形式での永続化を実行します。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/levtech_direct/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.browser_auth import run_code_script
from scripts.common.crawlers.message_pipeline import (
    MessageCrawlerConfig,
    MessagePipelineContext,
    generate_message_markdown,
    print_message_summary,
    run_message_pipeline,
    save_message_batch,
)
from scripts.common.models.message import MessageBatch, MessageItem

LEVTECH_SCRIPTS_DIR = Path(__file__).resolve().parent
NAVIGATE_SCRIPT_PATH = LEVTECH_SCRIPTS_DIR / "navigate_messages.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "levtech_direct" / "messages"
TARGET_URL = "https://levtech-direct.jp/mypage/message"

TAB_LABEL_MAP = {
    "active": "メッセージ（アクティブ）",
    "unread": "未読メッセージ",
    "company": "企業から",
    "headhunter": "ヘッドハンターから",
    "trash": "ゴミ箱",
    "archived": "ゴミ箱",
    "all": "すべて（全メッセージ・ゴミ箱含む）",
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
        template_code.replace("'__LEVTECH_TAB__'", json.dumps(tab))
        .replace("__FETCH_DETAILS__", "false" if no_details else "true")
        .replace("__LIMIT__", str(limit))
    ).strip().rstrip(";")

    tmp_script_path = LEVTECH_SCRIPTS_DIR / f".tmp_nav_messages_{tab}.mjs"
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
    tab = "trash" if ctx.tab == "archived" else ctx.tab
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
    date_str = f" ({msg.date})" if msg.date else ""
    comp_name = msg.company or "企業名不明"

    lines = [
        f"[{idx}] {badges_str} {comp_name}{date_str}",
        f"    件名:     {msg.subject or '（件名なし）'}",
    ]
    job_title = msg.job_title or msg.extra_metadata.get("jobTitle")
    if job_title:
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
    badges = " / ".join(badges_list) if badges_list else (msg.scout_type or "メッセージ")
    company = msg.company or "企業名不明"
    subject = msg.subject or "（件名なし）"
    date_text = msg.date or "-"
    job_link = f"[求人詳細]({msg.job_url})" if msg.job_url else "-"
    thread_link = f"[スレッド]({msg.url})" if msg.url else "-"
    return [str(idx), badges, company, subject, date_text, job_link, thread_link]


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
    if msg.date:
        lines.append(f"- **受信/更新日時**: {msg.date}")
    job_title = msg.job_title or msg.extra_metadata.get("jobTitle")
    if job_title:
        lines.append(f"- **求人タイトル**: {job_title}")
    job_salary = msg.extra_metadata.get("jobSalary")
    if job_salary:
        lines.append(f"- **想定年収**: {job_salary}")
    job_work_style = msg.extra_metadata.get("jobWorkStyle")
    if job_work_style:
        lines.append(f"- **勤務形態**: {job_work_style}")
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
        help="スレッド詳細・やり取り履歴の取得をスキップする（高速一覧取得）",
    )


CONFIG = MessageCrawlerConfig(
    site_id="levtech_direct",
    site_name="レバテックダイレクト",
    auth_site="levtech_direct",
    default_output_dir=DEFAULT_OUTPUT_DIR,
    tab_url_map={
        "active": TARGET_URL,
        "unread": TARGET_URL,
        "company": TARGET_URL,
        "headhunter": TARGET_URL,
        "trash": TARGET_URL,
        "archived": TARGET_URL,
        "all": TARGET_URL,
    },
    tab_label_map=TAB_LABEL_MAP,
    default_tab="active",
    tab_choices=["active", "unread", "company", "headhunter", "trash", "archived", "all"],
    save_mode="latest_and_history",
    custom_fetch_fn=_custom_fetch,
    summary_item_formatter=_format_summary_item,
    markdown_table_columns=["#", "種別/バッジ", "企業名", "件名/求人", "受信日時", "求人URL", "スレッドURL"],
    markdown_table_row_fn=_markdown_table_row,
    markdown_detail_item_fn=_markdown_detail_item,
    setup_args_fn=_setup_args,
    examples=[
        "uv run python scripts/levtech_direct/navigate_messages.py --summary --limit 3",
        "uv run python scripts/levtech_direct/navigate_messages.py --tab unread --no-details --summary  # 未読の一覧のみ",
    ],
    related=[
        "scripts/levtech_direct/search_jobs.py: 次に使う（スカウト企業の求人を探す）",
    ],
)


def print_formatted_summary(data: dict[str, Any] | MessageBatch, tab: str = "active") -> None:
    """メッセージ一覧のサマリをコンソールに整形出力する（後方互換用）."""
    if isinstance(data, dict) and "source" not in data:
        data = {**data, "source": "levtech_direct"}
    batch = MessageBatch.model_validate(data) if not isinstance(data, MessageBatch) else data
    if tab:
        batch.tab = "trash" if tab == "archived" else tab
        batch.tab_label = TAB_LABEL_MAP.get(tab, tab)
    print_message_summary(batch, CONFIG)


def generate_markdown(data: dict[str, Any] | MessageBatch, tab: str, now: datetime) -> str:
    """メッセージ一覧を構造化フロントマター付きMarkdownに整形する（後方互換用）."""
    if isinstance(data, dict) and "source" not in data:
        data = {**data, "source": "levtech_direct"}
    batch = MessageBatch.model_validate(data) if not isinstance(data, MessageBatch) else data
    if tab:
        batch.tab = "trash" if tab == "archived" else tab
        batch.tab_label = TAB_LABEL_MAP.get(tab, tab)
    return generate_message_markdown(batch, CONFIG, now)


def save_messages_result(
    data: dict[str, Any] | MessageBatch,
    tab: str = "active",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    now: datetime | None = None,
) -> list[Path]:
    """メッセージデータをMarkdownとJSONでファイル保存する（後方互換用）."""
    if now is None:
        now = datetime.now()
    if isinstance(data, dict) and "source" not in data:
        data = {**data, "source": "levtech_direct"}
    batch = MessageBatch.model_validate(data) if not isinstance(data, MessageBatch) else data
    batch.tab = "trash" if tab == "archived" else tab
    batch.tab_label = TAB_LABEL_MAP.get(tab, tab)
    batch.source = "levtech_direct"

    from types import SimpleNamespace
    ctx = MessagePipelineContext(
        config=CONFIG,
        args=SimpleNamespace(output_dir=output_dir, force=False, no_save=False),  # type: ignore
        entrypoint_ctx=None,  # type: ignore
        tab=batch.tab,
        tab_label=batch.tab_label,
        target_url=batch.url or TARGET_URL,
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
