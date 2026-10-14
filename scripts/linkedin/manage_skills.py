"""LinkedIn 保有スキル（Skills）CRUD 管理スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
LinkedInの保有スキル一覧（/details/skills/）の参照・追加・削除を安全に実行します。

変更操作（追加・削除）の実行前には必ず最新スキル一覧の自動バックアップを取得し、
変更後には最新スキル一覧を再同期してローカルファイルを更新します。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

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
from scripts.common.cli import to_relative_path
from scripts.linkedin.fetch_profile import (
    DEFAULT_PROFILE_SLUG,
    PROFILE_DATA_DIR,
    fetch_linkedin_profile,
    save_profile_data,
)

LINKEDIN_SCRIPTS_DIR = Path(__file__).resolve().parent
BACKUP_DIR = PROFILE_DATA_DIR / "backups"
MANAGE_SCRIPT_PATH = LINKEDIN_SCRIPTS_DIR / "manage_skills.mjs"


def execute_skill_action(
    session: str,
    action: str,
    payload: dict[str, Any],
    slug: str = DEFAULT_PROFILE_SLUG,
    timeout: float = 40.0,
) -> dict[str, Any]:
    """manage_skills.mjs をテンプレート置換を介して安全に実行する."""
    if not MANAGE_SCRIPT_PATH.exists():
        raise RuntimeError(f"Playwrightスクリプトが見つかりません: {MANAGE_SCRIPT_PATH}")

    template_code = MANAGE_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = (
        template_code.replace("'__LINKEDIN_ACTION__'", json.dumps(action))
        .replace("__LINKEDIN_PAYLOAD__", json.dumps(payload, ensure_ascii=False))
        .replace("'__LINKEDIN_PROFILE_SLUG__'", json.dumps(slug))
    )

    result = run_code_snippet(session, run_code, timeout=timeout)
    if not result:
        raise RuntimeError(f"Playwright実行で応答が取得できませんでした (action: {action})")
    if not result.get("success"):
        err = result.get("error") or "不明なエラー"
        raise RuntimeError(f"LinkedIn スキル操作エラー ({action}): {err}")
    return result


def fetch_current_skills(session: str, slug: str = DEFAULT_PROFILE_SLUG, timeout: float = 40.0) -> list[dict[str, Any]]:
    """LinkedInから最新のスキル一覧を取得する."""
    result = execute_skill_action(session, "list", {}, slug=slug, timeout=timeout)
    return result.get("skills", [])


def backup_skills(skills: list[dict[str, Any]]) -> Path:
    """変更操作前にスキル一覧のタイムスタンプ付き自動バックアップを保存する."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"backup_skills_{timestamp}.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(skills, f, ensure_ascii=False, indent=2)
    print(f"[安全ガード] 変更前バックアップを保存しました: {to_relative_path(backup_path)}", file=sys.stderr)
    return backup_path


def cmd_list(args: argparse.Namespace, session: str) -> None:
    """最新スキル一覧を取得・表示する."""
    skills = fetch_current_skills(session, slug=args.slug, timeout=args.timeout)

    # プロフィールファイル全体も同期・保存
    profile_data = fetch_linkedin_profile(session, slug=args.slug, timeout=args.timeout)
    saved_files = save_profile_data(profile_data)

    if args.json:
        print(json.dumps(skills, ensure_ascii=False, indent=2))
        return

    if args.summary:
        print("\n========================================================", file=sys.stderr)
        print(f" LinkedIn 保有スキル一覧 (計 {len(skills)} 件)", file=sys.stderr)
        print("========================================================\n", file=sys.stderr)
        for idx, sk in enumerate(skills, start=1):
            print(f"[{idx:2d}] {sk.get('name')} (ID: {sk.get('id')})", file=sys.stderr)
        print("\n[保存ファイル]", file=sys.stderr)
        for f in saved_files:
            print(f"  - {to_relative_path(f)}", file=sys.stderr)
    else:
        for f in saved_files:
            print(to_relative_path(f))


