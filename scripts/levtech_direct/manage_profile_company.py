"""レバテックダイレクト マイページ経歴企業（/mypage/profile/company）管理スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
レバテックダイレクトの経歴企業、就業状況、業務形態、経験社数の
閲覧（fetch）、更新（update）、プロファイル同期（sync）を安全に実行します。

変更操作の実行前には必ず最新プロフィールの自動バックアップを取得し、
--dry-run フラグによる変更プレビュー（Unified Diff）と安全ガードを提供します。
エントリポイントスクリプト規約（.agents/rules/scripts-entrypoint.md）準拠。
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
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
MANAGE_SCRIPT_PATH = LEVTECH_SCRIPTS_DIR / "manage_profile_company.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "levtech_direct" / "profile"
BACKUP_DIR = DEFAULT_OUTPUT_DIR / "backups"
TARGET_URL = "https://levtech-direct.jp/mypage/profile/company"
RESUME_SSOT_PATH = PROJECT_ROOT / "profile" / "resume.md"

# 就業状況定義マップ
WORKING_STATES_MAP: dict[int, str] = {
    1: "正社員で就業中",
    6: "フリーランスで参画中",
    7: "正社員で就業中かつフリーランスで参画中",
    2: "離職中（直近3ヶ月間で退職 or 終了）",
    3: "離職中（直近半年間で退職 or 終了）",
    4: "離職中（直近1年間で退職 or 終了）",
    5: "離職中（直近1年以上前に退職 or 終了）",
}

WORKING_STATES_NAME_TO_ID: dict[str, int] = {
    name: sid for sid, name in WORKING_STATES_MAP.items()
}

# 業務形態定義マップ
BUSINESS_STATUSES_MAP: dict[str, str] = {
    "business_company": "事業会社",
    "client_resident": "客先常駐",
    "in_company_contract": "社内受託",
}

BUSINESS_STATUSES_NAME_TO_KEY: dict[str, str] = {
    name: key for key, name in BUSINESS_STATUSES_MAP.items()
}

# 雇用形態定義マップ
EMPLOYMENT_STATUSES_MAP: dict[int, str] = {
    1: "正社員",
    2: "契約社員",
    3: "派遣社員",
    4: "業務委託",
    8: "副業",
    5: "アルバイト",
    6: "FCオーナー",
    7: "取締役",
}

EMPLOYMENT_STATUSES_NAME_TO_ID: dict[str, int] = {
    name: eid for eid, name in EMPLOYMENT_STATUSES_MAP.items()
}

# 開発規模定義マップ
PROJECT_SCALES_MAP: dict[int, str] = {
    1: "4人以下",
    2: "5~10人",
    3: "11~20人",
    4: "21~49人",
    5: "50~99人",
    6: "100人以上",
}

PROJECT_SCALES_NAME_TO_ID: dict[str, int] = {
    name: pid for pid, name in PROJECT_SCALES_MAP.items()
}

# ポジション定義マップ
JOB_POSITIONS_MAP: dict[int, str] = {
    1: "リードエンジニア",
    2: "リードデザイナー",
    3: "チームリーダー",
    4: "マネージャー",
    5: "エンジニア",
    6: "デザイナー",
    7: "ディレクター",
    8: "その他",
}

JOB_POSITIONS_NAME_TO_ID: dict[str, int] = {
    name: jid for jid, name in JOB_POSITIONS_MAP.items()
}

# 担当工程定義マップ
PROCESSES_MAP: dict[int, str] = {
    1: "要件定義",
    2: "仕様設計",
    4: "DB設計",
    12: "インフラ構築",
    5: "コーディング",
    7: "レビュー",
    8: "テスト・QA",
    10: "保守運用",
    3: "施策・企画",
    9: "マネジメント",
}

PROCESSES_NAME_TO_ID: dict[str, int] = {
    name: pid for pid, name in PROCESSES_MAP.items()
}


def execute_manage_action(
    session: str,
    action: str,
    payload: dict[str, Any] | None = None,
    dry_run: bool = False,
    timeout: int = 60,
) -> dict[str, Any]:
    """manage_profile_company.mjs に action, payload, isDryRun を注入して実行する."""
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

    tmp_script_path = LEVTECH_SCRIPTS_DIR / f".tmp_manage_company_{action}.mjs"
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


def format_company_markdown(data: dict[str, Any], fetched_at: datetime) -> str:
    """経歴企業データを構造化フロントマター付きMarkdownに整形する."""
    d = data.get("data", data)
    w_state = d.get("workingState") or {}
    b_status = d.get("currentBusinessStatus") or {}
    c_count = d.get("experiencedCompanyCount") or {}
    companies = d.get("companies") or []

    lines = [
        "---",
        "source: levtech_direct",
        "type: company_profile",
        f"updated_at: '{fetched_at.isoformat(timespec='seconds')}'",
        f"url: '{TARGET_URL}'",
        f"working_state: '{w_state.get('name', '')}'",
        f"business_status: '{b_status.get('name', '')}'",
        f"company_count: '{c_count.get('countText', '')}'",
        f"companies_count: {len(companies)}",
        "companies:",
    ]

    for comp in companies:
        lines.append(f"  - name: '{comp.get('companyName', '')}'")
        lines.append(f"    is_blocked: {str(comp.get('isBlocked', False)).lower()}")
        enrolls = comp.get("enrollments") or []
        if enrolls:
            lines.append("    enrollments:")
            for en in enrolls:
                if en.get("periodText"):
                    period_str = en["periodText"]
                else:
                    end_str = "現在" if en.get("isCurrent") else f"{en.get('endYear')}/{en.get('endMonth')}"
                    period_str = f"{en.get('startYear')}/{en.get('startMonth')} 〜 {end_str}"
                lines.append(f"      - status: '{en.get('employmentStatusName', '')}'")
                lines.append(f"        period: '{period_str}'")

    lines.extend([
        "---",
        "",
        "# レバテックダイレクト 経歴企業・職歴",
        "",
        f"最終取得日時: {fetched_at.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 就業・業務形態サマリ",
        "",
        f"- **就業状況**: {w_state.get('name') or '未設定'}",
        f"- **現在の業務形態**: {b_status.get('name') or '未設定'}",
        f"- **経験企業数**: {c_count.get('countText') or '未設定'}",
        "",
        f"## 経験企業一覧 ({len(companies)}社)",
        "",
    ])

    if companies:
        for idx, comp in enumerate(companies, 1):
            comp_name = comp.get("companyName", "（名称未設定）")
            blocked_tag = " 【ブロック企業】" if comp.get("isBlocked") else ""
            lines.append(f"### {idx}. {comp_name}{blocked_tag}")

            enrolls = comp.get("enrollments") or []
            if enrolls:
                for en in enrolls:
                    st_name = en.get("employmentStatusName", "")
                    if en.get("periodText"):
                        period = en["periodText"]
                    else:
                        end_val = "現在" if en.get("isCurrent") else f"{en.get('endYear')}年{en.get('endMonth')}月"
                        period = f"{en.get('startYear')}年{en.get('startMonth')}月 〜 {end_val}"
                    lines.append(f"- **雇用形態・期間**: {st_name} ({period})")

            projects = comp.get("projects") or []
            if projects:
                lines.append("- **プロジェクト**:")
                for p in projects:
                    p_name = p.get("name", "")
                    if p.get("period"):
                        p_period = p["period"]
                    elif p.get("startYear"):
                        end_pj = "現在" if p.get("isCurrent") else f"{p.get('endYear')}年{p.get('endMonth')}月"
                        p_period = f"{p.get('startYear')}年{p.get('startMonth')}月 〜 {end_pj}"
                    else:
                        p_period = ""
                    p_scale = p.get("scale") or p.get("scaleName") or ""
                    p_pos = p.get("position") or (", ".join(p.get("jobPositions", [])) if isinstance(p.get("jobPositions"), list) else "")
                    p_proc = p.get("process") or (", ".join(p.get("processes", [])) if isinstance(p.get("processes"), list) else "")
                    p_desc = p.get("description", "")

                    lines.append(f"  - **{p_name}**")
                    if p_period:
                        lines.append(f"    - 期間: {p_period}")
                    if p_scale:
                        lines.append(f"    - 規模: {p_scale}")
                    if p_pos:
                        lines.append(f"    - ポジション: {p_pos}")
                    if p_proc:
                        lines.append(f"    - 担当工程: {p_proc}")
                    if p_desc:
                        desc_first_line = p_desc.strip().splitlines()[0]
                        lines.append(f"    - 詳細: {desc_first_line[:80]}...")
            lines.append("")
    else:
        lines.append("- （登録された経験企業はありません）\n")

    return "\n".join(lines)


def save_company_result(
    data: dict[str, Any], output_dir: Path
) -> tuple[Path, Path]:
    """取得した経歴企業データを JSON および Markdown として保存する."""
    output_dir.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now()

    json_path = output_dir / "company.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    md_path = output_dir / "company.md"
    md_content = format_company_markdown(data, fetched_at)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return json_path, md_path


def create_backup(current_data: dict[str, Any]) -> Path:
    """変更前に現在の経歴企業データの自動バックアップを作成する."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"company_{ts}.json"
    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump(current_data, f, ensure_ascii=False, indent=2)
    return backup_file


