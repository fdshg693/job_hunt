"""LinkedIn 職歴（Experience）CRUD 管理スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
LinkedInの職歴詳細画面（/details/experience/）における
職歴データの作成・参照・更新・削除を安全に実行します。

変更操作（C/U/D）の実行前には必ず最新職歴の自動バックアップを取得し、
初期登録済みの実データ（株式会社ヘッドウォータース、株式会社プラスアルファ・コンサルティング等）
に対する変更・削除を厳格に保護・拒絶します。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/linkedin/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.auth_engine import ensure_site_authenticated
from scripts.common.browser_auth import (
    resolve_profile_path,
    run_code_script,
    run_code_snippet,
    run_playwright_cmd,
    update_profile_last_used,
)
from scripts.common.cli import to_relative_path

LINKEDIN_SCRIPTS_DIR = Path(__file__).resolve().parent
EXPERIENCE_DATA_DIR = PROJECT_ROOT / "data" / "linkedin" / "experience"
BACKUP_DIR = EXPERIENCE_DATA_DIR / "backups"
MANAGE_SCRIPT_PATH = LINKEDIN_SCRIPTS_DIR / "manage_experience.mjs"

# 既定のユーザープロフィールスラッグ
DEFAULT_PROFILE_SLUG = "seiwan-maikuma-25a744362"

# 永続保護対象ID（本番実績データ: 変更・削除を不可とする）
PROTECTED_EXPERIENCE_IDS: set[str] = {
    "2786421165",  # 株式会社ヘッドウォータース (Aug 2025 - Present)
    "2786411139",  # 株式会社プラスアルファ・コンサルティング (Apr 2024 - Jul 2025)
}

# 人間可読値と内部値のマッピング辞書
LOCATION_TYPE_MAP: dict[str, str] = {
    "on-site": "LocationType_ON_SITE",
    "onsite": "LocationType_ON_SITE",
    "hybrid": "LocationType_HYBRID",
    "remote": "LocationType_REMOTE",
}

EMPLOYMENT_TYPE_MAP: dict[str, str] = {
    "permanent": "1",
    "full-time": "1",
    "fulltime": "1",
    "contract": "2",
    "self-employed": "3",
    "part-time": "11",
    "parttime": "11",
    "internship": "18",
    "intern": "18",
    "apprenticeship": "19",
    "freelance": "20",
    "indirect contract": "29",
}

MONTH_MAP: dict[str, str] = {
    "january": "1", "jan": "1", "1": "1",
    "february": "2", "feb": "2", "2": "2",
    "march": "3", "mar": "3", "3": "3",
    "april": "4", "apr": "4", "4": "4",
    "may": "5", "5": "5",
    "june": "6", "jun": "6", "6": "6",
    "july": "7", "jul": "7", "7": "7",
    "august": "8", "aug": "8", "8": "8",
    "september": "9", "sep": "9", "9": "9",
    "october": "10", "oct": "10", "10": "10",
    "november": "11", "nov": "11", "11": "11",
    "december": "12", "dec": "12", "12": "12",
}


def normalize_location_type(val: str | None) -> str | None:
    """勤務形態文字列をLinkedIn内部値へ正規化する."""
    if not val:
        return None
    k = val.strip().lower()
    return LOCATION_TYPE_MAP.get(k, val)


def normalize_employment_type(val: str | None) -> str | None:
    """雇用形態文字列をLinkedIn内部値へ正規化する."""
    if not val:
        return None
    k = val.strip().lower()
    return EMPLOYMENT_TYPE_MAP.get(k, val)


def normalize_month(val: str | int | None) -> str | None:
    """月指定を1〜12の文字列へ正規化する."""
    if val is None:
        return None
    k = str(val).strip().lower()
    return MONTH_MAP.get(k, str(val))


def execute_experience_action(
    session: str,
    action: str,
    payload: dict[str, Any],
    slug: str = DEFAULT_PROFILE_SLUG,
    timeout: float = 35.0,
) -> dict[str, Any]:
    """manage_experience.mjs をテンプレート置換を介して安全に実行する."""
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
        raise RuntimeError(f"LinkedIn 職歴操作エラー ({action}): {err}")
    return result


def fetch_current_experiences(session: str, slug: str = DEFAULT_PROFILE_SLUG) -> list[dict[str, Any]]:
    """LinkedInから最新の職歴一覧を取得する."""
    result = execute_experience_action(session, "list", {}, slug=slug)
    return result.get("experiences", [])


def backup_experiences(experiences: list[dict[str, Any]]) -> Path:
    """変更操作前に職歴一覧のタイムスタンプ付き自動バックアップを保存する."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"backup_{timestamp}.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(experiences, f, ensure_ascii=False, indent=2)
    print(f"[安全ガード] 変更前バックアップを保存しました: {to_relative_path(backup_path)}", file=sys.stderr)
    return backup_path


