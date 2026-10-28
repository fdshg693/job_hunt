"""Forkwell の自己紹介・やりたいこと・スカウト設定を閲覧・更新する CLI.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
Forkwell Jobs のダッシュボード（/dashboard, /dashboard/preferences）における
自己紹介（Bio）、やりたい・目指したいこと（Career Vision）、スカウト受取設定の
閲覧・更新・バックアップを安全に実行します。

変更操作の実行前には必ず最新プロフィールの自動バックアップを取得し、
--dry-run フラグによる変更プレビュー（Unified Diff）と安全ガードを提供します。
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
from scripts.common.profile_sync import load_site_text, print_profile_diff, save_profile_backup
from scripts.forkwell.fetch_profile import (
    DEFAULT_OUTPUT_DIR,
    FETCH_SCRIPT_PATH,
    TARGET_URL,
    save_profile_result,
)

FORKWELL_SCRIPTS_DIR = Path(__file__).resolve().parent
MANAGE_SCRIPT_PATH = FORKWELL_SCRIPTS_DIR / "manage_profile.mjs"
BACKUP_DIR = DEFAULT_OUTPUT_DIR / "backups"
PREFERENCES_URL = "https://jobs.forkwell.com/dashboard/preferences"


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

    template_code = MANAGE_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = (
        template_code.replace("'__FORKWELL_ACTION__'", json.dumps(action))
        .replace("__FORKWELL_PAYLOAD__", json.dumps(payload or {}, ensure_ascii=False))
        .replace("__FORKWELL_DRY_RUN__", "true" if dry_run else "false")
    )

    tmp_script_path = FORKWELL_SCRIPTS_DIR / f".tmp_manage_{action}.mjs"
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


def backup_current_profile(session: str) -> list[Path]:
    """変更操作前に最新のプロフィールデータを自動バックアップする."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    fetch_result = run_code_script(session, FETCH_SCRIPT_PATH, timeout=45)
    if not fetch_result or not fetch_result.get("success"):
        raise RuntimeError("変更前自動バックアップ（最新プロフィール取得）に失敗したため、操作を中断します。")

    # タイムスタンプ付き個別バックアップ保存（共通安全ガード基盤）
    backup_file = save_profile_backup(
        site="forkwell",
        section="profile",
        data=fetch_result,
        backup_dir=BACKUP_DIR,
    )
    return [backup_file]


def generate_bio_from_profile() -> str:
    """vault/profile/sites/forkwell.md を読み込み、Forkwell向けの自己紹介文を取得する."""
    return load_site_text("forkwell")


def print_diff(previous: str, new: str, from_label: str = "現在登録内容", to_label: str = "反映予定内容") -> None:
    """テキスト差分（Unified Diff）を共通基盤の統一フォーマットで出力する."""
    print_profile_diff(
        before=previous,
        after=new,
        title="Forkwell プロフィール差分",
        from_label=from_label,
        to_label=to_label,
        stream=sys.stdout,
    )


# ----------------------------------------------------------------------
# サブコマンド実装
# ----------------------------------------------------------------------


