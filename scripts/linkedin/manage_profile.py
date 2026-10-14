"""LinkedIn プロフィール（Headline, About）更新・管理スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
LinkedInの Headline（肩書き）および About（自己紹介）を安全に更新します。

更新実行前には必ず変更対象データの自動バックアップ（JSON）を取得し、
更新完了後には最新プロフィールを再同期して永続化します。
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
MANAGE_SCRIPT_PATH = LINKEDIN_SCRIPTS_DIR / "manage_profile.mjs"


def execute_profile_action(
    session: str,
    action: str,
    payload: dict[str, Any],
    slug: str = DEFAULT_PROFILE_SLUG,
    timeout: float = 40.0,
) -> dict[str, Any]:
    """manage_profile.mjs をテンプレート置換を介して安全に実行する."""
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
        raise RuntimeError(f"LinkedIn プロフィール操作エラー ({action}): {err}")
    return result


def backup_profile(profile_data: dict[str, Any]) -> Path:
    """変更操作前にプロフィール情報のタイムスタンプ付き自動バックアップを保存する."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"backup_{timestamp}.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(profile_data, f, ensure_ascii=False, indent=2)
    print(f"[安全ガード] 変更前バックアップを保存しました: {to_relative_path(backup_path)}", file=sys.stderr)
    return backup_path


def cmd_show(args: argparse.Namespace, session: str) -> None:
    """現在のプロフィール情報を取得・表示する."""
    profile_data = fetch_linkedin_profile(session, slug=args.slug, timeout=args.timeout)
    saved_files = save_profile_data(profile_data)

    if args.json:
        print(json.dumps(profile_data, ensure_ascii=False, indent=2))
        return

    if args.summary:
        print("\n========================================================", file=sys.stderr)
        print(f" LinkedIn プロフィール: {profile_data.get('name')}", file=sys.stderr)
        print("========================================================\n", file=sys.stderr)
        print(f"Headline: {profile_data.get('headline')}", file=sys.stderr)
        print(f"所在地:   {profile_data.get('location')}", file=sys.stderr)
        about = profile_data.get("about", "")
        print(f"\n[About]\n{about[:200]}..." if len(about) > 200 else f"\n[About]\n{about}", file=sys.stderr)
        print("\n[保存ファイル]", file=sys.stderr)
        for f in saved_files:
            print(f"  - {to_relative_path(f)}", file=sys.stderr)
    else:
        for f in saved_files:
            print(to_relative_path(f))


def cmd_update(args: argparse.Namespace, session: str) -> None:
    """Headline または About を更新する."""
    # 1. 更新対象の取得
    headline = args.headline
    about = args.about

    if args.about_file:
        about_path = Path(args.about_file).resolve()
        if not about_path.exists():
            print(f"エラー: 指定されたAboutファイルが存在しません: {args.about_file}", file=sys.stderr)
            sys.exit(1)
        about = about_path.read_text(encoding="utf-8")

    if headline is None and about is None:
        print("エラー: --headline, --about, --about-file のいずれかを指定してください。", file=sys.stderr)
        sys.exit(1)

    # 2. 事前バックアップ
    print("[安全ガード] 最新プロフィールを取得し、事前バックアップを作成中...", file=sys.stderr)
    prev_profile = fetch_linkedin_profile(session, slug=args.slug, timeout=args.timeout)
    backup_profile(prev_profile)

    # 3. 更新実行
    payload: dict[str, Any] = {}
    if headline is not None:
        payload["headline"] = headline
    if about is not None:
        payload["about"] = about

    print("[実行中] LinkedIn プロフィールを更新しています...", file=sys.stderr)
    result = execute_profile_action(session, "update", payload, slug=args.slug, timeout=args.timeout)
    print(f"[完了] {result.get('message', '更新が完了しました。')}", file=sys.stderr)

    # 4. 最新プロフィールの再取得と保存
    updated_profile = fetch_linkedin_profile(session, slug=args.slug, timeout=args.timeout)
    saved_files = save_profile_data(updated_profile)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.summary:
        print(f"\n[操作完了] LinkedIn プロフィールを最新化しました", file=sys.stderr)
        if headline is not None:
            print(f"  新Headline: {updated_profile.get('headline')}", file=sys.stderr)
        for f in saved_files:
            print(f"  - {to_relative_path(f)}", file=sys.stderr)
    else:
        for f in saved_files:
            print(to_relative_path(f))


def main() -> None:
    parser = argparse.ArgumentParser(description="LinkedIn プロフィール（Headline, About）管理スクリプト")
    subparsers = parser.add_subparsers(dest="subcommand", help="実行する操作")

    # show
    show_parser = subparsers.add_parser("show", help="現在のプロフィールを表示")
    show_parser.add_argument("--slug", default=DEFAULT_PROFILE_SLUG, help="LinkedInプロフィールスラッグ")
    show_parser.add_argument("--session", default="job-hunt", help="Playwrightブラウザセッション名")
    show_parser.add_argument("--profile-path", default=None, help="カスタムブラウザプロファイルディレクトリ")
    show_parser.add_argument("--headed", action="store_true", help="ブラウザを表示して実行")
    show_parser.add_argument("--timeout", type=float, default=40.0, help="実行タイムアウト（秒）")
    show_parser.add_argument("--no-notify", action="store_true", help="手動ログイン時の通知を抑制")
    show_parser.add_argument("--summary", action="store_true", help="人間可読なサマリテキストを出力")
    show_parser.add_argument("--json", action="store_true", help="取得結果をJSON形式で標準出力")
    show_parser.add_argument("--keep-open", action="store_true", help="実行後にブラウザセッションを維持")

    # update
    update_parser = subparsers.add_parser("update", help="Headline または About を更新")
    update_parser.add_argument("--headline", default=None, help="新しい肩書き (Headline)")
    update_parser.add_argument("--about", default=None, help="新しい自己紹介文 (About)")
    update_parser.add_argument("--about-file", default=None, help="自己紹介文を記載したテキスト/Markdownファイルパス")
    update_parser.add_argument("--slug", default=DEFAULT_PROFILE_SLUG, help="LinkedInプロフィールスラッグ")
    update_parser.add_argument("--session", default="job-hunt", help="Playwrightブラウザセッション名")
    update_parser.add_argument("--profile-path", default=None, help="カスタムブラウザプロファイルディレクトリ")
    update_parser.add_argument("--headed", action="store_true", help="ブラウザを表示して実行")
    update_parser.add_argument("--timeout", type=float, default=50.0, help="実行タイムアウト（秒）")
    update_parser.add_argument("--no-notify", action="store_true", help="手動ログイン時の通知を抑制")
    update_parser.add_argument("--summary", action="store_true", help="人間可読なサマリテキストを出力")
    update_parser.add_argument("--json", action="store_true", help="実行結果をJSON形式で標準出力")
    update_parser.add_argument("--keep-open", action="store_true", help="実行後にブラウザセッションを維持")

    args = parser.parse_args()

    if not args.subcommand:
        parser.print_help(sys.stderr)
        sys.exit(0)

    profile_dir = resolve_profile_path(args.session, args.profile_path)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    target_check_url = f"https://www.linkedin.com/in/{args.slug}/"
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
        if args.subcommand == "show":
            cmd_show(args, args.session)
        elif args.subcommand == "update":
            cmd_update(args, args.session)

        update_profile_last_used(args.session)
    except Exception as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if not args.keep_open:
            run_playwright_cmd([f"-s={args.session}", "close"], timeout=10)


if __name__ == "__main__":
    main()