def save_experiences_data(
    experiences: list[dict[str, Any]],
    output_dir: Path = EXPERIENCE_DATA_DIR,
) -> list[Path]:
    """職歴一覧データをJSONおよびFrontmatter付きMarkdownとして保存する."""
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_files: list[Path] = []

    # 1. JSON 保存
    json_path = output_dir / "experiences.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(experiences, f, ensure_ascii=False, indent=2)
    saved_files.append(json_path)

    # 2. Markdown 保存
    md_path = output_dir / "experiences.md"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    md_content = [
        "---",
        "title: LinkedIn 職歴一覧 (Experiences)",
        f"updated_at: '{now_str}'",
        f"total_count: {len(experiences)}",
        "source: linkedin",
        "---",
        "",
        "# LinkedIn 職歴一覧 (Experiences)",
        "",
        f"最終同期日時: {now_str} / 合計 {len(experiences)} 件",
        "",
    ]

    for idx, exp in enumerate(experiences, start=1):
        e_id = exp.get("id", "")
        title = exp.get("title", "未設定")
        comp = exp.get("company", "未設定")
        emp = exp.get("employmentType", "")
        dur = exp.get("duration", "")
        loc = exp.get("location", "")
        rem = exp.get("remoteType", "")
        desc = exp.get("description", "")
        e_url = exp.get("editUrl", "")

        md_content.append(f"## {idx}. {title} - {comp}")
        md_content.append(f"- **職歴ID**: `{e_id}`")
        if emp:
            md_content.append(f"- **雇用形態**: {emp}")
        if dur:
            md_content.append(f"- **在籍期間**: {dur}")
        loc_str = f"{loc} ({rem})" if (loc and rem) else (loc or rem)
        if loc_str:
            md_content.append(f"- **勤務地**: {loc_str}")
        if e_url:
            md_content.append(f"- **編集URL**: [{e_url}]({e_url})")
        if desc:
            md_content.append("")
            md_content.append("### 業務詳細・ハイライト")
            md_content.append(desc)
        md_content.append("")
        md_content.append("---")
        md_content.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_content))
    saved_files.append(md_path)

    return saved_files


def verify_protected_id(
    target_id: str,
    allow_protected: bool = False,
    existing_ids: set[str] | None = None,
) -> None:
    """保護対象IDに対する操作要求を検証する.

    allow_protected が False の場合、保護対象IDであれば終了して阻止する。
    allow_protected が True の場合、警告を標準エラー出力した上で処理を許可する。
    """
    all_protected = set(PROTECTED_EXPERIENCE_IDS)
    if existing_ids:
        all_protected.update(existing_ids)

    if str(target_id) in all_protected:
        if allow_protected:
            print(
                f"[安全ガード警告] 指定された職歴ID ({target_id}) は本番保護対象データですが、"
                f"--allow-protected / --force が指定されたため操作を許可します。",
                file=sys.stderr,
            )
            return
        print(
            f"\n[保護ガード違反] 指定された職歴ID ({target_id}) は本番実績の保護対象データです。\n"
            f"保護リスト（PROTECTED_EXPERIENCE_IDS）に含まれる実績データに対する変更・削除は許可されていません。\n"
            f"本番実績の更新を行う場合は --allow-protected （または --force）を指定してください。",
            file=sys.stderr,
        )
        sys.exit(1)


