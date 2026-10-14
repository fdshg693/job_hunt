"""ビズリーチ WEB履歴書（フリーフォーマット・職務経歴）更新・CRUD管理スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
ビズリーチのWEB履歴書（フリーフォーマット、職務経歴詳細等）の
閲覧・更新・バックアップを安全に実行します。

変更操作の実行前には必ず最新プロフィールの自動バックアップを取得し、
--dry-run フラグによる変更プレビューと安全ガードを提供します。
"""

from __future__ import annotations

import argparse
import difflib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/bizreach/ の2階層上)
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
from scripts.bizreach.fetch_resume import save_resume_result

BIZREACH_SCRIPTS_DIR = Path(__file__).resolve().parent
MANAGE_SCRIPT_PATH = BIZREACH_SCRIPTS_DIR / "manage_resume.mjs"
FETCH_RESUME_SCRIPT_PATH = BIZREACH_SCRIPTS_DIR / "fetch_resume.mjs"
RESUME_DATA_DIR = PROJECT_ROOT / "data" / "bizreach" / "resume"
BACKUP_DIR = RESUME_DATA_DIR / "backups"
TARGET_URL = "https://www.bizreach.jp/resume/company/"
FREETEXT_URL = "https://www.bizreach.jp/resume/freetext/"


def execute_manage_action(
    session: str,
    action: str,
    payload: dict[str, Any] | None = None,
    dry_run: bool = False,
    timeout: int = 45,
) -> dict[str, Any]:
    """manage_resume.mjs に action, payload, isDryRun を注入して実行する."""
    if not MANAGE_SCRIPT_PATH.exists():
        raise RuntimeError(f"管理スクリプトが見つかりません: {MANAGE_SCRIPT_PATH}")

    template_code = MANAGE_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = (
        template_code.replace("'__BIZREACH_ACTION__'", json.dumps(action))
        .replace("__BIZREACH_PAYLOAD__", json.dumps(payload or {}, ensure_ascii=False))
        .replace("__BIZREACH_DRY_RUN__", "true" if dry_run else "false")
    )

    tmp_script_path = BIZREACH_SCRIPTS_DIR / f".tmp_manage_{action}.mjs"
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