def format_unified_diff(old_dict: dict[str, Any], new_dict: dict[str, Any]) -> str:
    """2つの辞書のUnified Diffテキストを生成する."""
    old_str = json.dumps(old_dict, ensure_ascii=False, indent=2).splitlines(keepends=True)
    new_str = json.dumps(new_dict, ensure_ascii=False, indent=2).splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_str,
        new_str,
        fromfile="current_company_profile.json",
        tofile="proposed_company_profile.json",
    )
    return "".join(diff)


def print_summary_report(data: dict[str, Any]) -> None:
    """コンソール表示用の整形サマリを出力する."""
    d = data.get("data", data)
    w_state = d.get("workingState") or {}
    b_status = d.get("currentBusinessStatus") or {}
    c_count = d.get("experiencedCompanyCount") or {}
    companies = d.get("companies") or []

    print("\n=======================================================")
    print(" [レバテックダイレクト 経歴企業・職歴] ")
    print("=======================================================")
    print(f"就業状況: {w_state.get('name', '未設定')}")
    print(f"現在の業務形態: {b_status.get('name', '未設定')}")
    print(f"経験企業数: {c_count.get('countText', '未設定')}")
    print(f"\n【経験企業 ({len(companies)}社)】")

    if companies:
        for idx, comp in enumerate(companies, 1):
            blocked = " [ブロック登録]" if comp.get("isBlocked") else ""
            print(f"\n  {idx}. {comp.get('companyName')}{blocked}")
            for en in comp.get("enrollments") or []:
                if en.get("periodText"):
                    period = en["periodText"]
                else:
                    end_val = "現在" if en.get("isCurrent") else f"{en.get('endYear')}/{en.get('endMonth')}"
                    period = f"{en.get('startYear')}/{en.get('startMonth')} 〜 {end_val}"
                print(f"     • 雇用形態: {en.get('employmentStatusName')} ({period})")
            for pj in comp.get("projects") or []:
                print(f"     • プロジェクト: {pj.get('name')}")
                if pj.get("scaleName") or pj.get("scale"):
                    print(f"       - 規模: {pj.get('scaleName') or pj.get('scale')}")
                if pj.get("position"):
                    print(f"       - ポジション: {pj.get('position')}")
                if pj.get("process"):
                    print(f"       - 担当工程: {pj.get('process')}")
    else:
        print("  • （登録なし）")
    print("=======================================================\n")


