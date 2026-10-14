"""レバテックダイレクト マイページ基本情報（/mypage/profile/basic）管理スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
レバテックダイレクトの基本情報（氏名、生年月日、電話番号、住所、年収、学歴、語学、資格等）の
閲覧（fetch）、更新（update）、プロファイル同期（sync）を安全に実行します。

変更操作の実行前には必ず最新プロフィールの自動バックアップを取得し、
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
from scripts.common.cli import EntrypointContext, create_base_parser, to_relative_path

LEVTECH_SCRIPTS_DIR = Path(__file__).resolve().parent
MANAGE_SCRIPT_PATH = LEVTECH_SCRIPTS_DIR / "manage_profile_basic.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "levtech_direct" / "profile"
BACKUP_DIR = DEFAULT_OUTPUT_DIR / "backups"
TARGET_URL = "https://levtech-direct.jp/mypage/profile/basic"


def execute_manage_action(
    session: str,
    action: str,
    payload: dict[str, Any] | None = None,
    dry_run: bool = False,
    timeout: int = 45,
) -> dict[str, Any]:
    """manage_profile_basic.mjs に action, payload, isDryRun を注入して実行する."""
    if not MANAGE_SCRIPT_PATH.exists():
        raise RuntimeError(f"管理スクリプトが見つかりません: {MANAGE_SCRIPT_PATH}")

    # セッションオープン
    profile_path = resolve_profile_path(session)
    run_playwright_cmd([f"-s={session}", "open", TARGET_URL, f"--profile={profile_path}"])

    template_code = MANAGE_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = (
        template_code.replace("'__LEVTECH_ACTION__'", json.dumps(action))
        .replace("__LEVTECH_PAYLOAD__", json.dumps(payload or {}, ensure_ascii=False))
        .replace("__LEVTECH_DRY_RUN__", "true" if dry_run else "false")
    )

    tmp_script_path = LEVTECH_SCRIPTS_DIR / f".tmp_manage_basic_{action}.mjs"
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
        f"url: '{TARGET_URL}'",
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


def print_formatted_summary(data: dict[str, Any]) -> None:
    """基本情報サマリをコンソールに整形出力する."""
    d = data.get("data", data)
    edu = d.get("education") or {}
    lang = d.get("language") or {}

    print("\n========================================================")
    print(" レバテックダイレクト 基本情報サマリ")
    print(f" URL:  {TARGET_URL}")
    print(f" ID:   {d.get('displayId', '不明')}")
    print("========================================================\n")

    print(f"氏名:       {d.get('lastName', '')} {d.get('firstName', '')} ({d.get('kanaLastName', '')} {d.get('kanaFirstName', '')})")
    print(f"生年月日:   {d.get('birthday', '未設定')} ({d.get('genderLabel', '未設定')})")
    print(f"電話番号:   {d.get('phoneNumber', '未設定')} (連絡許可: {d.get('isAcceptedCallByHeadhunter')})")
    print(f"現住所:     {d.get('prefectureName', '')} {d.get('address', '')}".strip() or "現住所:     未設定")
    print(f"現在年収:   {d.get('currentAnnualIncome', '未設定')} 万円")
    print("-" * 56)
    print("【学歴】")
    print(f"学校区分:   {edu.get('schoolCategoryName', '未設定')}")
    print(f"学校名:     {edu.get('schoolName', '未設定')} ({edu.get('facultyDepartment', '')})")
    print(f"卒業年月:   {edu.get('graduationDate', '未設定')}")
    print("-" * 56)
    print("【語学・資格】")
    print(f"母国語:     {lang.get('nativeLanguageName', '未設定')}")
    print(f"TOEIC:      {lang.get('toeic', '未設定')}")
    print(f"保有資格:   {d.get('certification', '未設定').replace(chr(10), ', ') if d.get('certification') else '未設定'}")
    print("========================================================\n")


def save_profile_result(data: dict[str, Any], output_dir: Path, backup_only: bool = False) -> list[Path]:
    """基本情報データをJSONおよびMarkdownで永続化する."""
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    saved_files: list[Path] = []

    # 1. バックアップ保存
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = now.strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"basic_{ts}.json"
    backup_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    saved_files.append(backup_file)

    if backup_only:
        return saved_files

    # 2. 最新JSON保存
    latest_json = output_dir / "basic_profile.json"
    latest_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    saved_files.append(latest_json)

    # 3. 最新Markdown保存
    md_content = format_profile_markdown(data, now)
    latest_md = output_dir / "basic_profile.md"
    latest_md.write_text(md_content, encoding="utf-8")
    saved_files.append(latest_md)

    return saved_files


def extract_sync_payload_from_profile() -> dict[str, Any]:
    """profile/resume.md から基本情報の同期ペイロードを抽出する."""
    resume_path = PROJECT_ROOT / "profile" / "resume.md"
    if not resume_path.exists():
        raise FileNotFoundError(f"職務経歴書マスターが見つかりません: {resume_path}")

    content = resume_path.read_text(encoding="utf-8")
    payload: dict[str, Any] = {}

    # Frontmatter 解析
    import re
    fm_match = re.search(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if fm_match:
        fm_text = fm_match.group(1)
        try:
            import yaml
            fm = yaml.safe_load(fm_text) or {}
        except ImportError:
            # 簡易正規表現パース
            fm = {}
            for line in fm_text.splitlines():
                if ":" in line and not line.strip().startswith("-"):
                    k, v = line.split(":", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if v.isdigit():
                        fm[k] = int(v)
                    else:
                        fm[k] = v

        if "name" in fm:
            parts = str(fm["name"]).split()
            if len(parts) == 2:
                payload["lastName"] = parts[0]
                payload["firstName"] = parts[1]
        if "birth_date" in fm:
            payload["birthday"] = str(fm["birth_date"])
        if "current_annual_income" in fm:
            try:
                payload["currentAnnualIncome"] = int(fm["current_annual_income"]) // 10000
            except ValueError:
                pass
        if "toeic_score" in fm:
            try:
                payload["toeic"] = int(fm["toeic_score"])
            except ValueError:
                pass
        if "location" in fm:
            payload["prefectureId"] = str(fm["location"])
        if "certifications" in fm and isinstance(fm["certifications"], list):
            payload["certification"] = "\n".join(str(c) for c in fm["certifications"])
        elif "certifications" in fm:
            payload["certification"] = str(fm["certifications"])

    # 本文からの補完（学歴等）
    # 学歴: 2024年3月 東京大学 文学部 西洋古典学専修 卒業
    edu_match = re.search(r"(\d{4})年(\d{1,2})月\s+([^\s]+)\s+([^\n]+?)\s*卒業", content)
    if edu_match:
        payload["education"] = {
            "schoolCategoryId": 1,  # 大学
            "schoolName": edu_match.group(3),
            "facultyDepartment": edu_match.group(4),
            "graduationYear": int(edu_match.group(1)),
            "graduationMonth": int(edu_match.group(2)),
        }

    # 電話番号
    tel_match = re.search(r"TEL:\s*([\d\-]+)", content)
    if tel_match:
        payload["phoneNumber"] = tel_match.group(1).replace("-", "")

    # カナ氏名
    kana_match = re.search(r"（([ァ-ン]+)\s+([ァ-ン]+)）", content)
    if kana_match:
        payload["kanaLastName"] = kana_match.group(1)
        payload["kanaFirstName"] = kana_match.group(2)

    return payload


def print_diff(previous: dict[str, Any], updated: dict[str, Any]) -> None:
    """変更前後のJSON差分（unified diff）を表示する."""
    prev_str = json.dumps(previous, ensure_ascii=False, indent=2)
    next_str = json.dumps(updated, ensure_ascii=False, indent=2)

    diff = difflib.unified_diff(
        prev_str.splitlines(keepends=True),
        next_str.splitlines(keepends=True),
        fromfile="変更前 (現在登録内容)",
        tofile="変更後 (反映予定内容)",
        lineterm="",
    )
    diff_text = "".join(diff)
    if diff_text:
        print("\n--- 差分プレビュー (Unified Diff) ---")
        print(diff_text)
        print("-------------------------------------\n")
    else:
        print("\n[差分なし] 登録内容に変更はありません。\n")


def main() -> int:
    parser = create_base_parser(
        description="レバテックダイレクト マイページ基本情報（/mypage/profile/basic）閲覧・更新・同期スクリプト",
    )
    parser.add_argument(
        "--session",
        type=str,
        default="job-hunt",
        help="ブラウザプロファイルセッション名 (デフォルト: job-hunt)",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="実行サブコマンド")

    # fetch
    fetch_parser = subparsers.add_parser("fetch", help="現在の基本情報を取得・保存する")
    fetch_parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR), help="出力先ディレクトリ")

    # update
    update_parser = subparsers.add_parser("update", help="基本情報を更新する")
    update_parser.add_argument("--dry-run", action="store_true", help="保存を実行せず差分プレビューのみ表示")
    update_parser.add_argument("--last-name", type=str, help="姓 (漢字)")
    update_parser.add_argument("--first-name", type=str, help="名 (漢字)")
    update_parser.add_argument("--kana-last-name", type=str, help="セイ (カタカナ)")
    update_parser.add_argument("--kana-first-name", type=str, help="メイ (カタカナ)")
    update_parser.add_argument("--birthday", type=str, help="生年月日 (YYYY-MM-DD)")
    update_parser.add_argument("--gender", type=int, choices=[1, 2, 3], help="性別 (1:男性, 2:女性, 3:無回答)")
    update_parser.add_argument("--phone", type=str, help="電話番号 (ハイフンなし)")
    update_parser.add_argument("--accept-call", action=argparse.BooleanOptionalAction, help="エージェント電話連絡許可")
    update_parser.add_argument("--postal-code", type=str, help="郵便番号")
    update_parser.add_argument("--prefecture", type=str, help="都道府県名またはID (例: 東京都 または 1)")
    update_parser.add_argument("--address", type=str, help="都道府県以降の住所")
    update_parser.add_argument("--is-married", action=argparse.BooleanOptionalAction, help="配偶者有無")
    update_parser.add_argument("--annual-income", type=int, help="現在年収 (万円)")
    update_parser.add_argument("--school-category", type=str, help="学校区分 (例: 大学 または 1)")
    update_parser.add_argument("--school-name", type=str, help="学校名")
    update_parser.add_argument("--faculty", type=str, help="学部/学科/専攻")
    update_parser.add_argument("--graduation-year", type=int, help="卒業年 (西暦)")
    update_parser.add_argument("--graduation-month", type=int, help="卒業月 (1-12)")
    update_parser.add_argument("--education-other", type=str, help="その他学歴")
    update_parser.add_argument("--toeic", type=int, help="TOEICスコア")
    update_parser.add_argument("--toefl", type=int, help="TOEFLスコア")
    update_parser.add_argument("--certification", type=str, help="保有資格テキスト")
    update_parser.add_argument("--payload", type=str, help="JSON文字列による直接指定")
    update_parser.add_argument("--payload-file", type=str, help="JSONファイルによる直接指定")
    update_parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR), help="出力先ディレクトリ")

    # sync
    sync_parser = subparsers.add_parser("sync", help="profile/resume.md から基本情報を自動抽出し更新する")
    sync_parser.add_argument("--dry-run", action="store_true", help="保存を実行せず差分プレビューのみ表示")
    sync_parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR), help="出力先ディレクトリ")

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    # 認証ガード
    if not ensure_site_authenticated("levtech_direct", session=args.session, target_url=TARGET_URL, exit_on_fail=False):
        ctx.error("レバテックダイレクトの認証状態が確認できませんでした。")
        return 2

    subcmd = args.subcommand or "fetch"
    output_dir = Path(getattr(args, "output_dir", DEFAULT_OUTPUT_DIR))

    try:
        if subcmd == "fetch":
            ctx.log("[INFO] レバテックダイレクト 基本情報を取得中...")
            result = execute_manage_action(args.session, "fetch")
            saved_paths = save_profile_result(result, output_dir=output_dir)
            ctx.add_result_paths(saved_paths)

            return ctx.flush_outputs(
                summary_fn=lambda: print_formatted_summary(result),
                json_data=result,
            )

        elif subcmd in ("update", "sync"):
            is_dry_run = getattr(args, "dry_run", False)

            # 変更前の最新データを取得して自動バックアップ
            ctx.log("[INFO] 変更前自動バックアップ（最新プロフィール取得）を実行中...")
            prev_result = execute_manage_action(args.session, "fetch")
            backup_files = save_profile_result(prev_result, output_dir=output_dir, backup_only=True)
            for bp in backup_files:
                ctx.log(f"[安全ガード] 変更前バックアップを保存しました: {to_relative_path(bp)}")

            # ペイロード作成
            payload: dict[str, Any] = {}
            if subcmd == "sync":
                ctx.log("[INFO] profile/resume.md から基本情報を抽出中...")
                payload = extract_sync_payload_from_profile()
            else:
                if args.payload:
                    payload = json.loads(args.payload)
                elif args.payload_file:
                    payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
                else:
                    if args.last_name is not None:
                        payload["lastName"] = args.last_name
                    if args.first_name is not None:
                        payload["firstName"] = args.first_name
                    if args.kana_last_name is not None:
                        payload["kanaLastName"] = args.kana_last_name
                    if args.kana_first_name is not None:
                        payload["kanaFirstName"] = args.kana_first_name
                    if args.birthday is not None:
                        payload["birthday"] = args.birthday
                    if args.gender is not None:
                        payload["gender"] = args.gender
                    if args.phone is not None:
                        payload["phoneNumber"] = args.phone
                    if args.accept_call is not None:
                        payload["isAcceptedCallByHeadhunter"] = args.accept_call
                    if args.postal_code is not None:
                        payload["postalCode"] = args.postal_code
                    if args.prefecture is not None:
                        payload["prefectureId"] = args.prefecture
                    if args.address is not None:
                        payload["address"] = args.address
                    if args.is_married is not None:
                        payload["isMarried"] = args.is_married
                    if args.annual_income is not None:
                        payload["currentAnnualIncome"] = args.annual_income
                    if args.toeic is not None:
                        payload["toeic"] = args.toeic
                    if args.toefl is not None:
                        payload["toefl"] = args.toefl
                    if args.certification is not None:
                        payload["certification"] = args.certification

                    # 学歴
                    edu: dict[str, Any] = {}
                    if args.school_category is not None:
                        edu["schoolCategoryId"] = args.school_category
                    if args.school_name is not None:
                        edu["schoolName"] = args.school_name
                    if args.faculty is not None:
                        edu["facultyDepartment"] = args.faculty
                    if args.graduation_year is not None:
                        edu["graduationYear"] = args.graduation_year
                    if args.graduation_month is not None:
                        edu["graduationMonth"] = args.graduation_month
                    if args.education_other is not None:
                        edu["other"] = args.education_other
                    if edu:
                        payload["education"] = edu

            if not payload:
                ctx.error("更新する項目が指定されていません。")
                return 1

            ctx.log(f"[INFO] 基本情報の反映を実行中 (dry_run={is_dry_run})...")
            update_result = execute_manage_action(
                args.session,
                "update",
                payload=payload,
                dry_run=is_dry_run,
            )

            prev_data = prev_result.get("data", {})
            new_data = update_result.get("data", {})

            if is_dry_run:
                print_diff(prev_data, new_data)
                ctx.log("[INFO] --dry-run 指定のため保存は実行されませんでした。")
                return ctx.flush_outputs(
                    summary_fn=lambda: print_formatted_summary(update_result),
                    json_data=update_result,
                )
            else:
                saved_paths = save_profile_result(update_result, output_dir=output_dir)
                ctx.add_result_paths(saved_paths)
                ctx.log("[INFO] 基本情報の保存が完了しました。")
                return ctx.flush_outputs(
                    summary_fn=lambda: print_formatted_summary(update_result),
                    json_data=update_result,
                )

        else:
            ctx.error(f"未知のサブコマンド: {subcmd}")
            return 1

    except Exception as e:
        ctx.error(f"実行中エラー: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