def backup_current_resume(session: str) -> list[Path]:
    """変更操作前に最新の職務経歴書・フリーフォーマットを自動バックアップする."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    fetch_result = run_code_script(session, FETCH_RESUME_SCRIPT_PATH, timeout=45)
    if not fetch_result or not fetch_result.get("success"):
        raise RuntimeError("変更前自動バックアップ（最新レジュメ取得）に失敗したため、操作を中断します。")

    # 通常のデータ保存
    saved_files = save_resume_result(fetch_result, output_dir=RESUME_DATA_DIR)

    # タイムスタンプ付き個別バックアップ保存
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"backup_{timestamp}.json"
    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump(fetch_result, f, ensure_ascii=False, indent=2)

    all_backups = list(saved_files) + [backup_file]
    print(f"[安全ガード] 変更前バックアップを保存しました: {to_relative_path(backup_file)}", file=sys.stderr)
    return all_backups


def generate_freetext_from_profile() -> str:
    """profile/resume.md および profile/skills.md を統合し、ビズリーチのフリーフォーマット用テキストを生成する."""
    resume_path = PROJECT_ROOT / "profile" / "resume.md"
    skills_path = PROJECT_ROOT / "profile" / "skills.md"

    if not resume_path.exists():
        raise FileNotFoundError(f"プロファイルマスターが見つかりません: {resume_path}")

    resume_text = resume_path.read_text(encoding="utf-8")
    skills_text = skills_path.read_text(encoding="utf-8") if skills_path.exists() else ""

    parts = []

    # 1. 職務要約
    parts.append("【職務要約】")
    summary_match = ""
    in_summary = False
    for line in resume_text.splitlines():
        if line.startswith("## 職務要約"):
            in_summary = True
            continue
        if in_summary:
            if line.startswith("## ") or line.startswith("---"):
                break
            summary_match += line + "\n"
    summary_clean = summary_match.strip()
    if summary_clean:
        parts.append(summary_clean)
    else:
        parts.append(
            "Webアプリケーションのフルスタック開発および生成AI・LLMを活用した機能開発・PoC検証・業務効率化基盤構築に従事。\n"
            "フロントエンド・バックエンド（Python/Java/C#/TS/Go）からインフラ（Azure/IaC/Docker/K8s/AKS）まで一貫対応できるフルスタック力と、"
            "最新のAgentic AI・自動化技術を開発プロセスに組み込む生産性向上力を強みとしています。"
        )

    # 2. 保有スキル・活かせる技術スタック
    parts.append("\n【保有スキル・活かせる技術スタック】")
    skills_lines = [
        "・言語/フレームワーク: Python (FastAPI), TypeScript/JavaScript (Next.js, React, React Router), Java (Spring Boot), C# (.NET), Go, SQL",
        "・クラウド/インフラ: Azure (実務1年+個人開発1.5年 / APIM, AKS, Container Apps, AI Search 等), Kubernetes / AKS (実務半年), IaC (Terraform, Bicep 1.5年), Docker, GCP, AWS",
        "・AI/LLM/エージェント技術: Microsoft Foundry Agent (Prompt Agent), Azure OpenAI Service, Azure APIM AI Gateway/OBO認証, Foundry Local (SLM), LangChain, Playwright",
        "・開発自動化/基盤: GitHub Agentic Workflow (PR自動レビュー基盤), AIコーディングエージェント活用基盤（ルール/スキル整備）, CI/CD (GitHub Actions, GitLab CI/CD, Azure DevOps)",
    ]
    parts.append("\n".join(skills_lines))

    # 3. 自身の強み・自己PR
    parts.append("\n【自己PR・自身の強み】")
    pr_lines = [
        "1. 自発的に学びの機会を創出し周囲を巻き込む主体性",
        "   現職（ヘッドウォータース）では、通常業務で接点のない社内テックリードを自ら巻き込み、業務時間外で共同アプリケーション開発を推進。より高度なアーキテクチャや実践知見を主体的に吸収・実践しています。社内LT登壇や週次勉強会の主催など、組織を越えて知見を共有する行動を継続しています。",
        "",
        "2. 最新のAI技術を先取りし開発現場に還元する推進力",
        "   生成AIや最新エージェント技術（Agentic AI, Foundry Agent, Claude Code, Copilot, MCP, SLM等）をいち早く検証・実務導入。AIエージェント向けルール/スキル整備やPR自動レビュー基盤を構築し、チーム全体の開発生産性とコード品質を大幅に引き上げました。",
        "",
        "3. 未知の環境でも自律的仮説検証で突破する問題解決力",
        "   ドキュメントの乏しい新技術（SLM/Foundry Local、Azure APIM AI Gateway、OBO認証フロー）でも、ソースコードや実地環境のエラーログから仕様を独自に解明し、早期にプロトタイプ実装や技術レポート作成を完遂する突破力を備えています。",
    ]
    parts.append("\n".join(pr_lines))

    # 4. 主な実績・課外活動
    parts.append("\n【主な社外活動・ハッカソン実績】")
    activities_lines = [
        "・第4回 Agentic AI Hackathon with Google Cloud ファイナリスト（2026年2月）",
        "  機械学習モデルチューニングWebアプリ（Visionfy）の開発において、フロントエンド（Next.js）、バックエンド（Python）、インフラ（GCP）の実装全般を主導。",
        "・自作AIツール・MCPサーバー運用: GCP上に自作MCPサーバーをデプロイし、Claude連携環境や日常開発自動化CLIツールを自作・運用。",
        "・資格・語学: TOEIC 955点（ビジネスレベル英語）、基本情報技術者試験（2022年）",
    ]
    parts.append("\n".join(activities_lines))

    return "\n".join(parts)


def print_diff(previous: str, new: str) -> None:
    """テキスト差分（unified diff）を人間可読に出力する."""
    prev_lines = previous.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(
        prev_lines,
        new_lines,
        fromfile="現在登録内容",
        tofile="反映予定内容",
        lineterm="",
    )
    diff_text = "".join(diff)
    if diff_text:
        print("\n--- 差分プレビュー (Diff) ---")
        print(diff_text)
        print("----------------------------\n")
    else:
        print("\n[差分なし] 登録内容と同一です。\n")


def cmd_show_freetext(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """現在のフリーフォーマットを表示する."""
    result = execute_manage_action(session, "get-freetext")
    text = result.get("freetext", "")

    if ctx.json_mode:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif ctx.summary:
        print("=== ビズリーチ フリーフォーマット（現在値） ===")
        print(text)
        print(f"\n文字数: {len(text)} 文字")
    else:
        print(text)
    return 0


def cmd_update_freetext(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """フリーフォーマットを更新する."""
    # テキスト取得
    new_text = ""
    if args.text:
        new_text = args.text
    elif args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            ctx.error(f"指定されたファイルが見つかりません: {file_path}")
            return 1
        new_text = file_path.read_text(encoding="utf-8")
    elif args.from_profile:
        new_text = generate_freetext_from_profile()
    else:
        ctx.error("--text, --file, または --from-profile のいずれかを指定してください。")
        return 1

    new_text = new_text.strip()
    if not new_text:
        ctx.error("更新テキストが空です。")
        return 1

    dry_run = getattr(args, "dry_run", False)

    # 1. 安全ガード: 本番更新時は必ず自動バックアップを取得
    backup_files: list[Path] = []
    if not dry_run:
        try:
            backup_files = backup_current_resume(session)
            ctx.add_result_paths(backup_files)
        except Exception as e:
            ctx.error(f"バックアップ失敗による中断: {e}")
            return 1

    # 2. アクション実行
    payload = {"text": new_text}
    result = execute_manage_action(session, "update-freetext", payload=payload, dry_run=dry_run)

    # 3. 結果出力
    prev_text = result.get("previousText", "")

    if dry_run:
        if ctx.summary or not ctx.json_mode:
            print("[DRY-RUN] ビズリーチ フリーフォーマット更新プレビュー")
            print(f"- 現在文字数: {len(prev_text)} 文字")
            print(f"- 反映後文字数: {len(new_text)} 文字")
            print(f"- 差分文字数: {len(new_text) - len(prev_text):+d} 文字")
            print_diff(prev_text, new_text)
            print("[INFO] --dry-run のためブラウザへの保存は実行されていません。")
        if ctx.json_mode:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    # 本番保存後
    # 保存後の最新データも再取得してファイル同期
    updated_files: list[Path] = []
    try:
        updated_files = backup_current_resume(session)
        ctx.add_result_paths(updated_files)
    except Exception as e:
        print(f"[警告] 更新後ファイルの再取得に失敗しました: {e}", file=sys.stderr)

    def summary_fn() -> None:
        print("=== ビズリーチ フリーフォーマット更新完了 ===")
        print(f"- 変更前文字数: {len(prev_text)} 文字")
        print(f"- 変更後文字数: {len(new_text)} 文字")
        print(f"- 反映先URL: {result.get('finalUrl', FREETEXT_URL)}")
        print_diff(prev_text, new_text)
        if backup_files:
            print("[作成・更新ファイル]")
            for bf in backup_files:
                print(f"  - {to_relative_path(bf)}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=result)


def print_career_summary(companies: list[dict[str, Any]]) -> None:
    """職務経歴（企業・プロジェクト）の構造化サマリを表示する."""
    print("\n========================================================")
    print(" ビズリーチ 登録職務経歴・プロジェクト一覧")
    print("========================================================\n")
    if not companies:
        print("職務経歴は登録されていません。")
        return

    for c in companies:
        c_idx = c.get("companyIndex", 0)
        c_name = c.get("companyName", "未設定")
        dept = c.get("departmentName", "")
        dept_str = f" ({dept})" if dept else ""
        s_date = f"{c.get('startYear')}年{c.get('startMonth')}月" if c.get("startYear") else "-"
        e_date = "現在" if c.get("isCurrent") else (f"{c.get('endYear')}年{c.get('endMonth')}月" if c.get("endYear") else "-")
        cur_str = "（在籍中）" if c.get("isCurrent") else ""
        projs = c.get("projects") or []

        print(f"■ [{c_idx}] {c_name}{dept_str} {cur_str}")
        print(f"    期間: {s_date} 〜 {e_date}")
        print(f"    プロジェクト数: {len(projs)} 件")

        for p in projs:
            p_idx = p.get("projectIndex", 0)
            p_title = p.get("title", "未設定")
            ps_date = f"{p.get('startYear')}年{p.get('startMonth')}月" if p.get("startYear") else "-"
            pe_date = "現在" if p.get("isCurrent") else (f"{p.get('endYear')}年{p.get('endMonth')}月" if p.get("endYear") else "-")
            p_cur = "（進行中）" if p.get("isCurrent") else ""
            desc = p.get("description", "").strip()
            desc_snip = desc.splitlines()[0][:40] + ("..." if len(desc.splitlines()[0]) > 40 else "") if desc else "-"

            print(f"      - [{p_idx}] {p_title} {p_cur}")
            print(f"          期間: {ps_date} 〜 {pe_date}")
            print(f"          業務概要: {desc_snip}")
        print()


def cmd_list_career(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """登録されている職歴（企業・プロジェクト）一覧を表示する."""
    result = execute_manage_action(session, "get-career")
    companies = result.get("companies", [])

    if ctx.json_mode:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print_career_summary(companies)
    return 0


def _apply_career_mutation(
    session: str,
    action: str,
    payload: dict[str, Any],
    dry_run: bool,
    force: bool,
    is_destructive: bool,
    ctx: EntrypointContext,
    target_desc: str,
) -> int:
    """職務経歴の変更操作を実行し、バックアップ、保護確認、再同期、出力規約を処理する."""
    # 1. 破壊的操作の --force チェック
    if is_destructive and not dry_run and not force:
        ctx.error(
            f"[保護エラー] {target_desc} は登録済みの実データに対する変更・削除操作です。\n"
            f"意図した操作であることを確認し、`--force` フラグを付けて再実行してください。"
        )
        return 1

    # 2. 自動バックアップ（本番実行時）
    backup_files: list[Path] = []
    if not dry_run:
        try:
            backup_files = backup_current_resume(session)
            ctx.add_result_paths(backup_files)
        except Exception as e:
            ctx.error(f"変更前自動バックアップ失敗による中断: {e}")
            return 1

    # 3. アクション実行
    result = execute_manage_action(session, action, payload=payload, dry_run=dry_run)

    # 4. Dry-Run 時のプレビュー出力
    if dry_run:
        if ctx.json_mode:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"\n[DRY-RUN] ビズリーチ 職務経歴操作プレビュー: {action}")
            print(f"対象: {target_desc}")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print("\n[INFO] --dry-run のためブラウザ上への保存は実行されていません。\n")
        return 0

    # 5. 本番反映後のデータ再同期（最新データを再フェッチしてファイル保存）
    updated_files: list[Path] = []
    try:
        updated_files = backup_current_resume(session)
        ctx.add_result_paths(updated_files)
    except Exception as e:
        print(f"[警告] 変更後データの再同期取得に失敗しました: {e}", file=sys.stderr)

    def summary_fn() -> None:
        print(f"\n=== ビズリーチ 職務経歴操作完了: {action} ===")
        print(f"- 対象: {target_desc}")
        if result.get("finalUrl"):
            print(f"- 反映先URL: {result.get('finalUrl')}")
        if backup_files:
            print("[作成・更新ファイル]")
            for bf in backup_files:
                print(f"  - {to_relative_path(bf)}")

    return ctx.flush_outputs(summary_fn=summary_fn, json_data=result)


def cmd_add_company(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """職歴（企業）を追加する."""
    dept = args.department or args.role
    if not dept:
        ctx.error("--department または --role を指定してください。")
        return 1

    payload: dict[str, Any] = {
        "companyName": args.name,
        "departmentName": dept,
        "startYear": args.start_year,
        "startMonth": args.start_month,
        "endYear": args.end_year,
        "endMonth": args.end_month,
        "isCurrent": args.current if args.current else (not args.end_year),
    }

    if args.proj_title:
        payload["initialProject"] = {
            "title": args.proj_title,
            "startYear": args.proj_start_year or args.start_year,
            "startMonth": args.proj_start_month or args.start_month,
            "endYear": args.proj_end_year,
            "endMonth": args.proj_end_month,
            "isCurrent": args.proj_current if args.proj_current else (not args.proj_end_year),
            "description": args.proj_description or "",
        }

    return _apply_career_mutation(
        session=session,
        action="add-company",
        payload=payload,
        dry_run=getattr(args, "dry_run", False),
        force=False,
        is_destructive=False,
        ctx=ctx,
        target_desc=f"企業追加 '{args.name}'",
    )


def cmd_update_company(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """職歴（企業）を更新する."""
    if args.index is None and not args.name:
        ctx.error("--index または --name（対象企業名）のいずれかを指定してください。")
        return 1

    dept = args.department or args.role
    payload: dict[str, Any] = {
        "companyIndex": args.index,
        "companyName": args.name,
        "newCompanyName": args.new_name,
        "departmentName": dept,
        "startYear": args.start_year,
        "startMonth": args.start_month,
        "endYear": args.end_year,
        "endMonth": args.end_month,
        "isCurrent": args.current,
    }
    payload = {k: v for k, v in payload.items() if v is not None}

    target_str = f"企業インデックス #{args.index}" if args.index is not None else f"企業名 '{args.name}'"
    return _apply_career_mutation(
        session=session,
        action="update-company",
        payload=payload,
        dry_run=getattr(args, "dry_run", False),
        force=getattr(args, "force", False),
        is_destructive=True,
        ctx=ctx,
        target_desc=f"企業更新 ({target_str})",
    )


def cmd_delete_company(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """職歴（企業）を削除する."""
    if args.index is None and not args.name:
        ctx.error("--index または --name（対象企業名）のいずれかを指定してください。")
        return 1

    payload: dict[str, Any] = {
        "companyIndex": args.index,
        "companyName": args.name,
    }
    payload = {k: v for k, v in payload.items() if v is not None}

    target_str = f"企業インデックス #{args.index}" if args.index is not None else f"企業名 '{args.name}'"
    return _apply_career_mutation(
        session=session,
        action="delete-company",
        payload=payload,
        dry_run=getattr(args, "dry_run", False),
        force=getattr(args, "force", False),
        is_destructive=True,
        ctx=ctx,
        target_desc=f"企業削除 ({target_str})",
    )


def cmd_add_project(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """プロジェクトを追加する."""
    if args.company_index is None and not args.company_name:
        ctx.error("--company-index または --company-name のいずれかを指定してください。")
        return 1

    desc = args.description if args.description is not None else (args.detail or "")
    if getattr(args, "file", None):
        file_path = Path(args.file)
        if not file_path.exists():
            ctx.error(f"指定されたファイルが見つかりません: {file_path}")
            return 1
        desc = file_path.read_text(encoding="utf-8")

    payload: dict[str, Any] = {
        "companyIndex": args.company_index,
        "companyName": args.company_name,
        "title": args.title,
        "startYear": args.start_year,
        "startMonth": args.start_month,
        "endYear": args.end_year,
        "endMonth": args.end_month,
        "isCurrent": args.current if args.current else (not args.end_year),
        "description": desc,
    }
    payload = {k: v for k, v in payload.items() if v is not None}

    target_parent = f"企業 #{args.company_index}" if args.company_index is not None else f"企業 '{args.company_name}'"
    return _apply_career_mutation(
        session=session,
        action="add-project",
        payload=payload,
        dry_run=getattr(args, "dry_run", False),
        force=False,
        is_destructive=False,
        ctx=ctx,
        target_desc=f"{target_parent} へのプロジェクト追加 '{args.title}'",
    )


def cmd_update_project(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """プロジェクトを更新する."""
    if args.company_index is None and not args.company_name:
        ctx.error("--company-index または --company-name のいずれかを指定してください。")
        return 1
    if args.project_index is None and not args.project_title:
        ctx.error("--project-index または --project-title のいずれかを指定してください。")
        return 1

    desc = args.description if args.description is not None else args.detail
    if getattr(args, "file", None):
        file_path = Path(args.file)
        if not file_path.exists():
            ctx.error(f"指定されたファイルが見つかりません: {file_path}")
            return 1
        desc = file_path.read_text(encoding="utf-8")
    is_current = args.current
    if is_current is None and args.end_year:
        is_current = False

    payload: dict[str, Any] = {
        "companyIndex": args.company_index,
        "companyName": args.company_name,
        "projectIndex": args.project_index,
        "projectTitle": args.project_title,
        "newTitle": args.new_title,
        "startYear": args.start_year,
        "startMonth": args.start_month,
        "endYear": args.end_year,
        "endMonth": args.end_month,
        "isCurrent": is_current,
        "description": desc,
    }
    payload = {k: v for k, v in payload.items() if v is not None}

    target_parent = f"企業 #{args.company_index}" if args.company_index is not None else f"企業 '{args.company_name}'"
    target_pj = f"PJ #{args.project_index}" if args.project_index is not None else f"PJ '{args.project_title}'"
    return _apply_career_mutation(
        session=session,
        action="update-project",
        payload=payload,
        dry_run=getattr(args, "dry_run", False),
        force=getattr(args, "force", False),
        is_destructive=True,
        ctx=ctx,
        target_desc=f"{target_parent} 内 {target_pj} の更新",
    )


def cmd_delete_project(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """プロジェクトを削除する."""
    if args.company_index is None and not args.company_name:
        ctx.error("--company-index または --company-name のいずれかを指定してください。")
        return 1
    if args.project_index is None and not args.project_title:
        ctx.error("--project-index または --project-title のいずれかを指定してください。")
        return 1

    payload: dict[str, Any] = {
        "companyIndex": args.company_index,
        "companyName": args.company_name,
        "projectIndex": args.project_index,
        "projectTitle": args.project_title,
    }
    payload = {k: v for k, v in payload.items() if v is not None}

    target_parent = f"企業 #{args.company_index}" if args.company_index is not None else f"企業 '{args.company_name}'"
    target_pj = f"PJ #{args.project_index}" if args.project_index is not None else f"PJ '{args.project_title}'"
    return _apply_career_mutation(
        session=session,
        action="delete-project",
        payload=payload,
        dry_run=getattr(args, "dry_run", False),
        force=getattr(args, "force", False),
        is_destructive=True,
        ctx=ctx,
        target_desc=f"{target_parent} 内 {target_pj} の削除",
    )


def cmd_backup(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """現在のWEB履歴書を手動バックアップする."""
    saved_files = backup_current_resume(session)
    ctx.add_result_paths(saved_files)

    def summary_fn() -> None:
        print("=== ビズリーチ WEB履歴書バックアップ完了 ===")
        for sf in saved_files:
            print(f"  - {to_relative_path(sf)}")

    return ctx.flush_outputs(summary_fn=summary_fn)


def cmd_check_form(args: argparse.Namespace, session: str, ctx: EntrypointContext) -> int:
    """職務経歴フォームの構造を検証する."""
    result = execute_manage_action(session, "get-career-form")
    if ctx.json_mode:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        fd = result.get("formData", {})
        print("=== 職務経歴編集フォーム構造 ===")
        print(f"- テキストエリア数: {fd.get('textareasCount')}")
        print(f"- 入力フィールド数: {fd.get('inputsCount')}")
        for ta in fd.get("textareas", []):
            print(f"  [Textarea #{ta.get('index')}] placeholder={ta.get('placeholder')} len={len(ta.get('value'))}")
    return 0


def main() -> None:
    """CLIエントリポイント."""
    # 共通オプションパーサー
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
        description="ビズリーチのWEB履歴書（フリーフォーマット・職務経歴）を管理・更新・バックアップします。",
        parents=[common_parser],
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. show-freetext
    subparsers.add_parser("show-freetext", parents=[common_parser], help="現在のフリーフォーマットテキストを表示する")

    # 2. update-freetext
    update_freetext_parser = subparsers.add_parser(
        "update-freetext", parents=[common_parser], help="フリーフォーマットテキストを更新する"
    )
    update_freetext_parser.add_argument("--text", help="更新するテキスト文字列")
    update_freetext_parser.add_argument("--file", help="更新するテキストファイルパス")
    update_freetext_parser.add_argument(
        "--from-profile",
        action="store_true",
        help="profile/resume.md から自己PR・職務要約を自動抽出して更新",
    )
    update_freetext_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="保存を実行せず、差分・反映内容のプレビューのみ行う",
    )

    # 3. list-career
    subparsers.add_parser("list-career", parents=[common_parser], help="登録済み職務経歴（企業・プロジェクト）一覧を表示する")

    # 4. add-company
    add_c_parser = subparsers.add_parser("add-company", parents=[common_parser], help="職歴（所属企業）を追加する")
    add_c_parser.add_argument("--name", required=True, help="企業名")
    add_c_parser.add_argument("--department", help="部署・役職名")
    add_c_parser.add_argument("--role", help="部署・役職名（--department と同一）")
    add_c_parser.add_argument("--start-year", type=int, required=True, help="入社年（例: 2024）")
    add_c_parser.add_argument("--start-month", type=int, required=True, help="入社月（1〜12）")
    add_c_parser.add_argument("--end-year", type=int, default=None, help="退社年")
    add_c_parser.add_argument("--end-month", type=int, default=None, help="退社月")
    add_c_parser.add_argument("--current", action="store_true", help="現在在職中")
    add_c_parser.add_argument("--proj-title", help="初期プロジェクト名")
    add_c_parser.add_argument("--proj-start-year", type=int, default=None, help="初期プロジェクト開始年")
    add_c_parser.add_argument("--proj-start-month", type=int, default=None, help="初期プロジェクト開始月")
    add_c_parser.add_argument("--proj-end-year", type=int, default=None, help="初期プロジェクト終了年")
    add_c_parser.add_argument("--proj-end-month", type=int, default=None, help="初期プロジェクト終了月")
    add_c_parser.add_argument("--proj-current", action="store_true", help="初期プロジェクト進行中")
    add_c_parser.add_argument("--proj-description", help="初期プロジェクト業務詳細")
    add_c_parser.add_argument("--dry-run", action="store_true", help="保存を実行せずプレビューのみ行う")

    # 5. update-company
    up_c_parser = subparsers.add_parser("update-company", parents=[common_parser], help="職歴（所属企業）を更新する")
    up_c_parser.add_argument("--index", type=int, default=None, help="対象企業インデックス（0〜）")
    up_c_parser.add_argument("--name", default=None, help="対象企業名")
    up_c_parser.add_argument("--new-name", default=None, help="変更後の新企業名")
    up_c_parser.add_argument("--department", default=None, help="変更後の部署・役職名")
    up_c_parser.add_argument("--role", default=None, help="変更後の部署・役職名（--department と同一）")
    up_c_parser.add_argument("--start-year", type=int, default=None, help="変更後の入社年")
    up_c_parser.add_argument("--start-month", type=int, default=None, help="変更後の入社月")
    up_c_parser.add_argument("--end-year", type=int, default=None, help="変更後の退社年")
    up_c_parser.add_argument("--end-month", type=int, default=None, help="変更後の退社月")
    up_c_parser.add_argument("--current", action="store_true", default=None, help="現在在職中")
    up_c_parser.add_argument("--force", action="store_true", help="既存の実データ更新を許可する保護解除フラグ")
    up_c_parser.add_argument("--dry-run", action="store_true", help="保存を実行せずプレビューのみ行う")

    # 6. delete-company
    del_c_parser = subparsers.add_parser("delete-company", parents=[common_parser], help="職歴（所属企業）を削除する")
    del_c_parser.add_argument("--index", type=int, default=None, help="削除対象企業インデックス（0〜）")
    del_c_parser.add_argument("--name", default=None, help="削除対象企業名")
    del_c_parser.add_argument("--force", action="store_true", help="既存の実データ削除を許可する保護解除フラグ")
    del_c_parser.add_argument("--dry-run", action="store_true", help="保存を実行せずプレビューのみ行う")

    # 7. add-project
    add_p_parser = subparsers.add_parser("add-project", parents=[common_parser], help="プロジェクトを追加する")
    add_p_parser.add_argument("--company-index", type=int, default=None, help="親企業のインデックス（0〜）")
    add_p_parser.add_argument("--company-name", default=None, help="親企業の名前")
    add_p_parser.add_argument("--title", required=True, help="プロジェクト名")
    add_p_parser.add_argument("--start-year", type=int, required=True, help="開始年")
    add_p_parser.add_argument("--start-month", type=int, required=True, help="開始月")
    add_p_parser.add_argument("--end-year", type=int, default=None, help="終了年")
    add_p_parser.add_argument("--end-month", type=int, default=None, help="終了月")
    add_p_parser.add_argument("--current", action="store_true", help="現在進行中")
    add_p_parser.add_argument("--description", default="", help="業務内容詳細")
    add_p_parser.add_argument("--detail", default=None, help="業務内容詳細（--description と同一）")
    add_p_parser.add_argument("--file", default=None, help="業務内容詳細テキストファイルのパス")
    add_p_parser.add_argument("--dry-run", action="store_true", help="保存を実行せずプレビューのみ行う")

    # 8. update-project
    up_p_parser = subparsers.add_parser("update-project", parents=[common_parser], help="プロジェクトを更新する")
    up_p_parser.add_argument("--company-index", type=int, default=None, help="親企業のインデックス（0〜）")
    up_p_parser.add_argument("--company-name", default=None, help="親企業の名前")
    up_p_parser.add_argument("--project-index", type=int, default=None, help="対象プロジェクトのインデックス（0〜）")
    up_p_parser.add_argument("--project-title", default=None, help="対象プロジェクト名")
    up_p_parser.add_argument("--new-title", default=None, help="変更後の新プロジェクト名")
    up_p_parser.add_argument("--start-year", type=int, default=None, help="変更後の開始年")
    up_p_parser.add_argument("--start-month", type=int, default=None, help="変更後の開始月")
    up_p_parser.add_argument("--end-year", type=int, default=None, help="変更後の終了年")
    up_p_parser.add_argument("--end-month", type=int, default=None, help="変更後の終了月")
    up_p_parser.add_argument("--current", action="store_true", default=None, help="現在進行中")
    up_p_parser.add_argument("--description", default=None, help="変更後の業務内容詳細")
    up_p_parser.add_argument("--detail", default=None, help="変更後の業務内容詳細（--description と同一）")
    up_p_parser.add_argument("--file", default=None, help="変更後の業務内容詳細テキストファイルのパス")
    up_p_parser.add_argument("--force", action="store_true", help="既存の実データ更新を許可する保護解除フラグ")
    up_p_parser.add_argument("--dry-run", action="store_true", help="保存を実行せずプレビューのみ行う")

    # 9. delete-project
    del_p_parser = subparsers.add_parser("delete-project", parents=[common_parser], help="プロジェクトを削除する")
    del_p_parser.add_argument("--company-index", type=int, default=None, help="親企業のインデックス（0〜）")
    del_p_parser.add_argument("--company-name", default=None, help="親企業の名前")
    del_p_parser.add_argument("--project-index", type=int, default=None, help="削除対象プロジェクトのインデックス（0〜）")
    del_p_parser.add_argument("--project-title", default=None, help="削除対象プロジェクト名")
    del_p_parser.add_argument("--force", action="store_true", help="既存の実データ削除を許可する保護解除フラグ")
    del_p_parser.add_argument("--dry-run", action="store_true", help="保存を実行せずプレビューのみ行う")

    # 10. backup
    subparsers.add_parser("backup", parents=[common_parser], help="現在のWEB履歴書・フリーフォーマットをバックアップする")

    # 11. check-form
    subparsers.add_parser("check-form", parents=[common_parser], help="職務経歴フォームの構造を検証する")

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    profile_dir = resolve_profile_path(args.session, args.profile_path)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 認証状態確認
        ensure_site_authenticated(
            site="bizreach",
            session=args.session,
            target_url=TARGET_URL,
            headed=args.headed,
            profile_dir=profile_dir,
            exit_on_fail=True,
        )

        update_profile_last_used(args.session)

        # コマンド分岐
        if args.command == "show-freetext":
            status = cmd_show_freetext(args, args.session, ctx)
        elif args.command == "update-freetext":
            status = cmd_update_freetext(args, args.session, ctx)
        elif args.command == "list-career":
            status = cmd_list_career(args, args.session, ctx)
        elif args.command == "add-company":
            status = cmd_add_company(args, args.session, ctx)
        elif args.command == "update-company":
            status = cmd_update_company(args, args.session, ctx)
        elif args.command == "delete-company":
            status = cmd_delete_company(args, args.session, ctx)
        elif args.command == "add-project":
            status = cmd_add_project(args, args.session, ctx)
        elif args.command == "update-project":
            status = cmd_update_project(args, args.session, ctx)
        elif args.command == "delete-project":
            status = cmd_delete_project(args, args.session, ctx)
        elif args.command == "backup":
            status = cmd_backup(args, args.session, ctx)
        elif args.command == "check-form":
            status = cmd_check_form(args, args.session, ctx)
        else:
            ctx.error(f"未知のコマンド: {args.command}")
            status = 1

        sys.exit(status)

    finally:
        if not args.keep_open:
            run_playwright_cmd([f"-s={args.session}", "close"], timeout=10)


if __name__ == "__main__":
    main()
