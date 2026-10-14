"""LinkedIn メッセージ（会話一覧・スレッド本文）自動取得スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
LinkedInのログイン状態確認・未ログイン時の通知待機ハンドオフ・メッセージ画面（/messaging/）からの
会話一覧抽出（内部スクロールによる遅延読込対応）・任意でスレッド本文取得・
構造化フロントマター付きMarkdownおよびJSON形式での永続化を実行します。

注意: スレッドを開くと相手に既読が通知されます（--threads 指定時のみ実施）。
また /messaging/ を開くと LinkedIn の仕様により先頭スレッドが自動で開かれます。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/linkedin/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.auth_engine import ensure_site_authenticated
from scripts.common.browser_auth import (
    resolve_profile_path,
    run_code_snippet,
    run_playwright_cmd,
    update_profile_last_used,
)
from scripts.common.cli import EntrypointContext, create_base_parser, to_relative_path

LINKEDIN_SCRIPTS_DIR = Path(__file__).resolve().parent
NAVIGATE_SCRIPT_PATH = LINKEDIN_SCRIPTS_DIR / "navigate_messages.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "linkedin" / "messages"
TARGET_URL = "https://www.linkedin.com/messaging/"

FILTER_CHOICES = ["all", "Focused", "Jobs", "Unread", "Connections", "InMail", "Starred"]


def print_formatted_summary(data: dict[str, Any], filter_name: str = "all") -> None:
    """メッセージ一覧のサマリをコンソールに整形出力する."""
    messages = data.get("messages", [])
    total_count = data.get("totalCount", len(messages))

    print("\n========================================================")
    print(f" LinkedIn メッセージ一覧 [フィルタ: {filter_name}]")
    print(f" URL:  {TARGET_URL}")
    print(f" 件数: {total_count} 件")
    print("========================================================\n")

    if not messages:
        print("該当するメッセージはありません。")
        return

    for idx, msg in enumerate(messages, start=1):
        flags = []
        if msg.get("unread"):
            flags.append("未読")
        if msg.get("label"):
            flags.append(msg["label"])
        flag_str = " ".join(f"[{f}]" for f in flags)
        print(f"[{idx}] {flag_str} {msg.get('name') or '名前不明'}  ({msg.get('date') or '-'})")
        if msg.get("snippet"):
            print(f"    抜粋:     {msg['snippet'][:120]}")
        if msg.get("threadUrl"):
            print(f"    スレッド: {msg['threadUrl']}")
        if msg.get("thread"):
            print(f"    本文:     {len(msg['thread'])} メッセージ取得")
        print("-" * 56)


def generate_markdown(data: dict[str, Any], filter_name: str, now: datetime) -> str:
    """メッセージ一覧を構造化フロントマター付きMarkdownに整形する."""
    messages = data.get("messages", [])
    total_count = data.get("totalCount", len(messages))
    fetched_at_str = now.isoformat(timespec="seconds")

    lines = [
        "---",
        "source: linkedin",
        "type: messages",
        f"filter: {filter_name}",
        f"fetched_at: '{fetched_at_str}'",
        f"url: '{TARGET_URL}'",
        f"total_count: {total_count}",
        "---",
        "",
        f"# LinkedIn メッセージ一覧 [{filter_name}] ({now.strftime('%Y-%m-%d %H時')})",
        "",
        f"- 取得日時: {now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 対象URL: {TARGET_URL}",
        f"- 取得件数: {total_count} 件",
        "",
    ]

    if not messages:
        lines.append("> 該当するメッセージはありません。\n")
        return "\n".join(lines)

    lines += [
        "## 会話一覧",
        "",
        "| # | 未読 | 種別 | 相手 | 日付 | 抜粋 |",
        "|---|---|---|---|---|---|",
    ]
    for idx, msg in enumerate(messages, start=1):
        name = (msg.get("name") or "名前不明").replace("|", "\\|")
        snippet = (msg.get("snippet") or "-")[:80].replace("|", "\\|")
        label = msg.get("label") or "-"
        unread = "●" if msg.get("unread") else "-"
        lines.append(f"| {idx} | {unread} | {label} | {name} | {msg.get('date') or '-'} | {snippet} |")
    lines.append("")

    lines += ["## 詳細", ""]
    for idx, msg in enumerate(messages, start=1):
        lines.append(f"### {idx}. {msg.get('name') or '名前不明'}")
        lines.append("")
        lines.append(f"- **日付**: {msg.get('date') or '-'}")
        if msg.get("label"):
            lines.append(f"- **種別**: {msg['label']}")
        lines.append(f"- **未読**: {'はい' if msg.get('unread') else 'いいえ'}")
        if msg.get("threadUrl"):
            lines.append(f"- **スレッドURL**: {msg['threadUrl']}")
        lines.append("")
        thread = msg.get("thread") or []
        if thread:
            lines.append("#### スレッド本文")
            lines.append("")
            for t in thread:
                when = " ".join(x for x in [t.get("day"), t.get("time")] if x)
                lines.append(f"**{t.get('sender') or '不明'}** ({when or '-'})")
                lines.append("")
                lines.append("```text")
                lines.append(t.get("text", ""))
                lines.append("```")
                lines.append("")
        elif msg.get("snippet"):
            lines.append(f"> **抜粋**: {msg['snippet']}")
            lines.append("")

    return "\n".join(lines)


def save_messages_result(
    data: dict[str, Any],
    filter_name: str = "all",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    now: datetime | None = None,
) -> list[Path]:
    """メッセージデータを latest と履歴（Markdown / JSON）として保存する."""
    if now is None:
        now = datetime.now()

    output_dir.mkdir(parents=True, exist_ok=True)
    history_dir = output_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    slug = filter_name.lower()
    latest_md = output_dir / f"messages_{slug}.md"
    latest_json = output_dir / f"messages_{slug}.json"

    time_str = now.strftime("%Y%m%d_%H%M%S")
    history_md = history_dir / f"messages_{slug}_{time_str}.md"
    history_json = history_dir / f"messages_{slug}_{time_str}.json"

    md_content = generate_markdown(data, filter_name, now)
    latest_md.write_text(md_content, encoding="utf-8")
    history_md.write_text(md_content, encoding="utf-8")

    json_payload = {
        "source": "linkedin",
        "type": "messages",
        "filter": filter_name,
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
    filter_name: str = "all",
    limit: int = 0,
    fetch_threads: bool = False,
    timeout: float = 180.0,
) -> dict[str, Any]:
    """navigate_messages.mjs にパラメータを注入して実行する."""
    if not NAVIGATE_SCRIPT_PATH.exists():
        raise RuntimeError(f"メッセージスクリプトが見つかりません: {NAVIGATE_SCRIPT_PATH}")

    template_code = NAVIGATE_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = (
        template_code.replace("'__LI_FILTER__'", json.dumps(filter_name))
        .replace("__FETCH_THREADS__", "true" if fetch_threads else "false")
        .replace("__LIMIT__", str(limit))
    ).strip().rstrip(";")

    result = run_code_snippet(session, run_code, timeout=timeout)
    if not result:
        raise RuntimeError("Playwrightスクリプトの実行に失敗しました")
    return result


def main() -> None:
    """CLIエントリポイント."""
    parser = create_base_parser(
        description=(
            "LinkedInのメッセージ会話一覧を取得・表示・ファイル保存します。\n"
            "注意: --threads を指定するとスレッドを開くため、相手に既読が通知されます。\n"
            "（/messaging/ を開くと先頭スレッドは LinkedIn により自動で開かれます）"
        ),
        default_limit=0,
    )
    parser.add_argument(
        "--filter",
        choices=FILTER_CHOICES,
        default="all",
        help="会話フィルタ (all: 絞り込みなし[デフォルト], Focused, Jobs, Unread, Connections, InMail, Starred)",
    )
    parser.add_argument(
        "--threads",
        action="store_true",
        help="各会話を開いてスレッド本文も取得する（既読副作用あり・低速。-n で件数を絞ることを推奨）",
    )
    parser.add_argument("-o", "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help=f"結果出力先ディレクトリ（デフォルト: {DEFAULT_OUTPUT_DIR}）")
    parser.add_argument("--no-save", action="store_true", help="ファイルへの保存を行わず画面表示のみ行う")
    parser.add_argument("--session", default="job-hunt", help="Playwright CLIセッション名（デフォルト: job-hunt）")
    parser.add_argument("--profile-path", help="ブラウザプロファイルディレクトリのパス（省略時は自動解決）")
    parser.add_argument("--headed", action="store_true", help="可視ブラウザで起動する（手動操作・デバッグ用）")
    parser.add_argument("--timeout", type=float, default=120.0, help="手動ログイン待機のタイムアウト秒数（デフォルト: 120秒）")
    parser.add_argument("--no-notify", action="store_true", help="認証壁検知時のOSトースト通知を送信しない")
    parser.add_argument("--keep-open", action="store_true", help="処理完了後にブラウザセッションを閉じずに保持する")

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    if not NAVIGATE_SCRIPT_PATH.exists():
        ctx.error(f"必須スクリプトが見つかりません: {NAVIGATE_SCRIPT_PATH}")
        sys.exit(1)

    profile_dir = resolve_profile_path(args.session, args.profile_path)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    try:
        ensure_site_authenticated(
            site="linkedin",
            session=args.session,
            target_url=TARGET_URL,
            headed=args.headed,
            timeout=args.timeout,
            no_notify=args.no_notify,
            profile_dir=profile_dir,
            exit_on_fail=True,
        )

        try:
            run_timeout = 180.0 + (args.limit or 30) * 8 if args.threads else 180.0
            nav_result = execute_navigate_messages(
                session=args.session,
                filter_name=args.filter,
                limit=args.limit or 0,
                fetch_threads=args.threads,
                timeout=run_timeout,
            )
        except Exception as e:
            ctx.error(f"LinkedIn メッセージの取得に失敗しました: {e}")
            sys.exit(1)

        if not nav_result.get("success"):
            err_msg = ", ".join(nav_result.get("errors", [])) or "実行失敗"
            ctx.error(f"LinkedIn メッセージの取得に失敗しました: {err_msg}")
            sys.exit(1)

        for err in nav_result.get("errors", []):
            ctx.warn(err)

        update_profile_last_used(args.session)

        saved_paths: list[Path] = []
        if not args.no_save:
            saved_paths = save_messages_result(
                nav_result,
                filter_name=args.filter,
                output_dir=args.output_dir,
                now=datetime.now(),
            )
            ctx.add_result_paths(saved_paths)

        def summary_fn() -> None:
            print_formatted_summary(nav_result, filter_name=args.filter)
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