def cmd_list(args: argparse.Namespace, session: str) -> None:
    """現在の職歴一覧を取得・保存・表示する."""
    experiences = fetch_current_experiences(session, slug=args.slug)
    saved_files = save_experiences_data(experiences)

    if args.json:
        print(json.dumps(experiences, ensure_ascii=False, indent=2))
        return

    if args.summary:
        print("\n========================================================", file=sys.stderr)
        print(f" LinkedIn 職歴一覧 (計 {len(experiences)} 件)", file=sys.stderr)
        print("========================================================\n", file=sys.stderr)
        for idx, exp in enumerate(experiences, start=1):
            is_prot = " [保護対象]" if exp.get("id") in PROTECTED_EXPERIENCE_IDS else ""
            print(f"[{idx}] {exp.get('title')} @ {exp.get('company')}{is_prot}", file=sys.stderr)
            print(f"    - ID:       {exp.get('id')}", file=sys.stderr)
            print(f"    - 期間:     {exp.get('duration')}", file=sys.stderr)
            print(f"    - 形態/地:  {exp.get('employmentType')} | {exp.get('location')} ({exp.get('remoteType')})", file=sys.stderr)
            if exp.get("description"):
                print(f"    - 概要:     {exp.get('description')[:80]}...", file=sys.stderr)
            print(file=sys.stderr)
        print("[保存ファイル]", file=sys.stderr)
        for f in saved_files:
            print(f"  - {to_relative_path(f)}", file=sys.stderr)
    else:
        # エントリポイント規約: デフォルトは作成・更新ファイルパスのみを標準出力
        for f in saved_files:
            print(to_relative_path(f))


def cmd_add(args: argparse.Namespace, session: str) -> None:
    """新規職歴を追加する."""
    # 1. 変更前一覧の取得 & 自動バックアップ
    print("[安全ガード] 最新職歴を取得し、事前バックアップを作成中...", file=sys.stderr)
    prev_exps = fetch_current_experiences(session, slug=args.slug)
    backup_experiences(prev_exps)

    # 2. ペイロード構築
    payload: dict[str, Any] = {
        "title": args.title,
        "company": args.company,
        "employmentType": normalize_employment_type(args.employment),
        "location": args.location,
        "locationType": normalize_location_type(args.location_type),
        "isCurrentlyWorking": bool(args.current),
        "startMonth": normalize_month(args.start_month),
        "startYear": str(args.start_year) if args.start_year else None,
        "endMonth": normalize_month(args.end_month) if not args.current else None,
        "endYear": str(args.end_year) if (not args.current and args.end_year) else None,
        "description": args.description or "",
    }

    print(f"[実行中] 新規職歴を追加しています: {args.title} @ {args.company}...", file=sys.stderr)
    result = execute_experience_action(session, "add", payload, slug=args.slug, timeout=40.0)
    print(f"[完了] {result.get('message', '職歴を追加しました。')}", file=sys.stderr)

    # 3. 最新一覧を再同期・保存
    updated_exps = fetch_current_experiences(session, slug=args.slug)
    saved_files = save_experiences_data(updated_exps)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.summary:
        print(f"\n[操作完了] 新規職歴が追加されました (新規ID: {result.get('createdId')})", file=sys.stderr)
        for f in saved_files:
            print(f"  - {to_relative_path(f)}", file=sys.stderr)
    else:
        for f in saved_files:
            print(to_relative_path(f))


