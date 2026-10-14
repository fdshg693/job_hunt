"""Forkwell メッセージ・スカウト自動取得スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
Forkwell Jobsのログイン状態確認・未ログイン時の通知待機ハンドオフ・インボックス画面（/inbox）からの
スカウト・メッセージ一覧抽出・右ペイン詳細取得・構造化フロントマター付きMarkdownおよびJSON形式での永続化を実行します。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/forkwell/ の2階層上)
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

FORKWELL_SCRIPTS_DIR = Path(__file__).resolve().parent
NAVIGATE_SCRIPT_PATH = FORKWELL_SCRIPTS_DIR / "navigate_messages.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "forkwell" / "messages"
TARGET_URL = "https://jobs.forkwell.com/inbox"

TAB_LABEL_MAP = {
    "active": "スカウト・やりとり",
    "archive": "アーカイブ",
    "archived": "アーカイブ",
    "all": "すべて（やりとり＋アーカイブ）",
}


def print_formatted_summary(data: dict[str, Any], tab: str = "active") -> None:
    """メッセージ一覧のサマリをコンソールに整形出力する."""
    tab_label = TAB_LABEL_MAP.get(tab, tab)
    messages = data.get("messages", [])
    total_count = data.get("totalCount", len(messages))

    print("\n========================================================")
    print(f" Forkwell メッセージ・スカウト一覧 [{tab_label}]")
    print(f" URL:  {data.get('url', TARGET_URL)}")
    print(f" 件数: 全 {total_count} 件")
    print("========================================================\n")

    if not messages:
        print("現在、受信したメッセージ・スカウトはありません。")
        return

    for idx, msg in enumerate(messages, start=1):
        badges_str = " ".join(f"[{b}]" for b in msg.get("badges", []))
        if not badges_str and msg.get("scoutType"):
            badges_str = f"[{msg.get('scoutType')}]"

        deadline_str = f" ({msg['deadline']})" if msg.get("deadline") else ""
        status_info = msg.get("statusText") or ""
        if status_info:
            status_info = f" | {status_info}"

        print(f"[{idx}] {badges_str} {msg.get('company', '企業名不明')}{status_info}")
        print(f"    件名:     {msg.get('subject', '（件名なし）')}")
        if msg.get("jobTitle") and msg.get("jobTitle") != msg.get("subject"):
            print(f"    求人名:   {msg['jobTitle']}")
        if msg.get("jobSalary"):
            print(f"    提示年収: {msg['jobSalary']}")
        if msg.get("threadUrl"):
            print(f"    スレッド: {msg['threadUrl']}")
        if msg.get("jobUrl"):
            print(f"    求人URL:  {msg['jobUrl']}")
        if msg.get("snippet"):
            print(f"    抜粋:     {msg['snippet'][:120]}...")
        print("-" * 56)


def generate_markdown(data: dict[str, Any], tab: str, now: datetime) -> str:
    """メッセージ一覧を構造化フロントマター付きMarkdownに整形する."""
    tab_label = TAB_LABEL_MAP.get(tab, tab)
    messages = data.get("messages", [])
    total_count = data.get("totalCount", len(messages))
    fetched_at_str = now.isoformat(timespec="seconds")
    fetched_at_display = now.strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "---",
        "source: forkwell",
        "type: messages",
        f"tab: {tab}",
        f"tab_label: '{tab_label}'",
        f"fetched_at: '{fetched_at_str}'",
        f"url: '{TARGET_URL}'",
        f"total_count: {total_count}",
        "---",
        "",
        f"# Forkwell メッセージ・スカウト一覧 [{tab_label}] ({now.strftime('%Y-%m-%d %H時')})",
        "",
        f"- 取得日時: {fetched_at_display}",
        f"- 対象URL: {TARGET_URL}",
        f"- 取得件数: {total_count} 件",
        "",
    ]

    if not messages:
        lines.append("> 現在、受信したメッセージ・スカウトはありません。\n")
        return "\n".join(lines)

    # 1. 概要テーブル
    lines.append("## メッセージ・スカウト一覧")
    lines.append("")
    lines.append("| # | 種別/バッジ | 企業名 | 件名 | ステータス/期限 | 求人URL | スレッドURL |")
    lines.append("|---|---|---|---|---|---|---|")

    for idx, msg in enumerate(messages, start=1):
        badges = " / ".join(msg.get("badges", [])) or msg.get("scoutType", "スカウト")
        company = (msg.get("company") or "企業名不明").replace("|", "\\|")
        subject = (msg.get("subject") or "（件名なし）").replace("|", "\\|")
        status_text = (msg.get("statusText") or "-").replace("|", "\\|")

        job_link = f"[求人詳細]({msg['jobUrl']})" if msg.get("jobUrl") else "-"
        thread_link = f"[スレッド]({msg['threadUrl']})" if msg.get("threadUrl") else "-"

        lines.append(f"| {idx} | {badges} | {company} | {subject} | {status_text} | {job_link} | {thread_link} |")

    lines.append("")

    # 2. 各メッセージの詳細セクション
    lines.append("## 詳細")
    lines.append("")

    for idx, msg in enumerate(messages, start=1):
        comp = msg.get("company", "企業名不明")
        subj = msg.get("subject", "（件名なし）")
        lines.append(f"### {idx}. {comp} - {subj}")
        lines.append("")
        if msg.get("badges"):
            lines.append(f"- **バッジ**: {', '.join(msg['badges'])}")
        if msg.get("statusText"):
            lines.append(f"- **状況**: {msg['statusText']}")
        if msg.get("deadline"):
            lines.append(f"- **有効期限**: {msg['deadline']}")
        if msg.get("jobTitle"):
            lines.append(f"- **求人タイトル**: {msg['jobTitle']}")
        if msg.get("jobSalary"):
            lines.append(f"- **想定年収**: {msg['jobSalary']}")
        if msg.get("jobRole"):
            lines.append(f"- **職種**: {msg['jobRole']}")
        if msg.get("jobUrl"):
            lines.append(f"- **求人URL**: {msg['jobUrl']}")
        if msg.get("threadUrl"):
            lines.append(f"- **スレッドURL**: {msg['threadUrl']}")
        lines.append("")

        body = (msg.get("body") or "").strip()
        if body:
            lines.append("#### メッセージ本文")
            lines.append("")
            lines.append("```text")
            lines.append(body)
            lines.append("```")
            lines.append("")
        elif msg.get("snippet"):
            lines.append(f"> **抜粋**: {msg['snippet']}")
            lines.append("")

    return "\n".join(lines)


def save_messages_result(
    data: dict[str, Any],
    tab: str = "active",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    now: datetime | None = None,
) -> list[Path]:
    """メッセージデータをMarkdownとJSONでファイル保存する."""
    if now is None:
        now = datetime.now()

    output_dir.mkdir(parents=True, exist_ok=True)
    history_dir = output_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    # 1. 最新ファイル
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
        "source": "forkwell",
        "type": "messages",
        "tab": tab,
        "tab_label": TAB_LABEL_MAP.get(tab, tab),
        "fetched_at": now.isoformat(timespec="seconds"),
        "url": TARGET_URL,
        **data,
    }
    json_str = json.dumps(json_payload, ensure_ascii=False, indent=2)
    latest_json.write_text(json_str, encoding="utf-8")
    history_json.write_text(json_str, encoding="utf-8")

    return [latest_md, latest_json, history_md]


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


def main() -> None:
    """CLIエントリポイント."""
    parser = create_base_parser(
        description="Forkwellのメッセージ・スカウト一覧を取得・表示・ファイル保存します。",
        default_limit=0,
    )
    parser.add_argument(
        "--tab",
        choices=["active", "archive", "archived", "all"],
        default="active",
        help="取得するタブ (active: スカウト・やりとり[デフォルト], archive: アーカイブ, all: すべて)",
    )
    parser.add_argument(
        "--no-details",
        action="store_true",
        help="カードクリックによる右ペイン詳細本文の取得をスキップする（高速一覧取得）",
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
        help="可視ブラウザで起動する（手動操作・デバッグ用）",
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

    # タブ正規化
    selected_tab = "archive" if args.tab == "archived" else args.tab

    if not NAVIGATE_SCRIPT_PATH.exists():
        ctx.error(f"必須スクリプトが見つかりません: {NAVIGATE_SCRIPT_PATH}")
        sys.exit(1)

    profile_dir = resolve_profile_path(args.session, args.profile_path)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. 認証チェック & 必要に応じてブラウザ起動・待機
        ensure_site_authenticated(
            site="forkwell",
            session=args.session,
            target_url=TARGET_URL,
            headed=args.headed,
            timeout=args.timeout,
            no_notify=args.no_notify,
            profile_dir=profile_dir,
            exit_on_fail=True,
        )

        # 2. スカウト・メッセージ取得スクリプト実行
        try:
            nav_result = execute_navigate_messages(
                session=args.session,
                tab=selected_tab,
                limit=args.limit,
                no_details=args.no_details,
                timeout=120,
            )
        except Exception as e:
            ctx.error(f"Forkwell メッセージ一覧の取得に失敗しました: {e}")
            sys.exit(1)

        if not nav_result or not nav_result.get("success"):
            err_msg = ", ".join(nav_result.get("errors", [])) if nav_result else "実行失敗"
            ctx.error(f"Forkwell メッセージ一覧の取得に失敗しました: {err_msg}")
            sys.exit(1)

        update_profile_last_used(args.session)

        # 3. ファイル永続化
        saved_paths: list[Path] = []
        if not args.no_save:
            now = datetime.now()
            saved_paths = save_messages_result(
                nav_result,
                tab=selected_tab,
                output_dir=args.output_dir,
                now=now,
            )
            ctx.add_result_paths(saved_paths)

        def summary_fn() -> None:
            print_formatted_summary(nav_result, tab=selected_tab)
            if saved_paths:
                ctx.log("\n[保存完了ファイル一覧]")
                for sp in saved_paths:
                    ctx.log(f"  - {to_relative_path(sp)}")

        sys.exit(ctx.flush_outputs(summary_fn=summary_fn, json_data=nav_result))

    finally:
        if not args.keep_open:
            run_playwright_cmd([f"-s={args.session}", "close"], timeout=10)


if __name__ == "__main__":
    main()