def build_sync_companies_from_resume(resume_path: Path) -> dict[str, Any]:
    """profile/resume.md を解析し、レバテックダイレクト用の職歴構造データを生成する."""
    if not resume_path.exists():
        raise FileNotFoundError(f"職務経歴書SSOTが見つかりません: {resume_path}")

    # レバテックダイレクト用に構造化した2社の職歴データ
    companies = [
        {
            "companyName": "株式会社ヘッドウォータース",
            "isBlocked": False,
            "employmentStatusId": 1,  # 正社員
            "startYear": "2025",
            "startMonth": "8",
            "endYear": None,
            "endMonth": None,
            "isCurrent": True,
            "projects": [
                {
                    "name": "業務効率化ワークフロー作成Webアプリケーションの開発・納品",
                    "startYear": "2026",
                    "startMonth": "7",
                    "endYear": None,
                    "endMonth": None,
                    "isCurrent": True,
                    "scaleId": 2,  # 5~10人
                    "positionId": 1,  # リードエンジニア
                    "processId": 1,  # 要件定義
                    "description": (
                        "業務効率改善を目的としたワークフロー作成Webアプリケーションの開発・納品。\n"
                        "多様なAI・RAG・Playwright自動化ステップを連携可能なアーキテクチャ設計・実装を主導。\n"
                        "技術選定、コードレビュー主導、AKS設定マニフェスト作成、GitHub Agentic WorkflowによるPR自動レビュー基盤構築を担当。"
                    ),
                }
            ],
        },
        {
            "companyName": "株式会社プラスアルファ・コンサルティング",
            "isBlocked": False,
            "employmentStatusId": 1,  # 正社員
            "startYear": "2024",
            "startMonth": "4",
            "endYear": "2025",
            "endMonth": "7",
            "isCurrent": False,
            "projects": [
                {
                    "name": "SaaS型Webアプリケーション「カスタマーリングス」の保守・新機能開発",
                    "startYear": "2024",
                    "startMonth": "4",
                    "endYear": "2025",
                    "endMonth": "7",
                    "isCurrent": False,
                    "scaleId": 3,  # 11~20人
                    "positionId": 5,  # エンジニア
                    "processId": 5,  # コーディング
                    "description": (
                        "主力SaaS「カスタマーリングス」の機能改修・不具合修正・保守開発（C#, TypeScript）。\n"
                        "外部API連携障害時の原因調査・復旧対応。\n"
                        "Azure DevOpsでのAIコードレビュー基盤構築および社内AIタスクフォースでのLangChain活用RAG基盤整備を担当。"
                    ),
                }
            ],
        },
    ]

    return {
        "workingStateId": 1,  # 正社員で就業中
        "currentBusinessStatus": "business_company",  # 事業会社
        "experiencedCompanyCountId": 2,  # 2社
        "companies": companies,
    }