def cmd_update(args: argparse.Namespace, session: str) -> None:
    """職歴を更新する."""
    target_id = str(args.id)

    # 1. 保護IDチェック（本番実績データは --allow-protected が指定されていない場合拒絶）
    verify_protected_id(target_id, allow_protected=getattr(args, "allow_protected", False))

    # 2. 変更前一覧の取得 & 自動バックアップ
    print(f"[安全ガード] 最新職歴を取得し、事前バックアップを作成中 (ID: {target_id})...", file=sys.stderr)
    prev_exps = fetch_current_experiences(session, slug=args.slug)
    backup_experiences(prev_exps)

    # 3. ペイロード構築
    payload: dict[str, Any] = {"id": target_id}
    if args.title is not None:
        payload["title"] = args.title
    if args.company is not None:
        payload["company"] = args.company
    if args.employment is not None:
        payload["employmentType"] = normalize_employment_type(args.employment)
    if args.location is not None:
        payload["location"] = args.location
    if args.location_type is not None:
        payload["locationType"] = normalize_location_type(args.location_type)
    if args.current is not None:
        payload["isCurrentlyWorking"] = args.current
    if args.start_month is not None:
        payload["startMonth"] = normalize_month(args.start_month)
    if args.start_year is not None:
        payload["startYear"] = str(args.start_year)
    if args.end_month is not None:
        payload["endMonth"] = normalize_month(args.end_month)
    if args.end_year is not None:
        payload["endYear"] = str(args.end_year)
    if args.description is not None:
        payload["description"] = args.description

    print(f"[実行中] 職歴 (ID: {target_id}) を更新しています...", file=sys.stderr)
    result = execute_experience_action(session, "update", payload, slug=args.slug, timeout=40.0)
    print(f"[完了] {result.get('message', '職歴を更新しました。')}", file=sys.stderr)

    # 4. 最新一覧を再同期・保存
    updated_exps = fetch_current_experiences(session, slug=args.slug)
    saved_files = save_experiences_data(updated_exps)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.summary:
        print(f"\n[操作完了] 職歴 (ID: {target_id}) が更新されました。", file=sys.stderr)
        for f in saved_files:
            print(f"  - {to_relative_path(f)}", file=sys.stderr)
    else:
        for f in saved_files:
            print(to_relative_path(f))


def cmd_delete(args: argparse.Namespace, session: str) -> None:
    """職歴を削除する."""
    target_id = str(args.id)

    # 1. 保護IDチェック（本番実績データは拒絶）
    verify_protected_id(target_id, allow_protected=False)

    # 2. 変更前一覧の取得 & 自動バックアップ
    print(f"[安全ガード] 最新職歴を取得し、事前バックアップを作成中 (ID: {target_id})...", file=sys.stderr)
    prev_exps = fetch_current_experiences(session, slug=args.slug)
    backup_experiences(prev_exps)

    # 3. 削除実行
    payload: dict[str, Any] = {"id": target_id}
    print(f"[実行中] 職歴 (ID: {target_id}) を削除しています...", file=sys.stderr)
    result = execute_experience_action(session, "delete", payload, slug=args.slug, timeout=40.0)
    print(f"[完了] {result.get('message', '職歴を削除しました。')}", file=sys.stderr)

    # 4. 最新一覧を再同期・保存
    updated_exps = fetch_current_experiences(session, slug=args.slug)
    saved_files = save_experiences_data(updated_exps)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.summary:
        print(f"\n[操作完了] 職歴 (ID: {target_id}) が正常に削除されました。", file=sys.stderr)
        for f in saved_files:
            print(f"  - {to_relative_path(f)}", file=sys.stderr)
    else:
        for f in saved_files:
            print(to_relative_path(f))


