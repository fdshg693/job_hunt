"""YOUTRUST のプロフィール（自己紹介・居住地等）を閲覧・更新・同期する CLI.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
YOUTRUST のプロフィール設定画面（/settings/profile）における
基本情報、ビジネスネーム、居住地、公開範囲、自己紹介等の
閲覧・更新・自動バックアップ・SSOT（vault/profile/）同期を安全に実行します。

変更操作の実行前には必ず最新プロフィールの完全自動バックアップを取得し、
--dry-run フラグによる変更プレビュー（Unified Diff）と安全ガードを提供します。
エントリポイントスクリプト規約（.agents/rules/scripts-entrypoint.md）準拠。
"""

from __future__ import annotations

import argparse
import json
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
from scripts.common.profile_sync import load_site_text, print_profile_diff, save_profile_backup

YOUTRUST_SCRIPTS_DIR = Path(__file__).resolve().parent
MANAGE_SCRIPT_PATH = YOUTRUST_SCRIPTS_DIR / "manage_profile.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "youtrust" / "profile"
BACKUP_DIR = DEFAULT_OUTPUT_DIR / "backups"
TARGET_URL = "https://youtrust.jp/settings/profile"


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
        template_code.replace("'__YOUTRUST_ACTION__'", json.dumps(action))
        .replace("__YOUTRUST_PAYLOAD__", json.dumps(payload or {}, ensure_ascii=False))
        .replace("__YOUTRUST_DRY_RUN__", "true" if dry_run else "false")
    )

    tmp_script_path = YOUTRUST_SCRIPTS_DIR / f".tmp_manage_{action}.mjs"
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
    """YOUTRUSTのプロフィールデータをフロントマター付きMarkdownに整形する."""
    api_data = data.get("api") or {}
    dom_data = data.get("dom") or {}

    me = api_data.get("me") or {}
    session_user = api_data.get("sessionUser") or {}
    affiliations = api_data.get("affiliations") or []
    careers = api_data.get("careers") or []
    motivation = api_data.get("motivation") or {}
    qualifications = api_data.get("qualifications") or []
    awards = api_data.get("awards") or []
    links = api_data.get("links") or []

    user_id = me.get("id") or session_user.get("id", "")
    full_name = dom_data.get("name") or me.get("name") or ""
    business_name = dom_data.get("businessName") or me.get("business_name") or ""
    introduction = dom_data.get("introduction") or me.get("raw_introduction_content") or me.get("introduction_content") or ""
    location = dom_data.get("location") or ""
    location_detail = dom_data.get("locationDetail") or ""
    location_scope = dom_data.get("locationScope") or "only_friends"
    birthday_scope = dom_data.get("birthdayScope") or "friend"

    # スキル一覧
    skills = me.get("skills") or []
    skill_names = [s.get("name", "") for s in skills if s.get("name")]

    lines = [
        "---",
        "source: youtrust",
        "type: profile",
        f"updated_at: '{fetched_at.isoformat(timespec='seconds')}'",
        f"url: '{TARGET_URL}'",
        f"user_id: '{user_id}'",
        f"name: '{full_name}'",
        f"business_name: '{business_name}'",
        f"birthday_scope: '{birthday_scope}'",
        f"location: '{location}'",
        f"location_scope: '{location_scope}'",
        "---",
        "",
        f"# YOUTRUST 登録プロフィール ({full_name})",
        "",
        "## 基本情報",
        "",
        f"- **氏名**: {full_name}",
        f"- **ビジネスネーム**: {business_name or '未設定'}",
        f"- **生年月日公開範囲**: {'つながりまで公開' if birthday_scope == 'friend' else '非公開'}",
        f"- **居住地・場所**: {location or '未設定'} ({location_detail or '補足なし'})",
        f"- **場所公開範囲**: {'すべてのユーザー' if location_scope == 'all_users' else 'つながりまで'}",
        "",
        "## 現在の所属・ポジション",
        "",
    ]

    if affiliations:
        for aff in affiliations:
            label = aff.get("display_label") or aff.get("name") or ""
            lines.append(f"- {label}")
    else:
        lines.append("- （所属情報なし）")
    lines.append("")

    lines.append("## 保有スキル・経験")
    lines.append("")
    if skill_names:
        lines.append(", ".join(skill_names))
    else:
        lines.append("- （登録されたスキルはありません）")
    lines.append("")

    lines.append("## 転職・副業意欲")
    lines.append("")
    job_mot = motivation.get("job_change_motivation", "")
    side_mot = motivation.get("side_job_motivation", "")
    lines.append(f"- **転職意欲**: {job_mot or '未設定'}")
    lines.append(f"- **副業意欲**: {side_mot or '未設定'}")
    lines.append("")

    lines.append("## 自己紹介")
    lines.append("")
    lines.append("```text")
    lines.append(introduction.strip() if introduction else "（未登録）")
    lines.append("```")
    lines.append("")

    if careers:
        lines.append("## 経歴・職歴一覧")
        lines.append("")
        for c in careers:
            comp = c.get("company") or {}
            comp_name = comp.get("name") or "企業名非公開"
            lines.append(f"### {comp_name}")
            projects = c.get("projects") or []
            for p in projects:
                p_name = p.get("name") or "プロジェクト"
                cats = [cat.get("v3_category_name", "") for cat in p.get("career_job_categories", [])]
                cat_str = f" ({', '.join(cats)})" if cats else ""
                lines.append(f"- **{p_name}**{cat_str}")
                desc = p.get("description") or p.get("raw_description") or ""
                if desc:
                    lines.append(f"  {desc.strip()}")
            lines.append("")

    if qualifications:
        lines.append("## 資格")
        lines.append("")
        for q in qualifications:
            lines.append(f"- {q.get('name', '')}")
        lines.append("")

    if awards:
        lines.append("## 受賞歴")
        lines.append("")
        for a in awards:
            lines.append(f"- {a.get('name', '')}")
        lines.append("")

    if links:
        lines.append("## 関連リンク")
        lines.append("")
        for lk in links:
            lines.append(f"- [{lk.get('name', 'Link')}]({lk.get('url', '')})")
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
        backup_json = save_profile_backup(
            site="youtrust",
            section=backup_tag,
            data=data,
            backup_dir=BACKUP_DIR,
        )
        saved.append(backup_json)

        ts = now.strftime("%Y%m%d_%H%M%S")
        backup_md = BACKUP_DIR / f"{ts}_{backup_tag}.md"
        backup_md.write_text(format_profile_markdown(data, now), encoding="utf-8")
        saved.append(backup_md)
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


