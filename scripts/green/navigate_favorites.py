"""Green の「気になる」一覧（受信・送信・マッチ）を取得して保存する CLI.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
Green（https://www.green-japan.com/favorites/received）の気になる求人・企業一覧を
自動取得し、data/green/favorites/ 配下に構造化フロントマター付きMarkdownおよび
JSON形式で永続化します。

エントリポイントスクリプト規約（.agents/rules/scripts-entrypoint.md）準拠。
デフォルト実行時は生成・該当ファイルパスのみをstdoutに出力し、
人間向けサマリは --summary オプション指定時のみ表示します。
"""

from __future__ import annotations

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
from scripts.common.cli import create_base_parser, entrypoint_guard

GREEN_SCRIPTS_DIR = Path(__file__).resolve().parent
NAVIGATE_FAVORITES_SCRIPT_PATH = GREEN_SCRIPTS_DIR / "navigate_favorites.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "green" / "favorites"
TARGET_URL = "https://www.green-japan.com/favorites/received"

TAB_LABEL_MAP = {
    "received": "企業から（受信）",
    "sent": "あなたから（送信）",
    "matched": "マッチング",
    "uninterested": "興味なし",
}


def print_formatted_summary(data: dict[str, Any], tab: str = "received") -> None:
    """気になる求人一覧のサマリをコンソールに整形出力する."""
    tab_label = TAB_LABEL_MAP.get(tab, tab)
    favorites = data.get("favorites", [])
    total_count = data.get("totalCount", len(favorites))

    print("\n========================================================")
    print(f" Green 気になる求人一覧 [{tab_label}]")
    print(f" URL:  {data.get('url', TARGET_URL)}")
    print(f" 件数: 全 {total_count} 件")
    print("========================================================\n")

    if not favorites:
        print("現在、対象の気になる求人はありません。")
        return

    for idx, fav in enumerate(favorites, start=1):
        company = fav.get("company", "企業名不明")
        job_title = fav.get("jobTitle", "求人タイトル不明")
        event_date = fav.get("eventDate", "")

        header = f"[{idx}] {company} / {job_title}"
        if event_date:
            header += f" ({event_date})"
        print(header)

        if fav.get("salary"):
            print(f"    想定年収: {fav['salary']}")
        if fav.get("location"):
            print(f"    勤務地:   {fav['location']}")
        if fav.get("tags"):
            print(f"    タグ:     {', '.join(fav['tags'])}")
        if fav.get("url"):
            print(f"    求人URL:  {fav['url']}")
        if fav.get("actionButtons"):
            print(f"    操作:     [{', '.join(fav['actionButtons'])}]")
        if fav.get("reviewSnippet"):
            snippet = fav["reviewSnippet"][:100].replace("\n", " ")
            print(f"    求職者の声: {snippet}...")
        print("-" * 56)


def generate_markdown(data: dict[str, Any], tab: str, now: datetime) -> str:
    """気になる一覧を構造化フロントマター付きMarkdownに整形する."""
    tab_label = TAB_LABEL_MAP.get(tab, tab)
    favorites = data.get("favorites", [])
    total_count = data.get("totalCount", len(favorites))
    fetched_at_str = now.isoformat(timespec="seconds")
    fetched_at_display = now.strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "---",
        "source: green",
        "type: favorites",
        f"tab: {tab}",
        f"tab_label: '{tab_label}'",
        f"fetched_at: '{fetched_at_str}'",
        f"total_count: {total_count}",
        "---",
        "",
        f"# Green 気になる求人一覧 ({tab_label})",
        "",
        f"- **取得日時**: {fetched_at_display}",
        f"- **対象URL**: `{data.get('url', TARGET_URL)}`",
        f"- **総件数**: {total_count} 件",
        "",
    ]

    if not favorites:
        lines.append("気になる求人はありません。")
        return "\n".join(lines) + "\n"

    lines.append("## 求人サマリ表")
    lines.append("")
    lines.append("| # | 企業名 | 求人タイトル | 想定年収 | 勤務地 | 受信/送信日 | 求人URL |")
    lines.append("|---|---|---|---|---|---|---|")
    for idx, fav in enumerate(favorites, start=1):
        comp = fav.get("company", "企業名不明").replace("|", "\\|")
        title = fav.get("jobTitle", "求人タイトル不明").replace("|", "\\|")
        sal = fav.get("salary", "-").replace("|", "\\|")
        loc = fav.get("location", "-").replace("|", "\\|")
        ev_date = fav.get("eventDate", "-").replace("|", "\\|")
        u = fav.get("url", "")
        link = f"[詳細]({u})" if u else "-"
        lines.append(f"| {idx} | {comp} | {title} | {sal} | {loc} | {ev_date} | {link} |")

    lines.append("")
    lines.append("## 詳細リスト")
    lines.append("")

    for idx, fav in enumerate(favorites, start=1):
        comp = fav.get("company", "企業名不明")
        title = fav.get("jobTitle", "求人タイトル不明")
        lines.append(f"### {idx}. {comp} - {title}")
        lines.append("")
        lines.append(f"- **企業ID**: `{fav.get('companyId', '')}`")
        lines.append(f"- **求人ID**: `{fav.get('jobId', '')}`")
        if fav.get("url"):
            lines.append(f"- **求人URL**: [{fav['url']}]({fav['url']})")
        if fav.get("salary"):
            lines.append(f"- **想定年収**: {fav['salary']}")
        if fav.get("location"):
            lines.append(f"- **勤務地**: {fav['location']}")
        if fav.get("eventDate"):
            lines.append(f"- **日時**: {fav['eventDate']}")
        if fav.get("tags"):
            lines.append(f"- **タグ**: {', '.join(fav['tags'])}")
        if fav.get("actionButtons"):
            lines.append(f"- **可能アクション**: {', '.join(fav['actionButtons'])}")
        if fav.get("reviewSnippet"):
            lines.append("")
            lines.append("#### 求職者の声・社員レビュー")
            lines.append("")
            lines.append(f"> {fav['reviewSnippet']}")

        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines) + "\n"


