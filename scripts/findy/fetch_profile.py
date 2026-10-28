"""Findy のプロフィール（キャリア・スキル）を取得して保存する CLI.

Findyプロフィール（キャリア・スキル）自動取得・永続化スクリプト.
リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
Findyのログイン状態確認・未ログイン時の通知待機ハンドオフ・キャリアスキル画面（/me/career-skills）からの
GraphQLレスポンスインターセプトによる完全な構造化プロフィールデータの抽出・永続化を実行します。
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
from scripts.common.cli import EntrypointContext, build_epilog, to_relative_path

FINDY_SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "findy" / "profile"
TARGET_URL = "https://findy-code.io/me/career-skills"


def _format_date(year: int | None, month: int | None, is_current: bool = False) -> str:
    """年月表示を整形する."""
    if is_current:
        return "現在"
    if not year:
        return "-"
    if month:
        return f"{year}年{month:02d}月"
    return f"{year}年"


def generate_profile_markdown(data: dict[str, Any], now: datetime) -> str:
    """取得したプロフィールデータをフロントマター付き構造化Markdownに整形する."""
    career_skills = data.get("careerSkills") or {}
    user = career_skills.get("currentUser") or {}
    profile = user.get("profile") or {}
    job_roles = user.get("jobRoles") or []
    skills = user.get("experiencedSkills") or []
    work_histories = user.get("workHistories") or []
    ai_usage = user.get("aiUsage") or {}
    certifications = user.get("certifications") or []
    edu = user.get("educationalBackground") or {}
    toeic = user.get("toeicScore")
    toefl = user.get("toeflScore")

    fetched_at_str = now.isoformat(timespec="seconds")
    fetched_at_display = now.strftime("%Y-%m-%d %H:%M:%S")
    self_updated_at = profile.get("selfUpdatedAt") or "-"

    # フロントマター用データの抽出
    annual_income = profile.get("numericAnnualIncome")
    english_skill_name = (profile.get("englishSkill") or {}).get("name", "-")

    roles_frontmatter = []
    for r in job_roles:
        role_name = (r.get("jobRole") or {}).get("name", "")
        year_name = (r.get("userJobYearType") or {}).get("name", "")
        if role_name:
            roles_frontmatter.append(f"{role_name} ({year_name})" if year_name else role_name)

    top_skills = []
    for s in skills:
        s_name = (s.get("skill") or {}).get("name", "")
        exp_y = s.get("experienceYears") or 0
        y_str = f"{exp_y}年" if exp_y > 0 else "1年未満"
        if s_name:
            top_skills.append(f"{s_name} ({y_str})")

    cert_names = []
    for c in certifications:
        c_name = (c.get("certification") or {}).get("name", "")
        c_year = c.get("certifiedYear")
        if c_name:
            cert_names.append(f"{c_name} ({c_year}年)" if c_year else c_name)

    # Markdown本文の構築
    lines = [
        "---",
        "source: findy",
        "type: profile",
        f"fetched_at: '{fetched_at_str}'",
        f"url: {TARGET_URL}",
        f"self_updated_at: '{self_updated_at}'",
    ]
    if annual_income is not None:
        lines.append(f"current_annual_income: {annual_income}")
    if english_skill_name != "-":
        lines.append(f"english_skill: '{english_skill_name}'")
    if roles_frontmatter:
        lines.append("job_roles:")
        for r in roles_frontmatter:
            lines.append(f"  - '{r}'")
    if top_skills:
        lines.append("primary_skills:")
        for s in top_skills[:15]:
            lines.append(f"  - '{s}'")
    if cert_names:
        lines.append("certifications:")
        for c in cert_names:
            lines.append(f"  - '{c}'")
    if toeic and isinstance(toeic, dict) and toeic.get("totalScore"):
        lines.append(f"toeic_score: {toeic['totalScore']}")
    lines.extend(["---", ""])

    # タイトルと基本情報
    lines.append("# Findy プロフィール（キャリア・スキル）")
    lines.append("")
    lines.append(f"- **取得日時**: {fetched_at_display}")
    lines.append(f"- **最終更新**: {self_updated_at}")
    if annual_income is not None:
        lines.append(f"- **現年収**: {annual_income:,} 円")
    lines.append(f"- **入力進捗率**: {profile.get('inputProgress', 0)}%")
    rank_val = user.get("userRank")
    rank_str = rank_val.get("status") if isinstance(rank_val, dict) else rank_val
    if rank_str:
        lines.append(f"- **会員ランク**: {rank_str}")
    if english_skill_name != "-":
        lines.append(f"- **語学力**: {english_skill_name}")
    doc_info = profile.get("workExperienceDoc")
    if doc_info and doc_info.get("filename"):
        lines.append(f"- **登録職務経歴書**: {doc_info.get('filename')} (アップロード日: {doc_info.get('uploadedAt', '-')})")
    lines.append("")

    # 職種・経験年数
    if job_roles:
        lines.append("## 職種・経験年数")
        lines.append("")
        for r in job_roles:
            role_obj = r.get("jobRole") or {}
            year_obj = r.get("userJobYearType") or {}
            r_name = role_obj.get("name", "未設定")
            y_name = year_obj.get("name", "未設定")
            lines.append(f"- **{r_name}**: {y_name}")
        lines.append("")

    # 保有スキル一覧
    if skills:
        lines.append("## 保有スキル・経験年数")
        lines.append("")
        lines.append("| スキル名 | 経験年数 | 算出区分 |")
        lines.append("|---|---|---|")
        for s in skills:
            s_name = (s.get("skill") or {}).get("name", "-")
            exp_years = s.get("experienceYears") or 0
            years_display = f"{exp_years}年" if exp_years > 0 else "1年未満"
            source_type = s.get("sourceType", "-")
            lines.append(f"| {s_name} | {years_display} | {source_type} |")
        lines.append("")

    # 職務要約
    latest_results = profile.get("latestDevelopmentResults")
    if latest_results:
        lines.append("## 直近の開発実績・職務要約")
        lines.append("")
        lines.append(latest_results.strip())
        lines.append("")

    # 自己PR
    bio = profile.get("bio")
    if bio:
        lines.append("## 自己PR")
        lines.append("")
        lines.append(bio.strip())
        lines.append("")

    # 今後やってみたいこと
    vision = profile.get("vision")
    if vision:
        lines.append("## 今後やってみたいこと")
        lines.append("")
        lines.append(vision.strip())
        lines.append("")

    # エンジニアリング領域におけるAI活用
    ai_comment = ai_usage.get("comment")
    if ai_comment:
        lines.append("## エンジニアリング領域におけるAI活用")
        lines.append("")
        lines.append(ai_comment.strip())
        lines.append("")

    # 職歴・プロジェクト詳細
    if work_histories:
        lines.append("## 職歴・プロジェクト履歴")
        lines.append("")
        for w_idx, wh in enumerate(work_histories, start=1):
            comp_name = wh.get("companyName") or "企業名未設定"
            emp_pattern = (wh.get("employmentPattern") or {}).get("name", "")
            emp_pattern_str = f"（{emp_pattern}）" if emp_pattern else ""
            is_current = wh.get("isCurrentlyWorking", False)
            start_str = _format_date(wh.get("startedOnYear"), wh.get("startedOnMonth"))
            end_str = _format_date(wh.get("endedOnYear"), wh.get("endedOnMonth"), is_current=is_current)

            lines.append(f"### {w_idx}. {comp_name} {emp_pattern_str}")
            lines.append(f"- **在籍期間**: {start_str} 〜 {end_str}")
            lines.append("")

            projects = wh.get("workHistoryProjects") or []
            if projects:
                for p_idx, proj in enumerate(projects, start=1):
                    p_name = proj.get("name") or "プロジェクト名未設定"
                    p_is_current = proj.get("isCurrentlyWorking", False)
                    p_start = _format_date(proj.get("startedOnYear"), proj.get("startedOnMonth"))
                    p_end = _format_date(proj.get("endedOnYear"), proj.get("endedOnMonth"), is_current=p_is_current)
                    pos = proj.get("positionName") or "-"
                    team = proj.get("teamScaleName") or "-"

                    proj_roles = [r.get("name") for r in proj.get("jobRoles") or [] if r.get("name")]
                    role_str = ", ".join(proj_roles) if proj_roles else "-"

                    proj_skills = [s.get("name") for s in proj.get("skills") or [] if s.get("name")]
                    skill_str = ", ".join(proj_skills) if proj_skills else "-"

                    lines.append(f"#### プロジェクト {w_idx}-{p_idx}: {p_name}")
                    lines.append(f"- **期間**: {p_start} 〜 {p_end}")
                    lines.append(f"- **職種/役割**: {role_str} / {pos}")
                    lines.append(f"- **チーム規模**: {team}")
                    lines.append(f"- **使用技術**: {skill_str}")
                    lines.append("")
                    detail = proj.get("detail")
                    if detail:
                        lines.append("**業務詳細**:")
                        lines.append("```text")
                        lines.append(detail.strip())
                        lines.append("```")
                        lines.append("")
            lines.append("---")
            lines.append("")

    # 学歴
    if edu:
        school = edu.get("schoolName") or "-"
        major = edu.get("major") or "-"
        grad_year = edu.get("graduatedAtYear")
        grad_month = edu.get("graduatedAtMonth")
        grad_str = _format_date(grad_year, grad_month) if grad_year else "-"
        detail = edu.get("detail")

        lines.append("## 学歴")
        lines.append("")
        lines.append(f"- **学校名**: {school}")
        lines.append(f"- **学部・学科**: {major}")
        lines.append(f"- **卒業年月**: {grad_str}")
        if detail:
            lines.append(f"- **専攻詳細**: {detail}")
        lines.append("")

    # 資格・語学スコア
    if certifications or toeic or toefl:
        lines.append("## 資格・語学スコア")
        lines.append("")
        if certifications:
            lines.append("### 保有資格")
            for c in certifications:
                c_name = (c.get("certification") or {}).get("name", "資格名未設定")
                c_y = c.get("certifiedYear")
                lines.append(f"- **{c_name}** ({c_y}年取得)" if c_y else f"- **{c_name}**")
            lines.append("")
        if toeic:
            if isinstance(toeic, dict):
                t_score = toeic.get("totalScore")
                t_year = toeic.get("testYear")
                y_part = f" ({t_year}年受験)" if t_year else ""
                lines.append(f"- **TOEICスコア**: {t_score}点{y_part}")
            else:
                lines.append(f"- **TOEICスコア**: {toeic}")
        if toefl:
            if isinstance(toefl, dict):
                t_score = toefl.get("totalScore")
                t_year = toefl.get("testYear")
                y_part = f" ({t_year}年受験)" if t_year else ""
                lines.append(f"- **TOEFLスコア**: {t_score}点{y_part}")
            else:
                lines.append(f"- **TOEFLスコア**: {toefl}")
        lines.append("")

    return "\n".join(lines)


def print_formatted_summary(data: dict[str, Any]) -> None:
    """プロフィール情報のサマリをコンソールに整形出力する."""
    career_skills = data.get("careerSkills") or {}
    user = career_skills.get("currentUser") or {}
    profile = user.get("profile") or {}
    job_roles = user.get("jobRoles") or []
    skills = user.get("experiencedSkills") or []
    work_histories = user.get("workHistories") or []
    ai_usage = user.get("aiUsage") or {}

    annual_income = profile.get("numericAnnualIncome")
    income_str = f"{annual_income:,} 円" if annual_income is not None else "未設定"
    english_skill_name = (profile.get("englishSkill") or {}).get("name", "未設定")

    print("\n========================================================")
    print(" Findy プロフィール（キャリア・スキル）情報")
    print(f" URL:        {TARGET_URL}")
    print(f" 最終更新日: {profile.get('selfUpdatedAt', '不明')}")
    print(f" 現年収:     {income_str}")
    print(f" 入力進捗:   {profile.get('inputProgress', 0)}%")
    print(f" 語学力:     {english_skill_name}")
    print("========================================================\n")

    # 職種
    if job_roles:
        print("■ 登録職種:")
        for r in job_roles:
            role_name = (r.get("jobRole") or {}).get("name", "")
            year_name = (r.get("userJobYearType") or {}).get("name", "")
            print(f"  - {role_name}: {year_name}")
        print()

    # 主要スキル（上位10件）
    if skills:
        skill_texts = []
        for s in skills[:10]:
            s_name = (s.get("skill") or {}).get("name", "")
            exp_y = s.get("experienceYears") or 0
            y_str = f"{exp_y}年" if exp_y > 0 else "1年未満"
            skill_texts.append(f"{s_name}({y_str})")
        print(f"■ 主要スキル (計{len(skills)}件):")
        print("  " + ", ".join(skill_texts))
        print()

    # AI活用
    ai_comment = ai_usage.get("comment")
    if ai_comment:
        print("■ AI活用方針・実績:")
        for line in ai_comment.strip().splitlines()[:3]:
            print(f"  {line}")
        if len(ai_comment.strip().splitlines()) > 3:
            print("  ...")
        print()

    # 職歴概要
    if work_histories:
        print(f"■ 職歴概要 ({len(work_histories)}社):")
        for wh in work_histories:
            c_name = wh.get("companyName", "企業名不明")
            is_cur = wh.get("isCurrentlyWorking", False)
            start_str = _format_date(wh.get("startedOnYear"), wh.get("startedOnMonth"))
            end_str = _format_date(wh.get("endedOnYear"), wh.get("endedOnMonth"), is_current=is_cur)
            projects_count = len(wh.get("workHistoryProjects") or [])
            print(f"  - {c_name} [{start_str} 〜 {end_str}] (プロジェクト: {projects_count}件)")
        print()

    # 自己PR抜粋
    bio = profile.get("bio")
    if bio:
        print("■ 自己PR抜粋:")
        bio_lines = [line for line in bio.strip().splitlines() if line.strip()]
        for line in bio_lines[:4]:
            print(f"  {line}")
        if len(bio_lines) > 4:
            print("  ...")
        print()


def save_profile_result(
    data: dict[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    base_filename: str | None = None,
) -> list[Path]:
    """取得結果を data/findy/profile 配下に保存し、latest.md / latest.json も更新する.

    作成・更新された全ファイルパスのリストを返す。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()

    # YYYY-MM-DD 形式（例: 2026-09-18）
    if not base_filename:
        base_filename = now.strftime("%Y-%m-%d")

    data_to_save = {
        "source": "findy",
        "fetched_at": now.isoformat(timespec="seconds"),
        **data,
    }

    saved_files: list[Path] = []

    # 1. 日付別 JSON 形式で保存
    json_path = output_dir / f"{base_filename}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data_to_save, f, ensure_ascii=False, indent=2)
    saved_files.append(json_path)

    # 2. 日付別 フロントマター付き Markdown 形式で保存
    md_path = output_dir / f"{base_filename}.md"
    md_content = generate_profile_markdown(data, now)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    saved_files.append(md_path)

    # 3. latest.json を同期更新
    latest_json_path = output_dir / "latest.json"
    with open(latest_json_path, "w", encoding="utf-8") as f:
        json.dump(data_to_save, f, ensure_ascii=False, indent=2)
    saved_files.append(latest_json_path)

    # 4. latest.md を同期更新
    latest_md_path = output_dir / "latest.md"
    with open(latest_md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    saved_files.append(latest_md_path)

    return saved_files


def main() -> None:
    """CLIエントリポイント."""
    parser = argparse.ArgumentParser(
        epilog=build_epilog(
            examples=[
                "uv run python scripts/findy/fetch_profile.py --summary",
                "uv run python scripts/findy/fetch_profile.py --no-save --json  # 保存せず JSON で確認",
            ],
            related=[
                "scripts/findy/manage_work_history.py: 次に使う（職歴・プロジェクトを更新）",
            ],
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Findyの共通プロファイルを用いて認証チェックを行い、キャリア・スキル画面からプロフィールデータを取得・永続化します。",
    )
    parser.add_argument(
        "-s",
        "--session",
        default="job-hunt",
        help="Playwright CLIセッション名（デフォルト: job-hunt）",
    )
    parser.add_argument(
        "--profile-path",
        type=str,
        default=None,
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
        default=600,
        help="手動ログイン待機のタイムアウト秒数（デフォルト: 600秒）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="取得結果をJSON形式で標準出力する",
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
    parser.add_argument(
        "--summary",
        action="store_true",
        help="プロフィールのサマリをコンソールに整形表示する",
    )

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    fetch_profile_script = FINDY_SCRIPTS_DIR / "fetch_profile.mjs"
    if not fetch_profile_script.exists():
        ctx.error(f"必須スクリプトが見つかりません: {fetch_profile_script}")
        sys.exit(1)

    profile_dir = resolve_profile_path(args.session, args.profile_path)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. 共通認証エンジンによるブラウザ起動・認証確認・手動待機ハンドオフ
        ensure_site_authenticated(
            site="findy",
            session=args.session,
            target_url=TARGET_URL,
            headed=args.headed,
            timeout=args.timeout,
            no_notify=args.no_notify,
            profile_dir=profile_dir,
            exit_on_fail=True,
        )

        # 2. キャリア・スキル画面からプロフィールデータ抽出
        fetch_result = run_code_script(args.session, fetch_profile_script, timeout=30)
        if not fetch_result or not fetch_result.get("success"):
            ctx.error("プロフィール画面への遷移またはキャリアスキルデータ取得に失敗しました。")
            sys.exit(1)

        update_profile_last_used(args.session)

        # 3. ファイル保存
        saved_files: list[Path] = []
        if not args.no_save:
            saved_files = save_profile_result(fetch_result, output_dir=args.output_dir)
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