def backup_current_profile(session: str, action_name: str = "backup") -> list[Path]:
    """変更操作前に最新のプロフィールデータを自動バックアップする."""
    view_result = execute_manage_action(session, "view")
    if not view_result or not view_result.get("success"):
        raise RuntimeError("変更前自動バックアップ（最新プロフィール取得）に失敗したため、操作を中断します。")

    data = view_result.get("data") or {}
    saved_backups = save_profile_data(data, backup_tag=f"pre_{action_name}")
    return saved_backups


def generate_intro_from_profile() -> str:
    """vault/profile/sites/youtrust.md を読み込み、YOUTRUST向けの自己紹介文を取得する."""
    return load_site_text("youtrust")


def print_diff(previous: str, new: str, from_label: str = "現在登録内容", to_label: str = "反映予定内容") -> None:
    """テキスト差分（Unified Diff）を共通基盤の統一フォーマットで出力する."""
    print_profile_diff(
        before=previous,
        after=new,
        title="YOUTRUST プロフィール差分",
        from_label=from_label,
        to_label=to_label,
        stream=sys.stderr,
    )


# ----------------------------------------------------------------------
# ハンドラ関数
# ----------------------------------------------------------------------


def handle_show(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """プロフィールの閲覧・保存."""
    result = execute_manage_action(session, "show")
    data = result.get("data") or {}

    saved_paths = save_profile_data(data)
    ctx.add_result_paths(saved_paths)

    def summary_fn() -> None:
        dom = data.get("dom") or {}
        me = data.get("api", {}).get("me") or {}
        print("=== YOUTRUST 登録プロフィール ===")
        print(f"- 氏名: {dom.get('name') or me.get('name')}")
        print(f"- ビジネスネーム: {dom.get('businessName') or me.get('business_name') or '未設定'}")
        print(f"- 居住地: {dom.get('location') or '未設定'} ({dom.get('locationDetail') or '補足なし'})")
        print(f"- 自己紹介文字数: {len(dom.get('introduction', ''))} 文字")
        print(f"- 保存ファイル: {[to_relative_path(p) for p in saved_paths]}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=result)


def handle_backup(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """プロフィールの手動バックアップ保存."""
    result = execute_manage_action(session, "backup")
    data = result.get("data") or {}

    saved_paths = save_profile_data(data, backup_tag="manual")
    ctx.add_result_paths(saved_paths)

    def summary_fn() -> None:
        print("=== YOUTRUST プロフィールバックアップ保存完了 ===")
        for p in saved_paths:
            print(f"- {to_relative_path(p)}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=result)


def handle_update(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """プロフィールの更新."""
    payload: dict[str, Any] = {}

    if getattr(args, "name", None):
        payload["name"] = args.name
    if getattr(args, "business_name", None) is not None:
        payload["business_name"] = args.business_name
    if getattr(args, "location", None):
        payload["location"] = args.location
    if getattr(args, "location_detail", None) is not None:
        payload["location_detail"] = args.location_detail
    if getattr(args, "birthday_scope", None):
        payload["birthday_scope"] = args.birthday_scope
    if getattr(args, "location_scope", None):
        payload["location_scope"] = args.location_scope

    # 自己紹介
    if getattr(args, "intro_text", None):
        payload["introduction"] = args.intro_text
    elif getattr(args, "intro_file", None):
        file_path = Path(args.intro_file)
        if not file_path.exists():
            ctx.error(f"指定された自己紹介ファイルが見つかりません: {file_path}")
            return 1
        payload["introduction"] = file_path.read_text(encoding="utf-8")
    elif getattr(args, "from_profile", False):
        payload["introduction"] = generate_intro_from_profile()

    if not payload:
        ctx.error("更新する項目（--name, --business-name, --location, --intro-text, --from-profile 等）が指定されていません。")
        return 1

    dry_run = getattr(args, "dry_run", False)

    # 1. 安全ガード: 本番更新前の自動バックアップ
    if not dry_run:
        try:
            backup_files = backup_current_profile(session, action_name="update")
            ctx.add_result_paths(backup_files)
        except Exception as e:
            ctx.error(f"バックアップ失敗による中断: {e}")
            return 1

    # 2. アクション実行
    result = execute_manage_action(session, "update", payload=payload, dry_run=dry_run)

    prev = result.get("previous") or {}
    changes = result.get("changes") or {}

    # 3. Dry-Run プレビュー
    if dry_run:
        print("[DRY-RUN] YOUTRUST プロフィール更新プレビュー:", file=sys.stderr)
        for k, v in changes.items():
            prev_v = prev.get(k, "")
            if k == "introduction":
                print_diff(str(prev_v), str(v), from_label="現在自己紹介", to_label="更新予定自己紹介")
            else:
                print(f"  - {k}: '{prev_v}' -> '{v}'", file=sys.stderr)
        print("[INFO] --dry-run のためブラウザ上への保存は実行されていません。", file=sys.stderr)
        return ctx.flush_outputs(json_data=result)

    # 4. 反映後の最新データを保存
    if result.get("data"):
        updated_paths = save_profile_data(result["data"])
        ctx.add_result_paths(updated_paths)

    def summary_fn() -> None:
        print("=== YOUTRUST プロフィール更新完了 ===")
        for k, v in changes.items():
            prev_v = prev.get(k, "")
            if k == "introduction":
                print(f"- 自己紹介: {len(str(prev_v))} 文字 -> {len(str(v))} 文字")
                print_diff(str(prev_v), str(v))
            else:
                print(f"- {k}: '{prev_v}' -> '{v}'")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=result)


def handle_sync(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """SSOT（vault/profile/）から自己紹介等を生成して同期."""
    intro = generate_intro_from_profile()
    args.intro_text = intro
    return handle_update(args, session, ctx)


# ----------------------------------------------------------------------
# CLI 設定とメイン
# ----------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = create_base_parser(
        description="YOUTRUST プロフィールCRUD管理スクリプト（安全ガード・差分プレビュー・SSOT同期）",
        examples=[
            "uv run python scripts/youtrust/manage_profile.py --action show --summary",
            'uv run python scripts/youtrust/manage_profile.py --action update --intro-file "vault/profile/resume.md" --dry-run',
            "uv run python scripts/youtrust/manage_profile.py --action sync --from-profile --dry-run  # vault/profile/ から同期",
        ],
        related=[
            "scripts/youtrust/manage_background.py: 職歴・学歴の更新はこちら",
        ],
    )

    parser.add_argument(
        "--session",
        default="job-hunt",
        help="ブラウザプロファイルセッション名 (デフォルト: job-hunt)",
    )

    parser.add_argument(
        "--action",
        choices=["show", "view", "backup", "update", "sync"],
        default="show",
        help="実行アクション (show: 閲覧・保存, backup: バックアップ, update: 項目更新, sync: SSOT同期)",
    )

    # 更新オプション
    parser.add_argument("--name", help="氏名")
    parser.add_argument("--business-name", help="ビジネスネーム")
    parser.add_argument("--location", help="居住地・場所（例: 東京都）")
    parser.add_argument("--location-detail", help="場所の補足")
    parser.add_argument("--birthday-scope", choices=["friend", "private"], help="生年月日公開範囲")
    parser.add_argument("--location-scope", choices=["all", "only_friends"], help="場所公開範囲")

    # 自己紹介更新
    parser.add_argument("--intro-text", help="自己紹介テキスト（直接指定）")
    parser.add_argument("--intro-file", help="自己紹介テキストファイルパス")
    parser.add_argument("--from-profile", action="store_true", help="SSOT (vault/profile/) から自己紹介を自動生成")

    # 安全ガード
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="更新を実際に行わず差分（Unified Diff）のみをプレビュー表示する",
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
        elif action == "update":
            return handle_update(args, session, ctx)
        elif action == "sync":
            return handle_sync(args, session, ctx)
        else:
            ctx.error(f"未知のアクションです: {action}")
            return 1


if __name__ == "__main__":
    sys.exit(main())