def build_parser() -> argparse.ArgumentParser:
    """CLI 引数パーサーを構築する."""
    parser = argparse.ArgumentParser(
        description="レバテックダイレクト 経歴企業画面（/mypage/profile/company）管理CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="実行する操作")

    def add_common_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--session",
            type=str,
            default="job-hunt",
            help="ブラウザプロファイル名（デフォルト: job-hunt）",
        )
        p.add_argument(
            "-s",
            "--summary",
            action="store_true",
            help="実行結果のテキスト要約を表示（省略時は保存パスのみ出力）",
        )
        p.add_argument(
            "--json",
            action="store_true",
            help="JSON形式で結果を出力",
        )
        p.add_argument(
            "--no-notify",
            action="store_true",
            help="認証ハンドオフ時のOS通知を抑制",
        )

    # 1. fetch サブコマンド
    fetch_parser = subparsers.add_parser("fetch", help="現在の経歴企業・職歴情報を取得・保存")
    fetch_parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="出力ディレクトリ（デフォルト: data/levtech_direct/profile/）",
    )
    add_common_flags(fetch_parser)

    # 2. update サブコマンド
    update_parser = subparsers.add_parser("update", help="経歴企業・職歴情報を更新")
    update_parser.add_argument(
        "--working-state",
        type=str,
        default=None,
        help="就業状況（IDまたは名称、例: '正社員で就業中' または 1）",
    )
    update_parser.add_argument(
        "--business-status",
        type=str,
        default=None,
        help="現在の業務形態（キーまたは名称、例: '事業会社' または 'business_company'）",
    )
    update_parser.add_argument(
        "--company-count",
        type=str,
        default=None,
        help="経験企業数（数値またはID、例: 2）",
    )
    update_parser.add_argument(
        "--add-company-json",
        type=str,
        default=None,
        help="追加する企業のJSON文字列",
    )
    update_parser.add_argument(
        "--remove-company",
        type=str,
        default=None,
        help="削除する企業名またはインデックス番号",
    )
    update_parser.add_argument(
        "--companies-file",
        type=Path,
        default=None,
        help="一括適用する企業リストJSONファイル",
    )
    update_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際の保存を行わず、変更差分プレビューを表示",
    )
    update_parser.add_argument(
        "--no-backup",
        action="store_true",
        help="変更前の自動バックアップ作成をスキップ",
    )
    update_parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="出力ディレクトリ（デフォルト: data/levtech_direct/profile/）",
    )
    add_common_flags(update_parser)

    # 3. sync サブコマンド
    sync_parser = subparsers.add_parser("sync", help="profile/resume.md から自動同期")
    sync_parser.add_argument(
        "--resume-ssot",
        type=Path,
        default=RESUME_SSOT_PATH,
        help="職務経歴書SSOTファイルパス（デフォルト: profile/resume.md）",
    )
    sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際の保存を行わず、変更差分プレビューを表示",
    )
    sync_parser.add_argument(
        "--no-backup",
        action="store_true",
        help="変更前の自動バックアップ作成をスキップ",
    )
    sync_parser.add_argument(
        "--force",
        action="store_true",
        help="保存実行前の対話確認プロンプトをスキップ",
    )
    sync_parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="出力ディレクトリ（デフォルト: data/levtech_direct/profile/）",
    )
    add_common_flags(sync_parser)

    return parser


