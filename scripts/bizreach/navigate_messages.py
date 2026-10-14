"""ビズリーチ メッセージ自動取得スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
ビズリーチのログイン状態確認・未ログイン時の通知待機ハンドオフ・メッセージ一覧画面からのスカウト/メッセージ抽出を実行します。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/bizreach/ の2階層上)
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

BIZREACH_SCRIPTS_DIR = Path(__file__).resolve().parent
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


def print_formatted_summary(data: dict[str, Any], tab: str = "all") -> None:
    """メッセージ一覧のサマリをコンソールに整形出力する."""
    tab_label = TAB_LABEL_MAP.get(tab, tab)
    print("\n========================================================")
    print(f" ビズリーチ メッセージ・スカウト一覧 [{tab_label}]")
    print(f" URL:  {data.get('url', 'https://www.bizreach.jp/messages/')}")
    print(f" 件数: {data.get('totalCount', 0)} 件")
    print("========================================================\n")

    messages = data.get("messages", [])
    if not messages:
        print("現在、受信したメッセージ・スカウトはありません。")
        return

    for idx, msg in enumerate(messages, start=1):
        type_badge = f"[{msg.get('scoutType', '通常')}]"
        unread_badge = "[未読] " if msg.get("isUnread") else ""
        print(f"[{idx}] {unread_badge}{type_badge} {msg.get('sender', '送信者名不明')}")
        print(f"    件名:     {msg.get('subject', '（件名なし）')}")
        if msg.get("date"):
            print(f"    日時:     {msg['date']}")
        if msg.get("url"):
            print(f"    URL:      {msg['url']}")
        if msg.get("attachedJobs"):
            print(f"    添付求人: {len(msg['attachedJobs'])} 件")
            for j_idx, job in enumerate(msg["attachedJobs"], start=1):
                j_title = job.get("title", "")
                j_company = job.get("company", "")
                j_salary = job.get("salary", "")
                j_url = job.get("url", "")
                sal_disp = f" ({j_salary})" if j_salary else ""
                print(f"      - [{j_idx}] {j_company} | {j_title}{sal_disp}")
                if j_url:
                    print(f"           {j_url}")
        if msg.get("snippet"):
            print(f"    抜粋:     {msg['snippet'][:100]}...")
        print("-" * 56)


def generate_markdown(data: dict[str, Any], tab: str, now: datetime) -> str:
    """メッセージ一覧を構造化フロントマター付きMarkdownに整形する."""
    tab_label = TAB_LABEL_MAP.get(tab, tab)
    url = data.get("url", "https://www.bizreach.jp/messages/")
    total_count = data.get("totalCount", 0)
    messages = data.get("messages", [])
    fetched_at_str = now.isoformat(timespec="seconds")
    fetched_at_display = now.strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "---",
        "source: bizreach",
        "type: messages",
        f"tab: {tab}",
        f"tab_label: '{tab_label}'",
        f"fetched_at: '{fetched_at_str}'",
        f"url: {url}",
        f"total_count: {total_count}",
        "---",
        "",
        f"# ビズリーチ メッセージ・スカウト一覧 [{tab_label}] ({now.strftime('%Y-%m-%d %H時')})",
        "",
        f"- 取得日時: {fetched_at_display}",
        f"- 対象URL: {url}",
        f"- 取得件数: {total_count} 件",
        "",
    ]

    if not messages:
        lines.append("> 現在、受信したメッセージ・スカウトはありません。\n")
        return "\n".join(lines)

    lines.append("## メッセージ・スカウト一覧")
    lines.append("")
    lines.append("| # | 状態 | 種別 | 送信者 | 件名 | 日時 | 添付求人 | スレッドURL |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for idx, msg in enumerate(messages, start=1):
        status = "未読" if msg.get("isUnread") else "既読"
        scout_type = msg.get("scoutType", "通常").replace("|", "\\|")
        sender = msg.get("sender", "送信者不明").replace("|", "\\|")
        subject = msg.get("subject", "（件名なし）").replace("|", "\\|")
        date_str = msg.get("date", "-").replace("|", "\\|")
        attached_count = f"{len(msg.get('attachedJobs', []))} 件" if msg.get("attachedJobs") else "-"
        m_url = msg.get("url", "")
        link = f"[詳細]({m_url})" if m_url else "-"
        lines.append(
            f"| {idx} | {status} | {scout_type} | {sender} | {subject} | {date_str} | {attached_count} | {link} |"
        )

    lines.append("")
    lines.append("## 詳細リスト")
    lines.append("")
    for idx, msg in enumerate(messages, start=1):
        status = "未読" if msg.get("isUnread") else "既読"
        sender = msg.get("sender", "送信者不明")
        subject = msg.get("subject", "（件名なし）")
        lines.append(f"### {idx}. [{status}] {sender} - {subject}")
        if msg.get("url"):
            lines.append(f"- **スレッドURL**: {msg['url']}")
        if msg.get("date"):
            lines.append(f"- **受信日時**: {msg['date']}")
        if msg.get("scoutType"):
            lines.append(f"- **スカウト種別**: {msg['scoutType']}")
        if msg.get("snippet"):
            lines.append(f"- **本文抜粋**: {msg['snippet']}")
        if msg.get("attachedJobs"):
            lines.append("- **添付求人一覧**:")
            for j_idx, job in enumerate(msg["attachedJobs"], start=1):
                j_title = job.get("title", "")
                j_comp = job.get("company", "")
                j_sal = job.get("salary", "")
                j_url = job.get("url", "")
                sal_part = f" ({j_sal})" if j_sal else ""
                url_part = f" [リンク]({j_url})" if j_url else ""
                lines.append(f"  - [{j_idx}] {j_comp} | {j_title}{sal_part}{url_part}")
        lines.append("")

    return "\n".join(lines)


def save_messages_result(
    data: dict[str, Any],
    tab: str = "all",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    now: datetime | None = None,
) -> tuple[Path, Path]:
    """メッセージデータをMarkdownとJSONでファイル保存する."""
    if now is None:
        now = datetime.now()

    output_dir.mkdir(parents=True, exist_ok=True)
    file_stem = f"{now.strftime('%Y-%m-%d-%H')}_{tab}"
    md_path = output_dir / f"{file_stem}.md"
    json_path = output_dir / f"{file_stem}.json"

    md_content = generate_markdown(data, tab, now)
    md_path.write_text(md_content, encoding="utf-8")

    json_payload = {
        "source": "bizreach",
        "type": "messages",
        "tab": tab,
        "tab_label": TAB_LABEL_MAP.get(tab, tab),
        "fetched_at": now.isoformat(timespec="seconds"),
        **data,
    }
    json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return md_path, json_path


def main() -> None:
    parser = create_base_parser(
        description="ビズリーチのメッセージ・スカウト一覧を取得・表示・ファイル保存します。"
    )
    parser.add_argument(
        "--tab",
        choices=["all", "direct", "headhunter"],
        default="all",
        help="取得するタブ (all: すべて, direct: 企業直コンタクト, headhunter: ヘッドハンター)",
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

    navigate_messages_script = BIZREACH_SCRIPTS_DIR / "navigate_messages.mjs"
    if not navigate_messages_script.exists():
        ctx.error(f"必須スクリプトが見つかりません: {navigate_messages_script}")
        sys.exit(1)

    profile_dir = resolve_profile_path(args.session, args.profile_path)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    target_url = TAB_URL_MAP.get(args.tab, "https://www.bizreach.jp/messages/")

    try:
        # 1. 共通認証エンジンによるブラウザ起動・認証確認・手動待機ハンドオフ
        ensure_site_authenticated(
            site="bizreach",
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
            nav_result["totalCount"] = len(nav_result["messages"])

        update_profile_last_used(args.session)

        # 3. ファイル保存
        saved_md: Path | None = None
        saved_json: Path | None = None
        if not args.no_save:
            saved_md, saved_json = save_messages_result(nav_result, tab=args.tab, output_dir=args.output_dir)
            if saved_md:
                ctx.add_result_path(saved_md)
            if saved_json:
                ctx.add_result_path(saved_json)

        def summary_fn() -> None:
            print_formatted_summary(nav_result, tab=args.tab)
            if saved_md and saved_json:
                ctx.log("\n[保存完了]")
                ctx.log(f"  Markdown: {to_relative_path(saved_md)}")
                ctx.log(f"  JSON:     {to_relative_path(saved_json)}")

        sys.exit(ctx.flush_outputs(summary_fn=summary_fn, json_data=nav_result))

    finally:
        if not args.keep_open:
            run_playwright_cmd([f"-s={args.session}", "close"], timeout=10)


if __name__ == "__main__":
    main()