def main() -> None:
    """CLIエントリポイント."""
    parser = argparse.ArgumentParser(
        description="LinkedIn 職歴（Experience）CRUD 管理スクリプト"
    )
    parser.add_argument(
        "-s",
        "--session",
        default="job-hunt",
        help="Playwright CLIセッション名（デフォルト: job-hunt）",
    )
    parser.add_argument(
        "--slug",
        default=DEFAULT_PROFILE_SLUG,
        help=f"LinkedInプロフィールスラッグ（デフォルト: {DEFAULT_PROFILE_SLUG}）",
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
    list_parser = subparsers.add_parser("list", help="登録済み職歴の一覧を表示・保存")
    list_parser.add_argument("--summary", action="store_true", help="人間向けサマリ表示")
    list_parser.add_argument("--json", action="store_true", help="JSON形式で出力")

    # 2. add
    add_parser = subparsers.add_parser("add", help="職歴を新規作成")
    add_parser.add_argument("--title", required=True, help="役職（例: Senior Software Engineer）")
    add_parser.add_argument("--company", required=True, help="企業名（例: Test Inc.）")
    add_parser.add_argument("--employment", default="permanent", help="雇用形態（例: permanent, contract, internship 等）")
    add_parser.add_argument("--location", default="Tokyo, Japan", help="勤務地（例: Tokyo, Japan）")
    add_parser.add_argument("--location-type", default="remote", help="勤務形態（remote, hybrid, on-site）")
    add_parser.add_argument("--start-year", type=int, default=2026, help="開始年（例: 2026）")
    add_parser.add_argument("--start-month", default="1", help="開始月（1〜12 または January〜December）")
    add_parser.add_argument("--end-year", type=int, default=None, help="終了年")
    add_parser.add_argument("--end-month", default=None, help="終了月")
    add_parser.add_argument("--current", action="store_true", default=True, help="在職中フラグ（デフォルト: True）")
    add_parser.add_argument("--not-current", action="store_false", dest="current", help="在職中でないフラグ")
    add_parser.add_argument("--description", type=str, default="", help="業務概要・ハイライト")
    add_parser.add_argument("--summary", action="store_true", help="人間向けサマリ表示")
    add_parser.add_argument("--json", action="store_true", help="JSON形式で出力")

    # 3. update
    update_parser = subparsers.add_parser("update", help="既存の職歴を更新（保護対象IDはデフォルトで拒絶）")
    update_parser.add_argument("--id", required=True, help="更新対象の職歴ID")
    update_parser.add_argument(
        "--allow-protected",
        "--force",
        dest="allow_protected",
        action="store_true",
        help="保護対象職歴IDに対する更新を明示的に許可する（本番実績データの最新化用）",
    )
    update_parser.add_argument("--title", type=str, default=None, help="役職")
    update_parser.add_argument("--company", type=str, default=None, help="企業名")
    update_parser.add_argument("--employment", type=str, default=None, help="雇用形態")
    update_parser.add_argument("--location", type=str, default=None, help="勤務地")
    update_parser.add_argument("--location-type", type=str, default=None, help="勤務形態")
    update_parser.add_argument("--start-year", type=int, default=None, help="開始年")
    update_parser.add_argument("--start-month", default=None, help="開始月")
    update_parser.add_argument("--end-year", type=int, default=None, help="終了年")
    update_parser.add_argument("--end-month", default=None, help="終了月")
    update_parser.add_argument("--current", type=lambda x: (str(x).lower() in ['true', '1', 'yes']), default=None, help="在職中フラグ")
    update_parser.add_argument("--description", type=str, default=None, help="業務概要・ハイライト")
    update_parser.add_argument("--summary", action="store_true", help="人間向けサマリ表示")
    update_parser.add_argument("--json", action="store_true", help="JSON形式で出力")

    # 4. delete
    del_parser = subparsers.add_parser("delete", help="職歴を削除（保護対象IDは拒絶）")
    del_parser.add_argument("--id", required=True, help="削除対象の職歴ID")
    del_parser.add_argument("--summary", action="store_true", help="人間向けサマリ表示")
    del_parser.add_argument("--json", action="store_true", help="JSON形式で出力")

    args = parser.parse_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(0)

    # 事前バリデーション: 保護IDに対する操作を早期チェック
    if args.subcommand in ("update", "delete"):
        target_id = str(args.id)
        allow_prot = getattr(args, "allow_protected", False) if args.subcommand == "update" else False
        verify_protected_id(target_id, allow_protected=allow_prot)

    # プロファイルディレクトリ解決
    profile_dir = resolve_profile_path(args.session, args.profile_path)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    # 認証確認・ブラウザセッション起動
    target_check_url = f"https://www.linkedin.com/in/{args.slug}/details/experience/"
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
        elif args.subcommand == "update":
            cmd_update(args, args.session)
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