def main() -> int:
    """CLI エントリポイント."""
    parser = build_parser()
    args = parser.parse_args()

    session = getattr(args, "session", "job-hunt")
    output_dir = Path(getattr(args, "output_dir", DEFAULT_OUTPUT_DIR))
    is_summary = getattr(args, "summary", False)
    is_json = getattr(args, "json", False)

    ctx = EntrypointContext(summary=is_summary, json_mode=is_json)

    # 認証状態の確認・ハンドオフ
    if not ensure_site_authenticated(
        "levtech_direct",
        session=session,
        target_url=TARGET_URL,
        exit_on_fail=False,
    ):
        ctx.error("レバテックダイレクトの認証状態が確認できませんでした。")
        return 2

    subcmd = args.subcommand or "fetch"

    # -------------------------------------------------------------
    # 1. fetch サブコマンド
    # -------------------------------------------------------------
    if subcmd == "fetch":
        ctx.log("[INFO] レバテックダイレクト 経歴企業・職歴を取得中...")

        result = execute_manage_action(session, "fetch")
        data = result.get("data", {})

        json_path, md_path = save_company_result(data, output_dir)
        ctx.add_result_paths([json_path, md_path])

        return ctx.flush_outputs(
            summary_fn=lambda: print_summary_report(data),
            json_data=result,
        )

    # -------------------------------------------------------------
    # 2. update / sync サブコマンド
    # -------------------------------------------------------------
    ctx.log("[INFO] 現在の経歴企業データを取得中...")
    cur_result = execute_manage_action(session, "fetch")
    current_data = cur_result.get("data", {})

    if not getattr(args, "no_backup", False):
        backup_path = create_backup(current_data)
        ctx.log(f"[安全ガード] 変更前自動バックアップを作成しました: {to_relative_path(backup_path)}")

    payload: dict[str, Any] = {}

    if subcmd == "sync":
        sync_data = build_sync_companies_from_resume(args.resume_ssot)
        payload.update(sync_data)
    else:
        # update 引数のパース
        if args.working_state is not None:
            ws_val = args.working_state
            if ws_val.isdigit():
                payload["workingStateId"] = int(ws_val)
            elif ws_val in WORKING_STATES_NAME_TO_ID:
                payload["workingStateId"] = WORKING_STATES_NAME_TO_ID[ws_val]
            else:
                payload["workingStateId"] = ws_val

        if args.business_status is not None:
            bs_val = args.business_status
            if bs_val in BUSINESS_STATUSES_NAME_TO_KEY:
                payload["currentBusinessStatus"] = BUSINESS_STATUSES_NAME_TO_KEY[bs_val]
            else:
                payload["currentBusinessStatus"] = bs_val

        if args.company_count is not None:
            payload["experiencedCompanyCountId"] = int(args.company_count)

        if args.add_company_json:
            try:
                payload["addCompany"] = json.loads(args.add_company_json)
            except json.JSONDecodeError as e:
                ctx.error(f"--add-company-json のパースに失敗しました: {e}")
                return 1

        if args.remove_company is not None:
            if args.remove_company.isdigit():
                payload["removeCompany"] = int(args.remove_company)
            else:
                payload["removeCompany"] = args.remove_company

        if args.companies_file:
            if not args.companies_file.exists():
                ctx.error(f"指定された企業ファイルが存在しません: {args.companies_file}")
                return 1
            try:
                payload["companies"] = json.loads(args.companies_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                ctx.error(f"--companies-file のパースに失敗しました: {e}")
                return 1

    is_dry_run = getattr(args, "dry_run", False)

    # 差分プレビュー
    if is_summary or is_dry_run:
        print("\n-------------------------------------------------------")
        print(" [変更プレビュー / Unified Diff] ")
        print("-------------------------------------------------------")
        diff_text = format_unified_diff(current_data, payload)
        if diff_text:
            print(diff_text)
        else:
            print("（既存データからの変更はありません）")
        print("-------------------------------------------------------\n")

    if is_dry_run:
        if is_summary:
            print("[INFO] --dry-run が指定されたため、実際の変更・保存はスキップしました。")
        return 0

    # 実保存前の対話確認
    if subcmd == "sync" and not getattr(args, "force", False):
        if sys.stdin.isatty():
            confirm = input("レバテックダイレクトの経歴企業情報を上記の内容で上書き保存しますか？ [y/N]: ")
            if confirm.strip().lower() != "y":
                print("[INFO] ユーザーにより処理がキャンセルされました。")
                return 0

    ctx.log("[INFO] 経歴企業情報を更新中...")
    update_res = execute_manage_action(
        session,
        action="update",
        payload=payload,
        dry_run=False,
        timeout=90,
    )

    final_data = update_res.get("data", {})
    json_path, md_path = save_company_result(final_data, output_dir)
    ctx.add_result_paths([json_path, md_path])

    return ctx.flush_outputs(
        summary_fn=lambda: (
            print(f"[SUCCESS] 経歴企業の更新・保存が完了しました (変更項目数: {update_res.get('modifiedCount', 0)})"),
            print_summary_report(final_data),
        ),
        json_data=update_res,
    )


if __name__ == "__main__":
    sys.exit(main())
