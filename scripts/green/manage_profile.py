"""Green（green-japan.com）プロフィール CRUD管理・同期スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
Green のプロフィール編集画面（/profiles/edit）における
基本情報、在籍企業、保有スキル、希望条件、職務経歴書（フリーフォーマット）等の
閲覧・更新・自動バックアップ・SSOT（profile/）同期を安全に実行します。

変更操作の実行前には必ず最新プロフィールの完全自動バックアップを取得し、
--dry-run フラグによる変更プレビュー（Unified Diff）と安全ガードを提供します。
エントリポイントスクリプト規約（.agents/rules/scripts-entrypoint.md）準拠。
"""

from __future__ import annotations

import argparse
import difflib
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
from scripts.common.cli import EntrypointContext, create_base_parser, to_relative_path

GREEN_SCRIPTS_DIR = Path(__file__).resolve().parent
MANAGE_SCRIPT_PATH = GREEN_SCRIPTS_DIR / "manage_profile.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "green" / "profile"
BACKUP_DIR = DEFAULT_OUTPUT_DIR / "backups"
TARGET_URL = "https://www.green-japan.com/profiles/edit"


def execute_manage_action(
    session: str,
    action: str,
    payload: dict[str, Any] | None = None,
    dry_run: bool = False,
    timeout: int = 45,
) -> dict[str, Any]:
    """manage_profile.mjs に action, payload, isDryRun を注入して実行する."""
    if not MANAGE_SCRIPT_PATH.exists():
        raise RuntimeError(f"管理スクリプトが見つかりません: {MANAGE_SCRIPT_PATH}")

    profile_path = resolve_profile_path(session)
    run_playwright_cmd([f"-s={session}", "open", TARGET_URL, f"--profile={profile_path}"])

    template_code = MANAGE_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = (
        template_code.replace("'__GREEN_ACTION__'", json.dumps(action))
        .replace("__GREEN_PAYLOAD__", json.dumps(payload or {}, ensure_ascii=False))
        .replace("__GREEN_DRY_RUN__", "true" if dry_run else "false")
    )

    tmp_script_path = GREEN_SCRIPTS_DIR / f".tmp_manage_{action}.mjs"
    tmp_script_path.write_text(run_code, encoding="utf-8")

    try:
        result = run_code_script(session, tmp_script_path, timeout=timeout)
        if not result:
            raise RuntimeError(f"Playwrightスクリプトの実行に失敗しました: {action}")
        if not result.get("success"):
            err = result.get("error") or "不明なエラー"
            raise RuntimeError(f"操作実行エラー ({action}): {err}")
        update_profile_last_used(session)
        return result
    finally:
        if tmp_script_path.exists():
            try:
                tmp_script_path.unlink()
            except Exception:
                pass


