"""LinkedIn 受信招待（つながり申請）一覧自動取得・価値評価スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
LinkedInの受信招待一覧（/mynetwork/invitation-manager/received/）から、
受信したつながり申請の一覧（氏名、肩書き、プロフィールURL、共通コネクション数、添付メッセージ等）を抽出し、
ユーザープロファイル（profile/preferences.md, skills.md, internal/criteria.md）と照合して
つながりの価値（属性分類、評価ランク、推奨アクション、マッチ点・注意点）を判定し、
構造化フロントマター付きMarkdownおよびJSON形式で永続化します。

注意: つながり申請の自動承認（Accept）や拒否（Ignore）は行わず、取得・検討専用です。
"""

from __future__ import annotations

import json
import sys
import time
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
from scripts.linkedin.invitation_evaluator import evaluate_invitations_batch

LINKEDIN_SCRIPTS_DIR = Path(__file__).resolve().parent
FETCH_SCRIPT_PATH = LINKEDIN_SCRIPTS_DIR / "fetch_invitations.mjs"
FETCH_PROFILE_SCRIPT_PATH = LINKEDIN_SCRIPTS_DIR / "fetch_applicant_profile.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "linkedin" / "invitations"
TARGET_URL = "https://www.linkedin.com/mynetwork/invitation-manager/received/"


def print_formatted_summary(data: dict[str, Any]) -> None:
    """受信招待一覧および価値評価のサマリをコンソールに整形出力する."""
    invitations = data.get("invitations", [])
    total_count = data.get("totalCount", len(invitations))

    print("\n========================================================")
    print(" LinkedIn 受信招待（つながり申請）一覧 & つながり価値評価")
    print(f" URL:  {TARGET_URL}")
    print(f" 件数: {total_count} 件")
    print("========================================================\n")

    if not invitations:
        if data.get("emptyState"):
            print("保留中の受信招待（つながり申請）はありません。")
        else:
            print("受信招待は見つかりませんでした。")
        return

    for idx, inv in enumerate(invitations, start=1):
        name = inv.get("name") or "氏名不明"
        headline = inv.get("headline") or "肩書きなし"
        profile_url = inv.get("profileUrl") or "-"
        mutual = inv.get("mutualConnections") or "-"
        has_msg = "あり" if inv.get("hasMessage") else "なし"
        eval_data = inv.get("evaluation") or {}

        print(f"[{idx}] {name}")
        if eval_data:
            rank_label = eval_data.get("rank_label") or eval_data.get("rank") or "-"
            cat_label = eval_data.get("category_label") or "-"
            action = eval_data.get("action") or "-"
            score = eval_data.get("score", 0)
            print(f"    【評価ランク】: {rank_label} (スコア: {score}/100)")
            print(f"    【属性分類】:   {cat_label}")
            print(f"    【推奨判断】:   {action}")

        print(f"    肩書き:       {headline}")
        print(f"    URL:          {profile_url}")
        if mutual != "-":
            print(f"    共通:         {mutual}")
        print(f"    メッセージ:   {has_msg}")

        if inv.get("message"):
            msg_snippet = inv["message"].replace("\n", " ")
            if len(msg_snippet) > 120:
                msg_snippet = msg_snippet[:120] + "..."
            print(f"    添付本文:     「{msg_snippet}」")

        if eval_data:
            match_points = eval_data.get("match_points", [])
            caution_points = eval_data.get("caution_points", [])
            if match_points:
                print("    [マッチ要因]")
                for mp in match_points:
                    print(f"      + {mp}")
            if caution_points:
                print("    [注意・懸念要因]")
                for cp in caution_points:
                    print(f"      - {cp}")
            if eval_data.get("summary_comment"):
                print(f"    [所感コメント]: {eval_data['summary_comment']}")

        prof_details = inv.get("profileDetails") or {}
        if prof_details.get("currentCompany") or prof_details.get("about"):
            print("    [プロフィール詳細]")
            if prof_details.get("currentCompany"):
                print(f"      現職: {prof_details.get('currentCompany')}")
            if prof_details.get("about"):
                about_snip = prof_details["about"].replace("\n", " ")
                if len(about_snip) > 80:
                    about_snip = about_snip[:80] + "..."
                print(f"      自己紹介: {about_snip}")

        if inv.get("replyUrl"):
            print(f"    返信URL:      {inv['replyUrl']}")
        print("-" * 56)


