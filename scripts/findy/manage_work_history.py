"""Findy 職歴（所属企業）およびプロジェクト CRUD 管理スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
Findyの「キャリア・スキル」画面（/me/career-skills）における
職歴（workHistories）およびプロジェクト（workHistoryProjects）の
作成・参照・更新・削除を安全に実行します。

変更操作（C/U/D）の実行前には必ず最新プロフィールの自動バックアップを取得し、
初期登録済みの実データに対する変更・削除には --force フラグを必須として保護します。
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
from scripts.common.cli import to_relative_path
from scripts.findy.fetch_profile import TARGET_URL, save_profile_result

FINDY_SCRIPTS_DIR = Path(__file__).resolve().parent
PROFILE_DATA_DIR = PROJECT_ROOT / "data" / "findy" / "profile"
BACKUP_DIR = PROFILE_DATA_DIR / "backups"
MANAGE_SCRIPT_PATH = FINDY_SCRIPTS_DIR / "manage_work_history.mjs"
FETCH_PROFILE_SCRIPT_PATH = FINDY_SCRIPTS_DIR / "fetch_profile.mjs"
AUTH_CHECK_SCRIPT_PATH = FINDY_SCRIPTS_DIR / "auth_check.mjs"
AUTH_GUARD_SCRIPT_PATH = FINDY_SCRIPTS_DIR / "auth_guard.mjs"


def fetch_current_profile_data(session: str) -> dict[str, Any]:
    """キャリア・スキル画面から現在のプロフィールデータを取得する."""
    result = run_code_script(session, FETCH_PROFILE_SCRIPT_PATH, timeout=30)
    if not result or not result.get("success"):
        raise RuntimeError("プロフィールデータの取得に失敗しました。")
    return result


def backup_profile_data(profile_data: dict[str, Any]) -> Path:
    """変更操作前にプロフィールのタイムスタンプ付き自動バックアップを保存する."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"backup_{timestamp}.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(profile_data, f, ensure_ascii=False, indent=2)
    print(f"[安全ガード] 変更前バックアップを保存しました: {to_relative_path(backup_path)}", file=sys.stderr)
    return backup_path


def extract_existing_ids(profile_data: dict[str, Any]) -> tuple[set[int], set[int]]:
    """プロフィールデータから既存の職歴IDセットおよびプロジェクトIDセットを抽出する."""
    career_skills = profile_data.get("careerSkills") or {}
    user = career_skills.get("currentUser") or {}
    work_histories = user.get("workHistories") or []

    company_ids: set[int] = set()
    project_ids: set[int] = set()

    for wh in work_histories:
        c_id = wh.get("id")
        if c_id is not None:
            company_ids.add(int(c_id))
        for proj in wh.get("workHistoryProjects") or []:
            p_id = proj.get("id")
            if p_id is not None:
                project_ids.add(int(p_id))

    return company_ids, project_ids