def format_profile_markdown(data: dict[str, Any], fetched_at: datetime) -> str:
    """Greenの完全プロフィールデータをフロントマター付きMarkdownに整形する."""
    user_data = data.get("userData") or {}
    user_resume = data.get("userResume") or {}
    block_companies = data.get("blockCompanies") or {}

    resume_text = user_resume.get("resume") or ""
    companies = user_data.get("userCompanies") or []
    skills = user_data.get("userSkills") or []
    exp_job_tags = user_data.get("userExpJobTags") or []
    hope_job_tags = user_data.get("userHopeJobTags") or []
    hope_areas = user_data.get("userHopeAreas") or []
    hope_conditions = user_data.get("userHopeConditions") or []
    statement = user_data.get("careerChangeStatement") or {}
    school = user_data.get("userGraduationSchool") or {}

    full_name = f"{user_data.get('lastName', '')} {user_data.get('firstName', '')}".strip()
    full_kana = f"{user_data.get('lastKana', '')} {user_data.get('firstKana', '')}".strip()

    lines = [
        "---",
        "source: green",
        "type: profile",
        f"updated_at: '{fetched_at.isoformat(timespec='seconds')}'",
        f"url: '{TARGET_URL}'",
        f"user_id: {user_data.get('id', '')}",
        f"name: '{full_name}'",
        f"age: {user_data.get('age', '')}",
        f"salary_current_man: {user_data.get('salary', '')}",
        "---",
        "",
        f"# Green 登録プロフィール ({full_name})",
        "",
        "## 基本情報",
        "",
        f"- **氏名**: {full_name} ({full_kana})",
        f"- **メールアドレス**: {user_data.get('mail', '')}",
        f"- **電話番号**: {user_data.get('phoneNumber', '')}",
        f"- **年齢**: {user_data.get('age', '')}歳",
        f"- **現住所**: {user_data.get('address', '')}",
        f"- **現（前）年収**: {user_data.get('salary', '')} 万円",
        f"- **TOEIC**: {user_data.get('toeic', '未登録')}",
        "",
        "## 最終学歴",
        "",
        f"- **学校名**: {school.get('schoolName', '')} ({school.get('schoolTypeName', '')})",
        f"- **学部・学科**: {school.get('departmentName', '')}",
        f"- **卒業年月**: {school.get('schoolGraduationYear', '')}年{school.get('schoolGraduationMonth', '')}月 ({school.get('graduationTypeName', '')})",
        "",
        "## 在籍企業・職歴",
        "",
    ]

    if companies:
        for c in companies:
            c_name = c.get("companyName") or "企業名非公開"
            emp_status = c.get("employmentStatusName") or "正社員"
            start_str = f"{c.get('startedOnYear', '')}年{c.get('startedOnMonth', '')}月"
            if c.get("enrolment"):
                period_str = f"{start_str} 〜 在籍中"
            else:
                period_str = f"{start_str} 〜 {c.get('endedOnYear', '')}年{c.get('endedOnMonth', '')}月"
            lines.append(f"### {c_name}")
            lines.append(f"- **雇用形態**: {emp_status}")
            lines.append(f"- **期間**: {period_str}")
            lines.append("")
    else:
        lines.append("- （登録された職歴企業はありません）")
        lines.append("")

    lines.append("## 保有スキル")
    lines.append("")
    if skills:
        skill_strs = []
        for s in skills:
            s_name = s.get("skill", {}).get("name") if isinstance(s.get("skill"), dict) else s.get("name", "")
            s_score = s.get("skillScore", {}).get("name") if isinstance(s.get("skillScore"), dict) else s.get("experienceYears", "")
            if s_name:
                skill_strs.append(f"{s_name} ({s_score})" if s_score else s_name)
        lines.append(", ".join(skill_strs))
    else:
        lines.append("- （登録されたスキルはありません）")
    lines.append("")

    lines.append("## 経験職種")
    lines.append("")
    if exp_job_tags:
        for j in exp_job_tags:
            tag_name = j.get("jobTag", {}).get("name") if isinstance(j.get("jobTag"), dict) else j.get("name", "")
            years = j.get("jobTag", {}).get("yearsOfExperience") if isinstance(j.get("jobTag"), dict) else j.get("experienceYears", "")
            lines.append(f"- {tag_name} ({years}年)" if years else f"- {tag_name}")
    else:
        lines.append("- （登録なし）")
    lines.append("")

    lines.append("## 希望条件")
    lines.append("")
    if hope_areas:
        area_names = [a.get("hopeArea", {}).get("name", "") for a in hope_areas if isinstance(a.get("hopeArea"), dict)]
        lines.append(f"- **希望勤務地**: {', '.join(area_names)}")
    if hope_job_tags:
        job_names = [j.get("jobTag", {}).get("name", "") for j in hope_job_tags if isinstance(j.get("jobTag"), dict)]
        lines.append(f"- **希望職種**: {', '.join(job_names)}")
    if hope_conditions:
        for hc in hope_conditions:
            lines.append(f"- **希望年収**: {hc.get('hopeSalary', '')} 万円 ({hc.get('hopeSalaryRemark', '')})")
    lines.append("")

    point_comment = statement.get("careerChangePoint", {}).get("comment") if isinstance(statement.get("careerChangePoint"), dict) else statement.get("careerChangePoint")
    highlight_comment = statement.get("careerHighlight", {}).get("comment") if isinstance(statement.get("careerHighlight"), dict) else statement.get("careerHighlight")
    supp_comment = statement.get("careerChangeStatementSupplement", {}).get("comment") if isinstance(statement.get("careerChangeStatementSupplement"), dict) else statement.get("careerChangeStatementSupplement")

    lines.append("## 企業に伝えたいこと")
    lines.append("")
    lines.append(f"- **前職から変えたいこと**: {point_comment or '未記入'}")
    lines.append(f"- **見てほしい役割・環境**: {highlight_comment or '未記入'}")
    lines.append(f"- **その他アピール・補足**: {supp_comment or '未記入'}")
    lines.append("")

    lines.append("## 職務経歴書・自己PR (フリーフォーマット)")
    lines.append("")
    lines.append("```text")
    lines.append(resume_text.strip())
    lines.append("```")
    lines.append("")

    blocks = block_companies.get("userBlockCompanies") or []
    if blocks:
        lines.append("## ブロック企業")
        lines.append("")
        for b in blocks:
            c = b.get("company") or {}
            lines.append(f"- {c.get('name', '')} ({c.get('homepageUrl', '')})")
        lines.append("")

    return "\n".join(lines)