def cmd_add(args: argparse.Namespace, session: str) -> None:
    """新規スキルを追加する."""
    skill_name = args.name.strip()
    if not skill_name:
        print("エラー: スキル名 (--name) を指定してください。", file=sys.stderr)
        sys.exit(1)

    # 1. 変更前一覧の取得 & 自動バックアップ
    print("[安全ガード] 最新スキル一覧を取得し、事前バックアップを作成中...", file=sys.stderr)
    prev_skills = fetch_current_skills(session, slug=args.slug, timeout=args.timeout)
    backup_skills(prev_skills)

    # 既存スキル重複チェック
    for sk in prev_skills:
        if sk.get("name", "").lower() == skill_name.lower():
            print(f"警告: スキル「{skill_name}」は既に登録されています (ID: {sk.get('id')})", file=sys.stderr)
            if not args.force:
                print("重複追加を避けるため処理を中断します。強制追加する場合は --force を指定してください。", file=sys.stderr)
                sys.exit(1)

    # 2. 追加実行
    print(f"[実行中] スキル「{skill_name}」を追加しています...", file=sys.stderr)
    result = execute_skill_action(session, "add", {"name": skill_name}, slug=args.slug, timeout=args.timeout)
    print(f"[完了] {result.get('message', 'スキルを追加しました。')}", file=sys.stderr)

    # 3. 最新プロフィールの再取得と保存
    updated_profile = fetch_linkedin_profile(session, slug=args.slug, timeout=args.timeout)
    saved_files = save_profile_data(updated_profile)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.summary:
        print(f"\n[操作完了] スキル「{skill_name}」を追加しました (現在計 {len(updated_profile.get('skills', []))} 件)", file=sys.stderr)
        for f in saved_files:
            print(f"  - {to_relative_path(f)}", file=sys.stderr)
    else:
        for f in saved_files:
            print(to_relative_path(f))


def cmd_delete(args: argparse.Namespace, session: str) -> None:
    """指定したスキルを削除する."""
    # 1. 変更前一覧の取得 & 自動バックアップ
    print("[安全ガード] 最新スキル一覧を取得し、事前バックアップを作成中...", file=sys.stderr)
    prev_skills = fetch_current_skills(session, slug=args.slug, timeout=args.timeout)
    backup_skills(prev_skills)

    target_id = args.id
    target_name = args.name

    # ID未指定かつ名前指定の場合、IDを逆引き解決
    if not target_id and target_name:
        for sk in prev_skills:
            if sk.get("name", "").lower() == target_name.strip().lower():
                target_id = sk.get("id")
                break
        if not target_id:
            print(f"エラー: 指定された名前「{target_name}」のスキルが見つかりませんでした。", file=sys.stderr)
            sys.exit(1)

    if not target_id:
        print("エラー: 削除対象のスキルID (--id) または名前 (--name) を指定してください。", file=sys.stderr)
        sys.exit(1)

    # 対象のスキル名特定（ログ用）
    display_name = target_name or target_id
    for sk in prev_skills:
        if str(sk.get("id")) == str(target_id):
            display_name = sk.get("name")
            break

    # 2. 削除実行
    print(f"[実行中] スキル「{display_name}」 (ID: {target_id}) を削除しています...", file=sys.stderr)
    result = execute_skill_action(session, "delete", {"id": target_id}, slug=args.slug, timeout=args.timeout)
    print(f"[完了] {result.get('message', 'スキルを削除しました。')}", file=sys.stderr)

    # 3. 最新プロフィールの再取得と保存
    updated_profile = fetch_linkedin_profile(session, slug=args.slug, timeout=args.timeout)
    saved_files = save_profile_data(updated_profile)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.summary:
        print(f"\n[操作完了] スキル「{display_name}」 (ID: {target_id}) を削除しました", file=sys.stderr)
        for f in saved_files:
            print(f"  - {to_relative_path(f)}", file=sys.stderr)
    else:
        for f in saved_files:
            print(to_relative_path(f))