def cmd_show_bio(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """現在の自己紹介を表示する."""
    result = execute_manage_action(session, "get-bio")
    data = result.get("data") or {}
    bio = data.get("bio", "")

    if ctx.json_mode:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif ctx.summary:
        print("=== Forkwell 自己紹介（現在値） ===")
        print(bio)
        print(f"\n文字数: {len(bio)} 文字")
    else:
        print(bio)
    return 0


def cmd_update_bio(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """自己紹介を更新する."""
    new_bio = ""
    if getattr(args, "text", None):
        new_bio = args.text
    elif getattr(args, "file", None):
        file_path = Path(args.file)
        if not file_path.exists():
            ctx.error(f"指定されたファイルが見つかりません: {file_path}")
            return 1
        new_bio = file_path.read_text(encoding="utf-8")
    elif getattr(args, "from_profile", False):
        new_bio = generate_bio_from_profile()
    else:
        ctx.error("--text, --file, または --from-profile のいずれかを指定してください。")
        return 1

    new_bio = new_bio.strip()
    if not new_bio:
        ctx.error("更新テキストが空です。")
        return 1

    dry_run = getattr(args, "dry_run", False)

    # 1. 安全ガード: 本番更新時は必ず自動バックアップを取得
    backup_files: list[Path] = []
    if not dry_run:
        try:
            backup_files = backup_current_profile(session)
            ctx.add_result_paths(backup_files)
        except Exception as e:
            ctx.error(f"バックアップ失敗による中断: {e}")
            return 1

    # 2. アクション実行
    payload = {"bio": new_bio}
    result = execute_manage_action(session, "update-bio", payload=payload, dry_run=dry_run)
    res_data = result.get("data") or {}
    prev_bio = res_data.get("previousBio", "")

    # 3. Dry-Run 結果出力
    if dry_run:
        if ctx.summary or not ctx.json_mode:
            print("[DRY-RUN] Forkwell 自己紹介更新プレビュー")
            print(f"- 現在文字数: {len(prev_bio)} 文字")
            print(f"- 反映後文字数: {len(new_bio)} 文字")
            print(f"- 差分文字数: {len(new_bio) - len(prev_bio):+d} 文字")
            print_diff(prev_bio, new_bio)
            print("[INFO] --dry-run のためブラウザ上への保存は実行されていません。")
        if ctx.json_mode:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    # 4. 本番反映後のデータ再同期（最新プロファイル全体を取得して profile.md/json を更新）
    updated_files: list[Path] = []
    try:
        fetch_res = run_code_script(session, FETCH_SCRIPT_PATH, timeout=45)
        if fetch_res and fetch_res.get("success"):
            updated_files = save_profile_result(fetch_res, output_dir=DEFAULT_OUTPUT_DIR)
            ctx.add_result_paths(updated_files)
    except Exception as e:
        print(f"[警告] 更新後ファイルの再同期に失敗しました: {e}", file=sys.stderr)

    def summary_fn() -> None:
        print("=== Forkwell 自己紹介更新完了 ===")
        print(f"- 変更前文字数: {len(prev_bio)} 文字")
        print(f"- 変更後文字数: {len(new_bio)} 文字")
        print(f"- 更新手法: {res_data.get('method', 'api')}")
        print(f"- 反映先URL: {res_data.get('finalUrl', TARGET_URL)}")
        print_diff(prev_bio, new_bio)
        all_affected = backup_files + updated_files
        if all_affected:
            print("[作成・更新ファイル]")
            for f in all_affected:
                print(f"  - {to_relative_path(f)}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=result)


def cmd_show_desired_role(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """現在のやりたい・目指したいこと（Career Vision）を表示する."""
    result = execute_manage_action(session, "get-desired-role")
    data = result.get("data") or {}
    role = data.get("desiredRole", "")

    if ctx.json_mode:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif ctx.summary:
        print("=== Forkwell やりたい・目指したいこと（現在値） ===")
        print(role)
    else:
        print(role)
    return 0


def cmd_update_desired_role(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """やりたい・目指したいこと（Career Vision）を更新する."""
    new_role = ""
    if getattr(args, "text", None):
        new_role = args.text
    elif getattr(args, "role", None):
        new_role = args.role
    elif getattr(args, "file", None):
        file_path = Path(args.file)
        if not file_path.exists():
            ctx.error(f"指定されたファイルが見つかりません: {file_path}")
            return 1
        new_role = file_path.read_text(encoding="utf-8")
    else:
        ctx.error("--text または --role または --file を指定してください。")
        return 1

    new_role = new_role.strip()
    if not new_role:
        ctx.error("更新テキストが空です。")
        return 1

    dry_run = getattr(args, "dry_run", False)

    # 1. 安全ガード
    backup_files: list[Path] = []
    if not dry_run:
        try:
            backup_files = backup_current_profile(session)
            ctx.add_result_paths(backup_files)
        except Exception as e:
            ctx.error(f"バックアップ失敗による中断: {e}")
            return 1

    # 2. アクション実行
    payload = {"desiredRole": new_role}
    result = execute_manage_action(session, "update-desired-role", payload=payload, dry_run=dry_run)
    res_data = result.get("data") or {}
    prev_role = res_data.get("previousRole", "")

    # 3. Dry-Run 出力
    if dry_run:
        if ctx.summary or not ctx.json_mode:
            print("[DRY-RUN] Forkwell やりたい・目指したいこと更新プレビュー")
            print_diff(prev_role, new_role)
            print("[INFO] --dry-run のためブラウザ上への保存は実行されていません。")
        if ctx.json_mode:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    # 4. 本番反映後のデータ再同期
    updated_files: list[Path] = []
    try:
        fetch_res = run_code_script(session, FETCH_SCRIPT_PATH, timeout=45)
        if fetch_res and fetch_res.get("success"):
            updated_files = save_profile_result(fetch_res, output_dir=DEFAULT_OUTPUT_DIR)
            ctx.add_result_paths(updated_files)
    except Exception as e:
        print(f"[警告] 更新後ファイルの再同期に失敗しました: {e}", file=sys.stderr)

    def summary_fn() -> None:
        print("=== Forkwell やりたい・目指したいこと更新完了 ===")
        print(f"- 反映先URL: {res_data.get('finalUrl', PREFERENCES_URL)}")
        print_diff(prev_role, new_role)
        all_affected = backup_files + updated_files
        if all_affected:
            print("[作成・更新ファイル]")
            for f in all_affected:
                print(f"  - {to_relative_path(f)}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=result)


def cmd_show_scout(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """現在のスカウト受け取り設定を表示する."""
    result = execute_manage_action(session, "get-scout")
    data = result.get("data") or {}
    status = data.get("status", "unknown")

    if ctx.json_mode:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif ctx.summary:
        print(f"Forkwell スカウト設定: {status.upper()} (active={data.get('active')})")
    else:
        print(status)
    return 0


def cmd_update_scout(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """スカウト受け取り設定を更新する."""
    target_status = (args.status or "").lower()
    if target_status not in ("on", "off"):
        ctx.error("--status には 'on' または 'off' を指定してください。")
        return 1

    dry_run = getattr(args, "dry_run", False)

    # 1. 安全ガード
    backup_files: list[Path] = []
    if not dry_run:
        try:
            backup_files = backup_current_profile(session)
            ctx.add_result_paths(backup_files)
        except Exception as e:
            ctx.error(f"バックアップ失敗による中断: {e}")
            return 1

    # 2. アクション実行
    payload = {"status": target_status}
    result = execute_manage_action(session, "update-scout", payload=payload, dry_run=dry_run)
    res_data = result.get("data") or {}

    if dry_run:
        if ctx.summary or not ctx.json_mode:
            print("[DRY-RUN] Forkwell スカウト設定更新プレビュー")
            print(f"- 現在設定: {res_data.get('previousStatus')}")
            print(f"- 変更予定: {res_data.get('targetStatus')}")
            if res_data.get("alreadySet"):
                print("[INFO] 既に目標の状態に設定されています。変更は不要です。")
            print("[INFO] --dry-run のためブラウザ上への変更は実行されていません。")
        if ctx.json_mode:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    def summary_fn() -> None:
        print("=== Forkwell スカウト設定更新完了 ===")
        print(f"- 変更前設定: {res_data.get('previousStatus')}")
        print(f"- 変更後設定: {res_data.get('updatedStatus')}")
        if backup_files:
            print("[バックアップファイル]")
            for f in backup_files:
                print(f"  - {to_relative_path(f)}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=result)


def cmd_list_career(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """登録されている職歴・プロジェクト一覧を表示する."""
    result = execute_manage_action(session, "get-career")
    data = result.get("data") or {}
    companies = data.get("companies", [])

    if ctx.json_mode:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print("\n========================================================")
    print(" Forkwell 登録職歴・プロジェクト一覧")
    print("========================================================\n")
    if not companies:
        print("職歴は登録されていません。")
        return 0

    for c in companies:
        c_idx = c.get("index", 0) + 1
        c_name = c.get("companyName", "未設定")
        c_period = c.get("period", "")
        projs = c.get("projects") or []

        print(f"■ [{c_idx}] {c_name} ({c_period})")
        print(f"    プロジェクト数: {len(projs)} 件")

        for p in projs:
            p_idx = p.get("index", 0) + 1
            p_role = p.get("role", "プロジェクト")
            p_period = p.get("period", "")
            desc = p.get("description", "").strip()
            desc_snip = desc.splitlines()[0][:50] + ("..." if len(desc.splitlines()[0]) > 50 else "") if desc else "-"

            print(f"      - [{p_idx}] {p_role} ({p_period})")
            print(f"          業務概要: {desc_snip}")
        print()
    return 0


def cmd_backup(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """現在のプロフィール・ダッシュボード内容を手動バックアップする."""
    saved_files = backup_current_profile(session)
    ctx.add_result_paths(saved_files)

    def summary_fn() -> None:
        print("=== Forkwell プロフィール手動バックアップ完了 ===")
        for sf in saved_files:
            print(f"  - {to_relative_path(sf)}")

    return ctx.flush_outputs(summary_fn=summary_fn)


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
        description="Forkwellのプロフィール（自己紹介・やりたいこと・スカウト受取設定等）を管理・更新・バックアップします。",
        parents=[common_parser],
        epilog=build_epilog(
            examples=[
                "uv run python scripts/forkwell/manage_profile.py show-bio --summary",
                "uv run python scripts/forkwell/manage_profile.py update-bio --file <bio.txt> --dry-run  # 差分プレビューのみ",
                "uv run python scripts/forkwell/manage_profile.py update-scout --status off --dry-run",
            ],
            related=[
                "scripts/forkwell/fetch_profile.py: 前に使う（プロフィール全体を取得）",
                "scripts/forkwell/manage_work_history.py: 職歴・プロジェクトの更新はこちら",
            ],
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. show-bio
    subparsers.add_parser("show-bio", parents=[common_parser], help="現在の自己紹介（Bio）を表示する")

    # 2. update-bio
    up_bio_p = subparsers.add_parser("update-bio", parents=[common_parser], help="自己紹介（Bio）を更新する")
    up_bio_p.add_argument("--text", help="更新する自己紹介テキスト文字列")
    up_bio_p.add_argument("--file", help="更新する自己紹介テキストファイルパス")
    up_bio_p.add_argument(
        "--from-profile",
        action="store_true",
        help="vault/profile/resume.md からForkwell向け自己紹介文を自動生成して更新",
    )
    up_bio_p.add_argument("--dry-run", action="store_true", help="保存を実行せず、差分・反映内容のプレビューのみ行う")

    # 3. show-role
    subparsers.add_parser("show-role", parents=[common_parser], help="現在のやりたい・目指したいこと（Career Vision）を表示する")

    # 4. update-role
    up_role_p = subparsers.add_parser("update-role", parents=[common_parser], help="やりたい・目指したいこと（Career Vision）を更新する")
    up_role_p.add_argument("--text", help="更新するテキスト文字列")
    up_role_p.add_argument("--role", help="更新するテキスト文字列（--text と同一）")
    up_role_p.add_argument("--file", help="更新するテキストファイルパス")
    up_role_p.add_argument("--dry-run", action="store_true", help="保存を実行せず、差分・反映内容のプレビューのみ行う")

    # 5. show-scout
    subparsers.add_parser("show-scout", parents=[common_parser], help="現在のスカウト受け取り設定を表示する")

    # 6. update-scout
    up_scout_p = subparsers.add_parser("update-scout", parents=[common_parser], help="スカウト受け取り設定を更新する")
    up_scout_p.add_argument("--status", choices=["on", "off"], required=True, help="スカウト設定 (on または off)")
    up_scout_p.add_argument("--dry-run", action="store_true", help="変更を実行せずプレビューのみ行う")

    # 7. list-career
    subparsers.add_parser("list-career", parents=[common_parser], help="登録済み職歴・プロジェクト一覧を表示する")

    # 8. backup
    subparsers.add_parser("backup", parents=[common_parser], help="現在のプロフィール・ダッシュボード内容を手動バックアップする")

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
        "show-bio": cmd_show_bio,
        "update-bio": cmd_update_bio,
        "show-role": cmd_show_desired_role,
        "update-role": cmd_update_desired_role,
        "show-scout": cmd_show_scout,
        "update-scout": cmd_update_scout,
        "list-career": cmd_list_career,
        "backup": cmd_backup,
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