def save_profile_data(
    data: dict[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    backup_tag: str | None = None,
) -> list[Path]:
    """プロフィールデータ（JSON & Markdown）を保存する."""
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    saved: list[Path] = []

    if backup_tag:
        # バックアップ保存
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = now.strftime("%Y%m%d_%H%M%S")
        backup_file = BACKUP_DIR / f"{ts}_{backup_tag}.json"
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        saved.append(backup_file)
        return saved

    # latest 保存
    json_path = output_dir / "latest.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    saved.append(json_path)

    md_content = format_profile_markdown(data, now)
    md_path = output_dir / "latest.md"
    md_path.write_text(md_content, encoding="utf-8")
    saved.append(md_path)

    return saved


def backup_current_profile(session: str, action_name: str = "update") -> list[Path]:
    """変更操作前に最新のプロフィールデータを自動バックアップする."""
    res = execute_manage_action(session, "view")
    if not res.get("success"):
        raise RuntimeError("変更前自動バックアップに失敗したため、操作を中断します。")

    data = res.get("data") or {}
    saved_backups = save_profile_data(data, backup_tag=f"before_{action_name}")
    for p in saved_backups:
        print(f"[安全ガード] 変更前バックアップを保存しました: {to_relative_path(p)}", file=sys.stderr)
    return saved_backups


def print_diff(previous: str, new: str, from_label: str = "現在登録内容", to_label: str = "反映予定内容") -> None:
    """テキスト差分（Unified Diff）をターミナルに出力する."""
    prev_lines = previous.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(
        prev_lines,
        new_lines,
        fromfile=from_label,
        tofile=to_label,
        lineterm="",
    )
    diff_text = "".join(diff)
    if diff_text:
        print("\n--- 差分プレビュー (Unified Diff) ---", file=sys.stderr)
        print(diff_text, file=sys.stderr)
        print("------------------------------------\n", file=sys.stderr)
    else:
        print("\n[差分なし] 登録内容と同一です。\n", file=sys.stderr)


def extract_resume_from_profile_ssot() -> str:
    """profile/resume.md からGreen向けの職務経歴書フリーテキストを生成する."""
    resume_path = PROJECT_ROOT / "profile" / "resume.md"
    if not resume_path.exists():
        raise FileNotFoundError(f"職務経歴書マスターが見つかりません: {resume_path}")

    content = resume_path.read_text(encoding="utf-8")

    # Frontmatter除去
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            content = parts[2].strip()

    return content


# ----------------------------------------------------------------------
# 各アクションハンドラー
# ----------------------------------------------------------------------


def handle_view(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """プロフィール全情報の取得と保存."""
    result = execute_manage_action(session, "view")
    data = result.get("data") or {}

    saved_paths = save_profile_data(data)
    ctx.add_result_paths(saved_paths)

    def summary_fn() -> None:
        user_data = data.get("userData") or {}
        full_name = f"{user_data.get('lastName', '')} {user_data.get('firstName', '')}".strip()
        print("=== Green プロフィール情報取得完了 ===")
        print(f"- 氏名: {full_name}")
        print(f"- 年齢: {user_data.get('age')} 歳")
        print(f"- 現年収: {user_data.get('salary')} 万円")
        print(f"- 登録スキル数: {len(user_data.get('userSkills') or [])} 件")
        print(f"- 職歴社数: {len(user_data.get('userCompanies') or [])} 社")
        print(f"- 職務経歴書文字数: {len((data.get('userResume') or {}).get('resume') or '')} 文字")
        print("\n[保存ファイル]")
        for p in saved_paths:
            print(f"  - {to_relative_path(p)}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=result)


def handle_update_resume(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """職務経歴書・自己PRテキスト（userResume）の更新."""
    new_text = ""
    if getattr(args, "resume_text", None):
        new_text = args.resume_text
    elif getattr(args, "resume_file", None):
        rf = Path(args.resume_file)
        if not rf.exists():
            ctx.error(f"指定されたファイルが見つかりません: {rf}")
            return 1
        new_text = rf.read_text(encoding="utf-8")
    elif getattr(args, "from_profile", False):
        new_text = extract_resume_from_profile_ssot()
    else:
        ctx.error("--resume-text, --resume-file, または --from-profile を指定してください。")
        return 1

    new_text = new_text.strip()
    if not new_text:
        ctx.error("更新対象の職務経歴書テキストが空です。")
        return 1

    dry_run = getattr(args, "dry_run", False)

    # 安全ガード: 本番更新前自動バックアップ
    if not dry_run:
        try:
            backup_files = backup_current_profile(session, action_name="update_resume")
            ctx.add_result_paths(backup_files)
        except Exception as e:
            ctx.error(f"バックアップ失敗による中断: {e}")
            return 1

    # アクション実行
    result = execute_manage_action(session, "update-resume", payload={"resume": new_text}, dry_run=dry_run)

    prev_text = result.get("previousResume", "")

    if dry_run:
        print_diff(prev_text, new_text)
        print(f"[DRY-RUN] 職務経歴書更新プレビュー: 変更前 {len(prev_text)} 文字 -> 変更後 {len(new_text)} 文字", file=sys.stderr)
        return ctx.flush_outputs(json_data=result)

    # 反映後に最新プロファイルを再取得して保存
    view_res = execute_manage_action(session, "view")
    if view_res.get("success"):
        updated_paths = save_profile_data(view_res.get("data") or {})
        ctx.add_result_paths(updated_paths)

    def summary_fn() -> None:
        print("=== Green 職務経歴書・自己PR更新完了 ===")
        print(f"- 変更前文字数: {len(prev_text)} 文字")
        print(f"- 変更後文字数: {len(new_text)} 文字")
        print_diff(prev_text, new_text)

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=result)


def handle_update_basic(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """基本情報・年収・住所・学歴等の更新."""
    payload: dict[str, Any] = {}
    if getattr(args, "salary", None) is not None:
        payload["salary"] = args.salary
    if getattr(args, "address", None):
        payload["address"] = args.address
    if getattr(args, "phone", None):
        payload["phoneNumber"] = args.phone
    if getattr(args, "toeic", None) is not None:
        payload["toeic"] = args.toeic
    if getattr(args, "graduation_year", None) is not None:
        payload["schoolGraduationYear"] = args.graduation_year
    if getattr(args, "department", None):
        payload["schoolDepartmentName"] = args.department

    if not payload:
        ctx.error("更新する項目（--salary, --address, --phone, --toeic, --graduation-year, --department 等）が指定されていません。")
        return 1

    dry_run = getattr(args, "dry_run", False)

    if not dry_run:
        try:
            backup_files = backup_current_profile(session, action_name="update_basic")
            ctx.add_result_paths(backup_files)
        except Exception as e:
            ctx.error(f"バックアップ失敗による中断: {e}")
            return 1

    result = execute_manage_action(session, "update-basic", payload=payload, dry_run=dry_run)

    if dry_run:
        print("[DRY-RUN] 基本情報更新プレビュー:", file=sys.stderr)
        for k, v in payload.items():
            print(f"  - {k}: {v}", file=sys.stderr)
        return ctx.flush_outputs(json_data=result)

    view_res = execute_manage_action(session, "view")
    if view_res.get("success"):
        updated_paths = save_profile_data(view_res.get("data") or {})
        ctx.add_result_paths(updated_paths)

    def summary_fn() -> None:
        print("=== Green 基本情報更新完了 ===")
        for k, v in payload.items():
            print(f"- {k}: {v}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=result)


def handle_update_skills(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """保有スキルの一括更新."""
    skills_list: list[dict[str, Any]] = []

    if getattr(args, "skills_file", None):
        sf = Path(args.skills_file)
        if not sf.exists():
            ctx.error(f"スキル指定ファイルが見つかりません: {sf}")
            return 1
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            skills_list = data if isinstance(data, list) else data.get("skills", [])
        except Exception as e:
            ctx.error(f"スキルJSONのパースに失敗しました: {e}")
            return 1
    elif getattr(args, "skills", None):
        for item in args.skills.split(","):
            parts = item.strip().split(":")
            if len(parts) >= 2:
                skills_list.append({"name": parts[0].strip(), "experienceYears": parts[1].strip()})
            elif parts[0].strip():
                skills_list.append({"name": parts[0].strip(), "experienceYears": "1年〜3年"})

    if not skills_list:
        ctx.error("--skills または --skills-file を指定してください。")
        return 1

    dry_run = getattr(args, "dry_run", False)

    if not dry_run:
        try:
            backup_files = backup_current_profile(session, action_name="update_skills")
            ctx.add_result_paths(backup_files)
        except Exception as e:
            ctx.error(f"バックアップ失敗による中断: {e}")
            return 1

    result = execute_manage_action(session, "update-skills", payload={"userSkills": skills_list}, dry_run=dry_run)

    if dry_run:
        print(f"[DRY-RUN] 保有スキル一括置換プレビュー: {len(skills_list)} 件", file=sys.stderr)
        for s in skills_list:
            print(f"  - {s.get('name')}: {s.get('experienceYears')}", file=sys.stderr)
        return ctx.flush_outputs(json_data=result)

    view_res = execute_manage_action(session, "view")
    if view_res.get("success"):
        updated_paths = save_profile_data(view_res.get("data") or {})
        ctx.add_result_paths(updated_paths)

    def summary_fn() -> None:
        print("=== Green 保有スキル更新完了 ===")
        print(f"- 登録件数: {len(skills_list)} 件")
        for s in skills_list:
            print(f"  - {s.get('name')}: {s.get('experienceYears')}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=result)


def handle_update_companies(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """在籍企業（職歴）の一括置換."""
    if not getattr(args, "companies_file", None):
        ctx.error("--companies-file を指定してください。")
        return 1

    cf = Path(args.companies_file)
    if not cf.exists():
        ctx.error(f"企業指定ファイルが見つかりません: {cf}")
        return 1

    try:
        data = json.loads(cf.read_text(encoding="utf-8"))
        companies_list = data if isinstance(data, list) else data.get("userCompanies", [])
    except Exception as e:
        ctx.error(f"企業JSONのパースに失敗しました: {e}")
        return 1

    dry_run = getattr(args, "dry_run", False)

    if not dry_run:
        try:
            backup_files = backup_current_profile(session, action_name="update_companies")
            ctx.add_result_paths(backup_files)
        except Exception as e:
            ctx.error(f"バックアップ失敗による中断: {e}")
            return 1

    result = execute_manage_action(session, "update-companies", payload={"userCompanies": companies_list}, dry_run=dry_run)

    if dry_run:
        print(f"[DRY-RUN] 在籍企業一括置換プレビュー: {len(companies_list)} 社", file=sys.stderr)
        for c in companies_list:
            print(f"  - {c.get('name')}", file=sys.stderr)
        return ctx.flush_outputs(json_data=result)

    view_res = execute_manage_action(session, "view")
    if view_res.get("success"):
        updated_paths = save_profile_data(view_res.get("data") or {})
        ctx.add_result_paths(updated_paths)

    def summary_fn() -> None:
        print("=== Green 在籍企業更新完了 ===")
        print(f"- 登録件数: {len(companies_list)} 社")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=result)


def handle_update_career_statement(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """企業に伝えたいこと（転職理由・見てほしい経験・補足）の更新."""
    payload: dict[str, Any] = {}
    if getattr(args, "statement_point", None):
        payload["careerChangePoint"] = args.statement_point
    if getattr(args, "statement_highlight", None):
        payload["careerHighlight"] = args.statement_highlight
    if getattr(args, "statement_supplement", None):
        payload["careerChangeStatementSupplement"] = args.statement_supplement

    if not payload:
        ctx.error("更新する項目（--statement-point, --statement-highlight, --statement-supplement）が指定されていません。")
        return 1

    dry_run = getattr(args, "dry_run", False)

    if not dry_run:
        try:
            backup_files = backup_current_profile(session, action_name="update_career_statement")
            ctx.add_result_paths(backup_files)
        except Exception as e:
            ctx.error(f"バックアップ失敗による中断: {e}")
            return 1

    result = execute_manage_action(session, "update-career-statement", payload=payload, dry_run=dry_run)

    if dry_run:
        print("[DRY-RUN] 企業に伝えたいこと更新プレビュー:", file=sys.stderr)
        for k, v in payload.items():
            print(f"  - {k}: {v}", file=sys.stderr)
        return ctx.flush_outputs(json_data=result)

    view_res = execute_manage_action(session, "view")
    if view_res.get("success"):
        updated_paths = save_profile_data(view_res.get("data") or {})
        ctx.add_result_paths(updated_paths)

    def summary_fn() -> None:
        print("=== Green 企業に伝えたいこと更新完了 ===")
        for k, v in payload.items():
            print(f"- {k}: {v}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=result)


DEFAULT_SYNC_SKILLS = [
    {"name": "Python", "experienceYears": "1年〜3年"},
    {"name": "TypeScript", "experienceYears": "1年〜3年"},
    {"name": "JavaScript", "experienceYears": "1年〜3年"},
    {"name": "Java", "experienceYears": "1年未満"},
    {"name": "C#", "experienceYears": "1年〜3年"},
    {"name": "SQL", "experienceYears": "1年〜3年"},
    {"name": "Go", "experienceYears": "1年未満"},
    {"name": "Next.js", "experienceYears": "1年〜3年"},
    {"name": "React", "experienceYears": "1年〜3年"},
    {"name": "Docker", "experienceYears": "1年〜3年"},
    {"name": "Git", "experienceYears": "1年〜3年"},
    {"name": "AWS", "experienceYears": "1年未満"},
    {"name": "Azure", "experienceYears": "1年〜3年"},
    {"name": "Kubernetes", "experienceYears": "1年未満"},
    {"name": "Terraform", "experienceYears": "1年〜3年"},
    {"name": "Linux", "experienceYears": "1年〜3年"},
    {"name": "PowerShell", "experienceYears": "1年〜3年"},
    {"name": "Windows", "experienceYears": "1年〜3年"},
    {"name": "Flask", "experienceYears": "1年未満"},
    {"name": "Node.js", "experienceYears": "1年〜3年"},
    {"name": "Spring", "experienceYears": "1年未満"},
]


def handle_sync_profile(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """ローカルSSOT（profile/）から Green への一括同期."""
    dry_run = getattr(args, "dry_run", False)

    # 1. 職務経歴書マスター
    new_resume = extract_resume_from_profile_ssot()

    # 2. 基本情報同期項目
    basic_payload = {
        "salary": 408,
        "schoolGraduationYear": 2024,
        "schoolDepartmentName": "文学部西洋古典学専修",
    }

    # 3. 企業に伝えたいこと同期項目
    statement_payload = {
        "careerChangePoint": "自社プロダクト企業で、モダンバックエンド・基盤技術やフルサイクル開発・AI活用に深くコミットしたい",
        "careerHighlight": "フルスタック開発力（Python/Java/C#/TS/Go）と未踏技術へのキャッチアップ・実装スピード、AI自動化による生産性向上",
        "careerChangeStatementSupplement": "TOEIC 955点（ビジネス英語力・海外一次情報調査）",
    }

    # 4. 保有スキル
    skills_payload = {"userSkills": DEFAULT_SYNC_SKILLS}

    if not dry_run:
        try:
            backup_files = backup_current_profile(session, action_name="sync_profile")
            ctx.add_result_paths(backup_files)
        except Exception as e:
            ctx.error(f"バックアップ失敗による中断: {e}")
            return 1

    # 職務経歴書の更新
    res_resume = execute_manage_action(session, "update-resume", payload={"resume": new_resume}, dry_run=dry_run)
    prev_resume = res_resume.get("previousResume", "")

    # 基本情報の更新
    res_basic = execute_manage_action(session, "update-basic", payload=basic_payload, dry_run=dry_run)

    # 企業に伝えたいことの更新
    res_statement = execute_manage_action(session, "update-career-statement", payload=statement_payload, dry_run=dry_run)

    # 保有スキルの更新
    res_skills = execute_manage_action(session, "update-skills", payload=skills_payload, dry_run=dry_run)

    if dry_run:
        print_diff(prev_resume, new_resume)
        print(f"[DRY-RUN] SSOT同期プレビュー: 職務経歴書 {len(prev_resume)} -> {len(new_resume)} 文字", file=sys.stderr)
        print(f"[DRY-RUN] 基本情報プレビュー: {basic_payload}", file=sys.stderr)
        print(f"[DRY-RUN] 企業に伝えたいことプレビュー: {statement_payload}", file=sys.stderr)
        print(f"[DRY-RUN] スキル登録プレビュー: {len(DEFAULT_SYNC_SKILLS)} 件", file=sys.stderr)
        return ctx.flush_outputs(json_data={
            "action": "sync_profile",
            "dryRun": True,
            "resume": res_resume,
            "basic": res_basic,
            "statement": res_statement,
            "skills": res_skills,
        })

    # 最新プロファイル保存
    view_res = execute_manage_action(session, "view")
    if view_res.get("success"):
        updated_paths = save_profile_data(view_res.get("data") or {})
        ctx.add_result_paths(updated_paths)

    def summary_fn() -> None:
        print("=== Green SSOTプロファイル一括同期完了 ===")
        print(f"- 職務経歴書更新: {len(prev_resume)} -> {len(new_resume)} 文字")
        print(f"- 基本情報同期: 年収 {basic_payload['salary']} 万円 / 卒業年 {basic_payload['schoolGraduationYear']} 年 / 学部学科 {basic_payload['schoolDepartmentName']}")
        print(f"- 企業に伝えたいこと: 3項目更新（前職から変えたいこと、見てほしい経験、補足アピール）")
        print(f"- 保有スキル同期: {len(DEFAULT_SYNC_SKILLS)} 件一括登録（Go, Next.js, React, Terraform, Linux, Azure等）")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data={"action": "sync_profile", "status": "success"})


def handle_backup(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """現在のプロフィールを手動バックアップ."""
    saved = backup_current_profile(session, action_name="manual")
    ctx.add_result_paths(saved)

    def summary_fn() -> None:
        print("=== Green プロフィールバックアップ完了 ===")
        for p in saved:
            print(f"- {to_relative_path(p)}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data={"backup": [to_relative_path(p) for p in saved]})


# ----------------------------------------------------------------------
# CLI エントリポイント
# ----------------------------------------------------------------------


def main() -> None:
    parser = create_base_parser(
        description="Green（green-japan.com）のプロフィール（基本情報・職歴・スキル・職務経歴書等）を管理・更新・同期します。"
    )
    parser.add_argument(
        "--session",
        default="job-hunt",
        help="Playwright CLIセッション名（デフォルト: job-hunt）",
    )
    parser.add_argument(
        "--profile-path",
        help="ブラウザプロファイルディレクトリの直接指定（未指定時は session から自動解決）",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="ブラウザを可視ウィンドウで起動する",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="処理完了後にブラウザセッションを閉じずに保持する",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="保存やAPI実行を行わず、差分や反映内容のプレビューのみ行う",
    )

    parser.add_argument(
        "--action",
        choices=[
            "view",
            "update_resume",
            "update_basic",
            "update_skills",
            "update_companies",
            "update_career_statement",
            "sync_profile",
            "backup",
        ],
        default="view",
        help="実行する操作（view: 閲覧/保存, update_resume: レジュメ更新, update_basic: 基本情報更新, update_skills: スキル更新, update_companies: 職歴更新, update_career_statement: 企業に伝えたいこと更新, sync_profile: SSOT同期, backup: 手動バックアップ）",
    )

    # 職務経歴書更新用
    parser.add_argument("--resume-text", help="職務経歴書テキスト文字列")
    parser.add_argument("--resume-file", help="職務経歴書テキストファイルパス")
    parser.add_argument(
        "--from-profile",
        action="store_true",
        help="profile/resume.md から職務経歴書を自動抽出して指定",
    )

    # 基本情報更新用
    parser.add_argument("--salary", type=int, help="現（前）年収（万円単位）")
    parser.add_argument("--address", help="現住所")
    parser.add_argument("--phone", help="電話番号（ハイフンなし）")
    parser.add_argument("--toeic", type=int, help="TOEICスコア")
    parser.add_argument("--graduation-year", type=int, help="卒業年（例: 2024）")
    parser.add_argument("--department", help="学部学科名（例: 文学部西洋古典学専修）")

    # 企業に伝えたいこと更新用
    parser.add_argument("--statement-point", help="前職から変えたいこと")
    parser.add_argument("--statement-highlight", help="見てほしい役割・環境")
    parser.add_argument("--statement-supplement", help="その他アピール・補足")

    # スキル更新用
    parser.add_argument("--skills", help="スキルリスト（カンマ区切り、例: 'Python:1年〜3年,TypeScript:1年〜3年'）")
    parser.add_argument("--skills-file", help="スキル一覧JSONファイルパス")

    # 企業職歴更新用
    parser.add_argument("--companies-file", help="在籍企業一覧JSONファイルパス")

    args = parser.parse_args()

    session = args.session
    profile_dir = resolve_profile_path(session, args.profile_path)
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    # 認証確認・ハンドオフ
    try:
        ensure_site_authenticated(
            site="green",
            session=session,
            profile_dir=profile_dir,
            headed=args.headed,
            exit_on_fail=True,
        )
    except Exception as e:
        ctx.error(f"Green 認証エラー: {e}")
        sys.exit(2)

    action_map = {
        "view": handle_view,
        "update_resume": handle_update_resume,
        "update_basic": handle_update_basic,
        "update_skills": handle_update_skills,
        "update_companies": handle_update_companies,
        "update_career_statement": handle_update_career_statement,
        "sync_profile": handle_sync_profile,
        "backup": handle_backup,
    }

    handler = action_map.get(args.action)
    if not handler:
        ctx.error(f"未対応のアクション: {args.action}")
        sys.exit(1)

    try:
        exit_code = handler(args, session, ctx)
    finally:
        if not args.keep_open:
            run_playwright_cmd([f"-s={session}", "close"])

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