def main() -> None:
    parser = argparse.ArgumentParser(description="LinkedIn 保有スキル（Skills）管理スクリプト")
    subparsers = parser.add_subparsers(dest="subcommand", help="実行する操作")

    # list
    list_parser = subparsers.add_parser("list", help="保有スキル一覧を取得")
    list_parser.add_argument("--slug", default=DEFAULT_PROFILE_SLUG, help="LinkedInプロフィールスラッグ")
    list_parser.add_argument("--session", default="job-hunt", help="Playwrightブラウザセッション名")
    list_parser.add_argument("--profile-path", default=None, help="カスタムブラウザプロファイルディレクトリ")
    list_parser.add_argument("--headed", action="store_true", help="ブラウザを表示して実行")
    list_parser.add_argument("--timeout", type=float, default=40.0, help="実行タイムアウト（秒）")
    list_parser.add_argument("--no-notify", action="store_true", help="手動ログイン時の通知を抑制")
    list_parser.add_argument("--summary", action="store_true", help="人間可読なサマリテキストを出力")
    list_parser.add_argument("--json", action="store_true", help="取得結果をJSON形式で標準出力")
    list_parser.add_argument("--keep-open", action="store_true", help="実行後にブラウザセッションを維持")

    # add
    add_parser = subparsers.add_parser("add", help="新規スキルを追加")
    add_parser.add_argument("--name", required=True, help="追加するスキル名 (例: Python)")
    add_parser.add_argument("--force", action="store_true", help="同名スキルが存在しても強制追加")
    add_parser.add_argument("--slug", default=DEFAULT_PROFILE_SLUG, help="LinkedInプロフィールスラッグ")
    add_parser.add_argument("--session", default="job-hunt", help="Playwrightブラウザセッション名")
    add_parser.add_argument("--profile-path", default=None, help="カスタムブラウザプロファイルディレクトリ")
    add_parser.add_argument("--headed", action="store_true", help="ブラウザを表示して実行")
    add_parser.add_argument("--timeout", type=float, default=45.0, help="実行タイムアウト（秒）")
    add_parser.add_argument("--no-notify", action="store_true", help="手動ログイン時の通知を抑制")
    add_parser.add_argument("--summary", action="store_true", help="人間可読なサマリテキストを出力")
    add_parser.add_argument("--json", action="store_true", help="実行結果をJSON形式で標準出力")
    add_parser.add_argument("--keep-open", action="store_true", help="実行後にブラウザセッションを維持")

    # delete
    delete_parser = subparsers.add_parser("delete", help="指定したスキルを削除")
    delete_parser.add_argument("--id", default=None, help="削除するスキルID")
    delete_parser.add_argument("--name", default=None, help="削除するスキル名（ID未指定時に逆引き）")
    delete_parser.add_argument("--slug", default=DEFAULT_PROFILE_SLUG, help="LinkedInプロフィールスラッグ")
    delete_parser.add_argument("--session", default="job-hunt", help="Playwrightブラウザセッション名")
    delete_parser.add_argument("--profile-path", default=None, help="カスタムブラウザプロファイルディレクトリ")
    delete_parser.add_argument("--headed", action="store_true", help="ブラウザを表示して実行")
    delete_parser.add_argument("--timeout", type=float, default=45.0, help="実行タイムアウト（秒）")
    delete_parser.add_argument("--no-notify", action="store_true", help="手動ログイン時の通知を抑制")
    delete_parser.add_argument("--summary", action="store_true", help="人間可読なサマリテキストを出力")
    delete_parser.add_argument("--json", action="store_true", help="実行結果をJSON形式で標準出力")
    delete_parser.add_argument("--keep-open", action="store_true", help="実行後にブラウザセッションを維持")

    args = parser.parse_args()

    if not args.subcommand:
        parser.print_help(sys.stderr)
        sys.exit(0)

    profile_dir = resolve_profile_path(args.session, args.profile_path)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    target_check_url = f"https://www.linkedin.com/in/{args.slug}/details/skills/"
    ensure_site_authenticated(
        site="linkedin",
        session=args.session,
        target_url=target_check_url,
        headed=args.headed,
        timeout=args.timeout,
        no_notify=args.no_notify,
        profile_dir=profile_dir,
        exit_on_fail=True,
    )

    try:
        if args.subcommand == "list":
            cmd_list(args, args.session)
        elif args.subcommand == "add":
            cmd_add(args, args.session)
        elif args.subcommand == "delete":
            cmd_delete(args, args.session)

        update_profile_last_used(args.session)
    except Exception as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if not args.keep_open:
            run_playwright_cmd([f"-s={args.session}", "close"], timeout=10)


if __name__ == "__main__":
    main()
