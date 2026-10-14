"""Wellfound（wellfound.com）プロフィール CRUD管理・同期スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
Wellfound のプロフィール編集画面（/profile/edit）における
基本情報、Bio、ソーシャルリンク、実績、保有スキル、職歴等の
閲覧・更新・自動バックアップを安全に実行します。

変更操作の実行前には必ず最新プロフィールの完全自動バックアップを取得し、
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

# プロジェクトルートパス (scripts/wellfound/ の2階層上)
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

WELLFOUND_SCRIPTS_DIR = Path(__file__).resolve().parent
MANAGE_SCRIPT_PATH = WELLFOUND_SCRIPTS_DIR / "manage_profile.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "wellfound" / "profile"
BACKUP_DIR = DEFAULT_OUTPUT_DIR / "backups"
TARGET_URL = "https://wellfound.com/profile/edit"


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
        template_code.replace("__WELLFOUND_ACTION__", json.dumps(action))
        .replace("__WELLFOUND_PAYLOAD__", json.dumps(payload or {}, ensure_ascii=False))
        .replace("__WELLFOUND_DRY_RUN__", "true" if dry_run else "false")
    )

    tmp_script_path = WELLFOUND_SCRIPTS_DIR / f".tmp_manage_{action}.mjs"
    tmp_script_path.write_text(run_code, encoding="utf-8")

    try:
        code, stdout, stderr = run_playwright_cmd(
            [f"-s={session}", "run-code", f"--filename={tmp_script_path}", "--raw"],
            timeout=timeout,
        )
        if code != 0 or not stdout.strip():
            print(f"[DEBUG EXEC] code={code}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}", file=sys.stderr)
            raise RuntimeError(f"Playwrightスクリプトの実行に失敗しました ({action}): {stderr.strip() or stdout.strip()}")

        try:
            result = json.loads(stdout.strip())
        except Exception:
            lines = stdout.strip().splitlines()
            result = None
            for l in reversed(lines):
                try:
                    result = json.loads(l)
                    break
                except Exception:
                    pass
            if not result:
                print(f"[DEBUG EXEC JSON FAILED] STDOUT:\n{stdout}", file=sys.stderr)
                raise RuntimeError(f"PlaywrightスクリプトのJSONパースに失敗しました: {stdout}")

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
    """Wellfoundの構造化プロフィールデータをフロントマター付きMarkdownに整形する."""
    candidate_id = data.get("candidateId") or ""
    name = data.get("name") or ""
    email = data.get("email") or ""
    bio = data.get("bio") or ""
    primary_roles = data.get("primaryRole") or []
    years_exp = data.get("yearsExperienceInPrimaryRole")
    location = data.get("location") or ""
    skills = data.get("skills") or []
    experiences = data.get("experiences") or []
    education = data.get("education") or []
    socials = data.get("socials") or {}
    what_ive_built = data.get("whatIveBuilt") or ""
    resume_url = data.get("resumeUrl") or ""
    preferences = data.get("preferences") or {}

    role_str = ", ".join(primary_roles) if isinstance(primary_roles, list) else str(primary_roles)

    lines = [
        "---",
        "source: wellfound",
        "type: profile",
        f"updated_at: '{fetched_at.isoformat(timespec='seconds')}'",
        f"url: '{TARGET_URL}'",
        f"candidate_id: '{candidate_id}'",
        f"name: '{name}'",
        f"email: '{email}'",
        f"location: '{location}'",
        f"primary_role: '{role_str}'",
        "---",
        "",
        f"# Wellfound 登録プロフィール ({name or 'ユーザー'})",
        "",
        "## 基本情報",
        "",
        f"- **氏名**: {name or '未設定'}",
        f"- **メールアドレス**: {email or '未設定'}",
        f"- **居住地**: {location or '未設定'}",
        f"- **主職種**: {role_str or '未設定'} ({years_exp}年)" if years_exp is not None else f"- **主職種**: {role_str or '未設定'}",
        f"- **レジュメURL**: {resume_url or '未登録'}",
        "",
        "## 自己紹介 (Bio)",
        "",
        "> " + (bio.replace("\n", "\n> ") if bio else "（未記入）"),
        "",
        "## 実績・成果 (What I've Built)",
        "",
        "```text",
        what_ive_built.strip() if what_ive_built else "（未記入）",
        "```",
        "",
        "## ソーシャルリンク",
        "",
        f"- **LinkedIn**: {socials.get('linkedinUrl') or '未設定'}",
        f"- **GitHub**: {socials.get('githubUrl') or '未設定'}",
        f"- **X / Twitter**: {socials.get('twitterUrl') or '未設定'}",
        f"- **個人サイト**: {socials.get('onlineBioUrl') or '未設定'}",
        "",
        "## 保有スキル",
        "",
    ]

    if skills:
        skill_names = [s.get("name") for s in skills if s.get("name")]
        lines.append(", ".join(skill_names))
    else:
        lines.append("- （登録されたスキルはありません）")
    lines.append("")

    lines.append("## 職歴 (Experience)")
    lines.append("")
    if experiences:
        for exp in experiences:
            comp = exp.get("company") or {}
            comp_name = comp.get("name") or "企業名非公開"
            title = exp.get("title") or "役職未設定"
            start_m = exp.get("startedAtMonth")
            start_y = exp.get("startedAtYear")
            start_str = f"{start_y}年{start_m}月" if start_y and start_m else (f"{start_y}年" if start_y else "")

            if exp.get("current"):
                period_str = f"{start_str} 〜 現在" if start_str else "在籍中"
            else:
                end_m = exp.get("endedAtMonth")
                end_y = exp.get("endedAtYear")
                end_str = f"{end_y}年{end_m}月" if end_y and end_m else (f"{end_y}年" if end_y else "")
                period_str = f"{start_str} 〜 {end_str}" if start_str or end_str else "期間不明"

            lines.append(f"### {comp_name} - {title}")
            lines.append(f"- **期間**: {period_str}")
            desc = exp.get("description") or ""
            if desc:
                lines.append(f"- **職務内容**:\n  {desc.strip()}")
            lines.append("")
    else:
        lines.append("- （登録された職歴はありません）")
        lines.append("")

    lines.append("## 最終学歴 (Education)")
    lines.append("")
    if education:
        for edu in education:
            c_name = edu.get("collegeName") or "学校名未設定"
            degree = edu.get("degree") or "学位未設定"
            grad_y = edu.get("graduationYear")
            grad_str = f" ({grad_y}年卒業)" if grad_y else ""
            lines.append(f"- **{c_name}**: {degree}{grad_str}")
        lines.append("")
    else:
        lines.append("- （登録された学歴はありません）")
        lines.append("")

    lines.append("## 希望条件 (Preferences)")
    lines.append("")
    sal = preferences.get("desiredSalary")
    curr = preferences.get("desiredSalaryCurrency") or "USD"
    if sal:
        lines.append(f"- **希望年収**: {sal:,} {curr}")
    rem = preferences.get("remotePreference")
    if rem is not None:
        lines.append(f"- **リモート勤務希望**: {'希望する' if rem else '希望しない'}")
    locs = preferences.get("interestedLocations") or []
    if locs:
        lines.append(f"- **希望勤務地**: {', '.join(locs)}")
    role_tags = preferences.get("roleTags") or []
    if role_tags:
        lines.append(f"- **希望職種タグ**: {', '.join(role_tags)}")
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
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = now.strftime("%Y%m%d_%H%M%S")
        backup_json = BACKUP_DIR / f"{ts}_{backup_tag}.json"
        with open(backup_json, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        saved.append(backup_json)

        backup_md = BACKUP_DIR / f"{ts}_{backup_tag}.md"
        md_content = format_profile_markdown(data, now)
        backup_md.write_text(md_content, encoding="utf-8")
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


def print_unified_diff(title: str, old_val: str, new_val: str) -> None:
    """変更前後の差分をコンソール（stderr）に表示する."""
    old_lines = (old_val or "").splitlines(keepends=True)
    new_lines = (new_val or "").splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile="current",
        tofile="proposed",
        lineterm="",
    )
    diff_text = "\n".join(diff)
    print(f"\n--- 差分プレビュー: {title} ---", file=sys.stderr)
    if diff_text.strip():
        print(diff_text, file=sys.stderr)
    else:
        print("（変更差分はありません）", file=sys.stderr)
    print("----------------------------------------\n", file=sys.stderr)


def backup_current_profile(session: str, output_dir: Path, action_name: str) -> dict[str, Any]:
    """変更前の完全自動バックアップを取得する."""
    print("[Wellfound] 更新前の最新プロフィールを取得してバックアップを保存します...", file=sys.stderr)
    view_res = execute_manage_action(session, action="view")
    if not view_res.get("success"):
        raise RuntimeError("変更前自動バックアップに失敗したため、操作を中断します。")
    current_profile = view_res.get("data") or {}
    backup_paths = save_profile_data(current_profile, output_dir=output_dir, backup_tag=f"pre_{action_name}")
    for bp in backup_paths:
        print(f"[安全ガード] 変更前バックアップを保存しました: {to_relative_path(bp)}", file=sys.stderr)
    return current_profile


def handle_view(args: argparse.Namespace, ctx: EntrypointContext) -> int:
    """プロフィール情報の閲覧・取得."""
    print("[Wellfound] プロフィールデータを抽出しています...", file=sys.stderr)
    res = execute_manage_action(args.session, action="view")
    profile_data = res.get("data") or {}

    saved_paths = save_profile_data(profile_data, output_dir=args.output_dir)
    ctx.add_result_paths(saved_paths)

    def summary_fn() -> None:
        print("=== Wellfound プロフィール情報取得完了 ===")
        print(f"- 氏名: {profile_data.get('name') or '未設定'}")
        print(f"- メール: {profile_data.get('email') or '未設定'}")
        print(f"- 主職種: {', '.join(profile_data.get('primaryRole') or [])}")
        print(f"- スキル数: {len(profile_data.get('skills') or [])}")
        print(f"- 職歴数: {len(profile_data.get('experiences') or [])}")
        print(f"- 保存先: {to_relative_path(saved_paths[0])}, {to_relative_path(saved_paths[1])}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=profile_data if args.json else None)


def handle_update_bio(args: argparse.Namespace, ctx: EntrypointContext) -> int:
    """自己紹介 (Bio) の更新."""
    if args.bio is None:
        ctx.error("--bio オプションで設定する自己紹介文を指定してください。")
        return 1

    new_bio = args.bio.strip()
    if len(new_bio) > 160:
        ctx.warn(f"Bioが160文字を超えています ({len(new_bio)}文字)。160文字に切り詰めます。")
        new_bio = new_bio[:160]

    current_profile = backup_current_profile(args.session, args.output_dir, "update_bio")
    old_bio = current_profile.get("bio") or ""
    print_unified_diff("自己紹介 (Bio)", old_bio, new_bio)

    if args.dry_run:
        def dry_summary() -> None:
            print("=== Wellfound [dry-run] 差分プレビュー ===")
            print(f"- 反映予定 Bio ({len(new_bio)}文字): {new_bio}")
            print("- 実際の更新は行われませんでした。")

        return ctx.flush_outputs(summary_fn=dry_summary, json_data={"dry_run": True, "new_bio": new_bio})

    print("[Wellfound] 自己紹介文を更新しています...", file=sys.stderr)
    update_res = execute_manage_action(
        args.session,
        action="update_bio",
        payload={"bio": new_bio},
        dry_run=False,
    )
    updated_profile = update_res.get("data", {}).get("profileData") or {}
    saved_paths = save_profile_data(updated_profile, output_dir=args.output_dir)
    ctx.add_result_paths(saved_paths)

    def summary_fn() -> None:
        print("=== Wellfound 自己紹介文 更新完了 ===")
        print(f"- 更新後 Bio: {updated_profile.get('bio')}")
        print(f"- 保存先: {to_relative_path(saved_paths[0])}, {to_relative_path(saved_paths[1])}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=updated_profile if args.json else None)


def handle_update_socials(args: argparse.Namespace, ctx: EntrypointContext) -> int:
    """ソーシャルリンクの更新."""
    payload: dict[str, str] = {}
    if args.linkedin is not None:
        payload["linkedinUrl"] = args.linkedin.strip()
    if args.github is not None:
        payload["githubUrl"] = args.github.strip()
    if args.twitter is not None:
        payload["twitterUrl"] = args.twitter.strip()
    if args.website is not None:
        payload["onlineBioUrl"] = args.website.strip()

    if not payload:
        ctx.error("更新するソーシャルリンク (--linkedin, --github, --twitter, --website) を指定してください。")
        return 1

    current_profile = backup_current_profile(args.session, args.output_dir, "update_socials")
    old_socials = current_profile.get("socials") or {}
    for k, new_v in payload.items():
        old_v = old_socials.get(k) or ""
        print_unified_diff(f"ソーシャルリンク: {k}", old_v, new_v)

    if args.dry_run:
        def dry_summary() -> None:
            print("=== Wellfound [dry-run] ソーシャルリンク差分プレビュー ===")
            for k, v in payload.items():
                print(f"- 反映予定 {k}: {v}")
            print("- 実際の更新は行われませんでした。")

        return ctx.flush_outputs(summary_fn=dry_summary, json_data={"dry_run": True, "payload": payload})

    print("[Wellfound] ソーシャルリンクを更新しています...", file=sys.stderr)
    update_res = execute_manage_action(
        args.session,
        action="update_socials",
        payload=payload,
        dry_run=False,
    )
    updated_profile = update_res.get("data", {}).get("profileData") or {}
    saved_paths = save_profile_data(updated_profile, output_dir=args.output_dir)
    ctx.add_result_paths(saved_paths)

    def summary_fn() -> None:
        print("=== Wellfound ソーシャルリンク 更新完了 ===")
        print(f"- 保存先: {to_relative_path(saved_paths[0])}, {to_relative_path(saved_paths[1])}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=updated_profile if args.json else None)


def handle_update_achievements(args: argparse.Namespace, ctx: EntrypointContext) -> int:
    """実績・成果 (What I've built) の更新."""
    if args.achievements is None:
        ctx.error("--achievements オプションで設定する実績・成果文を指定してください。")
        return 1

    new_ach = args.achievements.strip()
    if len(new_ach) > 1000:
        ctx.warn(f"実績文が1000文字を超えています ({len(new_ach)}文字)。1000文字に切り詰めます。")
        new_ach = new_ach[:1000]

    current_profile = backup_current_profile(args.session, args.output_dir, "update_achievements")
    old_ach = current_profile.get("whatIveBuilt") or ""
    print_unified_diff("実績・成果 (What I've built)", old_ach, new_ach)

    if args.dry_run:
        def dry_summary() -> None:
            print("=== Wellfound [dry-run] 実績・成果 差分プレビュー ===")
            print(f"- 反映予定 実績文 ({len(new_ach)}文字): {new_ach[:100]}...")
            print("- 実際の更新は行われませんでした。")

        return ctx.flush_outputs(summary_fn=dry_summary, json_data={"dry_run": True, "new_achievements": new_ach})

    print("[Wellfound] 実績・成果を更新しています...", file=sys.stderr)
    update_res = execute_manage_action(
        args.session,
        action="update_achievements",
        payload={"whatIveBuilt": new_ach},
        dry_run=False,
    )
    updated_profile = update_res.get("data", {}).get("profileData") or {}
    saved_paths = save_profile_data(updated_profile, output_dir=args.output_dir)
    ctx.add_result_paths(saved_paths)

    def summary_fn() -> None:
        print("=== Wellfound 実績・成果 更新完了 ===")
        print(f"- 保存先: {to_relative_path(saved_paths[0])}, {to_relative_path(saved_paths[1])}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=updated_profile if args.json else None)


def handle_update_experience(args: argparse.Namespace, ctx: EntrypointContext) -> int:
    """既存職歴の更新（終了日設定・在籍フラグ解除等）."""
    if not args.company_name:
        ctx.error("--company-name オプションで更新対象の企業名を指定してください。")
        return 1

    payload: dict[str, Any] = {
        "companyName": args.company_name.strip(),
    }
    if args.ended_at:
        payload["endedAt"] = args.ended_at.strip()
    if args.current is not None:
        payload["current"] = args.current
    if args.role_title:
        payload["title"] = args.role_title.strip()
    if args.description:
        payload["description"] = args.description.strip()

    current_profile = backup_current_profile(args.session, args.output_dir, "update_experience")
    print(f"\n--- 職歴更新プレビュー: {args.company_name} ---", file=sys.stderr)
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
    print("----------------------------------------\n", file=sys.stderr)

    if args.dry_run:
        def dry_summary() -> None:
            print("=== Wellfound [dry-run] 職歴更新差分プレビュー ===")
            print(f"- 対象企業: {args.company_name}")
            print(f"- 終了日: {args.ended_at or '(指定なし)'}")
            print(f"- 在籍フラグ: {args.current}")
            print("- 実際の更新は行われませんでした。")

        return ctx.flush_outputs(summary_fn=dry_summary, json_data={"dry_run": True, "payload": payload})

    print(f"[Wellfound] 職歴を更新しています ({args.company_name})...", file=sys.stderr)
    update_res = execute_manage_action(
        args.session,
        action="update_experience",
        payload=payload,
        dry_run=False,
    )
    updated_profile = update_res.get("data", {}).get("profileData") or {}
    saved_paths = save_profile_data(updated_profile, output_dir=args.output_dir)
    ctx.add_result_paths(saved_paths)

    def summary_fn() -> None:
        print("=== Wellfound 職歴 更新完了 ===")
        print(f"- 更新対象: {args.company_name}")
        print(f"- 保存先: {to_relative_path(saved_paths[0])}, {to_relative_path(saved_paths[1])}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=updated_profile if args.json else None)


def handle_add_experience(args: argparse.Namespace, ctx: EntrypointContext) -> int:
    """新規職歴の追加."""
    if not args.company_name or not args.role_title or not args.started_at:
        ctx.error("--company-name, --role-title, --started-at (MM/YYYY) は必須です。")
        return 1

    payload: dict[str, Any] = {
        "companyName": args.company_name.strip(),
        "title": args.role_title.strip(),
        "startedAt": args.started_at.strip(),
        "current": args.current if args.current is not None else True,
        "endedAt": args.ended_at.strip() if args.ended_at else "",
        "description": args.description.strip() if args.description else "",
    }

    current_profile = backup_current_profile(args.session, args.output_dir, "add_experience")
    print(f"\n--- 新規職歴追加プレビュー: {args.company_name} ---", file=sys.stderr)
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
    print("----------------------------------------\n", file=sys.stderr)

    if args.dry_run:
        def dry_summary() -> None:
            print("=== Wellfound [dry-run] 新規職歴追加プレビュー ===")
            print(f"- 企業名: {payload['companyName']}")
            print(f"- 役職: {payload['title']}")
            print(f"- 期間: {payload['startedAt']} 〜 {'現在' if payload['current'] else payload['endedAt']}")
            print("- 実際の更新は行われませんでした。")

        return ctx.flush_outputs(summary_fn=dry_summary, json_data={"dry_run": True, "payload": payload})

    print(f"[Wellfound] 新規職歴を追加しています ({args.company_name})...", file=sys.stderr)
    update_res = execute_manage_action(
        args.session,
        action="add_experience",
        payload=payload,
        dry_run=False,
    )
    updated_profile = update_res.get("data", {}).get("profileData") or {}
    saved_paths = save_profile_data(updated_profile, output_dir=args.output_dir)
    ctx.add_result_paths(saved_paths)

    def summary_fn() -> None:
        print("=== Wellfound 新規職歴 追加完了 ===")
        print(f"- 追加企業: {payload['companyName']}")
        print(f"- 保存先: {to_relative_path(saved_paths[0])}, {to_relative_path(saved_paths[1])}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=updated_profile if args.json else None)


def handle_remove_experience(args: argparse.Namespace, ctx: EntrypointContext) -> int:
    """職歴の削除."""
    payload: dict[str, Any] = {
        "companyName": (args.company_name or "").strip(),
    }

    current_profile = backup_current_profile(args.session, args.output_dir, "remove_experience")
    print(f"\n--- 職歴削除プレビュー: {args.company_name or '最初の該当職歴'} ---", file=sys.stderr)
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
    print("----------------------------------------\n", file=sys.stderr)

    if args.dry_run:
        def dry_summary() -> None:
            print("=== Wellfound [dry-run] 職歴削除プレビュー ===")
            print(f"- 削除対象企業: {payload['companyName'] or '先頭の職歴'}")
            print("- 実際の更新は行われませんでした。")

        return ctx.flush_outputs(summary_fn=dry_summary, json_data={"dry_run": True, "payload": payload})

    print(f"[Wellfound] 職歴を削除しています ({args.company_name or '先頭'})...", file=sys.stderr)
    update_res = execute_manage_action(
        args.session,
        action="remove_experience",
        payload=payload,
        dry_run=False,
    )
    updated_profile = update_res.get("data", {}).get("profileData") or {}
    saved_paths = save_profile_data(updated_profile, output_dir=args.output_dir)
    ctx.add_result_paths(saved_paths)

    def summary_fn() -> None:
        print("=== Wellfound 職歴 削除完了 ===")
        print(f"- 削除対象企業: {payload['companyName'] or '先頭'}")
        print(f"- 保存先: {to_relative_path(saved_paths[0])}, {to_relative_path(saved_paths[1])}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=updated_profile if args.json else None)


def handle_add_skills(args: argparse.Namespace, ctx: EntrypointContext) -> int:
    """スキルの追加."""
    if not args.skills:
        ctx.error("--skills オプションでカンマ区切りの追加スキル名を指定してください。")
        return 1

    skill_list = [s.strip() for s in args.skills.split(",") if s.strip()]
    if not skill_list:
        ctx.error("有効なスキルが指定されていません。")
        return 1

    current_profile = backup_current_profile(args.session, args.output_dir, "add_skills")
    existing_skills = [s.get("name") for s in current_profile.get("skills") or [] if s.get("name")]
    print(f"\n--- スキル追加プレビュー ---", file=sys.stderr)
    print(f"既存スキル: {', '.join(existing_skills)}", file=sys.stderr)
    print(f"追加予定: {', '.join(skill_list)}", file=sys.stderr)
    print("----------------------------------------\n", file=sys.stderr)

    if args.dry_run:
        def dry_summary() -> None:
            print("=== Wellfound [dry-run] スキル追加プレビュー ===")
            print(f"- 追加予定スキル: {', '.join(skill_list)}")
            print("- 実際の更新は行われませんでした。")

        return ctx.flush_outputs(summary_fn=dry_summary, json_data={"dry_run": True, "skills": skill_list})

    print("[Wellfound] スキルを追加しています...", file=sys.stderr)
    update_res = execute_manage_action(
        args.session,
        action="add_skills",
        payload={"skills": skill_list},
        dry_run=False,
        timeout=90,
    )
    updated_profile = update_res.get("data", {}).get("profileData") or {}
    saved_paths = save_profile_data(updated_profile, output_dir=args.output_dir)
    ctx.add_result_paths(saved_paths)

    def summary_fn() -> None:
        print("=== Wellfound スキル 追加完了 ===")
        current_skill_names = [s.get("name") for s in updated_profile.get("skills") or [] if s.get("name")]
        print(f"- 現在のスキル一覧: {', '.join(current_skill_names)}")
        print(f"- 保存先: {to_relative_path(saved_paths[0])}, {to_relative_path(saved_paths[1])}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=updated_profile if args.json else None)


def handle_update_identity(args: argparse.Namespace, ctx: EntrypointContext) -> int:
    """人種・エスニシティ等の修正."""
    payload: dict[str, bool] = {}
    if args.east_asian is not None:
        payload["eastAsian"] = args.east_asian
    if args.south_asian is not None:
        payload["southAsian"] = args.south_asian

    if not payload:
        ctx.error("--east-asian または --south-asian を指定してください。")
        return 1

    current_profile = backup_current_profile(args.session, args.output_dir, "update_identity")
    print(f"\n--- アイデンティティ修正プレビュー ---", file=sys.stderr)
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
    print("----------------------------------------\n", file=sys.stderr)

    if args.dry_run:
        def dry_summary() -> None:
            print("=== Wellfound [dry-run] アイデンティティ修正プレビュー ===")
            for k, v in payload.items():
                print(f"- {k}: {v}")
            print("- 実際の更新は行われませんでした。")

        return ctx.flush_outputs(summary_fn=dry_summary, json_data={"dry_run": True, "payload": payload})

    print("[Wellfound] アイデンティティ設定を更新しています...", file=sys.stderr)
    update_res = execute_manage_action(
        args.session,
        action="update_identity",
        payload=payload,
        dry_run=False,
    )
    updated_profile = update_res.get("data", {}).get("profileData") or {}
    saved_paths = save_profile_data(updated_profile, output_dir=args.output_dir)
    ctx.add_result_paths(saved_paths)

    def summary_fn() -> None:
        print("=== Wellfound アイデンティティ 更新完了 ===")
        print(f"- 保存先: {to_relative_path(saved_paths[0])}, {to_relative_path(saved_paths[1])}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=updated_profile if args.json else None)


def main() -> None:
    """メインエントリポイント."""
    parser = create_base_parser(description="Wellfound プロフィール CRUD管理・同期スクリプト")
    parser.add_argument(
        "--action",
        choices=[
            "view",
            "update_bio",
            "update_socials",
            "update_achievements",
            "update_experience",
            "add_experience",
            "remove_experience",
            "add_skills",
            "update_identity",
        ],
        default="view",
        help="実行アクション",
    )
    parser.add_argument("--bio", type=str, help="設定する自己紹介文 (最大160文字)")
    parser.add_argument("--linkedin", type=str, help="設定するLinkedIn URL")
    parser.add_argument("--github", type=str, help="設定するGitHub URL")
    parser.add_argument("--twitter", type=str, help="設定するX/Twitter URL")
    parser.add_argument("--website", type=str, help="設定する個人WebサイトURL")
    parser.add_argument("--achievements", type=str, help="設定する実績・成果文 (What I've built, 最大1000文字)")

    # 職歴関連
    parser.add_argument("--company-name", type=str, help="職歴の企業名")
    parser.add_argument("--role-title", type=str, help="職歴の役職名")
    parser.add_argument("--started-at", type=str, help="開始日 (MM/YYYY)")
    parser.add_argument("--ended-at", type=str, help="終了日 (MM/YYYY)")
    parser.add_argument("--current", action=argparse.BooleanOptionalAction, default=None, help="現在在籍中フラグ")
    parser.add_argument("--description", type=str, help="職務内容詳細")

    # スキル関連
    parser.add_argument("--skills", type=str, help="カンマ区切りの追加スキル名リスト")

    # アイデンティティ関連
    parser.add_argument("--east-asian", action=argparse.BooleanOptionalAction, default=None, help="East Asianフラグ")
    parser.add_argument("--south-asian", action=argparse.BooleanOptionalAction, default=None, help="South Asianフラグ")

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際の更新を行わず、変更差分のプレビューのみを表示する",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"プロフィールMarkdown/JSON出力ディレクトリ (デフォルト: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--session",
        type=str,
        default="job-hunt",
        help="Playwrightブラウザセッション名 (デフォルト: job-hunt)",
    )

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    # 1. サイト認証確認
    try:
        auth_ok = ensure_site_authenticated(
            site="wellfound",
            session=args.session,
            target_url=TARGET_URL,
            headed=False,
            exit_on_fail=True,
        )
    except Exception as e:
        ctx.error(f"Wellfound 認証エラー: {e}")
        sys.exit(2)

    if not auth_ok:
        ctx.error("Wellfound の認証に失敗しました。")
        sys.exit(2)

    action_map = {
        "view": handle_view,
        "update_bio": handle_update_bio,
        "update_socials": handle_update_socials,
        "update_achievements": handle_update_achievements,
        "update_experience": handle_update_experience,
        "add_experience": handle_add_experience,
        "remove_experience": handle_remove_experience,
        "add_skills": handle_add_skills,
        "update_identity": handle_update_identity,
    }

    handler = action_map.get(args.action)
    if not handler:
        ctx.error(f"未対応のアクションです: {args.action}")
        sys.exit(1)

    exit_code = handler(args, ctx)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

