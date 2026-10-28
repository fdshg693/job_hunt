"""Forkwell の職歴（企業）・プロジェクトを一覧・追加・更新・削除する CLI.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
Forkwell Jobs のダッシュボード（/dashboard）における
職歴・プロジェクト（company_users）の参照・追加・更新・削除を安全に実行します。

変更操作（C/U/D）の実行前には必ず最新プロフィールの自動バックアップを取得し、
既存の実データに対する変更・削除には --force フラグを必須として保護します。
--dry-run フラグによる変更プレビュー（Unified Diff / JSON）を提供します。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/forkwell/ の2階層上)
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
from scripts.common.profile_sync import print_profile_diff, save_profile_backup
from scripts.forkwell.fetch_profile import (
    DEFAULT_OUTPUT_DIR,
    FETCH_SCRIPT_PATH,
    save_profile_result,
)

FORKWELL_SCRIPTS_DIR = Path(__file__).resolve().parent
MANAGE_SCRIPT_PATH = FORKWELL_SCRIPTS_DIR / "manage_work_history.mjs"
BACKUP_DIR = DEFAULT_OUTPUT_DIR / "backups"


def execute_manage_action(
    session: str,
    action: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 35,
) -> dict[str, Any]:
    """manage_work_history.mjs に action, payload を注入して実行する."""
    if not MANAGE_SCRIPT_PATH.exists():
        raise RuntimeError(f"管理スクリプトが見つかりません: {MANAGE_SCRIPT_PATH}")

    template_code = MANAGE_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = (
        template_code.replace("'__FORKWELL_ACTION__'", json.dumps(action))
        .replace("__FORKWELL_PAYLOAD__", json.dumps(payload or {}, ensure_ascii=False))
    ).strip().rstrip(";")

    tmp_script_path = FORKWELL_SCRIPTS_DIR / f".tmp_manage_wh_{action}.mjs"
    tmp_script_path.write_text(run_code, encoding="utf-8")

    try:
        result = run_code_script(session, tmp_script_path, timeout=timeout)
        if not result:
            raise RuntimeError(f"Playwrightスクリプトの実行に失敗しました: {action}")
        if not result.get("success"):
            err = result.get("error") or "不明なエラー"
            raise RuntimeError(f"操作実行エラー ({action}): {err}")
        return result
    finally:
        if tmp_script_path.exists():
            try:
                tmp_script_path.unlink()
            except Exception:
                pass


def fetch_current_work_history(session: str) -> dict[str, Any]:
    """ダッシュボードから現在の職歴・プロジェクト一覧（company_users）を取得する."""
    res = execute_manage_action(session, "list")
    data = res.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("職歴データの形式が不正です。")
    return data


def backup_profile_data(raw_data: dict[str, Any]) -> Path:
    """変更操作前に職歴・プロフィールデータのタイムスタンプ付き自動バックアップを保存する."""
    return save_profile_backup(
        site="forkwell",
        section="work_history",
        data=raw_data,
        backup_dir=BACKUP_DIR,
    )


def extract_experiences_list(data: dict[str, Any]) -> list[dict[str, Any]]:
    """レスポンスから企業ごとの職歴グループ一覧を取得する."""
    return data.get("experiences") or []


def find_project_by_id(data: dict[str, Any], project_id: int) -> dict[str, Any] | None:
    """IDからプロジェクト（company_user レコード）を検索する."""
    for exp_group in extract_experiences_list(data):
        for item in exp_group.get("experiences") or []:
            if item.get("id") == project_id:
                return item
    return None


def find_projects_by_company(data: dict[str, Any], company_name: str) -> list[dict[str, Any]]:
    """企業名から該当するプロジェクト一覧を検索する."""
    matched = []
    comp_norm = company_name.strip().lower()
    for exp_group in extract_experiences_list(data):
        summary = exp_group.get("summary") or {}
        g_name = summary.get("company_name", "")
        if comp_norm in g_name.strip().lower():
            matched.extend(exp_group.get("experiences") or [])
    return matched


def format_date_str(year: int | None, month: int | None) -> str | None:
    """年・月から YYYY-MM-01 形式の日付文字列を生成する."""
    if not year or not month:
        return None
    return f"{year:04d}-{month:02d}-01"


def print_diff(previous: str, new: str, from_label: str = "現在登録内容", to_label: str = "反映予定内容") -> None:
    """テキスト差分（Unified Diff）を共通基盤の統一フォーマットで出力する."""
    print_profile_diff(
        before=previous,
        after=new,
        title="Forkwell 職歴・プロジェクト差分",
        from_label=from_label,
        to_label=to_label,
        stream=sys.stderr,
    )


# ----------------------------------------------------------------------
# サブコマンド処理
# ----------------------------------------------------------------------


def cmd_list(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """登録されている職歴・プロジェクト一覧を表示する."""
    raw_data = fetch_current_work_history(session)
    exp_groups = extract_experiences_list(raw_data)

    if ctx.json_mode:
        print(json.dumps(raw_data, ensure_ascii=False, indent=2))
        return 0

    print("\n========================================================", file=sys.stderr)
    print(" Forkwell 登録職歴・プロジェクト一覧", file=sys.stderr)
    print("========================================================\n", file=sys.stderr)

    if not exp_groups:
        print("職歴情報は登録されていません。", file=sys.stderr)
        return 0

    for idx, group in enumerate(exp_groups, start=1):
        summary = group.get("summary") or {}
        comp_name = summary.get("company_name", "未設定")
        comp_id = summary.get("company_id", "-")
        joined = summary.get("joined_at") or "-"
        left = summary.get("left_at") or "現在"
        projs = group.get("experiences") or []

        print(f"■ [{idx}] 企業: {comp_name} (ID: {comp_id})", file=sys.stderr)
        print(f"    在籍期間: {joined[:10] if joined != '-' else '-'} 〜 {left[:10] if left != '現在' else '現在'}", file=sys.stderr)
        print(f"    プロジェクト数: {len(projs)} 件", file=sys.stderr)

        for p_idx, p in enumerate(projs, start=1):
            p_id = p.get("id")
            pos = p.get("position", "エンジニア")
            p_joined = p.get("joined_at") or "-"
            p_left = p.get("left_at") or ("現在" if p.get("during_the_tenure") else "-")
            cur = "（在職中）" if p.get("during_the_tenure") else ""
            body = (p.get("body") or "").strip()
            first_line = body.splitlines()[0][:60] if body else "-"
            ellipsis = "..." if len(body.splitlines()[0]) > 60 else ""

            print(f"      - [{p_idx}] プロジェクトID: {p_id} | 役職: {pos} {cur}", file=sys.stderr)
            print(f"          期間: {p_joined[:10] if p_joined != '-' else '-'} 〜 {p_left[:10] if p_left != '現在' else '現在'}", file=sys.stderr)
            print(f"          概要: {first_line}{ellipsis}", file=sys.stderr)
        print(file=sys.stderr)

    return 0


def cmd_add_project(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """プロジェクトを追加する."""
    detail = ""
    if getattr(args, "detail", None):
        detail = args.detail
    elif getattr(args, "body", None):
        detail = args.body
    elif getattr(args, "file", None):
        file_path = Path(args.file)
        if not file_path.exists():
            ctx.error(f"指定されたファイルが見つかりません: {file_path}")
            return 1
        detail = file_path.read_text(encoding="utf-8")

    start_date = format_date_str(args.start_year, args.start_month)
    if not start_date:
        ctx.error("--start-year と --start-month は必須です。")
        return 1

    end_date = None if args.current else format_date_str(args.end_year, args.end_month)

    payload = {
        "company_name": args.company_name,
        "position": args.position or "エンジニア",
        "joined_at": start_date,
        "left_at": end_date,
        "during_the_tenure": bool(args.current),
        "body": detail,
    }

    dry_run = getattr(args, "dry_run", False)

    if dry_run:
        print("[DRY-RUN] Forkwell プロジェクト新規追加プレビュー", file=sys.stderr)
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        if ctx.json_mode:
            print(json.dumps({"dry_run": True, "action": "add-project", "payload": payload}, ensure_ascii=False, indent=2))
        return 0

    # 安全ガード: 変更前バックアップ
    current_data = fetch_current_work_history(session)
    backup_path = backup_profile_data(current_data)
    ctx.add_result_path(backup_path)

    # API 実行
    print(f"[実行中] 企業 '{args.company_name}' にプロジェクトを追加しています...", file=sys.stderr)
    mutation_res = execute_manage_action(session, "create", payload=payload)
    print("[完了] プロジェクトが追加されました。", file=sys.stderr)

    # 最新状態の再同期
    updated_files = sync_profile_cache(session)
    ctx.add_result_paths(updated_files)

    def summary_fn() -> None:
        print("=== Forkwell プロジェクト追加完了 ===")
        print(f"- 企業名: {args.company_name}")
        print(f"- 役職: {payload['position']}")
        print(f"- 期間: {payload['joined_at']} 〜 {payload['left_at'] or '現在'}")
        print(f"- バックアップ: {to_relative_path(backup_path)}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=mutation_res)


def cmd_update_project(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """プロジェクトを更新する."""
    project_id = args.id
    current_data = fetch_current_work_history(session)
    existing = find_project_by_id(current_data, project_id)

    if not existing:
        ctx.error(f"更新対象のプロジェクトID ({project_id}) が見つかりません。")
        return 1

    # 保護フラグチェック
    if not getattr(args, "force", False) and not getattr(args, "dry_run", False):
        ctx.error(
            f"[保護エラー] プロジェクトID ({project_id}) は本番登録済みの実データです。\n"
            f"実データを更新する場合は、意図的な操作であることを確認し `--force` オプションを付けて再実行してください。"
        )
        return 1

    # フィールド解決（省略時は既存維持）
    comp_name = args.company_name if args.company_name is not None else existing.get("company_name", "")
    position = args.position if args.position is not None else existing.get("position", "エンジニア")

    if args.start_year and args.start_month:
        start_date = format_date_str(args.start_year, args.start_month)
    else:
        start_date = (existing.get("joined_at") or "")[:10]

    if args.current:
        is_current = True
        end_date = None
    elif args.end_year and args.end_month:
        is_current = False
        end_date = format_date_str(args.end_year, args.end_month)
    else:
        is_current = existing.get("during_the_tenure", False)
        end_date = (existing.get("left_at") or "")[:10] if not is_current and existing.get("left_at") else None

    detail = ""
    if getattr(args, "detail", None) is not None:
        detail = args.detail
    elif getattr(args, "body", None) is not None:
        detail = args.body
    elif getattr(args, "file", None):
        file_path = Path(args.file)
        if not file_path.exists():
            ctx.error(f"指定されたファイルが見つかりません: {file_path}")
            return 1
        detail = file_path.read_text(encoding="utf-8")
    else:
        detail = existing.get("body", "")

    payload = {
        "id": project_id,
        "company_name": comp_name,
        "position": position,
        "joined_at": start_date,
        "left_at": end_date,
        "during_the_tenure": is_current,
        "body": detail,
    }

    dry_run = getattr(args, "dry_run", False)

    if dry_run:
        print(f"[DRY-RUN] Forkwell プロジェクト更新プレビュー (ID: {project_id})", file=sys.stderr)
        prev_body = existing.get("body", "")
        print_diff(prev_body, detail, from_label=f"現在 (ID: {project_id})", to_label="更新後")
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        if ctx.json_mode:
            print(json.dumps({"dry_run": True, "action": "update-project", "payload": payload}, ensure_ascii=False, indent=2))
        return 0

    # 安全ガード: 変更前バックアップ
    backup_path = backup_profile_data(current_data)
    ctx.add_result_path(backup_path)

    # API 実行
    print(f"[実行中] プロジェクトID {project_id} を更新しています...", file=sys.stderr)
    mutation_res = execute_manage_action(session, "update", payload=payload)
    print("[完了] プロジェクトが更新されました。", file=sys.stderr)

    # 最新状態の再同期
    updated_files = sync_profile_cache(session)
    ctx.add_result_paths(updated_files)

    def summary_fn() -> None:
        print(f"=== Forkwell プロジェクト更新完了 (ID: {project_id}) ===")
        print(f"- 企業名: {comp_name}")
        print(f"- 役職: {position}")
        print(f"- 期間: {start_date} 〜 {end_date or '現在'}")
        print(f"- バックアップ: {to_relative_path(backup_path)}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=mutation_res)


def cmd_delete_project(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """プロジェクトを削除する."""
    project_id = args.id
    current_data = fetch_current_work_history(session)
    existing = find_project_by_id(current_data, project_id)

    if not existing:
        ctx.error(f"削除対象のプロジェクトID ({project_id}) が見つかりません。")
        return 1

    # 保護フラグチェック
    if not getattr(args, "force", False) and not getattr(args, "dry_run", False):
        ctx.error(
            f"[保護エラー] プロジェクトID ({project_id}) は本番登録済みの実データです。\n"
            f"実データを削除する場合は、意図的な操作であることを確認し `--force` オプションを付けて再実行してください。"
        )
        return 1

    dry_run = getattr(args, "dry_run", False)

    if dry_run:
        print(f"[DRY-RUN] Forkwell プロジェクト削除プレビュー (ID: {project_id})", file=sys.stderr)
        print(f"- 企業名: {existing.get('company_name')}", file=sys.stderr)
        print(f"- 役職: {existing.get('position')}", file=sys.stderr)
        print(f"- 期間: {existing.get('joined_at')} 〜 {existing.get('left_at') or '現在'}", file=sys.stderr)
        if ctx.json_mode:
            print(json.dumps({"dry_run": True, "action": "delete-project", "target": existing}, ensure_ascii=False, indent=2))
        return 0

    # 安全ガード: 変更前バックアップ
    backup_path = backup_profile_data(current_data)
    ctx.add_result_path(backup_path)

    # API 実行
    print(f"[実行中] プロジェクトID {project_id} を削除しています...", file=sys.stderr)
    mutation_res = execute_manage_action(session, "delete", payload={"id": project_id})
    print("[完了] プロジェクトが削除されました。", file=sys.stderr)

    # 最新状態の再同期
    updated_files = sync_profile_cache(session)
    ctx.add_result_paths(updated_files)

    def summary_fn() -> None:
        print(f"=== Forkwell プロジェクト削除完了 (ID: {project_id}) ===")
        print(f"- 削除された企業・役職: {existing.get('company_name')} / {existing.get('position')}")
        print(f"- バックアップ: {to_relative_path(backup_path)}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=mutation_res)


def cmd_add_company(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """職歴（企業）を追加する（新しい企業における1件目のプロジェクトを作成）."""
    args.company_name = args.name
    return cmd_add_project(args, session, ctx)


def cmd_update_company(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """企業の名前を一括更新する（該当企業に属する全プロジェクトの企業名を変更）."""
    current_data = fetch_current_work_history(session)
    projects = find_projects_by_company(current_data, args.name)

    if not projects:
        ctx.error(f"該当する企業名 '{args.name}' のプロジェクトが見つかりません。")
        return 1

    if not getattr(args, "force", False) and not getattr(args, "dry_run", False):
        ctx.error(
            f"[保護エラー] 企業 '{args.name}' に紐付くプロジェクト（計 {len(projects)} 件）は本番登録済みの実データです。\n"
            f"実データを一括更新する場合は、意図的な操作であることを確認し `--force` オプションを付けて再実行してください。"
        )
        return 1

    new_name = args.new_name
    dry_run = getattr(args, "dry_run", False)

    if dry_run:
        print(f"[DRY-RUN] Forkwell 企業名一括更新プレビュー: '{args.name}' -> '{new_name}'", file=sys.stderr)
        print(f"- 対象プロジェクト数: {len(projects)} 件", file=sys.stderr)
        for p in projects:
            print(f"  - ID: {p.get('id')} | 役職: {p.get('position')}", file=sys.stderr)
        return 0

    backup_path = backup_profile_data(current_data)
    ctx.add_result_path(backup_path)

    for p in projects:
        p_id = p.get("id")
        payload = {
            "id": p_id,
            "company_name": new_name,
            "position": p.get("position"),
            "joined_at": (p.get("joined_at") or "")[:10],
            "left_at": (p.get("left_at") or "")[:10] if p.get("left_at") else None,
            "during_the_tenure": p.get("during_the_tenure", False),
            "body": p.get("body", ""),
        }
        execute_manage_action(session, "update", payload=payload)

    updated_files = sync_profile_cache(session)
    ctx.add_result_paths(updated_files)

    def summary_fn() -> None:
        print("=== Forkwell 企業名一括更新完了 ===")
        print(f"- 変更前: {args.name}")
        print(f"- 変更後: {new_name}")
        print(f"- 更新プロジェクト数: {len(projects)} 件")

    return ctx.flush_outputs(summary_fn=summary_fn)


def cmd_delete_company(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """企業に紐付く全プロジェクトを削除する."""
    current_data = fetch_current_work_history(session)
    projects = find_projects_by_company(current_data, args.name)

    if not projects:
        ctx.error(f"該当する企業名 '{args.name}' のプロジェクトが見つかりません。")
        return 1

    if not getattr(args, "force", False) and not getattr(args, "dry_run", False):
        ctx.error(
            f"[保護エラー] 企業 '{args.name}' に紐付く全プロジェクト（計 {len(projects)} 件）を削除します。\n"
            f"実データを削除する場合は、意図的な操作であることを確認し `--force` オプションを付けて再実行してください。"
        )
        return 1

    dry_run = getattr(args, "dry_run", False)

    if dry_run:
        print(f"[DRY-RUN] Forkwell 企業全プロジェクト削除プレビュー: '{args.name}'", file=sys.stderr)
        print(f"- 削除対象プロジェクト数: {len(projects)} 件", file=sys.stderr)
        for p in projects:
            print(f"  - ID: {p.get('id')} | 役職: {p.get('position')}", file=sys.stderr)
        return 0

    backup_path = backup_profile_data(current_data)
    ctx.add_result_path(backup_path)

    for p in projects:
        p_id = p.get("id")
        print(f"[削除中] プロジェクトID {p_id} を削除しています...", file=sys.stderr)
        execute_manage_action(session, "delete", payload={"id": p_id})

    updated_files = sync_profile_cache(session)
    ctx.add_result_paths(updated_files)

    def summary_fn() -> None:
        print("=== Forkwell 企業全プロジェクト削除完了 ===")
        print(f"- 企業名: {args.name}")
        print(f"- 削除件数: {len(projects)} 件")

    return ctx.flush_outputs(summary_fn=summary_fn)


def sync_profile_cache(session: str) -> list[Path]:
    """更新後にプロフィール全体を取得・保存して profile.md/json キャッシュを同期する."""
    print("[同期中] 反映後の最新プロフィールを取得・保存しています...", file=sys.stderr)
    try:
        fetch_res = run_code_script(session, FETCH_SCRIPT_PATH, timeout=45)
        if fetch_res and fetch_res.get("success"):
            return save_profile_result(fetch_res, output_dir=DEFAULT_OUTPUT_DIR)
    except Exception as e:
        print(f"[警告] キャッシュ同期に失敗しました: {e}", file=sys.stderr)
    return []


# ----------------------------------------------------------------------
# メイン・CLIエントリポイント
# ----------------------------------------------------------------------


def main() -> None:
    """CLIエントリポイント."""
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        "-s",
        "--summary",
        action="store_true",
        help="コンソール向け整形サマリ表示（指定しない場合は生成/合致ファイルパスのみ出力）",
    )
    common_parser.add_argument(
        "--json",
        action="store_true",
        help="結果をJSON形式で標準出力に出力",
    )
    common_parser.add_argument(
        "--session",
        default="job-hunt",
        help="Playwright CLIセッション名（デフォルト: job-hunt）",
    )
    common_parser.add_argument(
        "--profile-path",
        help="ブラウザプロファイルディレクトリのパス（省略時は自動解決）",
    )
    common_parser.add_argument(
        "--headed",
        action="store_true",
        help="ブラウザを可視ウィンドウで起動する",
    )
    common_parser.add_argument(
        "--keep-open",
        action="store_true",
        help="処理完了後にブラウザセッションを閉じずに保持する",
    )

    parser = argparse.ArgumentParser(
        description="Forkwellの職歴（企業）およびプロジェクト（company_users）を管理・更新・バックアップします。",
        parents=[common_parser],
        epilog=build_epilog(
            examples=[
                "uv run python scripts/forkwell/manage_work_history.py list --summary",
                'uv run python scripts/forkwell/manage_work_history.py add-project --company-name "<会社名>" --start-year 2024 --start-month 4 --current --file <detail.txt> --dry-run',
                "uv run python scripts/forkwell/manage_work_history.py delete-project --id <id> --force --dry-run  # 既存データの変更・削除は --force 必須",
            ],
            related=[
                "scripts/forkwell/fetch_profile.py: 前に使う（現在の職歴を取得）",
                "scripts/forkwell/manage_profile.py: 自己紹介・やりたいこと等の更新はこちら",
            ],
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. list
    subparsers.add_parser("list", parents=[common_parser], help="登録済み職歴・プロジェクトの一覧を表示")

    # 2. add-project
    add_p_p = subparsers.add_parser("add-project", parents=[common_parser], help="プロジェクトを追加")
    add_p_p.add_argument("--company-name", required=True, help="企業名（例: 株式会社ヘッドウォータース）")
    add_p_p.add_argument("--position", default="エンジニア", help="役職・職種（デフォルト: エンジニア）")
    add_p_p.add_argument("--start-year", type=int, required=True, help="開始年（例: 2024）")
    add_p_p.add_argument("--start-month", type=int, required=True, help="開始月（1〜12）")
    add_p_p.add_argument("--end-year", type=int, default=None, help="終了年")
    add_p_p.add_argument("--end-month", type=int, default=None, help="終了月")
    add_p_p.add_argument("--current", action="store_true", help="現在在籍中 / 進行中")
    add_p_p.add_argument("--detail", help="プロジェクト業務内容テキスト")
    add_p_p.add_argument("--body", help="プロジェクト業務内容テキスト（--detail と同一）")
    add_p_p.add_argument("--file", help="業務内容テキストファイルパス")
    add_p_p.add_argument("--dry-run", action="store_true", help="保存を実行せず、差分・反映内容のプレビューのみ行う")

    # 3. update-project
    up_p_p = subparsers.add_parser("update-project", parents=[common_parser], help="プロジェクトを更新")
    up_p_p.add_argument("--id", type=int, required=True, help="更新対象のプロジェクトID (company_user.id)")
    up_p_p.add_argument("--company-name", help="企業名")
    up_p_p.add_argument("--position", help="役職・職種")
    up_p_p.add_argument("--start-year", type=int, default=None, help="開始年")
    up_p_p.add_argument("--start-month", type=int, default=None, help="開始月")
    up_p_p.add_argument("--end-year", type=int, default=None, help="終了年")
    up_p_p.add_argument("--end-month", type=int, default=None, help="終了月")
    up_p_p.add_argument("--current", action="store_true", help="現在在籍中 / 進行中")
    up_p_p.add_argument("--detail", help="プロジェクト業務内容テキスト")
    up_p_p.add_argument("--body", help="プロジェクト業務内容テキスト（--detail と同一）")
    up_p_p.add_argument("--file", help="業務内容テキストファイルパス")
    up_p_p.add_argument("--force", action="store_true", help="既存の実データを変更する場合の保護解除フラグ")
    up_p_p.add_argument("--dry-run", action="store_true", help="保存を実行せず、差分・反映内容のプレビューのみ行う")

    # 4. delete-project
    del_p_p = subparsers.add_parser("delete-project", parents=[common_parser], help="プロジェクトを削除")
    del_p_p.add_argument("--id", type=int, required=True, help="削除対象のプロジェクトID (company_user.id)")
    del_p_p.add_argument("--force", action="store_true", help="既存の実データを削除する場合の保護解除フラグ")
    del_p_p.add_argument("--dry-run", action="store_true", help="保存を実行せず、差分・反映内容のプレビューのみ行う")

    # 5. add-company
    add_c_p = subparsers.add_parser("add-company", parents=[common_parser], help="職歴（企業）を追加")
    add_c_p.add_argument("--name", required=True, help="企業名")
    add_c_p.add_argument("--position", default="エンジニア", help="役職・職種（デフォルト: エンジニア）")
    add_c_p.add_argument("--start-year", type=int, required=True, help="開始年")
    add_c_p.add_argument("--start-month", type=int, required=True, help="開始月")
    add_c_p.add_argument("--end-year", type=int, default=None, help="終了年")
    add_c_p.add_argument("--end-month", type=int, default=None, help="終了月")
    add_c_p.add_argument("--current", action="store_true", help="現在在籍中")
    add_c_p.add_argument("--detail", default="", help="業務内容テキスト")
    add_c_p.add_argument("--dry-run", action="store_true", help="保存を実行せずプレビューのみ行う")

    # 6. update-company
    up_c_p = subparsers.add_parser("update-company", parents=[common_parser], help="企業の名前を一括更新")
    up_c_p.add_argument("--name", required=True, help="対象企業名")
    up_c_p.add_argument("--new-name", required=True, help="新しい企業名")
    up_c_p.add_argument("--force", action="store_true", help="既存の実データを変更する場合の保護解除フラグ")
    up_c_p.add_argument("--dry-run", action="store_true", help="保存を実行せずプレビューのみ行う")

    # 7. delete-company
    del_c_p = subparsers.add_parser("delete-company", parents=[common_parser], help="企業の全プロジェクトを削除")
    del_c_p.add_argument("--name", required=True, help="削除対象企業名")
    del_c_p.add_argument("--force", action="store_true", help="既存の実データを削除する場合の保護解除フラグ")
    del_c_p.add_argument("--dry-run", action="store_true", help="保存を実行せずプレビューのみ行う")

    args = parser.parse_args()

    session = args.session
    profile_dir = resolve_profile_path(session, args.profile_path)

    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    # 認証確認・ハンドオフ
    try:
        ensure_site_authenticated(
            site="forkwell",
            session=session,
            profile_dir=profile_dir,
            headed=args.headed,
            exit_on_fail=True,
        )
    except Exception as e:
        ctx.error(f"Forkwell 認証エラー: {e}")
        sys.exit(1)

    cmd_map = {
        "list": cmd_list,
        "add-project": cmd_add_project,
        "update-project": cmd_update_project,
        "delete-project": cmd_delete_project,
        "add-company": cmd_add_company,
        "update-company": cmd_update_company,
        "delete-company": cmd_delete_company,
    }

    handler = cmd_map.get(args.command)
    if not handler:
        ctx.error(f"未対応のサブコマンド: {args.command}")
        sys.exit(1)

    try:
        exit_code = handler(args, session, ctx)
    finally:
        if not args.keep_open:
            run_playwright_cmd(["-s=" + session, "close"])
        update_profile_last_used("forkwell")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
