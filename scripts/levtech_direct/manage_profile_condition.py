"""レバテックダイレクト マイページ希望条件（/mypage/profile/condition）管理スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
レバテックダイレクトの希望条件（希望年収、勤務地、職種、スキル、リモート条件、
業務内容・技術領域への意欲、雇用形態、こだわり条件等）の
閲覧（fetch）、更新（update）、プロファイル同期（sync）を安全に実行します。

変更操作の実行前には必ず最新希望条件の自動バックアップを取得し、
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
MANAGE_SCRIPT_PATH = LEVTECH_SCRIPTS_DIR / "manage_profile_condition.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "levtech_direct" / "profile"
BACKUP_DIR = DEFAULT_OUTPUT_DIR / "backups"
TARGET_URL = "https://levtech-direct.jp/mypage/profile/condition"
PREFERENCES_PATH = PROJECT_ROOT / "profile" / "preferences.md"

# 都道府県マッピング（名前 -> p_ID）
PREFECTURE_NAME_TO_PLACE_ID: dict[str, str] = {
    "東京都": "p_1", "神奈川県": "p_2", "千葉県": "p_3", "埼玉県": "p_4", "茨城県": "p_5",
    "群馬県": "p_6", "栃木県": "p_7", "北海道": "p_8", "青森県": "p_9", "岩手県": "p_10",
    "宮城県": "p_11", "秋田県": "p_12", "山形県": "p_13", "福島県": "p_14", "新潟県": "p_15",
    "富山県": "p_16", "石川県": "p_17", "福井県": "p_18", "山梨県": "p_19", "長野県": "p_20",
    "愛知県": "p_21", "岐阜県": "p_22", "静岡県": "p_23", "三重県": "p_24", "大阪府": "p_25",
    "兵庫県": "p_26", "京都府": "p_27", "滋賀県": "p_28", "奈良県": "p_29", "和歌山県": "p_30",
    "鳥取県": "p_31", "島根県": "p_32", "岡山県": "p_33", "広島県": "p_34", "山口県": "p_35",
    "徳島県": "p_36", "香川県": "p_37", "愛媛県": "p_38", "高知県": "p_39", "福岡県": "p_40",
    "佐賀県": "p_41", "長崎県": "p_42", "熊本県": "p_43", "大分県": "p_44", "宮崎県": "p_45",
    "鹿児島県": "p_46", "沖縄県": "p_47", "海外": "p_48",
}

# 意欲レベルマッピング
DESIRE_LEVEL_LABELS: dict[str, str] = {
    "strongly_desire": "強く希望",
    "desire": "希望",
    "not_motivated": "こだわらない",
    "refuse": "希望しない",
}

# 企業フェーズ・条件マッピング
BUSINESS_FORM_LABELS: dict[str, str] = {
    "in_house_development": "自社開発",
    "entrusted_development": "受託開発",
    "none": "こだわらない",
}
REMOTE_WORK_LABELS: dict[str, str] = {
    "full_remote": "フルリモート",
    "hybrid_work": "ハイブリッド勤務（リモート＋出社）",
    "none": "こだわらない",
}
PROJECT_SCALE_LABELS: dict[str, str] = {
    "venture_or_startup": "ベンチャー・スタートアップ",
    "large_company_or_listed": "大手・上場企業",
    "none": "こだわらない",
}

# 業務内容ラベル
BUSINESS_ITEM_LABELS: dict[str, str] = {
    "newBusinessStartUp": "新規事業立ち上げ",
    "servicePlanningProposal": "サービス企画・提案",
    "requirementDefinitionPlanning": "要件定義・基本設計",
    "pmDirection": "PM・ディレクション",
    "technologySelectionPromotion": "技術選定・技術推進",
    "architectureDesign": "アーキテクチャ設計",
    "codeQualityStandard": "コード品質・標準化",
    "developmentFlowEfficiency": "開発フロー改善・効率化",
    "coding": "コーディング・実装",
    "refactoring": "リファクタリング",
    "performanceTuning": "パフォーマンスチューニング",
    "bugInvestigation": "バグ調査・改修",
    "memberTraining": "メンバー育成・教育",
}

# 技術領域ラベル
TECH_DOMAIN_LABELS: dict[str, str] = {
    "serverApplication": "サーバーサイド・バックエンド",
    "frontApplication": "フロントエンド",
    "smartPhoneApplication": "スマートフォンアプリ",
    "infraMiddleware": "インフラ・ミドルウェア・クラウド",
    "embeddedControlSystem": "組込・制御系",
    "aiDataAnalysis": "AI・データ分析・機械学習",
    "technologyInvestigation": "要素技術調査・R&D",
}


def execute_manage_action(
    session: str,
    action: str,
    payload: dict[str, Any] | None = None,
    dry_run: bool = False,
    timeout: int = 45,
) -> dict[str, Any]:
    """manage_profile_condition.mjs に action, payload, isDryRun を注入して実行する."""
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

    tmp_script_path = LEVTECH_SCRIPTS_DIR / f".tmp_manage_condition_{action}.mjs"
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


def format_condition_markdown(data: dict[str, Any], fetched_at: datetime) -> str:
    """希望条件データを構造化フロントマター付きMarkdownに整形する."""
    d = data.get("data", data)
    jc = d.get("jobConditions") or {}
    businesses = d.get("businesses") or {}
    techs = d.get("technologyDomains") or {}

    lines = [
        "---",
        "source: levtech_direct",
        "type: condition_profile",
        f"updated_at: '{fetched_at.isoformat(timespec='seconds')}'",
        f"url: '{TARGET_URL}'",
        "---",
        "",
        "# レバテックダイレクト 希望条件",
        "",
        "## 基本希望条件",
        f"- **希望年収**: {d.get('annualIncome', '')}万円" if d.get("annualIncome") else "- **希望年収**: 未設定",
        f"- **転職希望時期**: {d.get('jobChangePeriodLabel', '') or '未設定'}",
        f"- **事業形態**: {BUSINESS_FORM_LABELS.get(jc.get('businessForm', ''), jc.get('businessForm', '未設定'))}",
        f"- **リモートワーク**: {REMOTE_WORK_LABELS.get(jc.get('remoteWork', ''), jc.get('remoteWork', '未設定'))}",
        f"- **企業規模**: {PROJECT_SCALE_LABELS.get(jc.get('projectScale', ''), jc.get('projectScale', '未設定'))}",
        "",
        "## 希望職種・スキル・勤務地",
    ]

    # 職種
    occs = d.get("occupations") or []
    if occs:
        occ_names = [o.get("name") if isinstance(o, dict) else str(o) for o in occs]
        lines.append(f"- **希望職種**: {', '.join(occ_names)}")
    else:
        lines.append("- **希望職種**: 未設定")

    # スキル
    skills = d.get("skills") or []
    if skills:
        skill_names = [s.get("name") if isinstance(s, dict) else str(s) for s in skills]
        lines.append(f"- **希望スキル**: {', '.join(skill_names)}")
    else:
        lines.append("- **希望スキル**: 未設定")

    # 勤務地
    places = d.get("workPlaces") or []
    if places:
        place_names = [p.get("name") if isinstance(p, dict) else str(p) for p in places]
        lines.append(f"- **希望勤務地**: {', '.join(place_names)}")
    else:
        lines.append("- **希望勤務地**: 未設定")

    # 雇用形態
    statuses = d.get("desiredEmploymentStatuses") or []
    if statuses:
        status_names = [s.get("name") if isinstance(s, dict) else str(s) for s in statuses]
        lines.append(f"- **希望雇用形態**: {', '.join(status_names)}")
    else:
        lines.append("- **希望雇用形態**: 未設定")

    # こだわり条件
    styles = d.get("workStyles") or []
    if styles:
        style_names = [s.get("name") if isinstance(s, dict) else str(s) for s in styles]
        lines.append(f"- **こだわり条件**: {', '.join(style_names)}")

    # 業務内容への意欲
    lines.extend([
        "",
        "## 業務内容への意欲",
    ])
    for k, label in BUSINESS_ITEM_LABELS.items():
        v = businesses.get(k, "")
        v_label = DESIRE_LEVEL_LABELS.get(v, v or "未設定")
        lines.append(f"- **{label}**: {v_label}")

    # 技術領域への意欲
    lines.extend([
        "",
        "## 技術領域への意欲",
    ])
    for k, label in TECH_DOMAIN_LABELS.items():
        v = techs.get(k, "")
        v_label = DESIRE_LEVEL_LABELS.get(v, v or "未設定")
        lines.append(f"- **{label}**: {v_label}")

    # 必ず満たしたい条件
    reqs = d.get("requiredConditions") or []
    if reqs:
        req_names = [r.get("name") if isinstance(r, dict) else str(r) for r in reqs]
        lines.extend([
            "",
            "## 必ず満たしたい条件",
            f"- {', '.join(req_names)}",
        ])

    # 補足情報・その他
    if d.get("other"):
        lines.extend([
            "",
            "## 補足情報・その他の希望条件",
            f"```\n{d['other']}\n```",
        ])

    return "\n".join(lines) + "\n"


def print_formatted_summary(data: dict[str, Any]) -> None:
    """希望条件サマリをコンソールに整形出力する."""
    d = data.get("data", data)
    jc = d.get("jobConditions") or {}
    occs = [o.get("name") if isinstance(o, dict) else str(o) for o in (d.get("occupations") or [])]
    skills = [s.get("name") if isinstance(s, dict) else str(s) for s in (d.get("skills") or [])]
    places = [p.get("name") if isinstance(p, dict) else str(p) for p in (d.get("workPlaces") or [])]
    statuses = [s.get("name") if isinstance(s, dict) else str(s) for s in (d.get("desiredEmploymentStatuses") or [])]

    print("=" * 60, file=sys.stderr)
    print("【レバテックダイレクト 希望条件サマリ】", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"・希望年収: {d.get('annualIncome', '未設定')}万円", file=sys.stderr)
    print(f"・転職時期: {d.get('jobChangePeriodLabel', '未設定')}", file=sys.stderr)
    print(f"・自社/受託: {BUSINESS_FORM_LABELS.get(jc.get('businessForm', ''), jc.get('businessForm', '未設定'))}", file=sys.stderr)
    print(f"・リモート: {REMOTE_WORK_LABELS.get(jc.get('remoteWork', ''), jc.get('remoteWork', '未設定'))}", file=sys.stderr)
    print(f"・企業規模: {PROJECT_SCALE_LABELS.get(jc.get('projectScale', ''), jc.get('projectScale', '未設定'))}", file=sys.stderr)
    print(f"・希望勤務地: {', '.join(places) if places else '未設定'}", file=sys.stderr)
    print(f"・希望職種: {', '.join(occs) if occs else '未設定'}", file=sys.stderr)
    print(f"・希望スキル: {', '.join(skills) if skills else '未設定'}", file=sys.stderr)
    print(f"・雇用形態: {', '.join(statuses) if statuses else '未設定'}", file=sys.stderr)
    if d.get("other"):
        print(f"・その他条件: {d['other']}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)


def save_condition_result(
    result: dict[str, Any],
    output_dir: Path,
    backup_only: bool = False,
) -> list[Path]:
    """希望条件データを保存し、保存したファイルパスのリストを返す."""
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    saved: list[Path] = []

    if backup_only:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = now.strftime("%Y%m%d_%H%M%S")
        backup_file = BACKUP_DIR / f"condition_{ts}.json"
        backup_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        saved.append(backup_file)
        return saved

    # 通常保存
    md_file = output_dir / "condition.md"
    md_content = format_condition_markdown(result, now)
    md_file.write_text(md_content, encoding="utf-8")
    saved.append(md_file)

    json_file = output_dir / "condition.json"
    json_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    saved.append(json_file)

    return saved


def parse_preferences_for_condition(pref_path: Path) -> dict[str, Any]:
    """profile/preferences.md から希望条件設定用の辞書を構築する."""
    if not pref_path.exists():
        raise FileNotFoundError(f"希望条件正本ファイルが見つかりません: {pref_path}")

    text = pref_path.read_text(encoding="utf-8")

    payload: dict[str, Any] = {}

    # 最低希望年収の抽出 (例: target_annual_income_min: 5500000 -> 550万円)
    min_income_match = re.search(r"target_annual_income_min:\s*(\d+)", text)
    if min_income_match:
        val = int(min_income_match.group(1)) // 10000
        payload["annualIncome"] = val

    # リモートワーク設定 (ハイブリッド勤務許容)
    payload["jobConditions"] = {
        "businessForm": "in_house_development",
        "remoteWork": "hybrid_work",
        "projectScale": "venture_or_startup",
    }

    # 転職希望時期: 2（半年以内に）
    payload["jobChangePeriod"] = 2

    # 雇用形態: 正社員
    payload["desiredEmploymentStatuses"] = ["regular_employee"]

    # 勤務地: 東京都, 神奈川県
    payload["workPlaces"] = ["p_1", "p_2"]

    # スキル
    payload["skills"] = ["Go", "Node.js", "React", "Next.js", "TypeScript", "Python"]

    # 業務内容への意欲
    payload["businesses"] = {
        "coding": "strongly_desire",
        "refactoring": "strongly_desire",
        "performanceTuning": "strongly_desire",
        "technologySelectionPromotion": "strongly_desire",
        "architectureDesign": "strongly_desire",
        "developmentFlowEfficiency": "desire",
        "newBusinessStartUp": "desire",
        "servicePlanningProposal": "refuse",
        "requirementDefinitionPlanning": "not_motivated",
        "pmDirection": "not_motivated",
        "codeQualityStandard": "not_motivated",
        "bugInvestigation": "desire",
        "memberTraining": "not_motivated",
    }

    # 技術領域への意欲
    payload["technologyDomains"] = {
        "serverApplication": "strongly_desire",
        "aiDataAnalysis": "strongly_desire",
        "frontApplication": "desire",
        "smartPhoneApplication": "desire",
        "infraMiddleware": "desire",
        "technologyInvestigation": "desire",
        "embeddedControlSystem": "not_motivated",
    }

    # こだわり条件 (workStyles): 22(副業もしたい), 15(フレックスタイムで働きたい)
    payload["workStyles"] = [15, 22]

    # 補足情報 (other)
    payload["other"] = (
        "フルリモートまたは都内への週1〜2日出社（ハイブリッド）を希望しています。"
        "モダンWeb・バックエンド（Go / Microservices / Next.js）および生成AI/LLMを活用したプロダクト開発に意欲があります。"
    )

    return payload


def print_diff(before_data: dict[str, Any], after_data: dict[str, Any]) -> None:
    """更新前後の差分をUnified Diffでstderrにプレビュー表示する."""
    before_str = format_condition_markdown(before_data, datetime.now())
    after_str = format_condition_markdown(after_data, datetime.now())

    diff = list(
        difflib.unified_diff(
            before_str.splitlines(keepends=True),
            after_str.splitlines(keepends=True),
            fromfile="現在の設定 (Current)",
            tofile="更新後の設定 (Updated)",
            n=3,
        )
    )

    if diff:
        print("\n--- 変更差分プレビュー (Unified Diff) ---", file=sys.stderr)
        diff_text = "".join(diff)
        print(diff_text, file=sys.stderr)
        print("-------------------------------------\n", file=sys.stderr)
    else:
        print("\n[差分なし] 登録内容に変更はありません。\n", file=sys.stderr)


def add_common_flags(p: argparse.ArgumentParser) -> None:
    """サブパーサーにも共通フラグを追加して位置によらず指定可能にする."""
    p.add_argument("-s", "--summary", action="store_true", default=argparse.SUPPRESS, help="コンソール向け整形サマリ表示")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="結果をJSON形式で標準出力に出力")
    p.add_argument("--session", type=str, default=argparse.SUPPRESS, help="セッション名 (デフォルト: job-hunt)")


def build_parser() -> argparse.ArgumentParser:
    """CLIパーサーを構築する."""
    parser = create_base_parser(
        description="レバテックダイレクト 希望条件画面（/mypage/profile/condition）管理スクリプト"
    )
    parser.add_argument("--session", type=str, default="job-hunt", help="セッション名 (デフォルト: job-hunt)")

    subparsers = parser.add_subparsers(dest="subcommand", help="実行する操作")

    # 1. fetch サブコマンド
    fetch_parser = subparsers.add_parser("fetch", help="現在の希望条件を取得して保存・表示")
    fetch_parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="出力ディレクトリ（デフォルト: data/levtech_direct/profile/）",
    )
    add_common_flags(fetch_parser)

    # 2. update サブコマンド
    update_parser = subparsers.add_parser("update", help="希望条件を更新")
    update_parser.add_argument("--dry-run", action="store_true", help="保存を実行せず差分プレビューのみ表示")
    update_parser.add_argument("--annual-income", type=int, help="希望年収（万円単位、例: 600）")
    update_parser.add_argument(
        "--remote",
        choices=["full_remote", "hybrid_work", "none"],
        help="リモート条件",
    )
    update_parser.add_argument(
        "--business-form",
        choices=["in_house_development", "entrusted_development", "none"],
        help="事業形態",
    )
    update_parser.add_argument(
        "--project-scale",
        choices=["venture_or_startup", "large_company_or_listed", "none"],
        help="企業規模",
    )
    update_parser.add_argument(
        "--job-change-period",
        type=int,
        choices=[1, 2, 3, 4, 5],
        help="転職希望時期 (1:3ヶ月以内, 2:半年以内, 3:1年以内, 4:良い仕事があれば, 5:未定)",
    )
    update_parser.add_argument(
        "--work-places",
        type=str,
        help="希望勤務地（カンマ区切り、例: 東京都,神奈川県 または p_1,p_2）",
    )
    update_parser.add_argument(
        "--occupations",
        type=str,
        help="希望職種ID（カンマ区切り、例: 16,12）",
    )
    update_parser.add_argument(
        "--skills",
        type=str,
        help="希望スキル名（カンマ区切り、例: Go,Node.js,React,Next.js）",
    )
    update_parser.add_argument(
        "--employment-statuses",
        type=str,
        help="希望雇用形態（カンマ区切り、例: regular_employee）",
    )
    update_parser.add_argument(
        "--work-styles",
        type=str,
        help="こだわり条件ID（カンマ区切り、例: 15,22）",
    )
    update_parser.add_argument("--other", type=str, help="補足情報・その他希望条件")
    update_parser.add_argument(
        "--no-backup",
        action="store_true",
        help="事前バックアップの作成をスキップ",
    )
    update_parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="出力ディレクトリ（デフォルト: data/levtech_direct/profile/）",
    )
    add_common_flags(update_parser)

    # 3. sync サブコマンド
    sync_parser = subparsers.add_parser("sync", help="profile/preferences.md から希望条件を反映・同期")
    sync_parser.add_argument("--dry-run", action="store_true", help="保存を実行せず差分プレビューのみ表示")
    sync_parser.add_argument(
        "--preferences-file",
        type=Path,
        default=PREFERENCES_PATH,
        help="希望条件SSOTファイルのパス（デフォルト: profile/preferences.md）",
    )
    sync_parser.add_argument(
        "--no-backup",
        action="store_true",
        help="事前バックアップの作成をスキップ",
    )
    sync_parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="出力ディレクトリ（デフォルト: data/levtech_direct/profile/）",
    )
    add_common_flags(sync_parser)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    session = getattr(args, "session", "job-hunt")
    output_dir = Path(getattr(args, "output_dir", DEFAULT_OUTPUT_DIR))
    is_summary = getattr(args, "summary", False)
    is_json = getattr(args, "json", False)

    ctx = EntrypointContext(summary=is_summary, json_mode=is_json)

    # 認証ガード
    if not ensure_site_authenticated("levtech_direct", session=session, target_url=TARGET_URL, exit_on_fail=False):
        ctx.error("レバテックダイレクトの認証状態が確認できませんでした。")
        return 2

    subcmd = args.subcommand or "fetch"

    try:
        # -------------------------------------------------------------
        # 1. fetch 操作
        # -------------------------------------------------------------
        if subcmd == "fetch":
            ctx.log("[INFO] レバテックダイレクト 希望条件を取得中...")
            result = execute_manage_action(session, "fetch", timeout=45)
            saved_paths = save_condition_result(result, output_dir=output_dir)
            ctx.add_result_paths(saved_paths)

            return ctx.flush_outputs(
                summary_fn=lambda: print_formatted_summary(result),
                json_data=result,
            )

        # -------------------------------------------------------------
        # 2. update / sync 操作
        # -------------------------------------------------------------
        elif subcmd in ("update", "sync"):
            is_dry_run = getattr(args, "dry_run", False)

            # 変更前の最新データを取得して自動バックアップ
            if not getattr(args, "no_backup", False):
                ctx.log("[INFO] 変更前自動バックアップ（最新希望条件取得）を実行中...")
                prev_result = execute_manage_action(session, "fetch", timeout=30)
                backup_files = save_condition_result(prev_result, output_dir=output_dir, backup_only=True)
                for bp in backup_files:
                    ctx.log(f"[安全ガード] 変更前バックアップを保存しました: {to_relative_path(bp)}")
            else:
                prev_result = execute_manage_action(session, "fetch", timeout=30)

            # ペイロード作成
            payload: dict[str, Any] = {}
            if subcmd == "sync":
                pref_file = getattr(args, "preferences_file", PREFERENCES_PATH)
                ctx.log(f"[INFO] {to_relative_path(pref_file)} から希望条件を抽出中...")
                payload = parse_preferences_for_condition(pref_file)
            else:
                if args.annual_income is not None:
                    payload["annualIncome"] = args.annual_income
                if args.job_change_period is not None:
                    payload["jobChangePeriod"] = args.job_change_period
                if args.other is not None:
                    payload["other"] = args.other

                jc: dict[str, Any] = {}
                if args.business_form:
                    jc["businessForm"] = args.business_form
                if args.remote:
                    jc["remoteWork"] = args.remote
                if args.project_scale:
                    jc["projectScale"] = args.project_scale
                if jc:
                    payload["jobConditions"] = jc

                if args.work_places:
                    raw_places = [p.strip() for p in args.work_places.split(",") if p.strip()]
                    mapped_places = [
                        PREFECTURE_NAME_TO_PLACE_ID.get(p, p) for p in raw_places
                    ]
                    payload["workPlaces"] = mapped_places

                if args.occupations:
                    payload["occupations"] = [
                        int(o.strip()) for o in args.occupations.split(",") if o.strip().isdigit()
                    ]

                if args.skills:
                    payload["skills"] = [s.strip() for s in args.skills.split(",") if s.strip()]

                if args.employment_statuses:
                    payload["desiredEmploymentStatuses"] = [
                        s.strip() for s in args.employment_statuses.split(",") if s.strip()
                    ]

                if args.work_styles:
                    payload["workStyles"] = [
                        int(w.strip()) for w in args.work_styles.split(",") if w.strip().isdigit()
                    ]

            if not payload:
                ctx.error("更新する項目が指定されていません。--help でオプションを確認してください。")
                return 1

            ctx.log(f"[INFO] 希望条件の反映を実行中 (dry_run={is_dry_run})...")
            update_result = execute_manage_action(
                session,
                "update",
                payload=payload,
                dry_run=is_dry_run,
                timeout=60,
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
                saved_paths = save_condition_result(update_result, output_dir=output_dir)
                ctx.add_result_paths(saved_paths)
                print_diff(prev_data, new_data)
                ctx.log("[INFO] 希望条件の保存が完了しました。")
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
