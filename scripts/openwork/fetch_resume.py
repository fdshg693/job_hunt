"""OpenWork の WEB 履歴書を取得して保存する CLI.

OpenWork WEB履歴書自動取得・永続化スクリプト.
リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
OpenWorkのログイン状態確認・未ログイン時の通知待機ハンドオフ・WEB履歴書画面（/mypage/resume）からの
構造化履歴書データ（基本情報、学歴、職歴、スキル、希望条件）の抽出・永続化を実行します。
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/openwork/ の2階層上)
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
from scripts.common.normalizers import parse_salary_range

OPENWORK_SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "openwork" / "resume"
TARGET_URL = "https://www.openwork.jp/mypage/resume"
LOGIN_URL = "https://www.openwork.jp/login.php"


def _parse_yen_amount(text: str | None) -> int | None:
    """万円表記（例: 450万円, 500万円以上）から円単位数値を抽出する."""
    if not text:
        return None
    s_min, s_max = parse_salary_range(text)
    if s_min is not None:
        return s_min
    if s_max is not None:
        return s_max
    # 純粋な数値
    m_num = re.search(r"(\d+)", text.replace(",", ""))
    if m_num:
        return int(m_num.group(1))
    return None


def _parse_company_count(text: str | None) -> int | None:
    """社数表記（例: 2社）から数値を抽出する."""
    if not text:
        return None
    m = re.search(r"(\d+)\s*社", text)
    if m:
        return int(m.group(1))
    return None


def generate_markdown(data: dict[str, Any], now: datetime) -> str:
    """WEB履歴書データを構造化フロントマター付きMarkdownに整形する."""
    basic = data.get("basicInfo", {})
    academic = data.get("academicHistory", {})
    careers = data.get("careerHistory", [])
    skills = data.get("skills", {})
    preferences = data.get("desiredConditions", {})

    fetched_at_str = now.isoformat(timespec="seconds")
    fetched_at_display = now.strftime("%Y-%m-%d %H:%M:%S")

    # 年収数値化
    cur_salary_int = _parse_yen_amount(basic.get("currentSalary"))
    des_salary_int = _parse_yen_amount(preferences.get("desiredSalary"))
    comp_count_int = _parse_company_count(basic.get("companyCount"))

    # フロントマター構築
    fm_lines = [
        "---",
        "source: openwork",
        "type: resume",
        f"fetched_at: '{fetched_at_str}'",
        f"url: {TARGET_URL}",
    ]
    if basic.get("name"):
        fm_lines.append(f"name: '{basic['name']}'")
    if basic.get("currentSalary"):
        fm_lines.append(f"current_salary: '{basic['currentSalary']}'")
    if cur_salary_int:
        fm_lines.append(f"current_salary_int: {cur_salary_int}")
    if comp_count_int is not None:
        fm_lines.append(f"company_count: {comp_count_int}")
    if academic.get("finalEducation"):
        fm_lines.append(f"final_education: '{academic['finalEducation']}'")

    # スキル一覧
    tech_skills = skills.get("skills", [])
    if tech_skills:
        skills_yaml = ", ".join(f"'{s}'" for s in tech_skills)
        fm_lines.append(f"skills: [{skills_yaml}]")

    # 希望条件
    if preferences.get("desiredOccupations"):
        occ_yaml = ", ".join(f"'{o}'" for o in preferences["desiredOccupations"])
        fm_lines.append(f"desired_occupations: [{occ_yaml}]")
    if preferences.get("desiredLocations"):
        loc_yaml = ", ".join(f"'{loc}'" for loc in preferences["desiredLocations"])
        fm_lines.append(f"desired_locations: [{loc_yaml}]")
    if preferences.get("desiredSalary"):
        fm_lines.append(f"desired_salary: '{preferences['desiredSalary']}'")
    if des_salary_int:
        fm_lines.append(f"desired_salary_int: {des_salary_int}")

    fm_lines.append("---")
    fm_lines.append("")

    # Markdown本文構築
    body_lines = [
        f"# OpenWork WEB履歴書 ({now.strftime('%Y-%m-%d')})",
        "",
        f"- 取得日時: {fetched_at_display}",
        f"- 取得元URL: {TARGET_URL}",
        "",
        "## 基本情報",
        "",
        f"- **氏名**: {basic.get('name', '未設定')}",
        f"- **氏名（カナ）**: {basic.get('kana', '未設定')}",
        f"- **性別**: {basic.get('gender', '未設定')}",
        f"- **生年月日・年齢**: {basic.get('birthDate', '未設定')} ({basic.get('age', '未設定')})",
        f"- **現在の就業状況**: {basic.get('employmentStatus', '未設定')}",
        f"- **現在の年収**: {basic.get('currentSalary', '未設定')}",
        f"- **経験社数**: {basic.get('companyCount', '未設定')}",
        "",
        "## 学歴",
        "",
        f"- **最終学歴区分**: {academic.get('finalEducation', '未設定')}",
        f"- **学校名**: {academic.get('schoolName', '未設定')}",
        f"- **学部・学科**: {academic.get('faculty', '未設定')}",
        f"- **卒業年月**: {academic.get('graduationDate', '未設定')}",
        f"- **文理区分**: {academic.get('majorType', '未設定')}",
        "",
    ]

    if careers:
        body_lines.append("## 職務経歴")
        body_lines.append("")
        for idx, c in enumerate(careers, start=1):
            comp_name = c.get("companyName", "会社名未設定")
            period = c.get("period", "期間未設定")
            cur_badge = "（現職）" if c.get("isCurrent") else ""
            body_lines.append(f"### {idx}. {comp_name} {cur_badge}")
            body_lines.append(f"- **在籍期間**: {period}")
            if c.get("employmentType"):
                body_lines.append(f"- **雇用形態**: {c['employmentType']}")
            if c.get("department"):
                body_lines.append(f"- **部署・役職**: {c['department']}")
            if c.get("annualIncome"):
                body_lines.append(f"- **在籍時年収**: {c['annualIncome']}")
            if c.get("businessDescription"):
                body_lines.append(f"- **事業内容**: {c['businessDescription']}")

            job_desc = c.get("jobDescription", "")
            if job_desc:
                body_lines.append("")
                body_lines.append("#### 職務内容・プロジェクト")
                body_lines.append("")
                body_lines.append(job_desc)
                body_lines.append("")
            body_lines.append("")

    body_lines.append("## スキル・資格・語学")
    body_lines.append("")
    if tech_skills:
        body_lines.append("### 保有スキル・技術スタック")
        body_lines.append("")
        for s in tech_skills:
            body_lines.append(f"- {s}")
        body_lines.append("")

    if skills.get("qualifications"):
        body_lines.append("### 保有資格")
        body_lines.append("")
        for q in skills["qualifications"]:
            body_lines.append(f"- {q}")
        body_lines.append("")

    if skills.get("languages"):
        body_lines.append("### 語学力")
        body_lines.append("")
        for lang in skills["languages"]:
            body_lines.append(f"- {lang}")
        body_lines.append("")

    if skills.get("selfPR"):
        body_lines.append("### 自己PR")
        body_lines.append("")
        body_lines.append(skills["selfPR"])
        body_lines.append("")

    body_lines.append("## 希望条件")
    body_lines.append("")
    if preferences.get("desiredOccupations"):
        body_lines.append(f"- **希望職種**: {', '.join(preferences['desiredOccupations'])}")
    if preferences.get("desiredIndustries"):
        body_lines.append(f"- **希望業種**: {', '.join(preferences['desiredIndustries'])}")
    if preferences.get("desiredLocations"):
        body_lines.append(f"- **希望勤務地**: {', '.join(preferences['desiredLocations'])}")
    if preferences.get("desiredSalary"):
        body_lines.append(f"- **希望年収**: {preferences['desiredSalary']}")
    if preferences.get("changeTiming"):
        body_lines.append(f"- **転職希望時期**: {preferences['changeTiming']}")
    body_lines.append("")

    return "\n".join(fm_lines) + "\n" + "\n".join(body_lines)


def print_formatted_summary(data: dict[str, Any]) -> None:
    """WEB履歴書のサマリをコンソールに整形出力する."""
    basic = data.get("basicInfo", {})
    academic = data.get("academicHistory", {})
    careers = data.get("careerHistory", [])
    skills = data.get("skills", {})
    preferences = data.get("desiredConditions", {})

    print("\n========================================================")
    print(" OpenWork WEB履歴書サマリ")
    print("========================================================\n")
    print(f"氏名:         {basic.get('name', '未設定')} ({basic.get('kana', '')})")
    print(f"現在年収:     {basic.get('currentSalary', '未設定')}")
    print(f"就業状況:     {basic.get('employmentStatus', '未設定')} (経験社数: {basic.get('companyCount', '未設定')})")
    print(f"最終学歴:     {academic.get('schoolName', '未設定')} {academic.get('faculty', '')} ({academic.get('finalEducation', '')})")

    if preferences.get("desiredOccupations"):
        print(f"\n希望職種:     {', '.join(preferences['desiredOccupations'])}")
    if preferences.get("desiredSalary"):
        print(f"希望年収:     {preferences['desiredSalary']}")
    if preferences.get("desiredLocations"):
        print(f"希望勤務地:   {', '.join(preferences['desiredLocations'])}")

    print(f"\n職歴件数:     {len(careers)} 社")
    for idx, c in enumerate(careers, start=1):
        cur_badge = " [現職]" if c.get("isCurrent") else ""
        print(f"  [{idx}] {c.get('companyName', '会社名未設定')} / {c.get('period', '期間未設定')}{cur_badge}")
        if c.get("department"):
            print(f"        部署・役職: {c['department']}")
        if c.get("annualIncome"):
            print(f"        在職時年収: {c['annualIncome']}")

    tech_skills = skills.get("skills", [])
    if tech_skills:
        print(f"\n保有スキル ({len(tech_skills)} 件):")
        print(f"  {', '.join(tech_skills[:12])}")
        if len(tech_skills) > 12:
            print(f"  ...他 {len(tech_skills) - 12} 件")

    if skills.get("selfPR"):
        print(f"\n自己PR: あり ({len(skills['selfPR'])} 文字)")
        lines = [line for line in skills["selfPR"].splitlines() if line.strip()][:3]
        for line in lines:
            print(f"  {line}")
        if len(skills["selfPR"].splitlines()) > 3:
            print("  ...")
    print("-" * 56)


def save_resume_result(
    data: dict[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    now: datetime | None = None,
) -> list[Path]:
    """WEB履歴書データをMarkdownとJSONでファイル保存する."""
    if now is None:
        now = datetime.now()

    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = now.strftime("%Y-%m-%d")

    dated_md = output_dir / f"{date_str}.md"
    dated_json = output_dir / f"{date_str}.json"
    latest_md = output_dir / "latest.md"
    latest_json = output_dir / "latest.json"

    # Markdown生成・保存
    md_content = generate_markdown(data, now)
    dated_md.write_text(md_content, encoding="utf-8")
    shutil.copyfile(dated_md, latest_md)

    # JSON保存
    json_payload = {
        "source": "openwork",
        "type": "resume",
        "fetched_at": now.isoformat(timespec="seconds"),
        "url": TARGET_URL,
        **data,
    }
    json_str = json.dumps(json_payload, ensure_ascii=False, indent=2)
    dated_json.write_text(json_str, encoding="utf-8")
    shutil.copyfile(dated_json, latest_json)

    return [dated_md, dated_json, latest_md, latest_json]


def main() -> None:
    """CLIエントリポイント."""
    parser = create_base_parser(
        examples=[
            "uv run python scripts/openwork/fetch_resume.py --summary",
            "uv run python scripts/openwork/fetch_resume.py --headed  # 未ログイン時に可視ブラウザでログイン",
        ],
        description="OpenWorkの共通プロファイルを用いて認証チェックを行い、WEB履歴書画面からデータを取得・永続化します。",
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
        help="ブラウザを可視ウィンドウで起動する（手動操作・外部ターミナル用）",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="手動ログイン・認証待機のタイムアウト秒数（デフォルト: 120秒）",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="処理完了後にブラウザセッションを閉じずに保持する",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="認証壁検知時のOSトースト通知を送信しない",
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

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    fetch_resume_script = OPENWORK_SCRIPTS_DIR / "fetch_resume.mjs"
    if not fetch_resume_script.exists():
        ctx.error(f"必須スクリプトが見つかりません: {fetch_resume_script}")
        sys.exit(1)

    profile_dir = resolve_profile_path(args.session, args.profile_path)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. 共通認証エンジンによる認証状態確認・ハンドオフ
        ensure_site_authenticated(
            site="openwork",
            session=args.session,
            target_url=TARGET_URL,
            headed=args.headed,
            timeout=args.timeout,
            no_notify=args.no_notify,
            profile_dir=profile_dir,
            exit_on_fail=True,
        )

        # 2. WEB履歴書画面からデータ抽出
        fetch_result = run_code_script(args.session, fetch_resume_script, timeout=30)
        if not fetch_result or not fetch_result.get("success"):
            ctx.error("WEB履歴書データ取得に失敗しました。")
            sys.exit(1)

        update_profile_last_used(args.session)

        # 3. ファイル保存
        saved_files: list[Path] = []
        if not args.no_save:
            saved_files = save_resume_result(fetch_result, output_dir=args.output_dir)
            ctx.add_result_paths(saved_files)

        def summary_fn() -> None:
            print_formatted_summary(fetch_result)
            if saved_files:
                ctx.log("\n[保存完了ファイル一覧]")
                for sf in saved_files:
                    ctx.log(f"  - {to_relative_path(sf)}")

        sys.exit(ctx.flush_outputs(summary_fn=summary_fn, json_data=fetch_result))

    finally:
        if not args.keep_open:
            run_playwright_cmd([f"-s={args.session}", "close"], timeout=10)


if __name__ == "__main__":
    main()
