"""レバテックダイレクト マイページ職務経歴・自己PR（/mypage/profile/resume）管理スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
レバテックダイレクトの職務経歴・自己PRテキストエリア（最大30,000文字）の
閲覧（fetch）、更新（update）、プロファイル同期（sync）を安全に実行します。

変更操作の実行前には必ず最新内容の自動バックアップを取得し、
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
MANAGE_SCRIPT_PATH = LEVTECH_SCRIPTS_DIR / "manage_profile_resume.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "levtech_direct" / "profile"
BACKUP_DIR = DEFAULT_OUTPUT_DIR / "backups"
TARGET_URL = "https://levtech-direct.jp/mypage/profile/resume"
RESUME_MD_PATH = PROJECT_ROOT / "profile" / "resume.md"
SKILLS_MD_PATH = PROJECT_ROOT / "profile" / "skills.md"


def execute_browser_action(
    session: str,
    action: str,
    payload: dict[str, Any] | None = None,
    dry_run: bool = False,
    timeout: float = 40.0,
) -> dict[str, Any]:
    """manage_profile_resume.mjs に action, payload, isDryRun を注入して実行する."""
    if not MANAGE_SCRIPT_PATH.exists():
        raise RuntimeError(f"管理スクリプトが見つかりません: {MANAGE_SCRIPT_PATH}")

    profile_path = resolve_profile_path(session)
    run_playwright_cmd([f"-s={session}", "open", TARGET_URL, f"--profile={profile_path}"])

    template_code = MANAGE_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = (
        template_code.replace("'__LEVTECH_ACTION__'", json.dumps(action))
        .replace("__LEVTECH_PAYLOAD__", json.dumps(payload or {}, ensure_ascii=False))
        .replace("__LEVTECH_DRY_RUN__", "true" if dry_run else "false")
    )

    tmp_script_path = LEVTECH_SCRIPTS_DIR / f".tmp_manage_resume_{action}.mjs"
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


def format_resume_markdown(data: dict[str, Any], fetched_at: datetime) -> str:
    """職務経歴・自己PRデータを構造化フロントマター付きMarkdownに整形する."""
    d = data.get("data", data)
    resume_text = d.get("resume", "")
    char_count = d.get("charCount", len(resume_text))
    max_char_count = d.get("maxCharCount", 30000)
    updated_at_text = d.get("updatedAtText", "")

    lines = [
        "---",
        "source: levtech_direct",
        "type: profile_resume",
        f"updated_at: '{fetched_at.isoformat(timespec='seconds')}'",
        f"url: '{TARGET_URL}'",
        f"char_count: {char_count}",
        f"max_char_count: {max_char_count}",
    ]
    if updated_at_text:
        lines.append(f"site_updated_at: '{updated_at_text}'")
    lines.extend([
        "---",
        "",
        "# レバテックダイレクト 職務経歴・自己PR",
        "",
        f"- **文字数**: {char_count:,} / {max_char_count:,} 文字",
    ])
    if updated_at_text:
        lines.append(f"- **サイト上最終更新**: {updated_at_text}")

    lines.extend([
        "",
        "## 登録テキスト",
        "",
        resume_text if resume_text else "(未登録)",
        "",
    ])

    return "\n".join(lines)


def print_formatted_summary(data: dict[str, Any]) -> None:
    """職務経歴・自己PRサマリをコンソールに整形出力する."""
    d = data.get("data", data)
    resume_text = d.get("resume", "")
    char_count = d.get("charCount", len(resume_text))
    max_char_count = d.get("maxCharCount", 30000)

    print("\n========================================================")
    print(" レバテックダイレクト 職務経歴・自己PR サマリ")
    print(f" URL:        {TARGET_URL}")
    print(f" 文字数:     {char_count:,} / {max_char_count:,} 文字")
    if d.get("updatedAtText"):
        print(f" 最終更新:   {d.get('updatedAtText')}")
    print("========================================================\n")

    if resume_text:
        preview = resume_text[:500] + ("\n...(中略)..." if len(resume_text) > 500 else "")
        print("【登録内容プレビュー】")
        print(preview)
    else:
        print("(現在職務経歴・自己PRは未登録です)")
    print("\n" + "=" * 56 + "\n")


def print_diff(previous: str, new: str) -> None:
    """テキスト差分（unified diff）を人間可読に出力する."""
    prev_lines = previous.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(
        prev_lines,
        new_lines,
        fromfile="現在の職務経歴・自己PR (レバテックダイレクト)",
        tofile="更新後の職務経歴・自己PR",
        lineterm="",
    )
    diff_text = "".join(diff)
    if not diff_text.strip():
        print("（テキストに変更差分はありません）", file=sys.stderr)
    else:
        print("\n--- 変更差分プレビュー (Unified Diff) ---", file=sys.stderr)
        for line in diff_text.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                print(f"\033[32m{line}\033[0m", file=sys.stderr)
            elif line.startswith("-") and not line.startswith("---"):
                print(f"\033[31m{line}\033[0m", file=sys.stderr)
            elif line.startswith("@@"):
                print(f"\033[36m{line}\033[0m", file=sys.stderr)
            else:
                print(line, file=sys.stderr)
        print("------------------------------------------\n", file=sys.stderr)


def save_resume_result(data: dict[str, Any], output_dir: Path, backup_only: bool = False) -> list[Path]:
    """職務経歴・自己PRデータをJSONおよびMarkdownで永続化する."""
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    saved_files: list[Path] = []

    # 1. バックアップ保存
    backup_file = BACKUP_DIR / f"resume_{now.strftime('%Y%m%d_%H%M%S')}.json"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    saved_files.append(backup_file)

    if backup_only:
        return saved_files

    # 2. 最新JSON保存
    latest_json = output_dir / "resume.json"
    latest_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    saved_files.append(latest_json)

    # 3. 最新Markdown保存
    md_content = format_resume_markdown(data, now)
    latest_md = output_dir / "resume.md"
    latest_md.write_text(md_content, encoding="utf-8")
    saved_files.append(latest_md)

    return saved_files


def generate_resume_text_from_profile() -> str:
    """profile/resume.md および profile/skills.md を統合し、レバテックダイレクト用の職務経歴・自己PRテキストを生成する."""
    if not RESUME_MD_PATH.exists():
        raise FileNotFoundError(f"職務経歴書マスターが見つかりません: {RESUME_MD_PATH}")

    resume_text = RESUME_MD_PATH.read_text(encoding="utf-8")
    skills_text = SKILLS_MD_PATH.read_text(encoding="utf-8") if SKILLS_MD_PATH.exists() else ""

    parts: list[str] = []

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
        "・言語/FW: Python (FastAPI), TypeScript/JavaScript (Next.js, React, React Router), Java (Spring Boot), C# (.NET), Go, SQL",
        "・クラウド/インフラ: Azure (実務1年+個人開発1.5年 / APIM, AKS, Container Apps, AI Search 等), Kubernetes / AKS (実務半年), IaC (Terraform, Bicep 1.5年), Docker, GCP, AWS",
        "・AI/LLM/エージェント技術: Microsoft Foundry Agent (Prompt Agent), Azure OpenAI Service, Azure APIM AI Gateway/OBO認証, Foundry Local (SLM), LangChain, Playwright",
        "・開発自動化/基盤: GitHub Agentic Workflow (PR自動レビュー基盤), AIコーディングエージェント活用基盤（ルール/スキル整備）, CI/CD (GitHub Actions, GitLab CI/CD, Azure DevOps)",
    ]
    parts.append("\n".join(skills_lines))

    # 3. 職務経歴詳細（プロジェクト抜粋）
    parts.append("\n【職務経歴】")
    career_match = ""
    in_career = False
    for line in resume_text.splitlines():
        if line.startswith("## 職務経歴"):
            in_career = True
            continue
        if in_career:
            if line.startswith("## 学歴") or line.startswith("## 課外活動"):
                break
            career_match += line + "\n"
    career_clean = career_match.strip()
    if career_clean:
        formatted_career = (
            career_clean.replace("### 1. ", "■ 1. ")
            .replace("### 2. ", "■ 2. ")
            .replace("#### プロジェクト", "▼ プロジェクト")
            .replace("---", "")
        )
        parts.append(formatted_career.strip())

    # 4. 自身の強み・自己PR
    parts.append("\n【自己PR・自身の強み】")
    pr_lines = [
        "1. 自発的に学びの機会を創出し周囲を巻き込む主体性",
        "   現職（ヘッドウォータース）では通常業務で接点のない社内テックリードを自ら巻き込み、業務時間外で共同アプリケーション開発を推進。より高度なアーキテクチャや実践知見を主体的に吸収・実践しています。社内LT登壇や週次勉強会の主催など、組織を越えて知見を共有する行動を継続しています。",
        "",
        "2. 最新のAI技術を先取りし開発現場に還元する推進力",
        "   生成AIや最新エージェント技術（Agentic AI, Foundry Agent, Claude Code, Copilot, MCP, SLM等）をいち早く検証・実務導入。AIエージェント向けルール/スキル整備やPR自動レビュー基盤を構築し、チーム全体の開発生産性とコード品質を大幅に引き上げました。",
        "",
        "3. 未知の環境でも自律的仮説検証で突破する問題解決力",
        "   ドキュメントの乏しい新技術（SLM/Foundry Local、Azure APIM AI Gateway、OBO認証フロー）でも、ソースコードや実地環境のエラーログから仕様を独自に解明し、早期にプロトタイプ実装や技術レポート作成を完遂する突破力を備えています。",
    ]
    parts.append("\n".join(pr_lines))

    # 5. 主な実績・課外活動・資格
    parts.append("\n【課外活動・ハッカソン実績・資格】")
    activities_lines = [
        "・第4回 Agentic AI Hackathon with Google Cloud ファイナリスト（2026年2月）",
        "  機械学習モデルチューニングWebアプリ（Visionfy）の開発において、フロントエンド（Next.js）、バックエンド（Python）、インフラ（GCP）の実装全般を主導。",
        "・自作AIツール・MCPサーバー運用: GCP上に自作MCPサーバーをデプロイし、Claude連携環境や日常開発自動化CLIツールを自作・運用。",
        "・学歴: 2024年3月 東京大学 文学部 西洋古典学専修 卒業",
        "・語学・資格: TOEIC 955点（ビジネスレベル英語）、基本情報技術者試験（2022年）、ITパスポート",
    ]
    parts.append("\n".join(activities_lines))

    text = "\n".join(parts)
    return text.replace("\r\n", "\n")


def parse_args() -> argparse.Namespace:
    parser = create_base_parser(
        description="レバテックダイレクト 職務経歴・自己PR（/mypage/profile/resume）管理スクリプト"
    )
    parser.add_argument(
        "--session",
        default="job-hunt",
        help="使用するブラウザプロファイル名（デフォルト: job-hunt）",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="サブコマンド")

    # fetch
    fetch_parser = subparsers.add_parser("fetch", help="現在の職務経歴・自己PRを取得して保存する（デフォルト）")
    fetch_parser.add_argument("-s", "--summary", action="store_true", help="サマリ表示")
    fetch_parser.add_argument("--json", action="store_true", help="JSON出力")
    fetch_parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"データ保存先ディレクトリ（デフォルト: {to_relative_path(DEFAULT_OUTPUT_DIR)}）",
    )

    # update
    update_parser = subparsers.add_parser("update", help="指定したテキストまたはファイルで職務経歴・自己PRを更新する")
    update_parser.add_argument("-s", "--summary", action="store_true", help="サマリ表示")
    update_parser.add_argument("--json", action="store_true", help="JSON出力")
    group = update_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", type=str, help="直接指定したテキストで更新する")
    group.add_argument("--file", type=Path, help="指定したファイルの内容で更新する")
    update_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際の更新を行わず、差分（Unified Diff）と文字数をプレビュー表示する",
    )
    update_parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"データ保存先ディレクトリ（デフォルト: {to_relative_path(DEFAULT_OUTPUT_DIR)}）",
    )

    # sync
    sync_parser = subparsers.add_parser("sync", help="profile/resume.md および skills.md からレバテック用テキストを自動生成して更新する")
    sync_parser.add_argument("-s", "--summary", action="store_true", help="サマリ表示")
    sync_parser.add_argument("--json", action="store_true", help="JSON出力")
    sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際の更新を行わず、差分（Unified Diff）と文字数をプレビュー表示する",
    )
    sync_parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"データ保存先ディレクトリ（デフォルト: {to_relative_path(DEFAULT_OUTPUT_DIR)}）",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    # 1. サイト認証確認
    if not ensure_site_authenticated("levtech_direct", session=args.session, target_url=TARGET_URL, exit_on_fail=False):
        ctx.error("レバテックダイレクトの認証状態が確認できませんでした。")
        return 2

    subcmd = args.subcommand or "fetch"
    output_dir = getattr(args, "output_dir", DEFAULT_OUTPUT_DIR)

    # -------------------------------------------------------------
    # 閲覧アクション (fetch)
    # -------------------------------------------------------------
    if subcmd == "fetch":
        ctx.log("[INFO] レバテックダイレクト 職務経歴・自己PRを取得中...")
        try:
            res = execute_browser_action(args.session, action="fetch")
        except Exception as e:
            ctx.error(f"職務経歴・自己PR取得に失敗しました: {e}")
            return 1

        saved_files = save_resume_result(res, output_dir)
        ctx.add_result_paths(saved_files)

        return ctx.flush_outputs(
            summary_fn=lambda: print_formatted_summary(res),
            json_data=res,
        )

    # -------------------------------------------------------------
    # 更新アクション (update / sync)
    # -------------------------------------------------------------
    if subcmd in ("update", "sync"):
        new_resume_text = ""
        if subcmd == "sync":
            try:
                new_resume_text = generate_resume_text_from_profile()
            except Exception as e:
                ctx.error(f"プロファイルからのテキスト生成に失敗しました: {e}")
                return 1
        elif subcmd == "update":
            if getattr(args, "file", None) is not None:
                if not args.file.exists():
                    ctx.error(f"指定されたファイルが存在しません: {args.file}")
                    return 1
                new_resume_text = args.file.read_text(encoding="utf-8").replace("\r\n", "\n")
            elif getattr(args, "text", None) is not None:
                new_resume_text = args.text.replace("\r\n", "\n")

        # 文字数バリデーション (10文字以上、30,000文字以内)
        char_len = len(new_resume_text)
        if char_len < 10:
            ctx.error(
                f"テキスト文字数が不足しています: "
                f"{char_len}文字 < 最小10文字"
            )
            return 1
        if char_len > 30000:
            ctx.error(
                f"テキスト文字数がレバテックダイレクトの上限を超えています: "
                f"{char_len:,}文字 > 上限30,000文字"
            )
            return 1

        # 安全ガード: 変更前自動バックアップ
        try:
            current_data = execute_browser_action(args.session, action="fetch")
            backup_files = save_resume_result(current_data, output_dir, backup_only=True)
            ctx.log(f"[安全ガード] 変更前バックアップを保存しました: {to_relative_path(backup_files[0])}")
        except Exception as e:
            ctx.error(f"変更前自動バックアップに失敗したため処理を中断します: {e}")
            return 1

        cur_resume_text = current_data.get("data", {}).get("resume", "")

        # 差分判定
        if cur_resume_text == new_resume_text:
            ctx.log("[案内] 既存の内容と同一のため、更新の必要はありません。")
            saved_paths = save_resume_result(current_data, output_dir)
            ctx.add_result_paths(saved_paths)
            return ctx.flush_outputs(
                summary_fn=lambda: print_formatted_summary(current_data),
                json_data=current_data,
            )

        payload = {"resume": new_resume_text}

        # DRY-RUN
        if getattr(args, "dry_run", False):
            ctx.log(f"\n[DRY-RUN] 職務経歴・自己PRの更新プレビュー ({char_len:,}文字 / 上限30,000文字):")
            print_diff(cur_resume_text, new_resume_text)
            try:
                dry_res = execute_browser_action(
                    args.session,
                    action="update",
                    payload=payload,
                    dry_run=True,
                )
                can_submit = dry_res.get("canSubmit", False)
                ctx.log(f"[DRY-RUN 検証] フォーム入力後の送信ボタン活性化: {'OK (活性化)' if can_submit else '無効'}")
            except Exception as e:
                ctx.warn(f"[DRY-RUN 警告] フォーム検証中に例外が発生しました: {e}")
            ctx.log("[DRY-RUN] 変更は適用されていません。")
            return 0

        # 差分表示
        ctx.log(f"\n職務経歴・自己PR 更新差分 ({char_len:,}文字 / 上限30,000文字):")
        print_diff(cur_resume_text, new_resume_text)

        # 確認プロンプト
        if not args.force:
            if sys.stdin.isatty():
                confirm = input("上記の差分でレバテックダイレクトの職務経歴・自己PRを更新しますか？ [y/N]: ").strip().lower()
                if confirm not in ("y", "yes"):
                    ctx.log("[中止] ユーザー操作により更新をキャンセルしました。")
                    return 0
            else:
                ctx.error("[安全ガード] 非対話環境では --force または --dry-run の指定が必要です。")
                return 1

        # 実際の更新実行
        ctx.log("[実行] レバテックダイレクトの職務経歴・自己PRを保存中...")
        try:
            update_res = execute_browser_action(
                args.session,
                action="update",
                payload=payload,
                dry_run=False,
            )
        except Exception as e:
            ctx.error(f"更新処理に失敗しました: {e}")
            return 1

        saved_files = save_resume_result(update_res, output_dir)
        ctx.add_result_paths(saved_files)

        return ctx.flush_outputs(
            summary_fn=lambda: print_formatted_summary(update_res),
            json_data=update_res,
        )

    ctx.error(f"未知のサブコマンドです: {subcmd}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
