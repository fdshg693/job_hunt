"""Green のメッセージ・スカウト一覧とスレッド本文を取得して保存する CLI.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
Green（https://www.green-japan.com/messages/v2）のメッセージ・スカウト一覧
およびスレッド詳細本文を自動取得し、data/green/messages/ 配下に
構造化フロントマター付きMarkdownおよびJSON形式で永続化します。

エントリポイントスクリプト規約（.agents/rules/scripts-entrypoint.md）準拠。
デフォルト実行時は生成・該当ファイルパスのみをstdoutに出力し、
人間向けサマリは --summary オプション指定時のみ表示します。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/green/ の2階層上)
GREEN_SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = GREEN_SCRIPTS_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.browser_auth import (
    resolve_profile_path,
    run_code_script,
    run_playwright_cmd,
    update_profile_last_used,
)
from scripts.common.crawlers.message_pipeline import (
    MessageCrawlerConfig,
    MessagePipelineContext,
    run_message_pipeline,
)
from scripts.common.models.message import MessageBatch, MessageItem

NAVIGATE_SCRIPT_PATH = GREEN_SCRIPTS_DIR / "navigate_messages.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "green" / "messages"
TARGET_URL = "https://www.green-japan.com/messages/v2"

TAB_LABEL_MAP = {
    "company": "企業から",
    "agent": "エージェントから",
    "all": "すべて（企業＋エージェント）",
}


def print_formatted_summary(data: dict[str, Any] | MessageBatch, tab: str = "all") -> None:
    """メッセージ一覧のサマリをコンソールに整形出力する."""
    tab_label = TAB_LABEL_MAP.get(tab, tab)
    if isinstance(data, MessageBatch):
        messages = [m.to_dict() for m in data.messages]
        total_count = data.total_count
        url = data.url or TARGET_URL
    else:
        messages = data.get("messages", [])
        total_count = data.get("totalCount", len(messages))
        url = data.get("url", TARGET_URL)

    print("\n========================================================")
    print(f" Green メッセージ・スカウト一覧 [{tab_label}]")
    print(f" URL:  {url}")
    print(f" 件数: 全 {total_count} 件")
    print("========================================================\n")

    if not messages:
        print("現在、受信したメッセージ・スカウトはありません。")
        return

    for idx, msg in enumerate(messages, start=1):
        type_str = f"[{'企業' if msg.get('type') == 'company' else 'エージェント'}]"
        scout_badge = f"[{msg.get('scoutType') or msg.get('scout_type')}]" if (msg.get("scoutType") or msg.get("scout_type")) else ""
        comp = msg.get("company", "企業名不明")
        sender = msg.get("senderName") or msg.get("sender")
        header = f"{type_str}{scout_badge} {comp}"
        if sender and sender != comp:
            header += f" ({sender})"
        print(f"[{idx}] {header}")

        if msg.get("subject"):
            print(f"    件名/紹介: {msg['subject']}")
        job_title = msg.get("jobTitle") or msg.get("job_title")
        if job_title:
            print(f"    求人名:    {job_title}")
        salary = msg.get("salary") or msg.get("jobSalary")
        if salary:
            print(f"    想定年収:  {salary}")
        thread_url = msg.get("threadUrl") or msg.get("url")
        if thread_url:
            print(f"    スレッド:  {thread_url}")

        # 添付求人
        attached = msg.get("attachedJob")
        if attached and isinstance(attached, dict):
            print(f"    添付求人:  {attached.get('url', '')}")

        # 本文スニペット
        thread_msgs = msg.get("messages")
        if thread_msgs and isinstance(thread_msgs, list) and len(thread_msgs) > 0:
            snippet = thread_msgs[0].get("body", "")[:120].replace("\n", " ")
            print(f"    本文抜粋:  {snippet}...")
        elif msg.get("snippet"):
            print(f"    本文抜粋:  {msg['snippet'][:120]}...")
        elif msg.get("body"):
            print(f"    本文抜粋:  {msg['body'][:120]}...")
        print("-" * 56)


def print_thread_detail_summary(thread: dict[str, Any]) -> None:
    """単一スレッド詳細のサマリを出力する."""
    thread_id = thread.get("threadId", "")
    thread_url = thread.get("threadUrl", "")
    attached = thread.get("attachedJob")
    messages = thread.get("messages", [])

    print("\n========================================================")
    print(f" Green スレッド詳細 [Thread ID: {thread_id}]")
    print(f" URL:  {thread_url}")
    print(f" メッセージ数: {len(messages)} 件")
    print("========================================================\n")

    if attached and isinstance(attached, dict):
        print(f"添付求人: {attached.get('url', '')}")
        if attached.get("rawText"):
            print(f"求人概要:\n{attached.get('rawText')}\n")

    for idx, m in enumerate(messages, start=1):
        sent_at = m.get("sentAt") or "日時不明"
        print(f"--- [Message #{idx} | {sent_at}] ---")
        print(m.get("body", ""))
        print()


def generate_markdown(data: dict[str, Any] | MessageBatch, tab: str, now: datetime) -> str:
    """メッセージ一覧を構造化フロントマター付きMarkdownに整形する."""
    tab_label = TAB_LABEL_MAP.get(tab, tab)
    if isinstance(data, MessageBatch):
        messages = [m.to_dict() for m in data.messages]
        total_count = data.total_count
        url = data.url or TARGET_URL
    else:
        messages = data.get("messages", [])
        total_count = data.get("totalCount", len(messages))
        url = data.get("url", TARGET_URL)

    fetched_at_str = now.isoformat(timespec="seconds")
    fetched_at_display = now.strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "---",
        "source: green",
        "type: messages",
        f"tab: {tab}",
        f"tab_label: '{tab_label}'",
        f"fetched_at: '{fetched_at_str}'",
        f"total_count: {total_count}",
        "---",
        "",
        f"# Green メッセージ・スカウト一覧 ({tab_label})",
        "",
        f"- **取得日時**: {fetched_at_display}",
        f"- **対象URL**: `{url}`",
        f"- **総件数**: {total_count} 件",
        "",
        "## メッセージ一覧",
        "",
    ]

    if not messages:
        lines.append("受信したメッセージ・スカウトはありません。")
        return "\n".join(lines) + "\n"

    for idx, msg in enumerate(messages, start=1):
        type_str = "企業" if msg.get("type") == "company" else "エージェント"
        scout_type = msg.get("scoutType") or msg.get("scout_type")
        scout_badge = f"`{scout_type}` " if scout_type else ""
        company = msg.get("company", "企業名不明")
        sender = msg.get("senderName") or msg.get("sender")
        sender_str = f" ({sender})" if (sender and sender != company) else ""

        lines.append(f"### {idx}. [{type_str}] {scout_badge}{company}{sender_str}")
        lines.append("")
        thread_id = msg.get("threadId") or msg.get("id", "")
        lines.append(f"- **スレッドID**: `{thread_id}`")
        thread_url = msg.get("threadUrl") or msg.get("url")
        if thread_url:
            lines.append(f"- **スレッドURL**: [{thread_url}]({thread_url})")
        if msg.get("subject"):
            lines.append(f"- **件名/紹介**: {msg['subject']}")
        job_title = msg.get("jobTitle") or msg.get("job_title")
        if job_title:
            lines.append(f"- **求人名**: {job_title}")
        salary = msg.get("salary") or msg.get("jobSalary")
        if salary:
            lines.append(f"- **想定年収**: {salary}")

        attached = msg.get("attachedJob")
        if attached and isinstance(attached, dict):
            lines.append(f"- **添付求人**: [{attached.get('url', '')}]({attached.get('url', '')})")

        thread_msgs = msg.get("messages")
        if thread_msgs and isinstance(thread_msgs, list) and len(thread_msgs) > 0:
            lines.append("")
            lines.append("#### メッセージ本文")
            lines.append("")
            for m in thread_msgs:
                sent_at = m.get("sentAt") or "日時不明"
                lines.append(f"> **[{sent_at}]**")
                for bl in m.get("body", "").splitlines():
                    lines.append(f"> {bl}")
                lines.append("")
        elif msg.get("body"):
            lines.append("")
            lines.append("#### メッセージ本文")
            lines.append("")
            for bl in msg["body"].splitlines():
                lines.append(f"> {bl}")
            lines.append("")

        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines) + "\n"


def generate_thread_markdown(thread: dict[str, Any], now: datetime) -> str:
    """単一スレッド詳細を構造化Markdownに整形する."""
    thread_id = thread.get("threadId", "")
    thread_url = thread.get("threadUrl", "")
    attached = thread.get("attachedJob") or {}
    messages = thread.get("messages", [])
    fetched_at_str = now.isoformat(timespec="seconds")
    fetched_at_display = now.strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "---",
        "source: green",
        "type: message_thread",
        f"thread_id: '{thread_id}'",
        f"fetched_at: '{fetched_at_str}'",
        f"message_count: {len(messages)}",
        "---",
        "",
        f"# Green スレッド詳細 (ID: {thread_id})",
        "",
        f"- **取得日時**: {fetched_at_display}",
        f"- **スレッドURL**: [{thread_url}]({thread_url})",
        f"- **メッセージ数**: {len(messages)} 件",
        "",
    ]

    if attached and isinstance(attached, dict) and attached.get("url"):
        lines.append("## 添付求人情報")
        lines.append("")
        lines.append(f"- **URL**: [{attached['url']}]({attached['url']})")
        if attached.get("rawText"):
            lines.append("")
            lines.append("```text")
            lines.append(attached["rawText"])
            lines.append("```")
        lines.append("")

    lines.append("## メッセージ履歴")
    lines.append("")

    if not messages:
        lines.append("メッセージはありません。")
    else:
        for idx, m in enumerate(messages, start=1):
            sent_at = m.get("sentAt") or "日時不明"
            lines.append(f"### メッセージ #{idx} ({sent_at})")
            lines.append("")
            for bl in m.get("body", "").splitlines():
                lines.append(f"> {bl}")
            lines.append("")

    return "\n".join(lines) + "\n"


def run_navigate(
    session: str,
    tab: str,
    limit: int = 0,
    fetch_details: bool = False,
    thread_id: str | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    """Playwrightスクリプトを実行してメッセージ一覧またはスレッド詳細を取得する."""
    if not NAVIGATE_SCRIPT_PATH.exists():
        raise RuntimeError(f"Playwrightスクリプトが見つかりません: {NAVIGATE_SCRIPT_PATH}")

    profile_path = resolve_profile_path(session)
    # ブラウザセッションオープン
    run_playwright_cmd([f"-s={session}", "open", TARGET_URL, f"--profile={profile_path}"])

    template_code = NAVIGATE_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = (
        template_code.replace("'__GREEN_TAB__'", json.dumps(tab))
        .replace("__LIMIT__", str(limit))
        .replace("__FETCH_DETAILS__", "true" if fetch_details else "false")
        .replace("'__THREAD_ID__'", json.dumps(thread_id or ""))
    )

    tmp_script = GREEN_SCRIPTS_DIR / f".tmp_nav_msg_{session}.mjs"
    tmp_script.write_text(run_code, encoding="utf-8")

    try:
        result = run_code_script(session, tmp_script, timeout=timeout)
        if not result:
            raise RuntimeError("Playwrightスクリプトの実行に失敗しました（空のレスポンス）")
        if not result.get("success"):
            errs = result.get("errors") or ["不明なエラー"]
            raise RuntimeError(f"スクリプト実行エラー: {', '.join(errs)}")
        update_profile_last_used(session)
        return result
    finally:
        if tmp_script.exists():
            try:
                tmp_script.unlink()
            except Exception:
                pass


def _custom_fetch(ctx: MessagePipelineContext) -> dict[str, Any]:
    thread_id = getattr(ctx.args, "thread_id", None)
    fetch_details = getattr(ctx.args, "details", False)
    limit = ctx.args.limit or 0
    return run_navigate(
        session=ctx.session,
        tab=ctx.tab,
        limit=limit,
        fetch_details=fetch_details,
        thread_id=thread_id,
        timeout=ctx.args.timeout,
    )


def _custom_save(batch: MessageBatch, ctx: MessagePipelineContext) -> list[Path]:
    output_dir = ctx.args.output_dir or DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    threads_dir = output_dir / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)
    now = ctx.now

    saved_files: list[Path] = []
    thread_id = getattr(ctx.args, "thread_id", None)

    # 1. 単一スレッド詳細取得の場合
    if thread_id:
        thread_detail = batch.extra_metadata.get("threadDetail") or {}
        if not thread_detail and batch.messages:
            thread_detail = batch.messages[0].to_dict()

        json_path = threads_dir / f"{thread_id}.json"
        md_path = threads_dir / f"{thread_id}.md"

        json_path.write_text(json.dumps(thread_detail, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(generate_thread_markdown(thread_detail, now), encoding="utf-8")
        saved_files.extend([json_path, md_path])

    # 2. 一覧取得の場合
    else:
        timestamp_str = now.strftime("%Y-%m-%d-%H%M%S")
        json_path = output_dir / f"{timestamp_str}_messages_{ctx.tab}.json"
        md_path = output_dir / f"{timestamp_str}_messages_{ctx.tab}.md"

        json_data = batch.to_dict()
        json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(generate_markdown(batch, ctx.tab, now), encoding="utf-8")
        saved_files.extend([json_path, md_path])

        # 各スレッドの詳細も取得していた場合、スレッド別にも保存
        if getattr(ctx.args, "details", False):
            for msg in batch.messages:
                m_dict = msg.to_dict()
                t_id = m_dict.get("threadId") or msg.id
                if t_id and m_dict.get("messages"):
                    t_json = threads_dir / f"{t_id}.json"
                    t_md = threads_dir / f"{t_id}.md"
                    t_json.write_text(json.dumps(m_dict, ensure_ascii=False, indent=2), encoding="utf-8")
                    t_md.write_text(generate_thread_markdown(m_dict, now), encoding="utf-8")
                    saved_files.extend([t_json, t_md])

    return saved_files


def _parse_batch(raw_dict: dict[str, Any]) -> MessageBatch:
    thread_detail = raw_dict.get("threadDetail")
    if thread_detail:
        item = MessageItem(
            id=thread_detail.get("threadId"),
            url=thread_detail.get("threadUrl", ""),
            extra_metadata=thread_detail,
        )
        return MessageBatch(
            source="green",
            type="message_thread",
            tab="thread",
            total_count=1,
            messages=[item],
            extra_metadata={"threadDetail": thread_detail},
        )

    # 通常一覧
    msgs = raw_dict.get("messages", [])
    items: list[MessageItem] = []
    for m in msgs:
        # Greenのmessagesリスト（会話本文）を保持
        m_copy = dict(m)
        thread_msgs = m_copy.get("messages")
        body_text = ""
        if thread_msgs and isinstance(thread_msgs, list) and len(thread_msgs) > 0:
            body_text = "\n\n".join(
                f"[{tm.get('sentAt', '')}]\n{tm.get('body', '')}" for tm in thread_msgs
            )
        items.append(
            MessageItem(
                id=m_copy.get("threadId"),
                sender=m_copy.get("senderName", ""),
                company=m_copy.get("company", ""),
                subject=m_copy.get("subject", ""),
                body=body_text,
                url=m_copy.get("threadUrl", ""),
                scout_type=m_copy.get("scoutType", "通常"),
                extra_metadata=m_copy,
            )
        )

    return MessageBatch(
        source="green",
        type="messages",
        tab=raw_dict.get("tab", "all"),
        tab_label=raw_dict.get("tab_label", "すべて"),
        url=raw_dict.get("url", TARGET_URL),
        total_count=raw_dict.get("totalCount", len(items)),
        messages=items,
        extra_metadata=raw_dict,
    )


def _setup_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--thread-id",
        type=str,
        default=None,
        help="特定スレッドIDの本文詳細のみを取得",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="一覧取得時に各スレッドの本文詳細も合わせて取得する",
    )


def _custom_summary(batch: MessageBatch, ctx: MessagePipelineContext) -> None:
    thread_id = getattr(ctx.args, "thread_id", None)
    if thread_id:
        thread_detail = batch.extra_metadata.get("threadDetail") or {}
        if not thread_detail and batch.messages:
            thread_detail = batch.messages[0].to_dict()
        print_thread_detail_summary(thread_detail)
    else:
        print_formatted_summary(batch, tab=ctx.tab)


CONFIG = MessageCrawlerConfig(
    site_id="green",
    site_name="Green",
    auth_site="green",
    default_output_dir=DEFAULT_OUTPUT_DIR,
    tab_url_map={
        "company": TARGET_URL,
        "agent": TARGET_URL,
        "all": TARGET_URL,
    },
    tab_label_map=TAB_LABEL_MAP,
    default_tab="all",
    tab_choices=["company", "agent", "all"],
    save_mode="timestamp_detailed",
    custom_fetch_fn=_custom_fetch,
    custom_save_fn=_custom_save,
    parse_batch_fn=_parse_batch,
    custom_summary_fn=_custom_summary,
    setup_args_fn=_setup_args,
    examples=[
        "uv run python scripts/green/navigate_messages.py --tab company --limit 20 --summary",
        "uv run python scripts/green/navigate_messages.py --details --limit 10  # スレッド本文も取得",
        "uv run python scripts/green/navigate_messages.py --thread-id <thread-id> --summary",
    ],
    related=[
        "scripts/green/fetch_job.py: 次に使う（スカウトの求人詳細を取得）",
    ],
)


def main() -> None:
    """CLIエントリポイント."""
    # 既存の Green は --summary 時にスレッド詳細用と一覧用でフォーマッターが分かれていたため
    # コールバックまたは引数でハンドリング
    sys.exit(run_message_pipeline(CONFIG))


if __name__ == "__main__":
    main()
