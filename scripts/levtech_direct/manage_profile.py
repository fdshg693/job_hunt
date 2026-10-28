"""レバテックダイレクトのプロフィール各セクションを閲覧・更新・SSOT 同期する CLI.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
レバテックダイレクトの全プロファイルセクション:
- 基本情報 (basic: /mypage/profile/basic)
- 経歴企業 (company: /mypage/profile/company)
- 職務経歴・自己PR (resume: /mypage/profile/resume)
- 希望条件 (condition: /mypage/profile/condition)
- 保有スキル (skill: /mypage/profile/skill)
の閲覧（fetch）、更新（update）、SSOT同期（sync）を安全に実行します。

変更操作の実行前には必ず最新プロファイルの自動バックアップを取得し、
--dry-run フラグによる変更プレビュー（Unified Diff）と安全ガードを提供します。
エントリポイントスクリプト規約（.agents/rules/scripts-entrypoint.md）準拠。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/levtech_direct/ の2階層上)
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
from scripts.common.cli import EntrypointContext, create_base_parser
from scripts.common.profile_sync import (
    VaultProfile,
    load_vault_profile,
    print_profile_diff,
    save_profile_backup,
)

LEVTECH_SCRIPTS_DIR = Path(__file__).resolve().parent
MANAGE_SCRIPT_PATH = LEVTECH_SCRIPTS_DIR / "manage_profile.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "levtech_direct" / "profile"
BACKUP_DIR = DEFAULT_OUTPUT_DIR / "backups"

SECTION_URLS: dict[str, str] = {
    "basic": "https://levtech-direct.jp/mypage/profile/basic",
    "company": "https://levtech-direct.jp/mypage/profile/company",
    "resume": "https://levtech-direct.jp/mypage/profile/resume",
    "condition": "https://levtech-direct.jp/mypage/profile/condition",
    "skill": "https://levtech-direct.jp/mypage/profile/skill",
}

ALL_SECTIONS = ["basic", "company", "resume", "condition", "skill"]

# 都道府県マップ
PREFECTURE_NAME_TO_PLACE_ID: dict[str, str] = {
    "東京都": "p_1", "神奈川県": "p_2", "千葉県": "p_3", "埼玉県": "p_4", "茨城県": "p_5",
    "群馬県": "p_6", "栃木県": "p_7", "北海道": "p_8", "青森県": "p_9", "岩手県": "p_10",
    "宮城県": "p_11", "秋田県": "p_12", "山形県": "p_13", "福島県": "p_14", "新潟県": "p_15",
    "富山県": "p_16", "石川県": "p_17", "福井県": "p_18", "山梨県": "p_19", "長野県": "p_20",
    "愛知県": "p_21", "岐阜県": "p_22", "静岡県": "p_23", "三重県": "p_24", "大阪府": "p_25",
    "兵庫県": "p_26", "京都府": "p_27", "滋賀県": "p_28", "奈良県": "p_29", "和歌山県": "p_30",
    "鳥取県": "p_31", "島根県": "p_32", "岡山県": "p_33", "広島県": "p_34", "山口県": "p_35",
    "徳島県": "p_36", "香川県": "p_37", "愛媛県": "p_38", "高知県": "p_39", "福岡県": "p_40",
    "佐賀県": "p_41", "長崎県": "p_42", "熊本県": "p_43", "大分県": "p_44", "宮崎県": "p_45",
    "鹿児島県": "p_46", "沖縄県": "p_47", "海外": "p_48",
}


def execute_manage_action(
    session: str,
    section: str,
    action: str,
    payload: dict[str, Any] | None = None,
    dry_run: bool = False,
    timeout: int = 50,
) -> dict[str, Any]:
    """manage_profile.mjs に section, action, payload, isDryRun を注入して実行する."""
    if not MANAGE_SCRIPT_PATH.exists():
        raise RuntimeError(f"管理スクリプトが見つかりません: {MANAGE_SCRIPT_PATH}")

    target_url = SECTION_URLS.get(section)
    if not target_url:
        raise ValueError(f"未知のセクションです: {section}")

    # セッションオープン
    profile_path = resolve_profile_path(session)
    run_playwright_cmd([f"-s={session}", "open", target_url, f"--profile={profile_path}"])

    template_code = MANAGE_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = (
        template_code.replace("'__LEVTECH_SECTION__'", json.dumps(section))
        .replace("'__LEVTECH_ACTION__'", json.dumps(action))
        .replace("__LEVTECH_PAYLOAD__", json.dumps(payload or {}, ensure_ascii=False))
        .replace("__LEVTECH_DRY_RUN__", "true" if dry_run else "false")
    )

    tmp_script_path = LEVTECH_SCRIPTS_DIR / f".tmp_manage_{section}_{action}.mjs"
    tmp_script_path.write_text(run_code, encoding="utf-8")

    try:
        result = run_code_script(session, tmp_script_path, timeout=timeout)
        if not result:
            raise RuntimeError(f"Playwrightスクリプトの実行に失敗しました: {section}/{action}")
        if not result.get("success"):
            err = result.get("error") or "不明なエラー"
            raise RuntimeError(f"操作実行エラー ({section}/{action}): {err}")
        update_profile_last_used(session)
        return result
    finally:
        if tmp_script_path.exists():
            try:
                tmp_script_path.unlink()
            except Exception:
                pass


# ==============================================================================
# Markdown フォーマッタ
# ==============================================================================


def format_basic_markdown(data: dict[str, Any], fetched_at: datetime) -> str:
    """基本情報データを構造化フロントマター付きMarkdownに整形する."""
    d = data.get("data", data)
    edu = d.get("education") or {}
    lang = d.get("language") or {}
    school_att = d.get("schoolAttendance") or {}

    lines = [
        "---",
        "source: levtech_direct",
        "type: basic_profile",
        f"updated_at: '{fetched_at.isoformat(timespec='seconds')}'",
        f"url: '{SECTION_URLS['basic']}'",
        f"display_id: '{d.get('displayId', '')}'",
        "---",
        "",
        "# レバテックダイレクト 基本情報",
        "",
        "## 基本プロフィール",
        f"- **氏名**: {d.get('lastName', '')} {d.get('firstName', '')} ({d.get('kanaLastName', '')} {d.get('kanaFirstName', '')})",
        f"- **生年月日**: {d.get('birthday', '')}",
        f"- **性別**: {d.get('genderLabel', '未設定')}",
        f"- **電話番号**: {d.get('phoneNumber', '')} (エージェント電話連絡許可: {'許可' if d.get('isAcceptedCallByHeadhunter') else '拒否'})",
        f"- **現住所**: {d.get('prefectureName', '')} {d.get('address', '')}".strip() or "- **現住所**: 未設定",
        f"- **郵便番号**: {d.get('postalCode', '') or '未設定'}",
        f"- **配偶者**: {'あり' if d.get('isMarried') is True else 'なし' if d.get('isMarried') is False else '未設定'}",
        f"- **現在年収**: {d.get('currentAnnualIncome', '')}万円" if d.get("currentAnnualIncome") else "- **現在年収**: 未設定",
        "",
        "## 学歴",
        f"- **学校区分**: {edu.get('schoolCategoryName', '') or '未設定'}",
        f"- **学校名**: {edu.get('schoolName', '') or '未設定'}",
        f"- **学部/学科/専攻**: {edu.get('facultyDepartment', '') or '未設定'}",
        f"- **卒業年月**: {edu.get('graduationDate', '') or '未設定'}",
    ]
    if edu.get("other"):
        lines.append(f"- **その他学歴**: {edu['other']}")

    lines.extend([
        "",
        "## 語学・資格",
        f"- **母国語**: {lang.get('nativeLanguageName', '') or '未設定'}",
        f"- **TOEIC**: {lang.get('toeic', '')}点" if lang.get("toeic") else "- **TOEIC**: 未設定",
        f"- **TOEFL**: {lang.get('toefl', '')}点" if lang.get("toefl") else "- **TOEFL**: 未設定",
    ])
    if d.get("certification"):
        lines.append(f"- **保有資格**:\n```\n{d['certification']}\n```")
    else:
        lines.append("- **保有資格**: 未設定")

    if school_att.get("experience"):
        lines.extend([
            "",
            "## スクール受講歴",
            f"- **受講経験**: {school_att.get('experience', '')}",
            f"- **受講期間**: {school_att.get('period', '') or '未設定'}",
        ])

    return "\n".join(lines) + "\n"


def format_company_markdown(data: dict[str, Any], fetched_at: datetime) -> str:
    """経歴企業データを構造化フロントマター付きMarkdownに整形する."""
    d = data.get("data", data)
    working_state = d.get("workingState") or {}
    business_status = d.get("currentBusinessStatus") or {}
    company_count = d.get("experiencedCompanyCount") or {}
    companies = d.get("companies") or []

    lines = [
        "---",
        "source: levtech_direct",
        "type: profile_company",
        f"updated_at: '{fetched_at.isoformat(timespec='seconds')}'",
        f"url: '{SECTION_URLS['company']}'",
        f"total_companies: {len(companies)}",
        "---",
        "",
        "# レバテックダイレクト 経歴企業",
        "",
        "## 現在の状況",
        f"- **就業状況**: {working_state.get('name', '未設定')}",
        f"- **現在の業務形態**: {business_status.get('name', '未設定')}",
        f"- **経験社数**: {company_count.get('countText', '未設定')}",
        "",
        "## 経歴企業一覧",
    ]

    for comp in companies:
        c_name = comp.get("companyName", "名称未設定")
        is_blocked = " [ブロック企業]" if comp.get("isBlocked") else ""
        lines.append(f"### {c_name}{is_blocked}")
        enrollments = comp.get("enrollments") or []
        for en in enrollments:
            status_name = en.get("employmentStatusName", "")
            period = en.get("periodText", "")
            lines.append(f"- 雇用形態: {status_name} ({period})")
        projects = comp.get("projects") or []
        for pj in projects:
            p_name = pj.get("name", "プロジェクト")
            lines.append(f"  - **{p_name}**")
            if pj.get("period"):
                lines.append(f"    - 期間: {pj['period']}")
            if pj.get("scale"):
                lines.append(f"    - 開発規模: {pj['scale']}")
            if pj.get("position"):
                lines.append(f"    - ポジション: {pj['position']}")
            if pj.get("process"):
                lines.append(f"    - 担当工程: {pj['process']}")
            if pj.get("description"):
                lines.append(f"    - 詳細: {pj['description']}")
        lines.append("")

    return "\n".join(lines) + "\n"


def format_resume_markdown(data: dict[str, Any], fetched_at: datetime) -> str:
    """職務経歴・自己PRデータを構造化フロントマター付きMarkdownに整形する."""
    d = data.get("data", data)
    resume_text = d.get("resume", "")
    char_count = d.get("charCount", len(resume_text))
    updated_at_text = d.get("updatedAtText", "")

    lines = [
        "---",
        "source: levtech_direct",
        "type: profile_resume",
        f"updated_at: '{fetched_at.isoformat(timespec='seconds')}'",
        f"url: '{SECTION_URLS['resume']}'",
        f"char_count: {char_count}",
        f"site_updated_at: '{updated_at_text}'",
        "---",
        "",
        "# レバテックダイレクト 職務経歴・自己PR",
        "",
        f"- **文字数**: {char_count:,} / 30,000文字",
        f"- **サイト更新日**: {updated_at_text or '未記載'}",
        "",
        "## 登録テキスト",
        "",
        resume_text,
        "",
    ]
    return "\n".join(lines)


def format_condition_markdown(data: dict[str, Any], fetched_at: datetime) -> str:
    """希望条件データを構造化フロントマター付きMarkdownに整形する."""
    d = data.get("data", data)
    lines = [
        "---",
        "source: levtech_direct",
        "type: profile_condition",
        f"updated_at: '{fetched_at.isoformat(timespec='seconds')}'",
        f"url: '{SECTION_URLS['condition']}'",
        f"annual_income: {d.get('annualIncome')}",
        "---",
        "",
        "# レバテックダイレクト 希望条件",
        "",
        f"- **希望年収**: {d.get('annualIncome')}万円" if d.get("annualIncome") else "- **希望年収**: 未設定",
        f"- **転職希望時期**: {d.get('jobChangePeriodLabel', '未設定')}",
        "",
        "## 希望職種・スキル・勤務地",
        f"- **希望職種**: {', '.join([o.get('name', '') for o in d.get('occupations', [])]) or '未設定'}",
        f"- **希望スキル**: {', '.join([s.get('name', '') for s in d.get('skills', [])]) or '未設定'}",
        f"- **希望勤務地**: {', '.join([p.get('name', '') for p in d.get('workPlaces', [])]) or '未設定'}",
        "",
        "## 雇用形態・働き方",
        f"- **希望雇用形態**: {', '.join([e.get('name', '') for e in d.get('desiredEmploymentStatuses', [])]) or '未設定'}",
        f"- **こだわり条件**: {', '.join([w.get('name', '') for w in d.get('workStyles', [])]) or '未設定'}",
        "",
    ]
    if d.get("other"):
        lines.append(f"## その他希望条件\n\n{d['other']}\n")
    return "\n".join(lines)


def format_skill_markdown(data: dict[str, Any], fetched_at: datetime) -> str:
    """保有スキルデータを構造化フロントマター付きMarkdownに整形する."""
    d = data.get("data", data)
    skills = d.get("skills", [])
    cur_occ = d.get("currentOccupation") or {}
    mgmt = d.get("managementScale") or {}

    lines = [
        "---",
        "source: levtech_direct",
        "type: profile_skill",
        f"updated_at: '{fetched_at.isoformat(timespec='seconds')}'",
        f"url: '{SECTION_URLS['skill']}'",
        f"total_skills: {len(skills)}",
        "---",
        "",
        "# レバテックダイレクト 保有スキル",
        "",
        f"- **現在の職種**: {cur_occ.get('name', '未設定')}",
        f"- **マネジメント規模**: {mgmt.get('name', '未設定')}",
        "",
        "## 保有スキル一覧",
    ]
    for s in skills:
        lines.append(f"- **{s.get('name', '')}**: {s.get('experienceYears', '経験年数未設定')}")
    lines.append("")
    return "\n".join(lines)


def save_section_result(
    section: str,
    data: dict[str, Any],
    output_dir: Path,
    backup_only: bool = False,
) -> list[Path]:
    """各セクションのデータをJSONおよびMarkdownで永続化する."""
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    saved_files: list[Path] = []

    # 1. バックアップ保存
    backup_path = save_profile_backup(
        site="levtech_direct",
        section=section,
        data=data,
        backup_dir=BACKUP_DIR,
        timestamp=now,
    )
    saved_files.append(backup_path)

    if backup_only:
        return saved_files

    # 2. 最新JSON保存
    latest_json = output_dir / f"{section}_profile.json"
    latest_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    saved_files.append(latest_json)

    # 3. 最新Markdown保存
    md_formatter = {
        "basic": format_basic_markdown,
        "company": format_company_markdown,
        "resume": format_resume_markdown,
        "condition": format_condition_markdown,
        "skill": format_skill_markdown,
    }.get(section)

    if md_formatter:
        md_content = md_formatter(data, now)
        latest_md = output_dir / f"{section}_profile.md"
        latest_md.write_text(md_content, encoding="utf-8")
        saved_files.append(latest_md)

    return saved_files


# ==============================================================================
# サマリ表示
# ==============================================================================


def print_section_summary(section: str, data: dict[str, Any]) -> None:
    """各セクションのサマリをコンソールに表示する."""
    d = data.get("data", data)
    print("\n========================================================")
    print(f" レバテックダイレクト [{section.upper()}] サマリ")
    print(f" URL: {SECTION_URLS.get(section, '')}")
    print("========================================================\n")

    if section == "basic":
        edu = d.get("education") or {}
        lang = d.get("language") or {}
        print(f"氏名:       {d.get('lastName', '')} {d.get('firstName', '')} ({d.get('kanaLastName', '')} {d.get('kanaFirstName', '')})")
        print(f"生年月日:   {d.get('birthday', '未設定')} ({d.get('genderLabel', '未設定')})")
        print(f"現住所:     {d.get('prefectureName', '')} {d.get('address', '')}".strip() or "現住所:     未設定")
        print(f"現在年収:   {d.get('currentAnnualIncome', '未設定')} 万円")
        print(f"学歴:       {edu.get('schoolCategoryName', '')} {edu.get('schoolName', '')} ({edu.get('graduationDate', '')})")
        print(f"語学・資格: 母国語:{lang.get('nativeLanguageName', '')} / TOEIC:{lang.get('toeic', '未設定')}")

    elif section == "company":
        ws = d.get("workingState") or {}
        bs = d.get("currentBusinessStatus") or {}
        cc = d.get("experiencedCompanyCount") or {}
        comps = d.get("companies") or []
        print(f"就業状況:     {ws.get('name', '未設定')}")
        print(f"現在の業務形態: {bs.get('name', '未設定')}")
        print(f"経験社数:     {cc.get('countText', '未設定')} (登録企業: {len(comps)}社)")
        for c in comps:
            print(f"・{c.get('companyName', '')} ({', '.join([e.get('employmentStatusName', '') for e in c.get('enrollments', [])])})")

    elif section == "resume":
        resume_text = d.get("resume", "")
        print(f"文字数:     {d.get('charCount', len(resume_text))} / 30,000文字")
        print(f"サイト更新日: {d.get('updatedAtText', '未記載')}")
        print("-" * 56)
        preview = resume_text[:300] + ("..." if len(resume_text) > 300 else "")
        print(preview)

    elif section == "condition":
        print(f"希望年収:   {d.get('annualIncome', '未設定')} 万円")
        print(f"転職希望時期: {d.get('jobChangePeriodLabel', '未設定')}")
        print(f"希望職種:   {', '.join([o.get('name', '') for o in d.get('occupations', [])])}")
        print(f"希望スキル: {', '.join([s.get('name', '') for s in d.get('skills', [])])}")
        print(f"希望勤務地: {', '.join([p.get('name', '') for p in d.get('workPlaces', [])])}")

    elif section == "skill":
        cur_occ = d.get("currentOccupation") or {}
        mgmt = d.get("managementScale") or {}
        skills = d.get("skills", [])
        print(f"現在の職種:     {cur_occ.get('name', '未設定')}")
        print(f"マネジメント規模: {mgmt.get('name', '未設定')}")
        print(f"登録スキル数:   {len(skills)}件")
        for s in skills[:10]:
            print(f"・{s.get('name', '')}: {s.get('experienceYears', '')}")
        if len(skills) > 10:
            print(f"  ... 他 {len(skills) - 10}件")

    print("========================================================\n")


# ==============================================================================
# SSOT (vault/profile/) からの同期ペイロード抽出
# ==============================================================================


def extract_sync_payload(section: str, profile: VaultProfile) -> dict[str, Any]:
    """SSOTプロフィールから各セクションの同期ペイロードを抽出する."""
    payload: dict[str, Any] = {}

    if section == "basic":
        last, first = profile.get_name_parts()
        if last:
            payload["lastName"] = last
        if first:
            payload["firstName"] = first

        kana_last, kana_first = profile.get_kana_parts()
        if kana_last:
            payload["kanaLastName"] = kana_last
        if kana_first:
            payload["kanaFirstName"] = kana_first

        if profile.birth_date:
            payload["birthday"] = profile.birth_date
        if profile.current_annual_income:
            payload["currentAnnualIncome"] = profile.current_annual_income // 10000
        if profile.toeic_score:
            payload["toeic"] = profile.toeic_score
        if profile.phone:
            payload["phoneNumber"] = profile.phone.replace("-", "")
        if profile.location:
            payload["prefectureId"] = profile.location
        if profile.certifications:
            payload["certification"] = "\n".join(profile.certifications)

        latest_edu = profile.get_latest_education()
        if latest_edu:
            payload["education"] = {
                "schoolCategoryId": 1,  # 大学
                "schoolName": latest_edu.school_name,
                "facultyDepartment": f"{latest_edu.faculty} {latest_edu.department}".strip(),
                "graduationYear": int(latest_edu.end_year) if latest_edu.end_year and latest_edu.end_year.isdigit() else 2024,
                "graduationMonth": int(latest_edu.end_month) if latest_edu.end_month and latest_edu.end_month.isdigit() else 3,
            }

    elif section == "company":
        payload["workingStateId"] = 1  # 正社員で就業中
        payload["currentBusinessStatus"] = "business_company"  # 事業会社
        payload["experiencedCompanyCountId"] = max(1, len(profile.companies))

        comp_list = []
        for c in profile.companies:
            projects = []
            for p in c.projects:
                projects.append({
                    "name": p.name,
                    "startYear": int(p.start_year) if p.start_year and p.start_year.isdigit() else None,
                    "startMonth": int(p.start_month) if p.start_month and p.start_month.isdigit() else None,
                    "endYear": int(p.end_year) if p.end_year and p.end_year.isdigit() else None,
                    "endMonth": int(p.end_month) if p.end_month and p.end_month.isdigit() else None,
                    "isCurrent": p.is_current,
                    "description": "\n".join([f"・{b}" for b in p.bullets]) if p.bullets else p.description,
                })
            comp_list.append({
                "companyName": c.company_name,
                "isBlocked": False,
                "enrollments": [{
                    "employmentStatusId": 1 if "正社員" in c.employment_type else 4,
                    "startYear": int(c.start_year) if c.start_year and c.start_year.isdigit() else None,
                    "startMonth": int(c.start_month) if c.start_month and c.start_month.isdigit() else None,
                    "endYear": int(c.end_year) if c.end_year and c.end_year.isdigit() else None,
                    "endMonth": int(c.end_month) if c.end_month and c.end_month.isdigit() else None,
                    "isCurrent": c.is_current,
                }],
                "projects": projects,
            })
        if comp_list:
            payload["companies"] = comp_list

    elif section == "resume":
        payload["resume"] = profile.generate_combined_resume_text()

    elif section == "condition":
        if profile.target_annual_income_min:
            payload["annualIncome"] = profile.target_annual_income_min // 10000
        elif profile.current_annual_income:
            payload["annualIncome"] = profile.current_annual_income // 10000

        # リモート希望
        if "フルリモート" in profile.remote_preference:
            payload["jobConditions"] = {"remoteWork": "full_remote"}
        elif "リモート" in profile.remote_preference:
            payload["jobConditions"] = {"remoteWork": "hybrid_work"}

        # 勤務地
        if profile.location and profile.location in PREFECTURE_NAME_TO_PLACE_ID:
            payload["workPlaces"] = [PREFECTURE_NAME_TO_PLACE_ID[profile.location]]

        # スキル
        skills = profile.primary_skills or [lang.name for lang in profile.languages]
        if skills:
            payload["skills"] = skills[:5]

    elif section == "skill":
        skills_payload = []
        for lang in profile.languages:
            skills_payload.append({"name": lang.name, "years": lang.years or 2.0})
        for fw in profile.frameworks_libraries[:5]:
            skills_payload.append({"name": fw, "years": 2.0})
        if skills_payload:
            payload["skills"] = skills_payload
        payload["currentOccupation"] = 1  # Webエンジニア/システムエンジニア
        payload["managementScale"] = 5    # 経験なし or 1~5人

    return payload


# ==============================================================================
# セクション処理ハンドラ
# ==============================================================================


def handle_section(
    session: str,
    section: str,
    action: str,
    payload: dict[str, Any] | None = None,
    dry_run: bool = False,
    output_dir: Path | None = None,
    ctx: EntrypointContext | None = None,
) -> int:
    """単一セクションの fetch / update / sync を実行する."""
    out_dir = output_dir or DEFAULT_OUTPUT_DIR
    if ctx is None:
        ctx = EntrypointContext()

    if action == "fetch":
        ctx.log(f"[INFO] レバテックダイレクト {section} 情報を取得中...")
        result = execute_manage_action(session, section, "fetch")
        saved_paths = save_section_result(section, result, output_dir=out_dir)
        ctx.add_result_paths(saved_paths)
        return ctx.flush_outputs(
            summary_fn=lambda: print_section_summary(section, result),
            json_data=result,
        )

    elif action in ("update", "sync"):
        # 1. 変更前バックアップ取得
        ctx.log(f"[INFO] 変更前自動バックアップ（最新 {section} 取得）を実行中...")
        prev_result = execute_manage_action(session, section, "fetch")
        save_section_result(section, prev_result, output_dir=out_dir, backup_only=True)

        # 2. ペイロード解決
        final_payload = payload or {}
        if action == "sync":
            ctx.log(f"[INFO] vault/profile/ から {section} ペイロードを抽出中...")
            profile = load_vault_profile()
            final_payload = extract_sync_payload(section, profile)

        if not final_payload:
            ctx.error(f"[{section}] 更新する項目が指定されていません。")
            return 1

        # 3. ブラウザ反映実行
        ctx.log(f"[INFO] {section} の反映を実行中 (dry_run={dry_run})...")
        update_result = execute_manage_action(
            session,
            section,
            "update",
            payload=final_payload,
            dry_run=dry_run,
        )

        prev_data = prev_result.get("data", {})
        new_data = update_result.get("data", {})

        # 4. 差分表示
        print_profile_diff(
            prev_data,
            new_data,
            title=f"レバテックダイレクト [{section.upper()}] 変更差分",
        )

        if dry_run:
            ctx.log(f"[INFO] --dry-run 指定のため {section} の保存は実行されませんでした。")
            return ctx.flush_outputs(
                summary_fn=lambda: print_section_summary(section, update_result),
                json_data=update_result,
            )
        else:
            saved_paths = save_section_result(section, update_result, output_dir=out_dir)
            ctx.add_result_paths(saved_paths)
            ctx.log(f"[INFO] {section} の保存が完了しました。")
            return ctx.flush_outputs(
                summary_fn=lambda: print_section_summary(section, update_result),
                json_data=update_result,
            )

    else:
        ctx.error(f"未知のアクションです: {action}")
        return 1


# ==============================================================================
# CLI エントリポイント
# ==============================================================================


def setup_cli_parser() -> argparse.ArgumentParser:
    """統合CLIの引数パーサーを構築する."""
    parser = create_base_parser(
        description="レバテックダイレクト マイページ統合プロファイル管理CLI",
        examples=[
            "uv run python scripts/levtech_direct/manage_profile.py --summary basic fetch",
            "uv run python scripts/levtech_direct/manage_profile.py --summary condition update --annual-income 600 --dry-run",
            "uv run python scripts/levtech_direct/manage_profile.py --summary sync --sections basic,condition --dry-run  # vault/profile/ から同期",
        ],
    )
    parser.add_argument(
        "--session",
        type=str,
        default="job-hunt",
        help="ブラウザプロファイルセッション名 (デフォルト: job-hunt)",
    )

    subparsers = parser.add_subparsers(dest="section", help="対象セクション (または sync)")

    # 1. basic
    p_basic = subparsers.add_parser("basic", help="基本情報 (/mypage/profile/basic) の管理")
    sp_basic = p_basic.add_subparsers(dest="action", help="実行アクション")
    sp_basic.add_parser("fetch", help="現在の基本情報を取得・保存する")
    u_basic = sp_basic.add_parser("update", help="基本情報を更新する")
    u_basic.add_argument("--dry-run", action="store_true", help="保存を実行せず差分プレビューのみ表示")
    u_basic.add_argument("--last-name", type=str, help="姓 (漢字)")
    u_basic.add_argument("--first-name", type=str, help="名 (漢字)")
    u_basic.add_argument("--kana-last-name", type=str, help="セイ (カタカナ)")
    u_basic.add_argument("--kana-first-name", type=str, help="メイ (カタカナ)")
    u_basic.add_argument("--birthday", type=str, help="生年月日 (YYYY-MM-DD)")
    u_basic.add_argument("--gender", type=int, choices=[1, 2, 3], help="性別 (1:男性, 2:女性, 3:無回答)")
    u_basic.add_argument("--phone", type=str, help="電話番号 (ハイフンなし)")
    u_basic.add_argument("--annual-income", type=int, help="現在年収 (万円)")
    u_basic.add_argument("--toeic", type=int, help="TOEICスコア")
    u_basic.add_argument("--certification", type=str, help="保有資格テキスト")
    u_basic.add_argument("--payload", type=str, help="JSON文字列による直接指定")
    u_basic.add_argument("--payload-file", type=str, help="JSONファイルによる直接指定")
    s_basic = sp_basic.add_parser("sync", help="vault/profile/resume.md から基本情報を自動同期する")
    s_basic.add_argument("--dry-run", action="store_true", help="保存を実行せず差分プレビューのみ表示")

    # 2. company
    p_comp = subparsers.add_parser("company", help="経歴企業 (/mypage/profile/company) の管理")
    sp_comp = p_comp.add_subparsers(dest="action", help="実行アクション")
    sp_comp.add_parser("fetch", help="現在の経歴企業を取得・保存する")
    u_comp = sp_comp.add_parser("update", help="経歴企業を更新する")
    u_comp.add_argument("--dry-run", action="store_true", help="保存を実行せず差分プレビューのみ表示")
    u_comp.add_argument("--working-state", type=int, help="就業状況ID")
    u_comp.add_argument("--business-status", type=str, help="現在の業務形態")
    u_comp.add_argument("--payload", type=str, help="JSON文字列による直接指定")
    u_comp.add_argument("--payload-file", type=str, help="JSONファイルによる直接指定")
    s_comp = sp_comp.add_parser("sync", help="vault/profile/resume.md から経歴企業を自動同期する")
    s_comp.add_argument("--dry-run", action="store_true", help="保存を実行せず差分プレビューのみ表示")

    # 3. resume
    p_res = subparsers.add_parser("resume", help="職務経歴・自己PR (/mypage/profile/resume) の管理")
    sp_res = p_res.add_subparsers(dest="action", help="実行アクション")
    sp_res.add_parser("fetch", help="現在の職務経歴・自己PRを取得・保存する")
    u_res = sp_res.add_parser("update", help="職務経歴・自己PRを更新する")
    u_res.add_argument("--dry-run", action="store_true", help="保存を実行せず差分プレビューのみ表示")
    u_res.add_argument("--resume", type=str, help="職務経歴テキスト")
    u_res.add_argument("--resume-file", type=str, help="職務経歴テキストファイル")
    s_res = sp_res.add_parser("sync", help="vault/profile/ から統合職務経歴書を自動同期する")
    s_res.add_argument("--dry-run", action="store_true", help="保存を実行せず差分プレビューのみ表示")

    # 4. condition
    p_cond = subparsers.add_parser("condition", help="希望条件 (/mypage/profile/condition) の管理")
    sp_cond = p_cond.add_subparsers(dest="action", help="実行アクション")
    sp_cond.add_parser("fetch", help="現在の希望条件を取得・保存する")
    u_cond = sp_cond.add_parser("update", help="希望条件を更新する")
    u_cond.add_argument("--dry-run", action="store_true", help="保存を実行せず差分プレビューのみ表示")
    u_cond.add_argument("--annual-income", type=int, help="希望年収 (万円)")
    u_cond.add_argument("--payload", type=str, help="JSON文字列による直接指定")
    u_cond.add_argument("--payload-file", type=str, help="JSONファイルによる直接指定")
    s_cond = sp_cond.add_parser("sync", help="vault/profile/ から希望条件を自動同期する")
    s_cond.add_argument("--dry-run", action="store_true", help="保存を実行せず差分プレビューのみ表示")

    # 5. skill
    p_skill = subparsers.add_parser("skill", help="保有スキル (/mypage/profile/skill) の管理")
    sp_skill = p_skill.add_subparsers(dest="action", help="実行アクション")
    sp_skill.add_parser("fetch", help="現在の保有スキルを取得・保存する")
    u_skill = sp_skill.add_parser("update", help="保有スキルを更新する")
    u_skill.add_argument("--dry-run", action="store_true", help="保存を実行せず差分プレビューのみ表示")
    u_skill.add_argument("--payload", type=str, help="JSON文字列による直接指定")
    u_skill.add_argument("--payload-file", type=str, help="JSONファイルによる直接指定")
    s_skill = sp_skill.add_parser("sync", help="vault/profile/skills.md から保有スキルを自動同期する")
    s_skill.add_argument("--dry-run", action="store_true", help="保存を実行せず差分プレビューのみ表示")

    # 6. 一括 sync
    p_all_sync = subparsers.add_parser("sync", help="vault/profile/ から全セクションを一括同期する")
    p_all_sync.add_argument("--dry-run", action="store_true", help="保存を実行せず差分プレビューのみ表示")
    p_all_sync.add_argument(
        "--sections",
        type=str,
        default="all",
        help="同期対象セクション (カンマ区切り: basic,company,resume,condition,skill または all)",
    )

    return parser


def run_section_cli(section: str, argv: list[str] | None = None) -> int:
    """旧スクリプトからの呼び出し用互換エントリーポイント."""
    args_list = list(sys.argv[1:] if argv is None else argv)
    # 引数の先頭にセクション名を挿入して main を実行
    new_argv = [sys.argv[0], section] + args_list
    sys_argv_backup = sys.argv
    try:
        sys.argv = new_argv
        return main()
    finally:
        sys.argv = sys_argv_backup


def main() -> int:
    parser = setup_cli_parser()
    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    section = args.section
    if not section:
        parser.print_help()
        return 1

    # 認証ガード（セクションのURLで確認）
    target_check_url = SECTION_URLS.get(section if section != "sync" else "basic", SECTION_URLS["basic"])
    if not ensure_site_authenticated("levtech_direct", session=args.session, target_url=target_check_url, exit_on_fail=False):
        ctx.error("レバテックダイレクトの認証状態が確認できませんでした。")
        return 2

    output_dir = DEFAULT_OUTPUT_DIR

    try:
        # 全体一括 sync
        if section == "sync":
            is_dry_run = getattr(args, "dry_run", False)
            sections_str = getattr(args, "sections", "all")
            target_sections = ALL_SECTIONS if sections_str == "all" else [s.strip() for s in sections_str.split(",") if s.strip()]

            ctx.log(f"[INFO] レバテックダイレクト 一括同期を開始します: {', '.join(target_sections)} (dry_run={is_dry_run})")
            for sec in target_sections:
                if sec not in SECTION_URLS:
                    ctx.log(f"[WARN] 未知のセクションのためスキップ: {sec}")
                    continue
                ctx.log(f"\n>>> セクション [{sec.upper()}] の同期処理中...")
                ret = handle_section(
                    session=args.session,
                    section=sec,
                    action="sync",
                    dry_run=is_dry_run,
                    output_dir=output_dir,
                    ctx=ctx,
                )
                if ret != 0:
                    ctx.error(f"[{sec}] の同期に失敗しました (exit={ret})")
                    return ret

            ctx.log("\n[SUCCESS] 一括同期処理が正常に完了しました。")
            return 0

        # 個別セクション (basic, company, resume, condition, skill)
        action = getattr(args, "action", "fetch") or "fetch"
        is_dry_run = getattr(args, "dry_run", False)

        # update ペイロード作成
        payload: dict[str, Any] = {}
        if action == "update":
            if getattr(args, "payload", None):
                payload = json.loads(args.payload)
            elif getattr(args, "payload_file", None):
                payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
            elif section == "resume" and getattr(args, "resume_file", None):
                payload["resume"] = Path(args.resume_file).read_text(encoding="utf-8")
            elif section == "resume" and getattr(args, "resume", None):
                payload["resume"] = args.resume
            else:
                # 引数から自動構築
                for key, val in vars(args).items():
                    if key in ("section", "action", "session", "summary", "json", "dry_run") or val is None:
                        continue
                    payload[key] = val

        return handle_section(
            session=args.session,
            section=section,
            action=action,
            payload=payload if payload else None,
            dry_run=is_dry_run,
            output_dir=output_dir,
            ctx=ctx,
        )

    except Exception as e:
        ctx.error(f"実行中エラー: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
