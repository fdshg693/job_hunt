"""Findy メッセージ・スカウト自動取得スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
Findyのログイン状態確認・未ログイン時の通知待機ハンドオフ・メッセージ一覧画面からのスカウト/メッセージ抽出を実行します。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/findy/ の2階層上)
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
from scripts.common.cli import EntrypointContext, create_base_parser, to_relative_path

FINDY_SCRIPTS_DIR = Path(__file__).resolve().parent
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


def print_formatted_summary(data: dict[str, Any], tab: str = "all") -> None:
    """メッセージ一覧のサマリをコンソールに整形出力する."""
    tab_label = TAB_LABEL_MAP.get(tab, tab)
    print("\n========================================================")
    print(f" Findy メッセージ・スカウト一覧 [{tab_label}]")
    print(f" URL:  {data.get('url', 'https://findy-code.io/matches')}")
    print(f" 件数: 全 {data.get('totalCount', 0)} 件（取得: {data.get('fetchedCount', len(data.get('messages', [])))} 件）")
    print("========================================================\n")

    messages = data.get("messages", [])
    if not messages:
        print("現在、受信したメッセージ・スカウトはありません。")
        return

    for idx, msg in enumerate(messages, start=1):
        type_badge = f"[{msg.get('scoutType', '通常')}]"
        unread_badge = "[未読] " if msg.get("isUnread") else ""
        replied_badge = "[返信済] " if msg.get("isReplied") else "[未返信] "
        print(f"[{idx}] {unread_badge}{replied_badge}{type_badge} {msg.get('company', '企業名不明')}")
        print(f"    件名:     {msg.get('subject', '（件名なし）')}")
        if msg.get("date"):
            print(f"    日時:     {msg['date']}")
        if msg.get("url"):
            print(f"    スレッド: {msg['url']}")
        if msg.get("jobUrl"):
            print(f"    求人URL:  {msg['jobUrl']}")
        if msg.get("snippet"):
            print(f"    抜粋:     {msg['snippet'][:100]}...")
        print("-" * 56)


def generate_markdown(data: dict[str, Any], tab: str, now: datetime) -> str:
    """メッセージ一覧を構造化フロントマター付きMarkdownに整形する."""
    tab_label = TAB_LABEL_MAP.get(tab, tab)
    url = data.get("url", "https://findy-code.io/matches")
    total_count = data.get("totalCount", 0)
    messages = data.get("messages", [])
    fetched_count = len(messages)
    fetched_at_str = now.isoformat(timespec="seconds")
    fetched_at_display = now.strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "---",
        "source: findy",
        "type: messages",
        f"tab: {tab}",
        f"tab_label: '{tab_label}'",
        f"fetched_at: '{fetched_at_str}'",
        f"url: {url}",
        f"total_count: {total_count}",
        f"fetched_count: {fetched_count}",
        "---",
        "",
        f"# Findy メッセージ・スカウト一覧 [{tab_label}] ({now.strftime('%Y-%m-%d %H時')})",
        "",
        f"- 取得日時: {fetched_at_display}",
        f"- 対象URL: {url}",
        f"- 総件数: {total_count} 件（取得件数: {fetched_count} 件）",
        "",
    ]

    if not messages:
        lines.append("> 現在、受信したメッセージ・スカウトはありません。\n")
        return "\n".join(lines)

    lines.append("## メッセージ・スカウト一覧")
    lines.append("")
    lines.append("| # | 状態 | 返信 | 種別 | 企業名 | 件名・内容 | 日時 | スレッドURL |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for idx, msg in enumerate(messages, start=1):
        status = "未読" if msg.get("isUnread") else "既読"
        replied = "返信済" if msg.get("isReplied") else "未返信"
        scout_type = msg.get("scoutType", "通常").replace("|", "\\|")
        company = msg.get("company", "企業名不明").replace("|", "\\|")
        subject = msg.get("subject", "（件名なし）").replace("|", "\\|")
        date_str = msg.get("date", "-").replace("|", "\\|")
        m_url = msg.get("url", "")
        link = f"[スレッド]({m_url})" if m_url else "-"
        lines.append(
            f"| {idx} | {status} | {replied} | {scout_type} | {company} | {subject} | {date_str} | {link} |"
        )

    lines.append("")
    lines.append("## 詳細リスト")
    lines.append("")
    for idx, msg in enumerate(messages, start=1):
        status = "未読" if msg.get("isUnread") else "既読"
        replied = "返信済" if msg.get("isReplied") else "未返信"
        company = msg.get("company", "企業名不明")
        subject = msg.get("subject", "（件名なし）")
        lines.append(f"### {idx}. [{status} / {replied}] {company} - {subject}")
        if msg.get("url"):
            lines.append(f"- **スレッドURL**: {msg['url']}")
        if msg.get("jobUrl"):
            lines.append(f"- **求人URL**: {msg['jobUrl']}")
        if msg.get("date"):
            lines.append(f"- **送受信日時**: {msg['date']}")
        if msg.get("scoutType"):
            lines.append(f"- **スカウト種別**: {msg['scoutType']}")
        if msg.get("snippet"):
            lines.append(f"- **本文抜粋**: {msg['snippet']}")
        if msg.get("latestMessage") and len(msg.get("latestMessage", "")) > len(msg.get("snippet", "")):
            # スニペット以上の全文がある場合は引用表示
            lines.append("- **最新メッセージ全文**:")
            lines.append("  ```")
            for m_line in msg["latestMessage"].splitlines():
                lines.append(f"  {m_line}")
            lines.append("  ```")
        lines.append("")

    return "\n".join(lines)


def save_messages_result(
    data: dict[str, Any],
    tab: str = "all",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    now: datetime | None = None,
) -> list[Path]:
    """メッセージデータを最新スナップショットと履歴ファイルとしてMarkdown/JSON保存する."""
    if now is None:
        now = datetime.now()

    output_dir.mkdir(parents=True, exist_ok=True)
    history_dir = output_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    # 1. 最新スナップショットファイル
    latest_md = output_dir / f"messages_{tab}.md"
    latest_json = output_dir / f"messages_{tab}.json"

    # 2. タイムスタンプ付き履歴ファイル
    time_str = now.strftime("%Y%m%d_%H%M%S")
    history_md = history_dir / f"messages_{tab}_{time_str}.md"
    history_json = history_dir / f"messages_{tab}_{time_str}.json"

    md_content = generate_markdown(data, tab, now)
    latest_md.write_text(md_content, encoding="utf-8")
    history_md.write_text(md_content, encoding="utf-8")

    json_payload = {
        "source": "findy",
        "type": "messages",
        "tab": tab,
        "tab_label": TAB_LABEL_MAP.get(tab, tab),
        "fetched_at": now.isoformat(timespec="seconds"),
        **data,
    }
    json_str = json.dumps(json_payload, ensure_ascii=False, indent=2)
    latest_json.write_text(json_str, encoding="utf-8")
    history_json.write_text(json_str, encoding="utf-8")

    return [latest_md, latest_json, history_md]


def main() -> None:
    parser = create_base_parser(
        description="Findyのメッセージ・スカウト一覧を取得・表示・ファイル保存します。"
    )
    parser.add_argument(
        "--tab",
        choices=["all", "unread", "unreplied", "archived"],
        default="all",
        help="取得するタブ・フィルター (all: すべて, unread: 未読, unreplied: 未返信, archived: 非表示)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"結果出力先ディレクトリ（デフォルト: {DEFAULT_OUTPUT_DIR}）",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="ファイルへの保存を行わず画面表示のみ行う",
    )
    parser.add_argument(
        "--session",
        default="job-hunt",
        help="Playwright CLIセッション名（デフォルト: job-hunt）",
    )
    parser.add_argument(
        "--profile-path",
        help="ブラウザプロファイルディレクトリのパス（省略時は自動解決）",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="可視ブラウザで起動する（手動操作用）",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="手動ログイン待機のタイムアウト秒数（デフォルト: 120秒）",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="認証壁検知時のOSトースト通知を送信しない",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="処理完了後にブラウザセッションを閉じずに保持する",
    )

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    navigate_messages_script = FINDY_SCRIPTS_DIR / "navigate_messages.mjs"
    if not navigate_messages_script.exists():
        ctx.error(f"必須スクリプトが見つかりません: {navigate_messages_script}")
        sys.exit(1)

    profile_dir = resolve_profile_path(args.session, args.profile_path)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    target_url = TAB_URL_MAP.get(args.tab, "https://findy-code.io/matches")

    try:
        # 1. 共通認証エンジンによるブラウザ起動・認証確認・手動待機ハンドオフ
        ensure_site_authenticated(
            site="findy",
            session=args.session,
            target_url=target_url,
            headed=args.headed,
            timeout=args.timeout,
            no_notify=args.no_notify,
            profile_dir=profile_dir,
            exit_on_fail=True,
        )

        # 2. メッセージ画面へナビゲート＆データ抽出
        nav_result = run_code_script(
            args.session,
            navigate_messages_script,
            timeout=40,
        )
        if not nav_result or not nav_result.get("success"):
            ctx.error("メッセージ一覧画面への遷移またはデータ取得に失敗しました。")
            sys.exit(1)

        # 件数制限の適用
        if args.limit and args.limit > 0 and "messages" in nav_result:
            nav_result["messages"] = nav_result["messages"][: args.limit]
            nav_result["fetchedCount"] = len(nav_result["messages"])

        update_profile_last_used(args.session)

        # 3. ファイル保存
        saved_paths: list[Path] = []
        if not args.no_save:
            saved_paths = save_messages_result(nav_result, tab=args.tab, output_dir=args.output_dir)
            for p in saved_paths:
                ctx.add_result_path(p)

        def summary_fn() -> None:
            print_formatted_summary(nav_result, tab=args.tab)
            if saved_paths:
                ctx.log("\n[保存完了]")
                for p in saved_paths:
                    ctx.log(f"  {to_relative_path(p)}")

        sys.exit(ctx.flush_outputs(summary_fn=summary_fn, json_data=nav_result))

    finally:
        if not args.keep_open:
            run_playwright_cmd([f"-s={args.session}", "close"], timeout=10)


if __name__ == "__main__":
    main()
