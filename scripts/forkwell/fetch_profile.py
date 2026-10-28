"""Forkwell のプロフィール（キャリア・希望・スキル）を取得して保存する CLI.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
Forkwell Jobsのログイン状態確認・未ログイン時の通知待機ハンドオフ・ダッシュボード
（/dashboard, /dashboard/preferences, /dashboard/skills）からの
構造化プロフィールデータ（キャリア・自己紹介・希望条件・経験技術・資格等）の抽出、
フロントマター付きMarkdownおよびJSON形式での永続化・事前バックアップ保存を実行します。
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
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
from scripts.common.cli import EntrypointContext, create_base_parser, to_relative_path

FORKWELL_SCRIPTS_DIR = Path(__file__).resolve().parent
FETCH_SCRIPT_PATH = FORKWELL_SCRIPTS_DIR / "fetch_profile.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "forkwell" / "profile"
BACKUPS_DIR = DEFAULT_OUTPUT_DIR / "backups"
TARGET_URL = "https://jobs.forkwell.com/dashboard"


def generate_profile_markdown(data: dict[str, Any], now: datetime) -> str:
    """取得したプロフィールデータをフロントマター付きMarkdownに整形する."""
    user_info = data.get("userInfo") or {}
    meta = user_info.get("meta") or {}
    forkwell_user = meta.get("forkwell", {}).get("user", {})
    user_id = forkwell_user.get("id")
    scout_user_id = forkwell_user.get("scout_user_id")

    career = data.get("career") or {}
    preferences = data.get("preferences") or {}
    skills = data.get("skills") or {}

    fetched_at_str = now.isoformat(timespec="seconds")
    fetched_at_display = now.strftime("%Y-%m-%d %H:%M:%S")

    # フロントマター用データ抽出
    fm_lines = [
        "---",
        "source: forkwell",
        "type: profile",
        f"fetched_at: '{fetched_at_str}'",
        f"url: {TARGET_URL}",
    ]
    if user_id:
        fm_lines.append(f"user_id: {user_id}")
    if scout_user_id:
        fm_lines.append(f"scout_user_id: {scout_user_id}")

    desired_role = preferences.get("desiredRole", "")
    if desired_role:
        clean_role = desired_role.replace("'", "''")
        fm_lines.append(f"desired_role: '{clean_role}'")

    desired_skills = preferences.get("desiredSkills", [])
    if desired_skills:
        skills_yaml = ", ".join(f"'{s}'" for s in desired_skills)
        fm_lines.append(f"desired_skills: [{skills_yaml}]")

    salary = preferences.get("salary", "")
    if salary:
        clean_sal = salary.replace("'", "''")
        fm_lines.append(f"salary_preference: '{clean_sal}'")

    certs = skills.get("certifications", [])
    if certs:
        certs_yaml = ", ".join(f"'{c}'" for c in certs)
        fm_lines.append(f"certifications: [{certs_yaml}]")

    langs = skills.get("languages", [])
    if langs:
        langs_yaml = ", ".join(f"'{lang}'" for lang in langs)
        fm_lines.append(f"languages: [{langs_yaml}]")

    fm_lines.append("---")
    fm_lines.append("")

    # 本文
    body_lines: list[str] = [
        "# Forkwell プロフィール（キャリア・やりたいこと・スキル）",
        "",
        f"- **取得日時**: {fetched_at_display}",
        f"- **ダッシュボードURL**: {TARGET_URL}",
    ]
    if user_id:
        body_lines.append(f"- **ユーザーID**: {user_id} (スカウトID: {scout_user_id})")
    if career.get("scoutStatus"):
        body_lines.append(f"- **スカウト設定**: {career.get('scoutStatus')}")
    if career.get("jobIntent"):
        body_lines.append(f"- **転職意欲**: {career.get('jobIntent')}")
    body_lines.append("")

    # やりたいこと・希望
    body_lines.append("## やりたいこと・希望")
    body_lines.append("")
    if desired_role:
        body_lines.append(f"- **目指したいこと**: {desired_role}")
    if desired_skills:
        body_lines.append(f"- **希望技術**: {', '.join(desired_skills)}")
    if preferences.get("conditions"):
        body_lines.append(f"- **希望条件**: {preferences.get('conditions')}")
    if preferences.get("otherPreferences"):
        body_lines.append(f"- **その他の希望条件**: {preferences.get('otherPreferences')}")
    if salary:
        body_lines.append(f"- **年収**: {salary}")
    body_lines.append("")

    # スキル
    body_lines.append("## スキル・経験技術")
    body_lines.append("")
    exp_skills = skills.get("experiencedSkills") or {}
    l3 = exp_skills.get("level3", [])
    l2 = exp_skills.get("level2", [])
    l1 = exp_skills.get("level1", [])
    if l3:
        body_lines.append(f"- **Lv. 3**: {', '.join(l3)}")
    if l2:
        body_lines.append(f"- **Lv. 2**: {', '.join(l2)}")
    if l1:
        body_lines.append(f"- **Lv. 1**: {', '.join(l1)}")
    if not (l3 or l2 or l1) and exp_skills.get("raw"):
        body_lines.append(f"- **経験技術（原文）**: {exp_skills.get('raw')}")

    if certs:
        body_lines.append("")
        body_lines.append("### 資格")
        for c in certs:
            body_lines.append(f"- {c}")

    if langs:
        body_lines.append("")
        body_lines.append("### 語学力")
        for lang in langs:
            body_lines.append(f"- {lang}")
    body_lines.append("")

    # 自己紹介
    bio = career.get("bio", "").strip()
    if bio:
        body_lines.append("## 自己紹介")
        body_lines.append("")
        body_lines.append(bio)
        body_lines.append("")

    # 職歴
    companies = career.get("companies", [])
    if companies:
        body_lines.append("## 職歴")
        body_lines.append("")
        for idx, comp in enumerate(companies, start=1):
            c_name = comp.get("companyName", "企業名未設定")
            c_period = comp.get("period", "")
            body_lines.append(f"### {idx}. {c_name} ({c_period})")
            body_lines.append("")

            projects = comp.get("projects", [])
            if projects:
                for p_idx, proj in enumerate(projects, start=1):
                    p_period = proj.get("period")
                    p_role = proj.get("role")
                    p_header = f"#### プロジェクト {p_idx}"
                    if p_role:
                        p_header += f": {p_role}"
                    if p_period:
                        p_header += f" ({p_period})"
                    body_lines.append(p_header)
                    body_lines.append("")
                    p_desc = proj.get("description", "").strip()
                    if p_desc:
                        body_lines.append(p_desc)
                        body_lines.append("")
            else:
                raw_text = comp.get("rawText", "").strip()
                if raw_text:
                    body_lines.append(raw_text)
                    body_lines.append("")
        body_lines.append("")
    elif career.get("workHistories"):
        body_lines.append("## 職歴")
        body_lines.append("")
        for wh in career.get("workHistories"):
            text = wh.get("text") or wh.get("rawText") if isinstance(wh, dict) else str(wh)
            if text:
                body_lines.append(f"- {text}")
        body_lines.append("")

    edus = career.get("educations", [])
    if edus:
        body_lines.append("## 学歴")
        body_lines.append("")
        for e in edus:
            body_lines.append(f"- {e}")
        body_lines.append("")

    other_exp = career.get("otherExperiences")
    if other_exp:
        body_lines.append("## その他の経験")
        body_lines.append("")
        body_lines.append(other_exp)
        body_lines.append("")

    work_cond = career.get("workConditions")
    if work_cond:
        body_lines.append("## 国内就労条件")
        body_lines.append("")
        body_lines.append(work_cond)
        body_lines.append("")

    return "\n".join(fm_lines) + "\n".join(body_lines)


def print_formatted_summary(data: dict[str, Any]) -> None:
    """プロフィールのサマリをコンソールに整形表示する."""
    career = data.get("career") or {}
    preferences = data.get("preferences") or {}
    skills = data.get("skills") or {}
    user_info = data.get("userInfo") or {}
    forkwell_user = user_info.get("meta", {}).get("forkwell", {}).get("user", {})

    print("\n========================================================")
    print(" Forkwell プロフィール（キャリア・やりたいこと・スキル）サマリ")
    print("========================================================\n")

    if forkwell_user.get("id"):
        print(f"ユーザーID:       {forkwell_user.get('id')} (スカウトID: {forkwell_user.get('scout_user_id')})")
    print(f"スカウト設定:     {career.get('scoutStatus', '未設定')}")
    print(f"転職意欲:         {career.get('jobIntent', '未設定')}")

    if preferences.get("desiredRole"):
        print(f"\n目指したいこと:   {preferences.get('desiredRole')}")
    if preferences.get("desiredSkills"):
        print(f"希望技術:         {', '.join(preferences.get('desiredSkills'))}")
    if preferences.get("salary"):
        print(f"年収条件:         {preferences.get('salary')}")
    if preferences.get("conditions"):
        print(f"希望条件:         {preferences.get('conditions')}")

    exp_skills = skills.get("experiencedSkills") or {}
    l3 = exp_skills.get("level3", [])
    l2 = exp_skills.get("level2", [])
    l1 = exp_skills.get("level1", [])
    if l3 or l2 or l1:
        print("\n経験技術:")
        if l3:
            print(f"  Lv. 3: {', '.join(l3)}")
        if l2:
            print(f"  Lv. 2: {', '.join(l2)}")
        if l1:
            print(f"  Lv. 1: {', '.join(l1)}")

    certs = skills.get("certifications", [])
    if certs:
        print(f"\n保有資格:         {', '.join(certs)}")

    langs = skills.get("languages", [])
    if langs:
        print(f"語学力:           {', '.join(langs)}")

    companies = career.get("companies", [])
    if companies:
        print(f"\n職歴:             {len(companies)} 社")
        for idx, comp in enumerate(companies, start=1):
            c_name = comp.get("companyName", "企業名未設定")
            c_period = comp.get("period", "")
            projs = comp.get("projects", [])
            print(f"  [{idx}] {c_name} ({c_period}) - プロジェクト数: {len(projs)}")

    bio = career.get("bio", "").strip()
    if bio:
        print(f"\n自己紹介 ({len(bio)} 文字):")
        lines = [line for line in bio.splitlines() if line.strip()][:4]
        for line in lines:
            print(f"  {line}")
        if len(bio.splitlines()) > 4:
            print("  ...")

    print("-" * 56)


def save_profile_result(
    data: dict[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    backup_only: bool = False,
    now: datetime | None = None,
) -> list[Path]:
    """プロフィールデータをMarkdownとJSONで永続化・バックアップ保存する."""
    if now is None:
        now = datetime.now()

    output_dir.mkdir(parents=True, exist_ok=True)
    backups_dir = output_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    date_str = now.strftime("%Y-%m-%d")
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")

    saved_files: list[Path] = []

    # 1. タイムスタンプ付きバックアップJSON（常に作成）
    backup_json = backups_dir / f"backup_{timestamp_str}.json"
    json_payload = {
        "source": "forkwell",
        "type": "profile",
        "fetched_at": now.isoformat(timespec="seconds"),
        "url": TARGET_URL,
        **data,
    }
    json_str = json.dumps(json_payload, ensure_ascii=False, indent=2)
    backup_json.write_text(json_str, encoding="utf-8")
    saved_files.append(backup_json)

    if backup_only:
        return saved_files

    # 2. 日付別および最新ファイル
    dated_md = output_dir / f"{date_str}.md"
    dated_json = output_dir / f"{date_str}.json"
    latest_md = output_dir / "profile.md"
    latest_json = output_dir / "profile.json"

    md_content = generate_profile_markdown(data, now)
    dated_md.write_text(md_content, encoding="utf-8")
    dated_json.write_text(json_str, encoding="utf-8")
    shutil.copyfile(dated_md, latest_md)
    shutil.copyfile(dated_json, latest_json)

    saved_files.extend([dated_md, dated_json, latest_md, latest_json])
    return saved_files


def main() -> None:
    """CLIエントリポイント."""
    parser = create_base_parser(
        description="Forkwellの共通プロファイルを用いて認証チェックを行い、ダッシュボードからプロフィールデータを取得・永続化・バックアップ保存します。",
        examples=[
            "uv run python scripts/forkwell/fetch_profile.py ",
            "uv run python scripts/forkwell/fetch_profile.py --summary  # 取得内容の要約も表示",
        ],
        related=[
            "scripts/forkwell/manage_profile.py: 次に使う（自己紹介・やりたいこと等を更新）",
            "scripts/forkwell/manage_work_history.py: 次に使う（職歴・プロジェクトを更新）",
        ],
    )
    parser.add_argument(
        "--session",
        default="job-hunt",
        help="Playwright CLIセッション名（デフォルト: job-hunt）",
    )
    parser.add_argument(
        "--profile-path",
        help="ブラウザプロファイルディレクトリのパス（省略時は自動解決）",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="ブラウザウィンドウを表示して実行する（デバッグ用）",
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
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"結果出力先ディレクトリ（デフォルト: {DEFAULT_OUTPUT_DIR}）",
    )
    parser.add_argument(
        "--backup-only",
        action="store_true",
        help="backups/ 配下へのタイムスタンプ付きバックアップ保存のみ行い、profile.md等の上書きをスキップする",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="ファイルへの保存を行わず画面表示のみ行う",
    )

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    if not FETCH_SCRIPT_PATH.exists():
        ctx.error(f"必須スクリプトが見つかりません: {FETCH_SCRIPT_PATH}")
        sys.exit(1)

    profile_dir = resolve_profile_path(args.session, args.profile_path)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. 共通認証エンジンによるブラウザ起動・認証確認・手動待機ハンドオフ
        ensure_site_authenticated(
            site="forkwell",
            session=args.session,
            target_url=TARGET_URL,
            headed=args.headed,
            timeout=args.timeout,
            no_notify=args.no_notify,
            profile_dir=profile_dir,
            exit_on_fail=True,
        )

        # 2. ダッシュボード画面からプロフィールデータ抽出
        fetch_result = run_code_script(args.session, FETCH_SCRIPT_PATH, timeout=60)
        if not fetch_result or not fetch_result.get("success"):
            ctx.error("プロフィール画面への遷移またはプロフィールデータ取得に失敗しました。")
            sys.exit(1)

        update_profile_last_used(args.session)

        # 3. ファイル保存
        saved_files: list[Path] = []
        if not args.no_save:
            saved_files = save_profile_result(
                fetch_result,
                output_dir=args.output_dir,
                backup_only=args.backup_only,
            )
            ctx.add_result_paths(saved_files)

        def summary_fn() -> None:
            print_formatted_summary(fetch_result)
            if saved_files:
                ctx.log("\n[保存完了ファイル一覧]")
                for sf in saved_files:
                    ctx.log(f"  - {to_relative_path(sf)}")

        sys.exit(ctx.flush_outputs(summary_fn=summary_fn, json_data=fetch_result))

    finally:
        if not args.keep_open:
            run_playwright_cmd([f"-s={args.session}", "close"], timeout=10)


if __name__ == "__main__":
    main()