def run_navigate(
    session: str,
    tab: str,
    limit: int = 0,
    timeout: int = 60,
) -> dict[str, Any]:
    """Playwrightスクリプトを実行して気になる一覧を取得する."""
    if not NAVIGATE_FAVORITES_SCRIPT_PATH.exists():
        raise RuntimeError(f"Playwrightスクリプトが見つかりません: {NAVIGATE_FAVORITES_SCRIPT_PATH}")

    profile_path = resolve_profile_path(session)
    # ブラウザセッションオープン
    run_playwright_cmd([f"-s={session}", "open", TARGET_URL, f"--profile={profile_path}"])

    template_code = NAVIGATE_FAVORITES_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = (
        template_code.replace("'__GREEN_TAB__'", json.dumps(tab))
        .replace("__LIMIT__", str(limit))
    )

    tmp_script = GREEN_SCRIPTS_DIR / f".tmp_nav_fav_{session}.mjs"
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
        description="Green 受信「気になる」一覧自動取得スクリプト",
        default_limit=0,
        examples=[
            "uv run python scripts/green/navigate_favorites.py --limit 30 --summary",
            "uv run python scripts/green/navigate_favorites.py --tab matched --summary  # マッチ済みのみ",
        ],
        related=[
            "scripts/green/fetch_job.py: 次に使う（気になる求人の詳細を取得）",
        ],
    )
    parser.add_argument(
        "--session",
        type=str,
        default="job-hunt",
        help="ブラウザプロファイルセッション名 (デフォルト: job-hunt)",
    )
    parser.add_argument(
        "--tab",
        choices=["received", "sent", "matched", "uninterested"],
        default="received",
        help="取得対象タブ (received: 企業から, sent: あなたから, matched: マッチング, uninterested: 興味なし, デフォルト: received)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="保存先ディレクトリ (デフォルト: data/green/favorites)",
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

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        sys.stderr.write(f"[Green] 気になるデータ（{TAB_LABEL_MAP.get(args.tab, args.tab)}）を取得中...\n")
        data = run_navigate(
            session=args.session,
            tab=args.tab,
            limit=args.limit,
        )

        saved_files: list[Path] = []
        timestamp_str = now.strftime("%Y-%m-%d-%H%M%S")

        # 1. 日付タイムスタンプ付きファイル保存
        dated_json_path = output_dir / f"{timestamp_str}_favorites_{args.tab}.json"
        dated_md_path = output_dir / f"{timestamp_str}_favorites_{args.tab}.md"

        json_text = json.dumps(data, ensure_ascii=False, indent=2)
        md_text = generate_markdown(data, args.tab, now)

        dated_json_path.write_text(json_text, encoding="utf-8")
        dated_md_path.write_text(md_text, encoding="utf-8")
        saved_files.extend([dated_json_path, dated_md_path])

        # 2. タブ別最新ファイル保存
        latest_tab_json = output_dir / f"latest_{args.tab}.json"
        latest_tab_md = output_dir / f"latest_{args.tab}.md"
        latest_tab_json.write_text(json_text, encoding="utf-8")
        latest_tab_md.write_text(md_text, encoding="utf-8")
        saved_files.extend([latest_tab_json, latest_tab_md])

        # 3. デフォルト（received）の場合は latest.json / latest.md も更新
        if args.tab == "received":
            latest_json = output_dir / "latest.json"
            latest_md = output_dir / "latest.md"
            latest_json.write_text(json_text, encoding="utf-8")
            latest_md.write_text(md_text, encoding="utf-8")
            saved_files.extend([latest_json, latest_md])

        for p in saved_files:
            ctx.add_result_path(p)

        def summary_fn() -> None:
            print_formatted_summary(data, tab=args.tab)

        ctx.flush_outputs(summary_fn=summary_fn, json_data=data)


if __name__ == "__main__":
    main()
