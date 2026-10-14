"""ビズリーチ職務経歴書（基本情報・職務経歴・フリーフォーマット）自動取得・永続化スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
ビズリーチのログイン状態確認・未ログイン時の通知待機ハンドオフ・職務経歴書画面からの
構造化レジュメデータ（基本情報、経験職種・業種、職務経歴・プロジェクト詳細、フリーフォーマット）の抽出・永続化を実行します。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
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
from scripts.common.normalizers import extract_skills_from_text, parse_salary_range

BIZREACH_SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "bizreach" / "resume"
TARGET_URL = "https://www.bizreach.jp/resume/company/"


def generate_markdown(data: dict[str, Any], now: datetime) -> str:
    """職務経歴書データを構造化フロントマター付きMarkdownに整形する."""
    basic = data.get("basicInfo", {})
    name = basic.get("name") or basic.get("氏名") or ""
    current_salary = basic.get("currentSalary") or basic.get("現在の年収") or ""
    english_level = basic.get("englishLevel") or basic.get("英語レベル") or basic.get("語学レベル") or ""
    final_edu = basic.get("finalEducation") or basic.get("最終学歴") or ""
    recent_job = basic.get("recentJobType") or basic.get("直近経験職種") or ""

    career_obj = data.get("career", {})
    industries_raw = data.get("experiencedIndustries") or career_obj.get("experiencedIndustries", [])
    industries = [
        f"{i.get('name', '')} ({i.get('years', '')})" if isinstance(i, dict) and i.get("years") else (i.get("name") if isinstance(i, dict) else str(i))
        for i in industries_raw
    ]

    occupations_raw = data.get("experiencedOccupations") or career_obj.get("experiencedJobCategories", [])
    occupations = [
        f"{o.get('name', '')} ({o.get('years', '')})" if isinstance(o, dict) and o.get("years") else (o.get("name") if isinstance(o, dict) else str(o))
        for o in occupations_raw
    ]

    management = data.get("managementExperience", {})
    mgmt_val = basic.get("マネジメント経験") or management.get("numberOfPeople")
    has_mgmt = management.get("hasExperience") if management.get("hasExperience") is not None else (bool(mgmt_val) and mgmt_val != "なし")

    careers = data.get("careerHistory") or career_obj.get("companies", [])
    free_format = data.get("freeFormat") or data.get("freetext") or ""

    fetched_at_str = now.isoformat(timespec="seconds")
    fetched_at_display = now.strftime("%Y-%m-%d %H:%M:%S")

    # 全文からスキル抽出
    all_text_parts = [free_format]
    for c in careers:
        all_text_parts.append(c.get("companyName", ""))
        all_text_parts.append(c.get("businessDescription", ""))
        for p in c.get("projects", []):
            all_text_parts.append(p.get("projectName") or p.get("title", ""))
            all_text_parts.append(p.get("description", ""))
    all_text = "\n".join(all_text_parts)
    skills = extract_skills_from_text(all_text)

    # 年収数値化
    salary_int, _ = parse_salary_range(current_salary)

    # フロントマター構築
    fm_lines = [
        "---",
        "source: bizreach",
        "type: resume",
        f"fetched_at: '{fetched_at_str}'",
        f"url: {TARGET_URL}",
    ]
    if name:
        fm_lines.append(f"name: '{name}'")
    if current_salary:
        fm_lines.append(f"current_salary: '{current_salary}'")
    if salary_int:
        fm_lines.append(f"current_salary_int: {salary_int}")
    if skills:
        skills_yaml = ", ".join(f"'{s}'" for s in skills)
        fm_lines.append(f"skills: [{skills_yaml}]")
    if industries:
        ind_yaml = ", ".join(f"'{i}'" for i in industries)
        fm_lines.append(f"experienced_industries: [{ind_yaml}]")
    if occupations:
        occ_yaml = ", ".join(f"'{o}'" for o in occupations)
        fm_lines.append(f"experienced_occupations: [{occ_yaml}]")
    fm_lines.append("---")
    fm_lines.append("")

    # Markdown本文構築
    body_lines = [
        f"# ビズリーチ 職務経歴書 ({now.strftime('%Y-%m-%d')})",
        "",
        f"- 取得日時: {fetched_at_display}",
        f"- 取得元URL: {TARGET_URL}",
        "",
        "## 基本情報",
        "",
        f"- 氏名: {name or '未設定'}",
        f"- 現在年収: {current_salary or '未設定'}",
        f"- 英語レベル: {english_level or '未設定'}",
        f"- 最終学歴: {final_edu or '未設定'}",
        f"- 直近経験職種: {recent_job or '未設定'}",
        "",
    ]

    if industries:
        body_lines.append("## 経験業種")
        body_lines.append("")
        for ind in industries:
            body_lines.append(f"- {ind}")
        body_lines.append("")

    if occupations:
        body_lines.append("## 経験職種")
        body_lines.append("")
        for occ in occupations:
            body_lines.append(f"- {occ}")
        body_lines.append("")

    if has_mgmt:
        body_lines.append("## マネジメント経験")
        body_lines.append("")
        body_lines.append(f"- マネジメント経験: {'あり' if has_mgmt else 'なし'}")
        if mgmt_val:
            body_lines.append(f"- 経験人数: {mgmt_val}")
        body_lines.append("")

    if careers:
        body_lines.append("## 職務経歴（会社別）")
        body_lines.append("")
        for idx, c in enumerate(careers, start=1):
            comp_name = c.get("companyName", "会社名未設定")
            period = c.get("period", "期間未設定")
            is_current = "（在籍中）" if c.get("isCurrent") or "在職中" in period else ""
            body_lines.append(f"### {idx}. {comp_name} {is_current}")
            body_lines.append(f"- **期間**: {period}")
            if c.get("employmentType"):
                body_lines.append(f"- **雇用形態**: {c['employmentType']}")
            role = c.get("role") or c.get("department")
            if role:
                body_lines.append(f"- **部署・役職**: {role}")
            if c.get("businessDescription"):
                body_lines.append(f"- **事業内容**: {c['businessDescription']}")

            projects = c.get("projects", [])
            if projects:
                body_lines.append("")
                body_lines.append("#### 職務内容・プロジェクト詳細")
                body_lines.append("")
                for p_idx, p in enumerate(projects, start=1):
                    p_name = p.get("projectName") or p.get("title", "プロジェクト")
                    p_period = p.get("period", "")
                    p_desc = p.get("description", "")
                    period_str = f" ({p_period})" if p_period else ""
                    body_lines.append(f"**{p_idx}) {p_name}{period_str}**")
                    if p_desc:
                        body_lines.append("")
                        body_lines.append(p_desc)
                        body_lines.append("")
            body_lines.append("")

    if free_format:
        body_lines.append("## 職務経歴書（フリーフォーマット）")
        body_lines.append("")
        body_lines.append(free_format)
        body_lines.append("")

    return "\n".join(fm_lines) + "\n" + "\n".join(body_lines)


def print_formatted_summary(data: dict[str, Any]) -> None:
    """職務経歴書のサマリをコンソールに整形出力する."""
    basic = data.get("basicInfo", {})
    name = basic.get("name") or basic.get("氏名") or "未設定"
    current_salary = basic.get("currentSalary") or basic.get("現在の年収") or "未設定"
    english_level = basic.get("englishLevel") or basic.get("英語レベル") or "未設定"
    final_edu = basic.get("finalEducation") or basic.get("最終学歴") or "未設定"
    recent_job = basic.get("recentJobType") or basic.get("直近経験職種") or "未設定"

    career_obj = data.get("career", {})
    industries_raw = data.get("experiencedIndustries") or career_obj.get("experiencedIndustries", [])
    industries = [i.get("name", str(i)) if isinstance(i, dict) else str(i) for i in industries_raw]

    occupations_raw = data.get("experiencedOccupations") or career_obj.get("experiencedJobCategories", [])
    occupations = [o.get("name", str(o)) if isinstance(o, dict) else str(o) for o in occupations_raw]

    careers = data.get("careerHistory") or career_obj.get("companies", [])
    free_format = data.get("freeFormat") or data.get("freetext") or ""

    print("\n========================================================")
    print(" ビズリーチ 職務経歴書サマリ")
    print("========================================================\n")
    print(f"氏名:         {name}")
    print(f"現在年収:     {current_salary}")
    print(f"英語レベル:   {english_level}")
    print(f"最終学歴:     {final_edu}")
    print(f"直近経験職種: {recent_job}")

    if industries:
        print(f"\n経験業種:     {', '.join(industries)}")
    if occupations:
        print(f"経験職種:     {', '.join(occupations)}")

    print(f"\n職歴件数:     {len(careers)} 社")
    for idx, c in enumerate(careers, start=1):
        period = c.get("period", "期間未設定")
        is_cur = " (在籍中)" if c.get("isCurrent") or "在職中" in period else ""
        print(f"  [{idx}] {c.get('companyName', '会社名未設定')} / {period}{is_cur}")
        role = c.get("role") or c.get("department")
        if role:
            print(f"        役職: {role}")
        projs = c.get("projects", [])
        if projs:
            print(f"        プロジェクト数: {len(projs)} 件")

    if free_format:
        print(f"\nフリーフォーマット職務経歴書: あり ({len(free_format)} 文字)")
        lines = [l for l in free_format.splitlines() if l.strip()][:5]
        print("  抜粋:")
        for l in lines:
            print(f"    {l}")
        if len(free_format.splitlines()) > 5:
            print("    ...")
    print("-" * 56)


def save_resume_result(
    data: dict[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    now: datetime | None = None,
) -> list[Path]:
    """職務経歴書データをMarkdownとJSONでファイル保存する."""
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
        "source": "bizreach",
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
        description="ビズリーチの共通プロファイルを用いて認証チェックを行い、職務経歴書画面からデータを取得・永続化します。"
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
        help="手動ログイン待機のタイムアウト秒数（デフォルト: 120秒）",
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

    fetch_resume_script = BIZREACH_SCRIPTS_DIR / "fetch_resume.mjs"
    if not fetch_resume_script.exists():
        ctx.error(f"必須スクリプトが見つかりません: {fetch_resume_script}")
        sys.exit(1)

    profile_dir = resolve_profile_path(args.session, args.profile_path)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. 共通認証エンジンによるブラウザ起動・認証確認・手動待機ハンドオフ
        ensure_site_authenticated(
            site="bizreach",
            session=args.session,
            target_url=TARGET_URL,
            headed=args.headed,
            timeout=args.timeout,
            no_notify=args.no_notify,
            profile_dir=profile_dir,
            exit_on_fail=True,
        )

        # 2. 職務経歴書データ抽出
        fetch_result = run_code_script(args.session, fetch_resume_script, timeout=60)
        if not fetch_result or not fetch_result.get("success"):
            ctx.error("職務経歴書データ取得に失敗しました。")
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