def generate_markdown(data: dict[str, Any], now: datetime) -> str:
    """受信招待一覧および価値評価を構造化フロントマター付きMarkdownに整形する."""
    invitations = data.get("invitations", [])
    total_count = data.get("totalCount", len(invitations))
    fetched_at_str = now.isoformat(timespec="seconds")
    fetched_at_display = now.strftime("%Y-%m-%d %H:%M:%S")

    # ランク別集計
    rank_counts: dict[str, int] = {"S": 0, "A": 0, "B": 0, "C": 0}
    for inv in invitations:
        r = (inv.get("evaluation") or {}).get("rank")
        if r in rank_counts:
            rank_counts[r] += 1

    lines = [
        "---",
        "source: linkedin",
        "type: invitations",
        f"fetched_at: '{fetched_at_str}'",
        f"url: '{TARGET_URL}'",
        f"total_count: {total_count}",
        f"rank_s_count: {rank_counts['S']}",
        f"rank_a_count: {rank_counts['A']}",
        f"rank_b_count: {rank_counts['B']}",
        f"rank_c_count: {rank_counts['C']}",
        "---",
        "",
        f"# LinkedIn 受信招待一覧 & つながり価値評価 ({now.strftime('%Y-%m-%d %H時')})",
        "",
        f"- 取得日時: {fetched_at_display}",
        f"- 対象URL: {TARGET_URL}",
        f"- 受信招待件数: {total_count} 件",
        f"- 評価内訳: S: {rank_counts['S']}件 / A: {rank_counts['A']}件 / B: {rank_counts['B']}件 / C: {rank_counts['C']}件",
        "",
    ]

    if not invitations:
        if data.get("emptyState"):
            lines.append("> 保留中の受信招待（つながり申請）はありません。\n")
        else:
            lines.append("> 該当する受信招待はありません。\n")
        return "\n".join(lines)

    lines += [
        "## 受信招待一覧サマリ",
        "",
        "| # | ランク | 属性カテゴリ | 氏名 | 肩書き (Headline) | メッセージ | 推奨判断 |",
        "|---|---|---|---|---|---|---|",
    ]
    for idx, inv in enumerate(invitations, start=1):
        name = (inv.get("name") or "氏名不明").replace("|", "\\|")
        headline = (inv.get("headline") or "-").replace("|", "\\|")
        if len(headline) > 40:
            headline = headline[:37] + "..."
        has_msg = "あり" if inv.get("hasMessage") else "-"
        p_url = inv.get("profileUrl") or ""
        p_link = f"[{name}]({p_url})" if p_url else name

        eval_data = inv.get("evaluation") or {}
        rank_badge = eval_data.get("rank") or "-"
        cat_badge = eval_data.get("category_label") or "-"
        action = eval_data.get("action") or "-"
        if len(action) > 28:
            action = action[:25] + "..."

        lines.append(f"| {idx} | **{rank_badge}** | {cat_badge} | {p_link} | {headline} | {has_msg} | {action} |")
    lines.append("")

    lines += ["## 申請者詳細 & 価値検討", ""]
    for idx, inv in enumerate(invitations, start=1):
        name = inv.get("name") or "氏名不明"
        eval_data = inv.get("evaluation") or {}
        prof_details = inv.get("profileDetails") or {}

        lines.append(f"### {idx}. {name}")
        lines.append("")
        if eval_data:
            lines.append("#### つながり価値評価")
            lines.append(f"- **推奨ランク**: `{eval_data.get('rank_label')}` (スコア: {eval_data.get('score')}/100)")
            lines.append(f"- **属性分類**: {eval_data.get('category_label')}")
            lines.append(f"- **推奨アクション**: **{eval_data.get('action')}**")
            if eval_data.get("summary_comment"):
                lines.append(f"- **所感**: {eval_data['summary_comment']}")
            if eval_data.get("match_points"):
                lines.append("- **マッチ要因**:")
                for mp in eval_data["match_points"]:
                    lines.append(f"  - {mp}")
            if eval_data.get("caution_points"):
                lines.append("- **注意・懸念要因**:")
                for cp in eval_data["caution_points"]:
                    lines.append(f"  - {cp}")
            lines.append("")

        lines.append("#### 申請者基本情報")
        if inv.get("headline"):
            lines.append(f"- **肩書き**: {inv['headline']}")
        if inv.get("profileUrl"):
            lines.append(f"- **プロフィールURL**: {inv['profileUrl']}")
        if inv.get("invitationId"):
            lines.append(f"- **招待ID**: `{inv['invitationId']}`")
        if inv.get("mutualConnections"):
            lines.append(f"- **共通のつながり**: {inv['mutualConnections']}")
        if inv.get("receivedTime"):
            lines.append(f"- **受信時期**: {inv['receivedTime']}")
        if inv.get("replyUrl"):
            lines.append(f"- **返信URL**: {inv['replyUrl']}")

        if inv.get("message"):
            lines.append("")
            lines.append("#### 添付メッセージ")
            lines.append("")
            lines.append("```text")
            lines.append(inv["message"])
            lines.append("```")

        if prof_details:
            lines.append("")
            lines.append("#### プロフィール詳細")
            if prof_details.get("currentCompany"):
                lines.append(f"- **現職企業**: {prof_details['currentCompany']}")
            if prof_details.get("location"):
                lines.append(f"- **所在地**: {prof_details['location']}")
            if prof_details.get("about"):
                lines.append(f"- **自己紹介 (About)**: {prof_details['about']}")
            if prof_details.get("skills"):
                lines.append(f"- **スキル**: {', '.join(prof_details['skills'])}")
            if prof_details.get("experiences"):
                lines.append("- **直近職歴**:")
                for exp in prof_details["experiences"]:
                    lines.append(f"  - {exp.get('role')} at {exp.get('company')} ({exp.get('period')})")

        lines.append("")

    return "\n".join(lines)