def execute_mutation(
    session: str,
    action: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """manage_work_history.mjs テンプレートに action と variables を注入して実行する."""
    if not MANAGE_SCRIPT_PATH.exists():
        raise RuntimeError(f"テンプレートスクリプトが見つかりません: {MANAGE_SCRIPT_PATH}")

    template_code = MANAGE_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = template_code.replace("'__FINDY_ACTION__'", json.dumps(action)).replace(
        "__FINDY_VARIABLES__", json.dumps(payload, ensure_ascii=False)
    )

    tmp_script_path = FINDY_SCRIPTS_DIR / f".tmp_mutation_{action}.mjs"
    tmp_script_path.write_text(run_code, encoding="utf-8")

    try:
        result = run_code_script(session, tmp_script_path, timeout=30)
        if not result:
            raise RuntimeError(f"Mutation実行スクリプトの呼び出しに失敗しました: {action}")
        if not result.get("success"):
            err = result.get("error") or "不明なエラー"
            raise RuntimeError(f"GraphQL Mutationエラー ({action}): {err}")
        return result
    finally:
        if tmp_script_path.exists():
            try:
                tmp_script_path.unlink()
            except Exception:
                pass


def cmd_list(args: argparse.Namespace, session: str) -> None:
    """現在の職歴・プロジェクト一覧を出力する."""
    data = fetch_current_profile_data(session)
    career_skills = data.get("careerSkills") or {}
    user = career_skills.get("currentUser") or {}
    work_histories = user.get("workHistories") or []

    if args.json:
        print(json.dumps(work_histories, ensure_ascii=False, indent=2))
        return

    # 人間向け整形表示またはサマリ
    print("\n========================================================", file=sys.stderr)
    print(" Findy 登録職歴・プロジェクト一覧", file=sys.stderr)
    print("========================================================\n", file=sys.stderr)

    if not work_histories:
        print("職歴情報は登録されていません。", file=sys.stderr)
        return

    for idx, wh in enumerate(work_histories, start=1):
        wh_id = wh.get("id")
        comp = wh.get("companyName", "未設定")
        emp = (wh.get("employmentPattern") or {}).get("name", "")
        cur = "（在職中）" if wh.get("isCurrentlyWorking") else ""
        s_date = f"{wh.get('startedOnYear')}年{wh.get('startedOnMonth')}月" if wh.get("startedOnYear") else "-"
        e_date = f"{wh.get('endedOnYear')}年{wh.get('endedOnMonth')}月" if wh.get("endedOnYear") else ("現在" if wh.get("isCurrentlyWorking") else "-")
        projects = wh.get("workHistoryProjects") or []

        print(f"■ [{idx}] 職歴ID: {wh_id} | {comp} ({emp}) {cur}", file=sys.stderr)
        print(f"    期間: {s_date} 〜 {e_date}", file=sys.stderr)
        print(f"    プロジェクト数: {len(projects)} 件", file=sys.stderr)

        for p_idx, p in enumerate(projects, start=1):
            p_id = p.get("id")
            p_name = p.get("name", "未設定")
            p_cur = "（進行中）" if p.get("isCurrentlyWorking") else ""
            p_start = f"{p.get('startedOnYear')}年{p.get('startedOnMonth')}月" if p.get("startedOnYear") else "-"
            p_end = f"{p.get('endedOnYear')}年{p.get('endedOnMonth')}月" if p.get("endedOnYear") else ("現在" if p.get("isCurrentlyWorking") else "-")
            pos = p.get("positionName") or "-"
            scale = p.get("teamScaleName") or "-"
            skills = ", ".join([s.get("name") for s in p.get("skills") or [] if s.get("name")]) or "-"
            print(f"      - プロジェクトID: {p_id} | {p_name} {p_cur}", file=sys.stderr)
            print(f"          期間: {p_start} 〜 {p_end} | 役職: {pos} | 規模: {scale}", file=sys.stderr)
            print(f"          技術: {skills}", file=sys.stderr)
        print(file=sys.stderr)


def cmd_masters(args: argparse.Namespace, session: str) -> None:
    """各種マスタデータを取得・表示する."""
    result = execute_mutation(session, "fetchMasters", {})
    masters = result.get("data") or {}

    if args.json:
        print(json.dumps(masters, ensure_ascii=False, indent=2))
        return

    print("\n========================================================", file=sys.stderr)
    print(" Findy キャリア・スキル マスタデータ", file=sys.stderr)
    print("========================================================\n", file=sys.stderr)

    print("■ 雇用形態 (allEmploymentPatterns):", file=sys.stderr)
    for ep in masters.get("allEmploymentPatterns") or []:
        print(f"  ID {ep['id']}: {ep['name']}", file=sys.stderr)
    print(file=sys.stderr)

    print("■ 役職区分 (allPositionTypes):", file=sys.stderr)
    for pos in masters.get("allPositionTypes") or []:
        print(f"  '{pos['id']}': {pos['name']}", file=sys.stderr)
    print(file=sys.stderr)

    print("■ チーム規模 (allTeamScaleTypes):", file=sys.stderr)
    for ts in masters.get("allTeamScaleTypes") or []:
        print(f"  '{ts['id']}': {ts['name']}", file=sys.stderr)
    print(file=sys.stderr)

    print(f"■ 職種 (allJobRoles - 計{len(masters.get('allJobRoles') or [])}件):", file=sys.stderr)
    for jr in masters.get("allJobRoles") or []:
        print(f"  ID {jr['id']}: {jr['name']} ({jr.get('identifier', '-')})", file=sys.stderr)
    print(file=sys.stderr)


def cmd_search_skills(args: argparse.Namespace, session: str) -> None:
    """スキルを検索する."""
    result = execute_mutation(session, "searchSkills", {"query": args.query})
    skills = (result.get("data") or {}).get("allSearchSkills") or []

    if args.json:
        print(json.dumps(skills, ensure_ascii=False, indent=2))
        return

    print(f"\n■ スキル検索結果 '{args.query}' (計{len(skills)}件):", file=sys.stderr)
    for s in skills:
        print(f"  ID {s['id']}: {s['name']}", file=sys.stderr)
    print(file=sys.stderr)


def find_company_by_id(profile_data: dict[str, Any], cid: int) -> dict[str, Any] | None:
    """職歴IDから職歴オブジェクトを取得する."""
    career_skills = profile_data.get("careerSkills") or {}
    user = career_skills.get("currentUser") or {}
    for wh in user.get("workHistories") or []:
        if wh.get("id") == cid:
            return wh
    return None


def find_project_by_id(profile_data: dict[str, Any], pid: int) -> dict[str, Any] | None:
    """プロジェクトIDからプロジェクトオブジェクトを取得する."""
    career_skills = profile_data.get("careerSkills") or {}
    user = career_skills.get("currentUser") or {}
    for wh in user.get("workHistories") or []:
        for p in wh.get("workHistoryProjects") or []:
            if p.get("id") == pid:
                return p
    return None


def _apply_change_and_sync(
    session: str,
    action: str,
    payload_or_builder: Any,
    args: argparse.Namespace,
    target_id: int | None = None,
    is_company: bool = True,
) -> None:
    """変更系操作を実行し、バックアップ、保護確認、再同期、出力規約を処理する."""
    # 1. 変更前の最新プロファイルを取得
    print("[安全ガード] 変更前プロフィールを取得中...", file=sys.stderr)
    prev_profile = fetch_current_profile_data(session)

    # 2. 自動バックアップを保存
    backup_profile_data(prev_profile)

    # 3. 既存ID保護チェック
    if target_id is not None:
        comp_ids, proj_ids = extract_existing_ids(prev_profile)
        is_existing = (target_id in comp_ids) if is_company else (target_id in proj_ids)
        if is_existing and not getattr(args, "force", False):
            target_type = "職歴（企業）" if is_company else "プロジェクト"
            print(
                f"\n[保護エラー] 指定された{target_type}ID ({target_id}) は本番登録済みの実データです。\n"
                f"実データを変更・削除する場合は、意図的な操作であることを確認し `--force` オプションを付けて再実行してください。",
                file=sys.stderr,
            )
            sys.exit(1)

    # ペイロードの構築
    if callable(payload_or_builder):
        payload = payload_or_builder(prev_profile)
    else:
        payload = payload_or_builder

    # 4. Mutation 実行
    print(f"[実行中] Mutation '{action}' を実行しています...", file=sys.stderr)
    mutation_result = execute_mutation(session, action, payload)
    print("[完了] Mutation が正常に反映されました。", file=sys.stderr)

    # 5. 反映後のプロファイルを取得・保存して最新状態を同期
    print("[同期中] 反映後の最新プロフィールを取得・保存しています...", file=sys.stderr)
    updated_profile = fetch_current_profile_data(session)
    saved_files = save_profile_result(updated_profile, output_dir=PROFILE_DATA_DIR)

    # 6. 出力規約（.agents/rules/scripts-entrypoint.md 準拠）
    if getattr(args, "json", False):
        print(json.dumps(mutation_result, ensure_ascii=False, indent=2))
    elif getattr(args, "summary", False):
        print(f"\n[操作完了] アクション '{action}' が正常に完了しました。", file=sys.stderr)
        if saved_files:
            print("[更新されたファイル一覧]", file=sys.stderr)
            for sf in saved_files:
                print(f"  - {to_relative_path(sf)}", file=sys.stderr)
    else:
        # デフォルト: 作成・更新されたファイルパスのみを標準出力（stdout）に出力
        for sf in saved_files:
            print(to_relative_path(sf))


def cmd_add_company(args: argparse.Namespace, session: str) -> None:
    """職歴（企業）を追加する."""
    payload = {
        "input": {
            "companyName": args.name,
            "employmentPatternId": args.employment,
            "startedOnYear": args.start_year,
            "startedOnMonth": args.start_month,
            "endedOnYear": None if args.current else args.end_year,
            "endedOnMonth": None if args.current else args.end_month,
            "isCurrentlyWorking": bool(args.current),
        }
    }
    _apply_change_and_sync(session, "createWorkHistory", payload, args, target_id=None, is_company=True)


def cmd_update_company(args: argparse.Namespace, session: str) -> None:
    """職歴（企業）を更新する."""
    def build_payload(prev_profile: dict[str, Any]) -> dict[str, Any]:
        existing = find_company_by_id(prev_profile, args.id)
        if not existing:
            raise RuntimeError(f"更新対象の職歴ID ({args.id}) が見つかりません。")

        emp_id = (
            args.employment
            if args.employment is not None
            else (existing.get("employmentPattern") or {}).get("id", 1)
        )
        name = args.name if args.name is not None else existing.get("companyName", "")
        start_year = args.start_year if args.start_year is not None else existing.get("startedOnYear")
        start_month = args.start_month if args.start_month is not None else existing.get("startedOnMonth")

        if args.current:
            is_cur = True
            end_year = None
            end_month = None
        else:
            is_cur = (
                existing.get("isCurrentlyWorking", False)
                if args.end_year is None and args.end_month is None
                else False
            )
            end_year = args.end_year if args.end_year is not None else existing.get("endedOnYear")
            end_month = args.end_month if args.end_month is not None else existing.get("endedOnMonth")

        return {
            "input": {
                "id": args.id,
                "companyName": name,
                "employmentPatternId": emp_id,
                "startedOnYear": start_year,
                "startedOnMonth": start_month,
                "endedOnYear": end_year,
                "endedOnMonth": end_month,
                "isCurrentlyWorking": is_cur,
            }
        }

    _apply_change_and_sync(session, "updateWorkHistory", build_payload, args, target_id=args.id, is_company=True)


def cmd_delete_company(args: argparse.Namespace, session: str) -> None:
    """職歴（企業）を削除する."""
    payload = {"input": {"id": args.id}}
    _apply_change_and_sync(session, "deleteWorkHistory", payload, args, target_id=args.id, is_company=True)


def cmd_add_project(args: argparse.Namespace, session: str) -> None:
    """プロジェクトを追加する."""
    role_ids = [int(r.strip()) for r in args.role_ids.split(",") if r.strip()] if args.role_ids else [7]
    skill_ids = [int(s.strip()) for s in args.skill_ids.split(",") if s.strip()] if args.skill_ids else []

    payload = {
        "input": {
            "usersWorkHistoryId": args.company_id,
            "name": args.name,
            "detail": args.detail or "",
            "startedOnYear": args.start_year,
            "startedOnMonth": args.start_month,
            "endedOnYear": None if args.current else args.end_year,
            "endedOnMonth": None if args.current else args.end_month,
            "isCurrentlyWorking": bool(args.current),
            "jobRoleIds": role_ids,
            "positionType": args.position,
            "teamScaleType": args.scale,
            "skillIds": skill_ids,
        }
    }
    _apply_change_and_sync(session, "createWorkHistoryProject", payload, args, target_id=None, is_company=False)


def cmd_update_project(args: argparse.Namespace, session: str) -> None:
    """プロジェクトを更新する."""
    def build_payload(prev_profile: dict[str, Any]) -> dict[str, Any]:
        existing = find_project_by_id(prev_profile, args.id)
        if not existing:
            raise RuntimeError(f"更新対象のプロジェクトID ({args.id}) が見つかりません。")

        name = args.name if args.name is not None else existing.get("name", "")
        detail = args.detail if args.detail is not None else existing.get("detail", "")
        start_year = args.start_year if args.start_year is not None else existing.get("startedOnYear")
        start_month = args.start_month if args.start_month is not None else existing.get("startedOnMonth")

        if args.current:
            is_cur = True
            end_year = None
            end_month = None
        else:
            is_cur = (
                existing.get("isCurrentlyWorking", False)
                if args.end_year is None and args.end_month is None
                else False
            )
            end_year = args.end_year if args.end_year is not None else existing.get("endedOnYear")
            end_month = args.end_month if args.end_month is not None else existing.get("endedOnMonth")

        if args.role_ids is not None:
            role_ids = [int(r.strip()) for r in args.role_ids.split(",") if r.strip()]
        else:
            role_ids = [r["id"] for r in existing.get("jobRoles") or [] if "id" in r] or [7]

        pos = args.position if args.position is not None else existing.get("positionType", "staff")
        scale = args.scale if args.scale is not None else existing.get("teamScaleType", "one_ten")

        if args.skill_ids is not None:
            skill_ids = [int(s.strip()) for s in args.skill_ids.split(",") if s.strip()]
        else:
            skill_ids = [s["id"] for s in existing.get("skills") or [] if "id" in s]

        return {
            "input": {
                "id": args.id,
                "name": name,
                "detail": detail,
                "startedOnYear": start_year,
                "startedOnMonth": start_month,
                "endedOnYear": end_year,
                "endedOnMonth": end_month,
                "isCurrentlyWorking": is_cur,
                "jobRoleIds": role_ids,
                "positionType": pos,
                "teamScaleType": scale,
                "skillIds": skill_ids,
            }
        }

    _apply_change_and_sync(session, "updateWorkHistoryProject", build_payload, args, target_id=args.id, is_company=False)


def cmd_delete_project(args: argparse.Namespace, session: str) -> None:
    """プロジェクトを削除する."""
    payload = {"input": {"id": args.id}}
    _apply_change_and_sync(session, "deleteWorkHistoryProject", payload, args, target_id=args.id, is_company=False)


def main() -> None:
    """CLIエントリポイント."""
    parser = argparse.ArgumentParser(
        description="Findy 職歴（企業）およびプロジェクト CRUD 管理スクリプト"
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
        help="ブラウザを可視ウィンドウで起動する（手動操作用）",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="手動ログイン待機のタイムアウト秒数（デフォルト: 600秒）",
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

    subparsers = parser.add_subparsers(dest="subcommand", help="実行するサブコマンド")

    # 1. list
    list_parser = subparsers.add_parser("list", help="登録済み職歴・プロジェクトの一覧を表示")
    list_parser.add_argument("--json", action="store_true", help="JSON形式で出力")

    # 2. masters
    masters_parser = subparsers.add_parser("masters", help="マスタデータ（雇用形態、役職、規模、職種）を取得・表示")
    masters_parser.add_argument("--json", action="store_true", help="JSON形式で出力")

    # 3. search-skills
    skill_parser = subparsers.add_parser("search-skills", help="スキルID検索")
    skill_parser.add_argument("-q", "--query", required=True, help="検索するスキル名（例: Python）")
    skill_parser.add_argument("--json", action="store_true", help="JSON形式で出力")

    # 4. add-company
    add_c_parser = subparsers.add_parser("add-company", help="職歴（所属企業）を追加")
    add_c_parser.add_argument("--name", required=True, help="企業名")
    add_c_parser.add_argument("--employment", type=int, default=1, help="雇用形態ID（1:正社員, 2:契約, 3:派遣, 4:バイト, 5:業務委託, 6:他 / デフォルト: 1）")
    add_c_parser.add_argument("--start-year", type=int, required=True, help="開始年（例: 2024）")
    add_c_parser.add_argument("--start-month", type=int, required=True, help="開始月（1〜12）")
    add_c_parser.add_argument("--end-year", type=int, default=None, help="終了年")
    add_c_parser.add_argument("--end-month", type=int, default=None, help="終了月")
    add_c_parser.add_argument("--current", action="store_true", help="現在在籍中")
    add_c_parser.add_argument("--summary", action="store_true", help="サマリ表示")
    add_c_parser.add_argument("--json", action="store_true", help="JSON形式で出力")

    # 5. update-company
    up_c_parser = subparsers.add_parser("update-company", help="職歴（所属企業）を更新")
    up_c_parser.add_argument("--id", type=int, required=True, help="職歴ID")
    up_c_parser.add_argument("--name", type=str, default=None, help="企業名")
    up_c_parser.add_argument("--employment", type=int, default=None, help="雇用形態ID")
    up_c_parser.add_argument("--start-year", type=int, default=None, help="開始年")
    up_c_parser.add_argument("--start-month", type=int, default=None, help="開始月")
    up_c_parser.add_argument("--end-year", type=int, default=None, help="終了年")
    up_c_parser.add_argument("--end-month", type=int, default=None, help="終了月")
    up_c_parser.add_argument("--current", action="store_true", help="現在在籍中")
    up_c_parser.add_argument("--force", action="store_true", help="既存の実データを変更する場合の保護解除フラグ")
    up_c_parser.add_argument("--summary", action="store_true", help="サマリ表示")
    up_c_parser.add_argument("--json", action="store_true", help="JSON形式で出力")

    # 6. delete-company
    del_c_parser = subparsers.add_parser("delete-company", help="職歴（所属企業）を削除")
    del_c_parser.add_argument("--id", type=int, required=True, help="削除対象の職歴ID")
    del_c_parser.add_argument("--force", action="store_true", help="既存の実データを削除する場合の保護解除フラグ")
    del_c_parser.add_argument("--summary", action="store_true", help="サマリ表示")
    del_c_parser.add_argument("--json", action="store_true", help="JSON形式で出力")

    # 7. add-project
    add_p_parser = subparsers.add_parser("add-project", help="プロジェクトを追加")
    add_p_parser.add_argument("--company-id", type=int, required=True, help="親職歴ID（usersWorkHistoryId）")
    add_p_parser.add_argument("--name", required=True, help="プロジェクト名")
    add_p_parser.add_argument("--detail", type=str, default="", help="業務詳細")
    add_p_parser.add_argument("--start-year", type=int, required=True, help="開始年")
    add_p_parser.add_argument("--start-month", type=int, required=True, help="開始月")
    add_p_parser.add_argument("--end-year", type=int, default=None, help="終了年")
    add_p_parser.add_argument("--end-month", type=int, default=None, help="終了月")
    add_p_parser.add_argument("--current", action="store_true", help="現在進行中")
    add_p_parser.add_argument("--role-ids", type=str, default="7", help="職種ID（カンマ区切り、デフォルト: 7:フルスタックエンジニア）")
    add_p_parser.add_argument("--position", choices=["staff", "leader", "manager"], default="staff", help="役職（デフォルト: staff）")
    add_p_parser.add_argument("--scale", choices=["one_ten", "ten_fifty", "fifty_hundred", "more_hundred"], default="one_ten", help="チーム規模（デフォルト: one_ten）")
    add_p_parser.add_argument("--skill-ids", type=str, default="", help="スキルID（カンマ区切り、例: 5,81）")
    add_p_parser.add_argument("--summary", action="store_true", help="サマリ表示")
    add_p_parser.add_argument("--json", action="store_true", help="JSON形式で出力")

    # 8. update-project
    up_p_parser = subparsers.add_parser("update-project", help="プロジェクトを更新")
    up_p_parser.add_argument("--id", type=int, required=True, help="プロジェクトID")
    up_p_parser.add_argument("--name", type=str, default=None, help="プロジェクト名")
    up_p_parser.add_argument("--detail", type=str, default=None, help="業務詳細")
    up_p_parser.add_argument("--start-year", type=int, default=None, help="開始年")
    up_p_parser.add_argument("--start-month", type=int, default=None, help="開始月")
    up_p_parser.add_argument("--end-year", type=int, default=None, help="終了年")
    up_p_parser.add_argument("--end-month", type=int, default=None, help="終了月")
    up_p_parser.add_argument("--current", action="store_true", help="現在進行中")
    up_p_parser.add_argument("--role-ids", type=str, default=None, help="職種ID（カンマ区切り）")
    up_p_parser.add_argument("--position", choices=["staff", "leader", "manager"], default=None, help="役職")
    up_p_parser.add_argument("--scale", choices=["one_ten", "ten_fifty", "fifty_hundred", "more_hundred"], default=None, help="チーム規模")
    up_p_parser.add_argument("--skill-ids", type=str, default=None, help="スキルID（カンマ区切り）")
    up_p_parser.add_argument("--force", action="store_true", help="既存の実データを変更する場合の保護解除フラグ")
    up_p_parser.add_argument("--summary", action="store_true", help="サマリ表示")
    up_p_parser.add_argument("--json", action="store_true", help="JSON形式で出力")

    # 9. delete-project
    del_p_parser = subparsers.add_parser("delete-project", help="プロジェクトを削除")
    del_p_parser.add_argument("--id", type=int, required=True, help="削除対象のプロジェクトID")
    del_p_parser.add_argument("--force", action="store_true", help="既存の実データを削除する場合の保護解除フラグ")
    del_p_parser.add_argument("--summary", action="store_true", help="サマリ表示")
    del_p_parser.add_argument("--json", action="store_true", help="JSON形式で出力")

    args = parser.parse_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(0)

    # 必須スクリプトの存在確認
    for s_path in [MANAGE_SCRIPT_PATH, FETCH_PROFILE_SCRIPT_PATH, AUTH_CHECK_SCRIPT_PATH, AUTH_GUARD_SCRIPT_PATH]:
        if not s_path.exists():
            print(f"エラー: 必須スクリプトが見つかりません: {s_path}", file=sys.stderr)
            sys.exit(1)

    # プロファイル解決
    profile_dir = resolve_profile_path(args.session, args.profile_path)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    # ブラウザセッション準備・認証確認
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

    try:
        # サブコマンドのディスパッチ
        if args.subcommand == "list":
            cmd_list(args, args.session)
        elif args.subcommand == "masters":
            cmd_masters(args, args.session)
        elif args.subcommand == "search-skills":
            cmd_search_skills(args, args.session)
        elif args.subcommand == "add-company":
            cmd_add_company(args, args.session)
        elif args.subcommand == "update-company":
            cmd_update_company(args, args.session)
        elif args.subcommand == "delete-company":
            cmd_delete_company(args, args.session)
        elif args.subcommand == "add-project":
            cmd_add_project(args, args.session)
        elif args.subcommand == "update-project":
            cmd_update_project(args, args.session)
        elif args.subcommand == "delete-project":
            cmd_delete_project(args, args.session)

        # 最終利用日更新
        update_profile_last_used(args.session)

    except Exception as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if not args.keep_open:
            run_playwright_cmd([f"-s={args.session}", "close"], timeout=10)


if __name__ == "__main__":
    main()
