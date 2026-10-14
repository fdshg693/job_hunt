"""Findyいいね画面自動遷移・求人サマリ取得スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
Findyのログイン状態確認・未ログイン時の通知待機ハンドオフ・いいね画面へのナビゲーションを実行します。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパスを sys.path に追加して直接実行に対応
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
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "findy" / "likes"

TAB_URL_MAP = {
    "main": "https://findy-code.io/likes",
    "agent": "https://findy-code.io/likes/agent",
    "sent": "https://findy-code.io/likes/sent",
    "expired": "https://findy-code.io/likes/expired",
    "passed": "https://findy-code.io/likes/passed",
}


def print_formatted_summary(data: dict[str, Any]) -> None:
    """いいね求人一覧のサマリをコンソールに整形出力する."""
    print("\n========================================================")
    print(" Findy 「いいねを受け取った求人」一覧")
    print(f" URL:  {data.get('url', 'https://findy-code.io/likes')}")
    print(f" 件数: {data.get('totalCount', 0)} 件")
    print("========================================================\n")

    jobs = data.get("jobs", [])
    if not jobs:
        empty_msg = data.get("emptyMessage")
        if empty_msg:
            print(f"（{empty_msg}）")
        else:
            print("現在、受け取ったいいね求人はありません。")
        return

    for idx, job in enumerate(jobs, start=1):
        print(f"[{idx}] {job.get('company', '企業名非公開')} / {job.get('title', '（求人タイトル）')}")
        if job.get("url"):
            print(f"    URL:    {job['url']}")
        if job.get("salary"):
            print(f"    年収:   {job['salary']}")
        if job.get("deadline"):
            print(f"    期限:   いいね有効期限 {job['deadline']}")
        if job.get("tags"):
            print(f"    タグ:   {', '.join(job['tags'])}")
        print("-" * 56)


def generate_markdown(data: dict[str, Any], now: datetime) -> str:
    """いいね求人サマリを構造化フロントマター付きMarkdownに整形する."""
    url = data.get("url", "https://findy-code.io/likes")
    total_count = data.get("totalCount", 0)
    jobs = data.get("jobs", [])
    fetched_at_str = now.isoformat(timespec="seconds")
    fetched_at_display = now.strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "---",
        "source: findy",
        "type: likes",
        f"fetched_at: '{fetched_at_str}'",
        f"url: {url}",
        f"total_count: {total_count}",
        "---",
        "",
        f"# Findy いいね求人一覧 ({now.strftime('%Y-%m-%d %H時')})",
        "",
        f"- 取得日時: {fetched_at_display}",
        f"- 対象URL: {url}",
        f"- 取得件数: {total_count} 件",
        "",
    ]

    if not jobs:
        empty_msg = data.get("emptyMessage") or "現在、受け取ったいいね求人はありません。"
        lines.append(f"> {empty_msg}\n")
        return "\n".join(lines)

    lines.append("## いいね求人一覧")
    lines.append("")
    lines.append("| # | 企業名 | 求人タイトル | 想定年収 | 有効期限 | 求人URL |")
    lines.append("|---|---|---|---|---|---|")
    for idx, job in enumerate(jobs, start=1):
        comp = job.get("company", "企業名非公開").replace("|", "\\|")
        title = job.get("title", "（求人タイトル）").replace("|", "\\|")
        sal = job.get("salary", "-") or "-"
        deadline = job.get("deadline", "-") or "-"
        j_url = job.get("url", "")
        link = f"[詳細]({j_url})" if j_url else "-"
        lines.append(f"| {idx} | {comp} | {title} | {sal} | {deadline} | {link} |")

    lines.append("")
    lines.append("## 詳細リスト")
    lines.append("")
    for idx, job in enumerate(jobs, start=1):
        comp = job.get("company", "企業名非公開")
        title = job.get("title", "（求人タイトル）")
        lines.append(f"### {idx}. {comp} - {title}")
        if job.get("url"):
            lines.append(f"- **URL**: {job['url']}")
        if job.get("salary"):
            lines.append(f"- **想定年収**: {job['salary']}")
        if job.get("deadline"):
            lines.append(f"- **有効期限**: {job['deadline']}")
        if job.get("features"):
            lines.append(f"- **特徴**: {', '.join(job['features'])}")
        if job.get("tags"):
            lines.append(f"- **タグ**: {', '.join(job['tags'])}")
        lines.append("")

    return "\n".join(lines)


def save_likes_result(
    data: dict[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    now: datetime | None = None,
) -> tuple[Path, Path]:
    """いいねデータをMarkdownとJSONでファイル保存する."""
    if now is None:
        now = datetime.now()

    output_dir.mkdir(parents=True, exist_ok=True)
    file_stem = now.strftime("%Y-%m-%d-%H")
    md_path = output_dir / f"{file_stem}.md"
    json_path = output_dir / f"{file_stem}.json"

    md_content = generate_markdown(data, now)
    md_path.write_text(md_content, encoding="utf-8")

    json_payload = {
        "source": "findy",
        "type": "likes",
        "fetched_at": now.isoformat(timespec="seconds"),
        **data,
    }
    json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return md_path, json_path


def main() -> None:
    parser = create_base_parser(
        description="Findyのいいね求人一覧を取得・表示・ファイル保存します。"
    )
    parser.add_argument(
        "--tab",
        choices=["main", "agent", "sent", "expired", "passed"],
        default="main",
        help="取得するいいねタブ (デフォルト: main = いいねを受け取った求人)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"保存先ディレクトリ (デフォルト: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="ファイル保存（Markdown/JSON）をスキップする",
    )
    parser.add_argument(
        "--session",
        default="job-hunt",
        help="ブラウザプロファイルセッション名 (デフォルト: job-hunt)",
    )
    parser.add_argument(
        "--profile-path",
        help="プロファイルディレクトリの直接指定（通常は指定不要）",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="デバッグ用: ブラウザを可視ウィンドウで起動（通常不要）",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="手動ログインの待機タイムアウト秒数 (デフォルト: 120)",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="未認証時のWindows OSトースト通知を抑制する",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="スクリプト終了時にブラウザセッションを閉じずに保持する",
    )

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    navigate_likes_script = FINDY_SCRIPTS_DIR / "navigate_likes.mjs"
    if not navigate_likes_script.exists():
        ctx.error(f"必須スクリプトが見つかりません: {navigate_likes_script}")
        sys.exit(1)

    profile_dir = resolve_profile_path(args.session, args.profile_path)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    target_url = TAB_URL_MAP.get(args.tab, "https://findy-code.io/likes")

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

        # 2. いいね画面へナビゲート＆データ抽出
        nav_result = run_code_script(args.session, navigate_likes_script, timeout=30)
        if not nav_result or not nav_result.get("success"):
            ctx.error("いいね一覧画面への遷移または求人データ取得に失敗しました。")
            sys.exit(1)

        update_profile_last_used(args.session)

        # 3. ファイル保存
        saved_md: Path | None = None
        saved_json: Path | None = None
        if not args.no_save:
            saved_md, saved_json = save_likes_result(nav_result, output_dir=args.output_dir)
            if saved_md:
                ctx.add_result_path(saved_md)
            if saved_json:
                ctx.add_result_path(saved_json)

        def summary_fn() -> None:
            print_formatted_summary(nav_result)
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
