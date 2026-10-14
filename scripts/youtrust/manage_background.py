"""YOUTRUST（youtrust.jp）職歴・学歴 CRUD管理・同期スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
YOUTRUST の職歴・学歴設定画面（/settings/background）における
職歴（Career Company History / Career）および学歴（Education）の
閲覧・追加・更新・削除・自動バックアップ・SSOT（profile/）同期を安全に実行します。

変更操作（add / update / delete / sync）の実行前には必ず最新状態の完全自動バックアップを取得し、
--dry-run フラグによる変更プレビューと安全ガードを提供します。
エントリポイントスクリプト規約（.agents/rules/scripts-entrypoint.md）準拠。
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/youtrust/ の2階層上)
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
from scripts.common.cli import EntrypointContext, create_base_parser, entrypoint_guard, to_relative_path

YOUTRUST_SCRIPTS_DIR = Path(__file__).resolve().parent
MANAGE_SCRIPT_PATH = YOUTRUST_SCRIPTS_DIR / "manage_background.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "youtrust" / "background"
BACKUP_DIR = DEFAULT_OUTPUT_DIR / "backups"
TARGET_URL = "https://youtrust.jp/settings/background"


def execute_manage_action(
    session: str,
    action: str,
    target: str = "career",
    payload: dict[str, Any] | None = None,
    dry_run: bool = False,
    timeout: int = 45,
) -> dict[str, Any]:
    """manage_background.mjs に action, target, payload, isDryRun を注入して実行する."""
    if not MANAGE_SCRIPT_PATH.exists():
        raise RuntimeError(f"管理スクリプトが見つかりません: {MANAGE_SCRIPT_PATH}")

    profile_path = resolve_profile_path(session)
    run_playwright_cmd([f"-s={session}", "open", TARGET_URL, f"--profile={profile_path}"])

    template_code = MANAGE_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = (
        template_code.replace("'__YOUTRUST_ACTION__'", json.dumps(action))
        .replace("'__YOUTRUST_TARGET__'", json.dumps(target))
        .replace("__YOUTRUST_PAYLOAD__", json.dumps(payload or {}, ensure_ascii=False))
        .replace("__YOUTRUST_DRY_RUN__", "true" if dry_run else "false")
    ).strip().rstrip(";")

    tmp_script_path = YOUTRUST_SCRIPTS_DIR / f".tmp_manage_bg_{action}_{target}.mjs"
    tmp_script_path.write_text(run_code, encoding="utf-8")

    try:
        result = run_code_script(session, tmp_script_path, timeout=timeout)
        if not result:
            raise RuntimeError(f"Playwrightスクリプトの実行に失敗しました: {action} ({target})")
        if not result.get("success"):
            err = result.get("error") or "不明なエラー"
            raise RuntimeError(f"操作実行エラー ({action} - {target}): {err}")
        update_profile_last_used(session)
        return result
    finally:
        if tmp_script_path.exists():
            try:
                tmp_script_path.unlink()
            except Exception:
                pass


def format_background_markdown(data: dict[str, Any], fetched_at: datetime) -> str:
    """YOUTRUSTの職歴・学歴データをフロントマター付きMarkdownに整形する."""
    histories = data.get("career_company_histories") or []
    educations = data.get("educations") or []

    lines = [
        "---",
        "source: youtrust",
        "type: background",
        f"updated_at: '{fetched_at.isoformat(timespec='seconds')}'",
        f"url: '{TARGET_URL}'",
        f"career_company_count: {len(histories)}",
        f"education_count: {len(educations)}",
        "---",
        "",
        "# YOUTRUST 登録職歴・学歴",
        "",
        "## 1. 職歴一覧（Career Company Histories）",
        "",
    ]

    LABEL_MAP = {
        "label_type_none": "正社員",
        "label_type_side_job": "副業・業務委託",
        "label_type_internship": "インターン",
        "label_type_contract": "契約社員",
        "label_type_secondment": "出向",
        "label_type_dispatch": "派遣社員",
        "label_type_part_time": "パート・アルバイト",
        "label_type_self_employed": "自営業",
        "label_type_freelance": "フリーランス",
        "label_type_executive": "経営者・役員",
        "label_type_advisor": "顧問・アドバイザー",
        "label_type_volunteer": "ボランティア・プロボノ",
        "label_type_trainee": "研修生・実習生",
        "label_type_other": "その他",
    }

    if not histories:
        lines.append("- （登録された職歴はありません）")
        lines.append("")
    else:
        for idx, h in enumerate(histories, 1):
            h_id = h.get("id") or ""
            comp_obj = h.get("company") or {}
            corp_master = h.get("corporate_master") or {}
            comp_name = h.get("company_name") or comp_obj.get("name") or corp_master.get("name") or "企業名未設定"
            joined = h.get("joined_at") or "開始時期未設定"
            left = h.get("left_at") or "在職中"
            label = LABEL_MAP.get(h.get("label_type", ""), h.get("label_type") or "未設定")
            lines.append(f"### 1.{idx} {comp_name} (ID: {h_id})")
            lines.append(f"- **在籍期間**: {joined} 〜 {left}")
            lines.append(f"- **雇用形態**: {label}")

            careers = h.get("careers") or []
            if careers:
                lines.append("- **部署・プロジェクト一覧**:")
                for c in careers:
                    c_id = c.get("id") or ""
                    dept_name = c.get("name") or "部署名なし"
                    role = c.get("role") or "役割なし"
                    began = c.get("began_at") or ""
                    ended = c.get("ended_at") or "現在"
                    period_str = f" ({began} 〜 {ended})" if began else ""
                    lines.append(f"  - **{dept_name}** / {role}{period_str} [ID: {c_id}]")
                    desc = c.get("description") or c.get("raw_description") or ""
                    if desc:
                        indented_desc = "\n".join(f"      {line}" for line in desc.strip().splitlines())
                        lines.append("    - 業務詳細:")
                        lines.append(f"```text\n{desc.strip()}\n```")
            lines.append("")

    lines.append("## 2. 学歴一覧（Educations）")
    lines.append("")

    if not educations:
        lines.append("- （登録された学歴はありません）")
        lines.append("")
    else:
        for idx, e in enumerate(educations, 1):
            e_id = e.get("id") or ""
            name = e.get("name") or "学校名未設定"
            major = e.get("major_subject") or "学部・専攻未設定"
            entered = e.get("entered_at") or "入学時期未設定"
            grad = e.get("graduated_at") or "卒業時期未設定"
            seminar = e.get("seminar_name") or ""
            club = e.get("club_name") or ""

            lines.append(f"### 2.{idx} {name} (ID: {e_id})")
            lines.append(f"- **学部・学科・専攻**: {major}")
            lines.append(f"- **在籍期間**: {entered} 〜 {grad}")
            if seminar:
                lines.append(f"- **ゼミ・研究室**: {seminar}")
            if club:
                lines.append(f"- **サークル・部活**: {club}")
            lines.append("")

    return "\n".join(lines)


def save_background_data(
    data: dict[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    backup_tag: str | None = None,
) -> list[Path]:
    """職歴・学歴データ（JSON & Markdown）を保存する."""
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    saved: list[Path] = []

    if backup_tag:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = now.strftime("%Y%m%d_%H%M%S")
        backup_json = BACKUP_DIR / f"{ts}_{backup_tag}.json"
        with open(backup_json, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        saved.append(backup_json)

        backup_md = BACKUP_DIR / f"{ts}_{backup_tag}.md"
        backup_md.write_text(format_background_markdown(data, now), encoding="utf-8")
        saved.append(backup_md)
        return saved

    # latest 保存
    json_path = output_dir / "latest.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    saved.append(json_path)

    md_content = format_background_markdown(data, now)
    md_path = output_dir / "latest.md"
    md_path.write_text(md_content, encoding="utf-8")
    saved.append(md_path)

    return saved


def backup_current_background(session: str, action_name: str = "backup") -> list[Path]:
    """変更操作前に最新の職歴・学歴データを自動バックアップする."""
    view_result = execute_manage_action(session, "view", target="all")
    if not view_result or not view_result.get("success"):
        raise RuntimeError("変更前自動バックアップ（最新職歴・学歴取得）に失敗したため、操作を中断します。")

    data = view_result.get("data") or {}
    saved_backups = save_background_data(data, backup_tag=f"pre_{action_name}")
    for p in saved_backups:
        print(f"[安全ガード] 変更前バックアップを保存しました: {to_relative_path(p)}", file=sys.stderr)
    return saved_backups



def normalize_label_type(label: str | None) -> str | None:
    """雇用形態の文字列表現を YOUTRUST の label_type 形式に正規化する."""
    if not label:
        return None
    val = label.strip()
    if val.startswith("label_type_"):
        return val
    mapping = {
        "正社員": "label_type_none",
        "full_time": "label_type_none",
        "副業": "label_type_side_job",
        "副業・業務委託": "label_type_side_job",
        "業務委託": "label_type_side_job",
        "インターン": "label_type_internship",
        "internship": "label_type_internship",
        "契約社員": "label_type_contract",
        "contract": "label_type_contract",
        "出向": "label_type_secondment",
        "派遣社員": "label_type_dispatch",
        "派遣": "label_type_dispatch",
        "パート・アルバイト": "label_type_part_time",
        "アルバイト": "label_type_part_time",
        "パート": "label_type_part_time",
        "自営業": "label_type_self_employed",
        "フリーランス": "label_type_freelance",
        "freelance": "label_type_freelance",
        "経営者・役員": "label_type_executive",
        "役員": "label_type_executive",
        "経営者": "label_type_executive",
        "顧問・アドバイザー": "label_type_advisor",
        "顧問": "label_type_advisor",
        "ボランティア・プロボノ": "label_type_volunteer",
        "研修生・実習生": "label_type_trainee",
        "その他": "label_type_other",
        "none": "label_type_none",
        "未設定": "label_type_none",
    }
    return mapping.get(val, "label_type_none")


def load_profile_resume() -> dict[str, Any]:
    """profile/resume.md から職歴・学歴情報を詳細に抽出する."""
    resume_path = PROJECT_ROOT / "profile" / "resume.md"
    if not resume_path.exists():
        raise FileNotFoundError(f"職務経歴書マスターが見つかりません: {resume_path}")

    content = resume_path.read_text(encoding="utf-8")

    # 1. 学歴抽出 (例: - **2024年3月 東京大学 文学部 西洋古典学専修 卒業**)
    educations: list[dict[str, Any]] = []
    edu_match = re.search(r"##\s*学歴\s*\n+-\s*\*\*(\d{4})年(\d{1,2})月\s+([^\n*]+?)\s*卒業\*\*", content)
    if edu_match:
        grad_year, grad_month, full_edu = edu_match.groups()
        parts = [p.strip() for p in full_edu.split() if p.strip()]
        school = parts[0] if parts else ""
        major = " ".join(parts[1:]) if len(parts) > 1 else ""
        grad_month_int = int(grad_month)
        grad_str = f"{grad_year}-{grad_month_int:02d}-31"
        entered_str = f"{int(grad_year)-4:04d}-04-01"
        educations.append({
            "name": school,
            "major_subject": major,
            "entered_at": entered_str,
            "graduated_at": grad_str,
        })

    # 2. 職歴抽出 (各企業セクション ### N. ...)
    companies: list[dict[str, Any]] = []
    # 職歴セクションの抽出
    career_section_match = re.search(r"##\s*職務経歴\s*\n([\s\S]+?)(?=\n##\s*学歴|\n##\s*保有スキル|\Z)", content)
    career_section = career_section_match.group(1) if career_section_match else ""

    # 企業ごとに分割
    company_blocks = re.split(r"(?=\n###\s*\d+\.\s*)", "\n" + career_section)
    for block in company_blocks:
        block = block.strip()
        if not block.startswith("###"):
            continue

        header_m = re.match(r"###\s*\d+\.\s*([^\n（(]+)[（(](\d{4}年\d{1,2}月)〜([^\n）)]+)[）)]", block)
        if not header_m:
            continue

        comp_name = header_m.group(1).strip()
        joined_raw = header_m.group(2).strip()
        left_raw = header_m.group(3).strip()

        j_y, j_m = re.findall(r"\d+", joined_raw)
        joined_at = f"{j_y}-{int(j_m):02d}-01"

        if "在職中" in left_raw or "現在" in left_raw:
            left_at = None
        else:
            l_parts = re.findall(r"\d+", left_raw)
            if len(l_parts) >= 2:
                # 月末日計算の簡易化 (4,6,9,11月は30、それ以外は31)
                l_m = int(l_parts[1])
                l_d = 30 if l_m in (4, 6, 9, 11) else (28 if l_m == 2 else 31)
                left_at = f"{l_parts[0]}-{l_m:02d}-{l_d:02d}"
            else:
                left_at = None

        # 雇用形態
        emp_match = re.search(r"-\s*\*\*雇用形態\*\*:\s*([^\n]+)", block)
        label_raw = emp_match.group(1).strip() if emp_match else "正社員"
        label_type = normalize_label_type(label_raw) or "label_type_none"

        # 役職/役割
        role_match = re.search(r"-\s*\*\*役職/役割\*\*:\s*([^\n]+)", block)
        comp_role = role_match.group(1).strip() if role_match else ""

        # プロジェクト一覧抽出 (#### プロジェクト...)
        projects: list[dict[str, Any]] = []
        proj_blocks = re.split(r"(?=\n####\s*プロジェクト)", "\n" + block)
        for p_block in proj_blocks:
            p_block = p_block.strip()
            if not p_block.startswith("####"):
                continue

            p_head = re.match(r"####\s*プロジェクト(?:\d+)?:\s*([^\n]+)", p_block)
            proj_title = p_head.group(1).strip() if p_head else "プロジェクト"

            # 期間
            p_period_m = re.search(r"-\s*\*\*期間\*\*:\s*(\d{4}年\d{1,2}月)〜([^\n]+)", p_block)
            began_at = None
            ended_at = None
            if p_period_m:
                b_raw, e_raw = p_period_m.group(1).strip(), p_period_m.group(2).strip()
                b_nums = re.findall(r"\d+", b_raw)
                if len(b_nums) >= 2:
                    began_at = f"{b_nums[0]}-{int(b_nums[1]):02d}-01"
                if "在職中" in e_raw or "現在" in e_raw:
                    ended_at = None
                else:
                    e_nums = re.findall(r"\d+", e_raw)
                    if len(e_nums) >= 2:
                        e_m = int(e_nums[1])
                        e_d = 30 if e_m in (4, 6, 9, 11) else (28 if e_m == 2 else 31)
                        ended_at = f"{e_nums[0]}-{e_m:02d}-{e_d:02d}"

            # 使用技術
            tech_match = re.search(r"-\s*\*\*使用技術\*\*:\s*([^\n]+)", p_block)
            tech_str = tech_match.group(1).strip() if tech_match else ""

            # 業務内容・実績
            body_match = re.search(r"-\s*\*\*業務内容・実績\*\*:\s*\n([\s\S]+)", p_block)
            body_text = ""
            if body_match:
                raw_body = body_match.group(1).strip()
                body_lines = []
                for bl in raw_body.splitlines():
                    # インデント調整
                    line = re.sub(r"^\s{2,4}-\s*", "・", bl)
                    line = re.sub(r"^-\s*", "・", line)
                    body_lines.append(line)
                body_text = "\n".join(body_lines)

            desc_parts = []
            if body_text:
                desc_parts.append(body_text)
            if tech_str:
                desc_parts.append(f"\n【使用技術】\n{tech_str}")
            full_desc = "\n".join(desc_parts).strip()

            # プロジェクト単位の役割
            proj_role = comp_role.split("/")[0].strip() if comp_role else "エンジニア"

            projects.append({
                "title": proj_title,
                "role": proj_role,
                "began_at": began_at or joined_at,
                "ended_at": ended_at if left_at is None else (ended_at or left_at),
                "description": full_desc,
                "tech": tech_str,
            })

        companies.append({
            "company_name": comp_name,
            "joined_at": joined_at,
            "left_at": left_at,
            "label_type": label_type,
            "role": comp_role,
            "projects": projects,
        })

    return {
        "educations": educations,
        "companies": companies,
    }


def print_diff(previous: str, new: str, from_label: str = "現在登録内容", to_label: str = "反映予定内容") -> None:
    """テキスト差分（unified diff）を stderr に出力する."""
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


# ----------------------------------------------------------------------
# ハンドラ関数
# ----------------------------------------------------------------------


def handle_show(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """職歴・学歴の一覧取得と最新保存."""
    result = execute_manage_action(session, "show", target=args.target)
    data = result.get("data") or {}

    saved_paths = save_background_data(data)
    ctx.add_result_paths(saved_paths)

    def summary_fn() -> None:
        histories = data.get("career_company_histories") or []
        educations = data.get("educations") or []
        print("=== YOUTRUST 登録職歴・学歴 ===")
        print(f"- 職歴企業数: {len(histories)} 社")
        for h in histories:
            h_id = h.get("id") or ""
            comp_obj = h.get("company") or {}
            corp_master = h.get("corporate_master") or {}
            comp_name = h.get("company_name") or comp_obj.get("name") or corp_master.get("name") or "企業名未設定"
            joined = h.get("joined_at") or ""
            left = h.get("left_at") or "在職中"
            careers = h.get("careers") or []
            print(f"  • {comp_name} ({joined} 〜 {left}) [ID: {h_id}] - 部署数: {len(careers)}")
        print(f"- 学歴数: {len(educations)} 件")
        for e in educations:
            e_id = e.get("id") or ""
            s_name = e.get("name") or "学校名未設定"
            major = e.get("major_subject") or ""
            grad = e.get("graduated_at") or ""
            print(f"  • {s_name} {major} ({grad} 卒業) [ID: {e_id}]")
        print(f"- 保存ファイル: {[to_relative_path(p) for p in saved_paths]}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=result)


def handle_backup(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """職歴・学歴の手動バックアップ保存."""
    result = execute_manage_action(session, "backup", target=args.target)
    data = result.get("data") or {}

    saved_paths = save_background_data(data, backup_tag="manual")
    ctx.add_result_paths(saved_paths)

    def summary_fn() -> None:
        print("=== YOUTRUST 職歴・学歴バックアップ保存完了 ===")
        for p in saved_paths:
            print(f"- {to_relative_path(p)}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=result)


def handle_add(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """職歴または学歴の新規追加."""
    target = args.target
    payload: dict[str, Any] = {}

    if target == "education":
        if not args.school:
            ctx.error("学歴の追加には学校名 (--school) が必須です。")
            return 1
        payload["name"] = args.school
        payload["major_subject"] = args.faculty or ""
        payload["entered_at"] = args.entered
        payload["graduated_at"] = args.graduated
        payload["seminar_name"] = args.seminar
        payload["club_name"] = args.club
    else:
        # target == 'career'
        if args.history_id:
            # 既存企業への部署・プロジェクト追加
            payload["career_company_history_id"] = args.history_id
            payload["department_name"] = args.dept or ""
            payload["role"] = args.role or ""
            payload["description"] = args.desc or ""
            payload["began_at"] = args.joined
            payload["ended_at"] = args.left
            if args.category:
                payload["career_job_categories"] = [
                    {"v3_category_type": "v3_engineering__system_engineer", "v3_category_name": args.category}
                ]
            payload["add_current_affiliation"] = bool(args.current or not args.left)
        else:
            # 企業職歴新規追加
            if not args.company:
                ctx.error("企業職歴の追加には会社名 (--company) が必須です。")
                return 1
            payload["company_name"] = args.company
            payload["corporate_number"] = getattr(args, "corporate_number", None)
            payload["joined_at"] = args.joined
            payload["left_at"] = args.left
            payload["department_name"] = args.dept or ""
            payload["role"] = args.role or ""
            payload["description"] = args.desc or ""
            label_in = getattr(args, "label", None) or getattr(args, "label_type", None)
            payload["label_type"] = normalize_label_type(label_in) or "label_type_none"
            if args.category:
                payload["career_job_categories"] = [
                    {"v3_category_type": "v3_engineering__system_engineer", "v3_category_name": args.category}
                ]

    dry_run = getattr(args, "dry_run", False)

    # 1. 安全ガード: 本番追加前の自動バックアップ
    if not dry_run:
        try:
            backup_files = backup_current_background(session, action_name=f"add_{target}")
            ctx.add_result_paths(backup_files)
        except Exception as e:
            ctx.error(f"バックアップ失敗による中断: {e}")
            return 1

    # 2. アクション実行
    result = execute_manage_action(session, "add", target=target, payload=payload, dry_run=dry_run)

    # 3. Dry-Run プレビュー
    if dry_run:
        print(f"[DRY-RUN] YOUTRUST {target} 追加プレビュー:", file=sys.stderr)
        print(f"  エンドポイント: {result.get('endpoint')}", file=sys.stderr)
        print(f"  送信Payload: {json.dumps(result.get('payload'), ensure_ascii=False, indent=2)}", file=sys.stderr)
        print("[INFO] --dry-run のためAPI呼び出しはスキップされました。", file=sys.stderr)
        return ctx.flush_outputs(json_data=result)

    # 4. 反映後の最新データを保存
    if result.get("data"):
        updated_paths = save_background_data(result["data"])
        ctx.add_result_paths(updated_paths)

    def summary_fn() -> None:
        print(f"=== YOUTRUST {target} 追加完了 ===")
        print(f"- 作成データ: {json.dumps(result.get('created', {}), ensure_ascii=False)}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=result)


def handle_update(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """職歴または学歴の更新."""
    target = args.target
    payload: dict[str, Any] = {}

    if target == "education":
        edu_id = args.edu_id or args.id
        if not edu_id:
            ctx.error("学歴の更新には対象学歴ID (--edu-id / --id) が必須です。")
            return 1
        payload["id"] = edu_id
        if args.school:
            payload["name"] = args.school
        if args.faculty:
            payload["major_subject"] = args.faculty
        if args.entered:
            payload["entered_at"] = args.entered
        if args.graduated:
            payload["graduated_at"] = args.graduated
        if args.seminar:
            payload["seminar_name"] = args.seminar
        if args.club:
            payload["club_name"] = args.club
    else:
        # target == 'career'
        if args.career_id:
            history_id = args.history_id or args.id
            if not history_id:
                ctx.error("部署の更新には企業職歴ID (--history-id) が必須です。")
                return 1
            payload["history_id"] = history_id
            payload["career_id"] = args.career_id
            if args.dept:
                payload["department_name"] = args.dept
            if args.role:
                payload["role"] = args.role
            if args.desc:
                payload["description"] = args.desc
            if args.joined:
                payload["began_at"] = args.joined
            if args.left:
                payload["ended_at"] = args.left
            if args.category:
                payload["career_job_categories"] = [
                    {"v3_category_type": "v3_engineering__system_engineer", "v3_category_name": args.category}
                ]
        else:
            history_id = args.history_id or args.id
            if not history_id:
                ctx.error("企業職歴の更新には対象企業職歴ID (--history-id / --id) が必須です。")
                return 1
            payload["history_id"] = history_id
            if args.company:
                payload["company_name"] = args.company
            if args.joined:
                payload["joined_at"] = args.joined
            if args.left is not None:
                payload["left_at"] = args.left
            label_in = getattr(args, "label", None) or getattr(args, "label_type", None)
            if label_in:
                payload["label_type"] = normalize_label_type(label_in)

    dry_run = getattr(args, "dry_run", False)

    # 1. 安全ガード: 本番更新前の自動バックアップ
    if not dry_run:
        try:
            backup_files = backup_current_background(session, action_name=f"update_{target}")
            ctx.add_result_paths(backup_files)
        except Exception as e:
            ctx.error(f"バックアップ失敗による中断: {e}")
            return 1

    # 2. アクション実行
    result = execute_manage_action(session, "update", target=target, payload=payload, dry_run=dry_run)

    # 3. Dry-Run プレビュー
    if dry_run:
        print(f"[DRY-RUN] YOUTRUST {target} 更新プレビュー:", file=sys.stderr)
        print(f"  エンドポイント: {result.get('endpoint')}", file=sys.stderr)
        print(f"  送信Payload: {json.dumps(result.get('payload'), ensure_ascii=False, indent=2)}", file=sys.stderr)
        print("[INFO] --dry-run のためAPI呼び出しはスキップされました。", file=sys.stderr)
        return ctx.flush_outputs(json_data=result)

    # 4. 反映後の最新データを保存
    if result.get("data"):
        updated_paths = save_background_data(result["data"])
        ctx.add_result_paths(updated_paths)

    def summary_fn() -> None:
        print(f"=== YOUTRUST {target} 更新完了 ===")
        print(f"- 更新結果: {json.dumps(result.get('updated', {}), ensure_ascii=False)}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=result)


def handle_delete(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """職歴または学歴の削除."""
    target = args.target
    payload: dict[str, Any] = {}

    if target == "education":
        edu_id = args.edu_id or args.id
        if not edu_id:
            ctx.error("学歴の削除には対象学歴ID (--edu-id / --id) が必須です。")
            return 1
        payload["id"] = edu_id
    else:
        # target == 'career'
        if args.career_id:
            history_id = args.history_id or args.id
            if not history_id:
                ctx.error("部署の削除には企業職歴ID (--history-id) が必要です。")
                return 1
            payload["history_id"] = history_id
            payload["career_id"] = args.career_id
        else:
            history_id = args.history_id or args.id
            if not history_id:
                ctx.error("企業職歴の削除には対象企業職歴ID (--history-id / --id) が必須です。")
                return 1
            payload["history_id"] = history_id

    dry_run = getattr(args, "dry_run", False)

    # 1. 安全ガード: 本番削除前の自動バックアップ
    if not dry_run:
        try:
            backup_files = backup_current_background(session, action_name=f"delete_{target}")
            ctx.add_result_paths(backup_files)
        except Exception as e:
            ctx.error(f"バックアップ失敗による中断: {e}")
            return 1

    # 2. アクション実行
    result = execute_manage_action(session, "delete", target=target, payload=payload, dry_run=dry_run)

    # 3. Dry-Run プレビュー
    if dry_run:
        print(f"[DRY-RUN] YOUTRUST {target} 削除プレビュー:", file=sys.stderr)
        print(f"  削除エンドポイント: {result.get('endpoint')}", file=sys.stderr)
        print(f"  削除対象ID: {result.get('id') or result.get('career_id')}", file=sys.stderr)
        print("[INFO] --dry-run のためAPI呼び出しはスキップされました。", file=sys.stderr)
        return ctx.flush_outputs(json_data=result)

    # 4. 反映後の最新データを保存
    if result.get("data"):
        updated_paths = save_background_data(result["data"])
        ctx.add_result_paths(updated_paths)

    def summary_fn() -> None:
        print(f"=== YOUTRUST {target} 削除完了 ===")
        print(f"- 削除ID: {result.get('deleted_id') or result.get('deleted_career_id')}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=result)


def handle_sync(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """profile/resume.md から職歴・学歴を抽出し、比較・最新同期を実行する."""
    profile_data = load_profile_resume()

    # 現在のYOUTRUST登録データを取得
    current_result = execute_manage_action(session, "view", target="all")
    cur_data = current_result.get("data") or {}
    cur_histories = cur_data.get("career_company_histories") or []
    cur_educations = cur_data.get("educations") or []

    dry_run = getattr(args, "dry_run", False)
    execute_sync = getattr(args, "execute", False)

    print("=== SSOT (profile/resume.md) 抽出情報 ===", file=sys.stderr)
    print(f"SSOT 職歴企業数: {len(profile_data['companies'])} 社", file=sys.stderr)
    for c in profile_data["companies"]:
        p_count = len(c.get("projects", []))
        print(f"  • {c['company_name']} ({c['joined_at']} 〜 {c['left_at'] or '在職中'}) [{c.get('label_type')}] - プロジェクト数: {p_count}", file=sys.stderr)
    print(f"SSOT 学歴数: {len(profile_data['educations'])} 件", file=sys.stderr)
    for e in profile_data["educations"]:
        print(f"  • {e['name']} {e['major_subject']} ({e['graduated_at']} 卒業)", file=sys.stderr)

    print("\n=== YOUTRUST 登録現況 ===", file=sys.stderr)
    print(f"YOUTRUST 職歴企業数: {len(cur_histories)} 社", file=sys.stderr)
    for h in cur_histories:
        comp_obj = h.get("company") or {}
        corp_master = h.get("corporate_master") or {}
        c_name = h.get("company_name") or comp_obj.get("name") or corp_master.get("name") or "企業名未設定"
        careers = h.get("careers") or []
        print(f"  • {c_name} ({h.get('joined_at') or '開始時期未設定'} 〜 {h.get('left_at') or '在職中'}) [ID: {h.get('id')}] - 部署数: {len(careers)}", file=sys.stderr)
    print(f"YOUTRUST 学歴数: {len(cur_educations)} 件", file=sys.stderr)
    for e in cur_educations:
        print(f"  • {e.get('name')} {e.get('major_subject')} ({e.get('graduated_at')} 卒業) [ID: {e.get('id')}]", file=sys.stderr)

    if not execute_sync:
        # 計画出力のみ
        saved_paths = save_background_data(cur_data)
        ctx.add_result_paths(saved_paths)
        print("\n[INFO] 同期を実行するには `--execute` フラグを付与してください（安全ガードによる自動バックアップ付き）。", file=sys.stderr)

        def summary_fn() -> None:
            print("=== YOUTRUST 職歴・学歴 SSOT 照合完了 ===")
            print(f"- 現在のデータ保存先: {[to_relative_path(p) for p in saved_paths]}")
            print("- 反映を行う場合は `python scripts/youtrust/manage_background.py --action sync --execute` を実行してください。")

        return ctx.flush_outputs(summary_fn=summary_fn, json_data={"ssot": profile_data, "current": cur_data})

    # === 同期実行フロー ===
    print("\n>>> SSOTからYOUTRUSTへの同期処理を開始します <<<", file=sys.stderr)

    # 1. 安全ガード: 事前自動バックアップ
    try:
        backup_files = backup_current_background(session, action_name="sync_full")
        ctx.add_result_paths(backup_files)
    except Exception as e:
        ctx.error(f"バックアップ失敗による中断: {e}")
        return 1

    actions_taken: list[dict[str, Any]] = []

    # 2. 学歴の同期
    # YOUTRUSTに学歴が未登録の場合、SSOTの学歴を追加
    for edu in profile_data["educations"]:
        matching_edu = next((e for e in cur_educations if e.get("name") == edu["name"]), None)
        if not matching_edu:
            print(f"[同期] 学歴を追加します: {edu['name']} {edu['major_subject']}", file=sys.stderr)
            add_res = execute_manage_action(session, "add", target="education", payload=edu, dry_run=dry_run)
            actions_taken.append({"action": "add_education", "name": edu["name"], "result": add_res.get("created")})
        else:
            print(f"[同期] 学歴は既に登録済みです: {edu['name']} (ID: {matching_edu.get('id')})", file=sys.stderr)

    # 3. 企業職歴の同期
    # 現在の職歴企業マップ (企業名 -> history)
    cur_comp_map = {}
    for h in cur_histories:
        c_obj = h.get("company") or {}
        c_master = h.get("corporate_master") or {}
        c_name = h.get("company_name") or c_obj.get("name") or c_master.get("name") or ""
        cur_comp_map[c_name] = h

    for comp in profile_data["companies"]:
        c_name = comp["company_name"]
        hist = cur_comp_map.get(c_name)

        if hist:
            # 既存企業の更新
            h_id = hist["id"]
            print(f"[同期] 既存企業職歴を更新します: {c_name} (ID: {h_id})", file=sys.stderr)
            upd_payload = {
                "history_id": h_id,
                "company_name": c_name,
                "joined_at": comp["joined_at"],
                "left_at": comp["left_at"],
                "label_type": comp["label_type"],
            }
            upd_res = execute_manage_action(session, "update", target="career", payload=upd_payload, dry_run=dry_run)
            actions_taken.append({"action": "update_company", "name": c_name, "id": h_id})

            # プロジェクトの同期
            existing_careers = hist.get("careers") or []
            comp_projects = comp.get("projects") or []
            existing_titles = [c.get("name", "").strip() for c in existing_careers if c.get("name")]

            def is_same_project(t1: str, t2: str) -> bool:
                clean1 = re.sub(r"[\s（）()・]+", "", t1).lower()
                clean2 = re.sub(r"[\s（）()・]+", "", t2).lower()
                return clean1 == clean2 or clean1 in clean2 or clean2 in clean1

            def compact_description(desc: str, max_len: int = 280) -> str:
                if not desc or len(desc) <= max_len:
                    return desc
                lines = desc.strip().splitlines()
                tech_lines = []
                body_lines = []
                is_tech = False
                for l in lines:
                    if "【使用技術】" in l:
                        is_tech = True
                    if is_tech:
                        tech_lines.append(l)
                    else:
                        body_lines.append(l)

                tech_text = "\n".join(tech_lines).strip()
                tech_len = len(tech_text) + 2 if tech_text else 0
                avail_len = max(max_len - tech_len, 50)

                compacted_body = []
                b_len = 0
                for bl in body_lines:
                    line_clean = bl.strip()
                    if not line_clean:
                        continue
                    if b_len + len(line_clean) + 1 <= avail_len:
                        compacted_body.append(line_clean)
                        b_len += len(line_clean) + 1
                    else:
                        rem = avail_len - b_len - 4
                        if rem > 15:
                            compacted_body.append(line_clean[:rem] + "...")
                        break

                parts = []
                if compacted_body:
                    parts.append("\n".join(compacted_body))
                if tech_text:
                    parts.append(tech_text)
                return "\n\n".join(parts).strip()

            # 未登録プロジェクトのみを新規追加 (POST)
            for proj in comp_projects:
                proj_title = proj["title"].strip()
                if any(is_same_project(proj_title, et) for et in existing_titles):
                    print(f"[同期] プロジェクト '{proj_title}' は既に登録済みのためスキップします。", file=sys.stderr)
                    continue

                cat_type = "v3_engineering__ai_engineer" if any(k in (proj_title + proj["role"] + proj["description"]).lower() for k in ("ai", "llm", "slm", "openai")) else "v3_engineering__web_engineer"
                print(f"[同期] 部署・プロジェクトを追加します: {proj_title} ({cat_type})", file=sys.stderr)

                # 日付の正規化 (YYYY-M-01 形式)
                began_str = proj["began_at"]
                if began_str and len(began_str.split("-")) >= 2:
                    parts = began_str.split("-")
                    began_str = f"{parts[0]}-{int(parts[1])}-01"

                ended_str = proj["ended_at"]
                if ended_str and len(ended_str.split("-")) >= 3:
                    parts = ended_str.split("-")
                    ended_str = f"{parts[0]}-{int(parts[1])}-{parts[2]}"

                dept_payload = {
                    "career_company_history_id": h_id,
                    "department_name": proj_title,
                    "role": proj["role"],
                    "description": compact_description(proj["description"]),
                    "began_at": began_str,
                    "ended_at": ended_str,
                    "career_job_categories": [cat_type],
                    "add_current_affiliation": bool(not comp["left_at"] and not proj["ended_at"]),
                }
                dept_res = execute_manage_action(session, "add", target="career", payload=dept_payload, dry_run=dry_run)
                actions_taken.append({"action": "add_career", "company": c_name, "title": proj_title})

        else:
            # 企業職歴の新規作成
            print(f"[同期] 新規企業職歴を作成します: {c_name}", file=sys.stderr)
            comp_projects = comp.get("projects") or []
            p0 = comp_projects[0] if comp_projects else {}

            cat_type = "v3_engineering__ai_engineer" if any(k in (p0.get("title", "") + p0.get("role", "") + p0.get("description", "")).lower() for k in ("ai", "llm", "slm", "openai")) else "v3_engineering__web_engineer"

            def compact_description(desc: str, max_len: int = 280) -> str:
                if not desc or len(desc) <= max_len:
                    return desc
                lines = desc.strip().splitlines()
                tech_lines = []
                body_lines = []
                is_tech = False
                for l in lines:
                    if "【使用技術】" in l:
                        is_tech = True
                    if is_tech:
                        tech_lines.append(l)
                    else:
                        body_lines.append(l)

                tech_text = "\n".join(tech_lines).strip()
                tech_len = len(tech_text) + 2 if tech_text else 0
                avail_len = max(max_len - tech_len, 50)

                compacted_body = []
                b_len = 0
                for bl in body_lines:
                    line_clean = bl.strip()
                    if not line_clean:
                        continue
                    if b_len + len(line_clean) + 1 <= avail_len:
                        compacted_body.append(line_clean)
                        b_len += len(line_clean) + 1
                    else:
                        rem = avail_len - b_len - 4
                        if rem > 15:
                            compacted_body.append(line_clean[:rem] + "...")
                        break

                parts = []
                if compacted_body:
                    parts.append("\n".join(compacted_body))
                if tech_text:
                    parts.append(tech_text)
                return "\n\n".join(parts).strip()

            joined_str = comp["joined_at"]
            if joined_str and len(joined_str.split("-")) >= 2:
                j_parts = joined_str.split("-")
                joined_str = f"{j_parts[0]}-{int(j_parts[1])}-01"

            left_str = comp["left_at"]
            if left_str and len(left_str.split("-")) >= 3:
                l_parts = left_str.split("-")
                left_str = f"{l_parts[0]}-{int(l_parts[1])}-{l_parts[2]}"

            p0_began = p0.get("began_at") or joined_str
            if p0_began and len(p0_began.split("-")) >= 2:
                b_parts = p0_began.split("-")
                p0_began = f"{b_parts[0]}-{int(b_parts[1])}-01"

            p0_ended = p0.get("ended_at") or left_str
            if p0_ended and len(p0_ended.split("-")) >= 3:
                e_parts = p0_ended.split("-")
                p0_ended = f"{e_parts[0]}-{int(e_parts[1])}-{e_parts[2]}"

            comp_payload = {
                "company_name": c_name,
                "label_type": comp["label_type"],
                "joined_at": joined_str,
                "left_at": left_str,
                "department_name": p0.get("title", ""),
                "role": p0.get("role", comp.get("role", "")),
                "description": compact_description(p0.get("description", "")),
                "category": "Webエンジニア",
                "career_job_categories": [cat_type],
            }
            new_comp_res = execute_manage_action(session, "add", target="career", payload=comp_payload, dry_run=dry_run)
            created_hist = new_comp_res.get("created") or {}
            new_h_id = created_hist.get("id") or (
                new_comp_res.get("data", {}).get("career_company_histories", [{}])[-1].get("id")
            )
            actions_taken.append({"action": "create_company", "name": c_name, "id": new_h_id})

            # 残りのプロジェクトを追加
            if new_h_id and len(comp_projects) > 1:
                for proj in comp_projects[1:]:
                    proj_title = proj["title"].strip()
                    cat_type = "v3_engineering__ai_engineer" if any(k in (proj_title + proj["role"] + proj["description"]).lower() for k in ("ai", "llm", "slm", "openai")) else "v3_engineering__web_engineer"

                    began_str = proj["began_at"]
                    if began_str and len(began_str.split("-")) >= 2:
                        parts = began_str.split("-")
                        began_str = f"{parts[0]}-{int(parts[1])}-01"

                    ended_str = proj["ended_at"]
                    if ended_str and len(ended_str.split("-")) >= 3:
                        parts = ended_str.split("-")
                        ended_str = f"{parts[0]}-{int(parts[1])}-{parts[2]}"

                    print(f"[同期] 部署・プロジェクトを追加します: {proj_title}", file=sys.stderr)
                    dept_payload = {
                        "career_company_history_id": new_h_id,
                        "department_name": proj_title,
                        "role": proj["role"],
                        "description": compact_description(proj["description"]),
                        "began_at": began_str,
                        "ended_at": ended_str,
                        "career_job_categories": [cat_type],
                        "add_current_affiliation": False,
                    }
                    execute_manage_action(session, "add", target="career", payload=dept_payload, dry_run=dry_run)
                    actions_taken.append({"action": "add_career", "company": c_name, "title": proj_title})

    # 4. 最終状態の取得と保存
    final_view = execute_manage_action(session, "view", target="all")
    final_data = final_view.get("data") or {}
    updated_paths = save_background_data(final_data)
    ctx.add_result_paths(updated_paths)

    def summary_fn() -> None:
        print("=== YOUTRUST 職歴・学歴最新化（SSOT同期）完了 ===")
        print(f"- 実行アクション数: {len(actions_taken)}")
        for a in actions_taken:
            print(f"  • {a['action']}: {a.get('name') or a.get('title') or a.get('company')}")
        print(f"- 最新データ保存先: {[to_relative_path(p) for p in updated_paths]}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data={"actions": actions_taken, "data": final_data})


# ----------------------------------------------------------------------
# CLI 設定とメイン
# ----------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = create_base_parser(
        description="YOUTRUST 職歴・学歴CRUD管理スクリプト（安全ガード・差分プレビュー・SSOT同期）",
    )

    parser.add_argument(
        "--session",
        default="job-hunt",
        help="ブラウザプロファイルセッション名 (デフォルト: job-hunt)",
    )

    parser.add_argument(
        "--target",
        choices=["career", "education", "all"],
        default="career",
        help="操作対象 (career: 職歴, education: 学歴, all: 全体)",
    )

    parser.add_argument(
        "--action",
        choices=["show", "view", "backup", "add", "update", "delete", "sync"],
        default="show",
        help="実行アクション (show: 閲覧・保存, backup: バックアップ, add: 追加, update: 更新, delete: 削除, sync: SSOT照合/最新同期)",
    )

    # 職歴関連オプション
    parser.add_argument("--company", help="会社名")
    parser.add_argument("--corporate-number", help="法人番号")
    parser.add_argument("--joined", help="入社年月 / 開始時期 (例: 2025-08-01)")
    parser.add_argument("--left", help="退社年月 / 終了時期 (在職中は指定不要)")
    parser.add_argument("--dept", "--department", dest="dept", help="部署名・プロジェクト名")
    parser.add_argument("--role", help="役職・役割 (例: AIエンジニア / メンバ)")
    parser.add_argument("--desc", "--description", dest="desc", help="職務・プロジェクト詳細内容")
    parser.add_argument("--category", help="職種カテゴリ名 (例: システムエンジニア)")
    parser.add_argument("--current", action="store_true", help="現在の所属企業・部署として登録")
    parser.add_argument("--label", "--label-type", dest="label_type", help="雇用形態 (正社員, 契約社員, 業務委託, 副業 等)")

    # 学歴関連オプション
    parser.add_argument("--school", help="学校名 (例: 東京大学)")
    parser.add_argument("--faculty", "--major", dest="faculty", help="学部・学科・専攻")
    parser.add_argument("--entered", help="入学年月 (例: 2016-04-01)")
    parser.add_argument("--graduated", help="卒業年月 (例: 2024-03-31)")
    parser.add_argument("--seminar", help="ゼミ・研究室名")
    parser.add_argument("--club", help="サークル・部活名")

    # ID指定 (更新・削除用)
    parser.add_argument("--id", help="更新・削除対象ID (企業職歴IDまたは学歴ID)")
    parser.add_argument("--history-id", help="企業職歴ID")
    parser.add_argument("--career-id", help="部署・プロジェクトID")
    parser.add_argument("--edu-id", help="学歴ID")

    # 安全ガード & 実行フラグ
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="変更を実際に行わず差分・Payloadのみをプレビュー表示する",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="sync アクション実行時に、SSOTの職歴・学歴を実際にYOUTRUSTへ反映する",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    session = args.session or "job-hunt"

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        # 認証チェック
        ensure_site_authenticated(site="youtrust", session=session)

        action = args.action
        if action in ("show", "view"):
            return handle_show(args, session, ctx)
        elif action == "backup":
            return handle_backup(args, session, ctx)
        elif action == "add":
            return handle_add(args, session, ctx)
        elif action == "update":
            return handle_update(args, session, ctx)
        elif action == "delete":
            return handle_delete(args, session, ctx)
        elif action == "sync":
            return handle_sync(args, session, ctx)
        else:
            ctx.error(f"未知のアクションです: {action}")
            return 1


if __name__ == "__main__":
    sys.exit(main())
