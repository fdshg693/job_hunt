"""Green メッセージ・スカウト自動取得スクリプト.

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
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.auth_engine import ensure_site_authenticated
from scripts.common.browser_auth import (
    resolve_profile_path,
    run_code_script,
    run_playwright_cmd,
    update_profile_last_used,
)
from scripts.common.cli import create_base_parser, entrypoint_guard, to_relative_path

GREEN_SCRIPTS_DIR = Path(__file__).resolve().parent
NAVIGATE_SCRIPT_PATH = GREEN_SCRIPTS_DIR / "navigate_messages.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "green" / "messages"
TARGET_URL = "https://www.green-japan.com/messages/v2"

TAB_LABEL_MAP = {
    "company": "企業から",
    "agent": "エージェントから",
    "all": "すべて（企業＋エージェント）",
}


def print_formatted_summary(data: dict[str, Any], tab: str = "all") -> None:
    """メッセージ一覧のサマリをコンソールに整形出力する."""
    tab_label = TAB_LABEL_MAP.get(tab, tab)
    messages = data.get("messages", [])
    total_count = data.get("totalCount", len(messages))

    print("\n========================================================")
    print(f" Green メッセージ・スカウト一覧 [{tab_label}]")
    print(f" URL:  {data.get('url', TARGET_URL)}")
    print(f" 件数: 全 {total_count} 件")
    print("========================================================\n")

    if not messages:
        print("現在、受信したメッセージ・スカウトはありません。")
        return

    for idx, msg in enumerate(messages, start=1):
        type_str = f"[{'企業' if msg.get('type') == 'company' else 'エージェント'}]"
        scout_badge = f"[{msg['scoutType']}]" if msg.get("scoutType") else ""
        header = f"{type_str}{scout_badge} {msg.get('company', '企業名不明')}"
        if msg.get("senderName"):
            header += f" ({msg['senderName']})"
        print(f"[{idx}] {header}")

        if msg.get("subject"):
            print(f"    件名/紹介: {msg['subject']}")
        if msg.get("jobTitle"):
            print(f"    求人名:    {msg['jobTitle']}")
        if msg.get("salary"):
            print(f"    想定年収:  {msg['salary']}")
        if msg.get("threadUrl"):
            print(f"    スレッド:  {msg['threadUrl']}")

        # 添付求人
        attached = msg.get("attachedJob")
        if attached and isinstance(attached, dict):
            print(f"    添付求人:  {attached.get('url', '')}")

        # 本文スニペット
        thread_msgs = msg.get("messages")
        if thread_msgs and isinstance(thread_msgs, list) and len(thread_msgs) > 0:
            snippet = thread_msgs[0].get("body", "")[:120].replace("\n", " ")
            print(f"    本文抜粋:  {snippet}...")
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


def generate_markdown(data: dict[str, Any], tab: str, now: datetime) -> str:
    """メッセージ一覧を構造化フロントマター付きMarkdownに整形する."""
    tab_label = TAB_LABEL_MAP.get(tab, tab)
    messages = data.get("messages", [])
    total_count = data.get("totalCount", len(messages))
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
        f"- **対象URL**: `{data.get('url', TARGET_URL)}`",
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
        scout_badge = f"`{msg['scoutType']}` " if msg.get("scoutType") else ""
        company = msg.get("company", "企業名不明")
        sender = f" ({msg['senderName']})" if msg.get("senderName") else ""

        lines.append(f"### {idx}. [{type_str}] {scout_badge}{company}{sender}")
        lines.append("")
        lines.append(f"- **スレッドID**: `{msg.get('threadId', '')}`")
        if msg.get("threadUrl"):
            lines.append(f"- **スレッドURL**: [{msg['threadUrl']}]({msg['threadUrl']})")
        if msg.get("subject"):
            lines.append(f"- **件名/紹介**: {msg['subject']}")
        if msg.get("jobTitle"):
            lines.append(f"- **求人名**: {msg['jobTitle']}")
        if msg.get("salary"):
            lines.append(f"- **想定年収**: {msg['salary']}")

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


def main() -> None:
    parser = create_base_parser(
        description="Green メッセージ・スカウト自動取得スクリプト",
        default_limit=0,
    )
    parser.add_argument(
        "--session",
        type=str,
        default="job-hunt",
        help="ブラウザプロファイルセッション名 (デフォルト: job-hunt)",
    )
    parser.add_argument(
        "--tab",
        choices=["company", "agent", "all"],
        default="all",
        help="取得対象タブ (company: 企業から, agent: エージェントから, all: 両方, デフォルト: all)",
    )
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
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="保存先ディレクトリ (デフォルト: data/green/messages)",
    )

    args = parser.parse_args()

    # 認証確認・自動ハンドオフ
    sys.stderr.write(f"[Green] セッション '{args.session}' の認証状態を確認中...\n")
    if not ensure_site_authenticated("green", session=args.session):
        sys.stderr.write("[Green] 認証が完了しなかったため、処理を中断します。\n")
        sys.exit(2)

    now = datetime.now()
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    threads_dir = output_dir / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        sys.stderr.write("[Green] メッセージデータを取得中...\n")
        data = run_navigate(
            session=args.session,
            tab=args.tab,
            limit=args.limit,
            fetch_details=args.details,
            thread_id=args.thread_id,
        )

        saved_files: list[Path] = []

        # 1. 単一スレッド詳細取得の場合
        if args.thread_id:
            thread_detail = data.get("threadDetail") or {}
            thread_id = args.thread_id
            json_path = threads_dir / f"{thread_id}.json"
            md_path = threads_dir / f"{thread_id}.md"

            json_path.write_text(json.dumps(thread_detail, ensure_ascii=False, indent=2), encoding="utf-8")
            md_path.write_text(generate_thread_markdown(thread_detail, now), encoding="utf-8")

            saved_files.extend([json_path, md_path])

            summary_fn = lambda: print_thread_detail_summary(thread_detail)
            json_payload = thread_detail

        # 2. 一覧取得の場合
        else:
            timestamp_str = now.strftime("%Y-%m-%d-%H%M%S")
            json_path = output_dir / f"{timestamp_str}_messages_{args.tab}.json"
            md_path = output_dir / f"{timestamp_str}_messages_{args.tab}.md"

            json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            md_path.write_text(generate_markdown(data, args.tab, now), encoding="utf-8")

            saved_files.extend([json_path, md_path])

            # 各スレッドの詳細も取得していた場合、スレッド別にも保存
            if args.details:
                for msg in data.get("messages", []):
                    t_id = msg.get("threadId")
                    if t_id and msg.get("messages"):
                        t_json = threads_dir / f"{t_id}.json"
                        t_md = threads_dir / f"{t_id}.md"
                        t_json.write_text(json.dumps(msg, ensure_ascii=False, indent=2), encoding="utf-8")
                        t_md.write_text(generate_thread_markdown(msg, now), encoding="utf-8")
                        saved_files.extend([t_json, t_md])

            summary_fn = lambda: print_formatted_summary(data, tab=args.tab)
            json_payload = data

        for p in saved_files:
            ctx.add_result_path(p)

        ctx.flush_outputs(summary_fn=summary_fn, json_data=json_payload)


if __name__ == "__main__":
    main()