def save_invitations_result(
    data: dict[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    now: datetime | None = None,
) -> list[Path]:
    """招待データを latest と履歴（Markdown / JSON）として保存する."""
    if now is None:
        now = datetime.now()

    output_dir.mkdir(parents=True, exist_ok=True)
    history_dir = output_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    time_str = now.strftime("%Y%m%d_%H%M%S")
    latest_md = output_dir / "latest.md"
    latest_json = output_dir / "latest.json"
    timestamp_json = output_dir / f"{time_str}.json"
    history_md = history_dir / f"invitations_{time_str}.md"
    history_json = history_dir / f"invitations_{time_str}.json"

    md_content = generate_markdown(data, now)
    latest_md.write_text(md_content, encoding="utf-8")
    history_md.write_text(md_content, encoding="utf-8")

    json_payload = {
        "source": "linkedin",
        "type": "invitations",
        "fetched_at": now.isoformat(timespec="seconds"),
        "url": TARGET_URL,
        **data,
    }
    json_str = json.dumps(json_payload, ensure_ascii=False, indent=2)
    latest_json.write_text(json_str, encoding="utf-8")
    timestamp_json.write_text(json_str, encoding="utf-8")
    history_json.write_text(json_str, encoding="utf-8")

    return [latest_md, latest_json, timestamp_json]


def fetch_single_applicant_profile(session: str, profile_url: str, timeout: float = 30.0) -> dict[str, Any]:
    """申請者のプロフィール詳細を取得する."""
    if not FETCH_PROFILE_SCRIPT_PATH.exists():
        return {"error": "fetch_applicant_profile.mjs が見つかりません"}

    template_code = FETCH_PROFILE_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = template_code.replace("__PROFILE_URL__", profile_url).strip().rstrip(";")

    try:
        res = run_code_snippet(session, run_code, timeout=timeout)
        if isinstance(res, dict) and res.get("success"):
            return res
        return {"error": res.get("error") if isinstance(res, dict) else "詳細取得失敗"}
    except Exception as e:
        return {"error": str(e)}


def execute_fetch_invitations(
    session: str,
    limit: int = 0,
    fetch_profiles: bool = False,
    timeout: float = 120.0,
    ctx: EntrypointContext | None = None,
) -> dict[str, Any]:
    """fetch_invitations.mjs を実行し、オプションに応じてプロフィール詳細も取得する."""
    if not FETCH_SCRIPT_PATH.exists():
        raise RuntimeError(f"招待取得スクリプトが見つかりません: {FETCH_SCRIPT_PATH}")

    template_code = FETCH_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = template_code.replace("__LIMIT__", str(limit)).strip().rstrip(";")

    result = run_code_snippet(session, run_code, timeout=timeout)
    if not result:
        raise RuntimeError("Playwrightスクリプトの実行に失敗しました")

    invitations = result.get("invitations", [])

    # オプション: 申請者プロフィールの追加取得
    if fetch_profiles and invitations:
        if ctx:
            ctx.log(f"申請者プロフィール詳細の取得を開始します (計 {len(invitations)} 件)...")
        for idx, inv in enumerate(invitations, start=1):
            p_url = inv.get("profileUrl")
            if not p_url:
                continue
            if ctx:
                ctx.log(f"[{idx}/{len(invitations)}] {inv.get('name')} のプロフィールを取得中...")
            prof_data = fetch_single_applicant_profile(session, p_url, timeout=timeout)
            inv["profileDetails"] = prof_data
            # レートリミット回避のための待機
            time.sleep(2.5)

    return result


def main() -> None:
    """CLIエントリポイント."""
    parser = create_base_parser(
        description=(
            "LinkedInの受信招待（つながり申請）一覧を取得・プロフィール連携・価値評価します。\n"
            "注意: 承諾（Accept）や拒否（Ignore）の自動操作は行わず、読み取り・情報抽出のみを実行します。"
        ),
        default_limit=0,
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
        "--fetch-profiles",
        action="store_true",
        help="各申請者のプロフィール詳細ページも巡回して経歴・スキル等の追加情報を取得する",
    )
    parser.add_argument(
        "--evaluate",
        action="store_true",
        default=True,
        help="ユーザーのプロファイル（profile/）と照合し価値評価・推奨判断を算出する（デフォルト: 有効）",
    )
    parser.add_argument(
        "--no-evaluate",
        action="store_false",
        dest="evaluate",
        help="価値評価を行わない",
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="既存の受信招待JSONファイルを読み込んで評価・サマリ・Markdown生成を行う（ブラウザ起動なし）",
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
        type=float,
        default=120.0,
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

    # 1. オフライン入力ファイルからの読み込みモード
    if args.input:
        if not args.input.exists():
            ctx.error(f"指定された入力ファイルが存在しません: {args.input}")
            sys.exit(1)

        try:
            input_data = json.loads(args.input.read_text(encoding="utf-8"))
        except Exception as e:
            ctx.error(f"入力JSONの解析に失敗しました: {e}")
            sys.exit(1)

        if args.evaluate:
            input_data["invitations"] = evaluate_invitations_batch(input_data.get("invitations", []))

        saved_paths: list[Path] = []
        if not args.no_save:
            saved_paths = save_invitations_result(input_data, output_dir=args.output_dir, now=datetime.now())
            ctx.add_result_paths(saved_paths)

        def summary_fn() -> None:
            print_formatted_summary(input_data)
            if saved_paths:
                ctx.log("\n[保存完了ファイル一覧]")
                for sp in saved_paths:
                    ctx.log(f"  - {to_relative_path(sp)}")

        sys.exit(ctx.flush_outputs(summary_fn=summary_fn, json_data=input_data))

    # 2. 通常のブラウザ自動フェッチモード
    if not FETCH_SCRIPT_PATH.exists():
        ctx.error(f"必須スクリプトが見つかりません: {FETCH_SCRIPT_PATH}")
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
            fetch_result = execute_fetch_invitations(
                session=args.session,
                limit=args.limit or 0,
                fetch_profiles=args.fetch_profiles,
                timeout=args.timeout,
                ctx=ctx,
            )
        except Exception as e:
            ctx.error(f"LinkedIn 受信招待の取得に失敗しました: {e}")
            sys.exit(1)

        if not fetch_result.get("success"):
            err_msg = ", ".join(fetch_result.get("errors", [])) or "実行失敗"
            ctx.error(f"LinkedIn 受信招待の取得に失敗しました: {err_msg}")
            sys.exit(1)

        for err in fetch_result.get("errors", []):
            ctx.warn(err)

        update_profile_last_used(args.session)

        # 評価ロジック実行
        if args.evaluate:
            fetch_result["invitations"] = evaluate_invitations_batch(fetch_result.get("invitations", []))

        saved_paths: list[Path] = []
        if not args.no_save:
            saved_paths = save_invitations_result(
                fetch_result,
                output_dir=args.output_dir,
                now=datetime.now(),
            )
            ctx.add_result_paths(saved_paths)

        def summary_fn() -> None:
            print_formatted_summary(fetch_result)
            if saved_paths:
                ctx.log("\n[保存完了ファイル一覧]")
                for sp in saved_paths:
                    ctx.log(f"  - {to_relative_path(sp)}")

        sys.exit(ctx.flush_outputs(summary_fn=summary_fn, json_data=fetch_result))

    finally:
        if not args.keep_open:
            run_playwright_cmd([f"-s={args.session}", "close"], timeout=10)


if __name__ == "__main__":
    main()
