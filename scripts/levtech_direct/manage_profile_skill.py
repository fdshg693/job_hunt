"""レバテックダイレクト マイページ保有スキル（/mypage/profile/skill）管理スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
レバテックダイレクトの保有スキル（スキル名、経験年数）、現在の職種、担当工程、
マネジメント経験等の閲覧（fetch）、更新（update）、プロファイル同期（sync）を安全に実行します。

変更操作の実行前には必ず最新スキルの自動バックアップを取得し、
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
MANAGE_SCRIPT_PATH = LEVTECH_SCRIPTS_DIR / "manage_profile_skill.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "levtech_direct" / "profile"
BACKUP_DIR = DEFAULT_OUTPUT_DIR / "backups"
TARGET_URL = "https://levtech-direct.jp/mypage/profile/skill"
SKILLS_SSOT_PATH = PROJECT_ROOT / "profile" / "skills.md"

# 経験年数ラベルマップ
EXPERIENCE_YEARS_MAP: dict[int, str] = {
    15: "半年未満",
    6: "半年以上",
    7: "1年以上",
    8: "1年半以上",
    9: "2年以上",
    10: "3年以上",
    11: "4年以上",
    12: "5年以上",
    13: "7年以上",
    14: "10年以上",
}

EXPERIENCE_YEARS_NAME_TO_ID: dict[str, int] = {
    name: yid for yid, name in EXPERIENCE_YEARS_MAP.items()
}

# マネジメント規模マップ
MANAGEMENT_SCALES_MAP: dict[int, str] = {
    1: "1~5人",
    2: "6~10人",
    3: "11~50人",
    4: "51人以上",
    5: "経験なし",
}

MANAGEMENT_SCALES_NAME_TO_ID: dict[str, int] = {
    name: mid for mid, name in MANAGEMENT_SCALES_MAP.items()
}


def parse_year_to_id(val: Any) -> int:
    """年数表記（数値・文字列）をレバテックの experienceYearId に変換する."""
    if val is None or val == "":
        return 9  # デフォルト: 2年以上

    if isinstance(val, (int, float)):
        v = float(val)
        if v < 0.5:
            return 15
        if v < 1.0:
            return 6
        if v < 1.5:
            return 7
        if v < 2.0:
            return 8
        if v < 3.0:
            return 9
        if v < 4.0:
            return 10
        if v < 5.0:
            return 11
        if v < 7.0:
            return 12
        if v < 10.0:
            return 13
        return 14

    s = str(val).strip()
    if s in EXPERIENCE_YEARS_NAME_TO_ID:
        return EXPERIENCE_YEARS_NAME_TO_ID[s]

    try:
        num = int(s)
        if num in EXPERIENCE_YEARS_MAP:
            return num
    except ValueError:
        pass

    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", s)
    if m:
        return parse_year_to_id(float(m.group(1)))

    if "半年未満" in s:
        return 15
    if "半年" in s:
        return 6
    return 9


def execute_manage_action(
    session: str,
    action: str,
    payload: dict[str, Any] | None = None,
    dry_run: bool = False,
    timeout: int = 45,
) -> dict[str, Any]:
    """manage_profile_skill.mjs に action, payload, isDryRun を注入して実行する."""
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

    tmp_script_path = LEVTECH_SCRIPTS_DIR / f".tmp_manage_skill_{action}.mjs"
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


def format_skill_markdown(data: dict[str, Any], fetched_at: datetime) -> str:
    """保有スキルデータを構造化フロントマター付きMarkdownに整形する."""
    d = data.get("data", data)
    skills = d.get("skills") or []
    cur_occ = d.get("currentOccupation") or {}
    mgmt = d.get("managementScale") or {}
    occupations = d.get("occupations") or []
    processes = d.get("processes") or []

    lines = [
        "---",
        "source: levtech_direct",
        "type: skill_profile",
        f"updated_at: '{fetched_at.isoformat(timespec='seconds')}'",
        f"url: '{TARGET_URL}'",
        f"skills_count: {len(skills)}",
        f"current_occupation: '{cur_occ.get('name', '')}'",
        f"management_scale: '{mgmt.get('name', '')}'",
        "skills:",
    ]

    for s in skills:
        lines.append(f"  - name: '{s.get('name', '')}'")
        lines.append(f"    id: {s.get('id', 'null')}")
        lines.append(f"    experience_year_id: {s.get('experienceYearId', 'null')}")
        lines.append(f"    experience_years: '{s.get('experienceYears', '')}'")

    lines.extend([
        "---",
        "",
        "# レバテックダイレクト 保有スキル・職種",
        "",
        f"最終取得日時: {fetched_at.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"## 経験スキル ({len(skills)}件)",
        "",
    ])

    if skills:
        for s in skills:
            s_name = s.get("name", "")
            s_years = s.get("experienceYears", "")
            s_id = s.get("id")
            id_str = f" (ID: {s_id})" if s_id else ""
            lines.append(f"- **{s_name}**: {s_years}{id_str}")
    else:
        lines.append("- （未登録）")

    lines.extend([
        "",
        "## 職種",
        "",
        f"- **現在の職種**: {cur_occ.get('name') or '（未設定）'}",
    ])

    if occupations:
        lines.append("- **経験職種**:")
        for o in occupations:
            lines.append(f"  - {o.get('name')}: {o.get('experienceYears') or '未設定'}")

    lines.extend([
        "",
        "## 経験担当工程",
        "",
    ])

    if processes:
        for p in processes:
            lines.append(f"- **{p.get('name')}**: {p.get('experienceYears') or '未設定'}")
    else:
        lines.append("- （未登録）")

    lines.extend([
        "",
        "## マネジメント経験",
        "",
        f"- **最大規模**: {mgmt.get('name') or '（未設定）'}",
        "",
    ])

    return "\n".join(lines)


def save_skill_result(
    result: dict[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    backup_only: bool = False,
) -> list[Path]:
    """取得・更新したスキルデータをMarkdownおよびJSON形式で永続化する."""
    now = datetime.now()
    output_dir.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    saved_files: list[Path] = []
    md_content = format_skill_markdown(result, now)
    json_content = json.dumps(result, ensure_ascii=False, indent=2)

    # 1. バックアップファイル
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    backup_md = BACKUP_DIR / f"skill_{timestamp_str}.md"
    backup_md.write_text(md_content, encoding="utf-8")
    saved_files.append(backup_md)

    if backup_only:
        return saved_files

    # 2. 正本Markdown & JSON
    main_md = output_dir / "skill.md"
    main_md.write_text(md_content, encoding="utf-8")
    saved_files.append(main_md)

    main_json = output_dir / "skill.json"
    main_json.write_text(json_content, encoding="utf-8")
    saved_files.append(main_json)

    return saved_files


def print_formatted_summary(result: dict[str, Any], is_dry_run: bool = False) -> None:
    """人間向けの整形済みサマリを標準エラー出力等に出力する."""
    d = result.get("data", result)
    skills = d.get("skills") or []
    cur_occ = d.get("currentOccupation") or {}
    mgmt = d.get("managementScale") or {}
    occupations = d.get("occupations") or []
    processes = d.get("processes") or []

    status_tag = "[DRY-RUN プレビュー]" if is_dry_run else "[レバテックダイレクト 保有スキル]"
    print(f"\n=======================================================")
    print(f" {status_tag} ")
    print(f"=======================================================")
    print(f"現在の職種: {cur_occ.get('name') or '未設定'}")
    print(f"マネジメント経験: {mgmt.get('name') or '未設定'}")

    if occupations:
        occ_str = ", ".join(f"{o.get('name')} ({o.get('experienceYears')})" for o in occupations)
        print(f"経験職種: {occ_str}")

    print(f"\n【経験スキル ({len(skills)}件)】")
    for s in skills:
        print(f"  • {s.get('name')}: {s.get('experienceYears')} (ID: {s.get('id', 'N/A')})")

    if processes:
        print(f"\n【経験担当工程】")
        for p in processes:
            print(f"  • {p.get('name')}: {p.get('experienceYears')}")

    print("=======================================================\n")


def display_diff(old_content: str, new_content: str) -> None:
    """旧テキストと新テキストの差分（Unified Diff）を表示する."""
    diff = list(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile="現在のスキル (Before)",
            tofile="更新後のスキル (After)",
            n=3,
        )
    )
    if not diff:
        print("[DIFF] 変更差分はありませんでした（同一内容です）。")
        return

    print("\n" + "=" * 25 + " 変更差分 (Diff) " + "=" * 25)
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            print(f"\033[32m{line.rstrip()}\033[0m")
        elif line.startswith("-") and not line.startswith("---"):
            print(f"\033[31m{line.rstrip()}\033[0m")
        elif line.startswith("@"):
            print(f"\033[36m{line.rstrip()}\033[0m")
        else:
            print(line.rstrip())
    print("=" * 66 + "\n")


def parse_skills_ssot(skills_file: Path) -> list[dict[str, Any]]:
    """profile/skills.md からスキル名と経験年数を解析してリスト化する."""
    if not skills_file.exists():
        raise FileNotFoundError(f"スキルファイルが見つかりません: {skills_file}")

    content = skills_file.read_text(encoding="utf-8")

    # Frontmatter抽出
    extracted_skills: list[dict[str, Any]] = []
    fm_match = re.match(r"^---\r?\n(.*?)\r?\n---", content, re.DOTALL)
    if not fm_match:
        return extracted_skills

    fm_text = fm_match.group(1)

    # 言語抽出 (languages)
    # - name: "Python"
    #   years: 1.5
    lang_blocks = re.findall(
        r'-\s+name:\s*["\']?([^"\'\n]+)["\']?\s*\n\s+years:\s*([0-9.]+)',
        fm_text,
    )
    for name, years_str in lang_blocks:
        name = name.strip()
        years_num = float(years_str)
        # "TypeScript / JavaScript" のような複合名を分割
        if "/" in name:
            subnames = [s.strip() for s in name.split("/")]
            for sn in subnames:
                extracted_skills.append({
                    "name": sn,
                    "years": years_num,
                    "experienceYears": EXPERIENCE_YEARS_MAP[parse_year_to_id(years_num)],
                })
        else:
            extracted_skills.append({
                "name": name,
                "years": years_num,
                "experienceYears": EXPERIENCE_YEARS_MAP[parse_year_to_id(years_num)],
            })

    # フレームワーク抽出 (frameworks_libraries)
    fm_fw = re.search(r"frameworks_libraries:\s*\n((?:\s+-\s+.*?\n)+)", fm_text)
    if fm_fw:
        fw_lines = re.findall(r'-\s+["\']?([^"\'\n]+)["\']?', fm_fw.group(1))
        for fw in fw_lines:
            fw = fw.strip()
            if "/" in fw:
                subfws = [s.strip() for s in fw.split("/")]
                for sfw in subfws:
                    extracted_skills.append({
                        "name": sfw,
                        "years": 1.5,
                        "experienceYears": "1年半以上",
                    })
            else:
                extracted_skills.append({
                    "name": fw,
                    "years": 1.5,
                    "experienceYears": "1年半以上",
                })

    # クラウド・インフラ抽出 (infrastructure_cloud)
    fm_infra = re.search(r"infrastructure_cloud:\s*\n((?:\s+-\s+.*?\n)+)", fm_text)
    if fm_infra:
        infra_lines = re.findall(r'-\s+["\']?([^"\'\n]+)["\']?', fm_infra.group(1))
        for item in infra_lines:
            item_clean = item.strip().split("(")[0].strip()
            if "/" in item_clean:
                subitems = [s.strip() for s in item_clean.split("/")]
                for sitem in subitems:
                    extracted_skills.append({
                        "name": sitem,
                        "years": 1.0,
                        "experienceYears": "1年以上",
                    })
            elif item_clean:
                extracted_skills.append({
                    "name": item_clean,
                    "years": 1.0,
                    "experienceYears": "1年以上",
                })

    return extracted_skills


def build_parser() -> argparse.ArgumentParser:
    """CLI引数パーサーを構築する."""
    parser = create_base_parser(
        description="レバテックダイレクト 保有スキル管理スクリプト（取得・更新・同期・バックアップ）",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="実行サブコマンド")

    def add_common_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--session",
            type=str,
            default="job-hunt",
            help="ブラウザプロファイル名（デフォルト: job-hunt）",
        )
        p.add_argument(
            "--summary",
            action="store_true",
            help="実行結果のテキスト要約を表示（省略時は保存パスのみ出力）",
        )
        p.add_argument(
            "--json",
            action="store_true",
            help="JSON形式で結果を出力",
        )

    # 1. fetch サブコマンド
    fetch_parser = subparsers.add_parser("fetch", help="保有スキル・職種・マネジメント規模の最新状態を取得・保存")
    fetch_parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="出力ディレクトリ（デフォルト: data/levtech_direct/profile/）",
    )
    add_common_flags(fetch_parser)

    # 2. update サブコマンド
    update_parser = subparsers.add_parser("update", help="スキルの追加・削除・年数更新、職種等の変更")
    update_parser.add_argument("--dry-run", action="store_true", help="保存を実行せず差分プレビューのみ表示")
    update_parser.add_argument("--add-skill", type=str, help="追加するスキル名")
    update_parser.add_argument("--remove-skill", type=str, help="削除するスキル名")
    update_parser.add_argument("--set-skill", type=str, help="年数を設定・更新するスキル名")
    update_parser.add_argument("--years", type=str, default="2年以上", help="経験年数（例: '2年', '2年以上', '半年以上' 等）")
    update_parser.add_argument("--current-occupation", type=str, help="現在の職種（ID または 名称）")
    update_parser.add_argument("--management-scale", type=str, help="マネジメント経験（ID または 名称）")
    update_parser.add_argument("--skills-file", type=Path, help="一括適用するスキルリストJSONファイル")
    update_parser.add_argument("--no-backup", action="store_true", help="事前バックアップの作成をスキップ")
    update_parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="出力ディレクトリ（デフォルト: data/levtech_direct/profile/）",
    )
    add_common_flags(update_parser)

    # 3. sync サブコマンド
    sync_parser = subparsers.add_parser("sync", help="profile/skills.md から主要スキルを抽出・同期")
    sync_parser.add_argument("--dry-run", action="store_true", help="保存を実行せず差分プレビューのみ表示")
    sync_parser.add_argument(
        "--skills-ssot",
        type=Path,
        default=SKILLS_SSOT_PATH,
        help="スキルSSOTファイルのパス（デフォルト: profile/skills.md）",
    )
    sync_parser.add_argument("--no-backup", action="store_true", help="事前バックアップの作成をスキップ")
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
            ctx.log("[INFO] レバテックダイレクト 保有スキル・職種を取得中...")
            result = execute_manage_action(session, "fetch", timeout=45)
            saved_paths = save_skill_result(result, output_dir=output_dir)
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
                ctx.log("[INFO] 変更前自動バックアップ（最新スキル取得）を実行中...")
                prev_result = execute_manage_action(session, "fetch", timeout=30)
                backup_files = save_skill_result(prev_result, output_dir=output_dir, backup_only=True)
                for bp in backup_files:
                    ctx.log(f"[安全ガード] 変更前バックアップを保存しました: {to_relative_path(bp)}")
            else:
                prev_result = execute_manage_action(session, "fetch", timeout=30)

            cur_skills = list(prev_result.get("data", {}).get("skills", []))
            payload: dict[str, Any] = {}

            if subcmd == "sync":
                ssot_file = getattr(args, "skills_ssot", SKILLS_SSOT_PATH)
                ctx.log(f"[INFO] {to_relative_path(ssot_file)} からスキル一覧を抽出中...")
                ssot_skills = parse_skills_ssot(ssot_file)

                # 既存スキルをマップ化（小文字比較）
                skill_map: dict[str, dict[str, Any]] = {
                    s["name"].lower(): s for s in cur_skills
                }

                # SSOTスキルを統合（既存に存在すれば年数を更新、なければ追加）
                for s in ssot_skills:
                    s_lower = s["name"].lower()
                    if s_lower in skill_map:
                        skill_map[s_lower]["experienceYears"] = s["experienceYears"]
                    else:
                        skill_map[s_lower] = {
                            "name": s["name"],
                            "experienceYears": s["experienceYears"],
                        }

                payload["skills"] = list(skill_map.values())

            elif subcmd == "update":
                # ファイル指定がある場合
                if args.skills_file:
                    sf_path = Path(args.skills_file)
                    if not sf_path.exists():
                        ctx.error(f"指定されたスキルファイルが存在しません: {sf_path}")
                        return 1
                    with open(sf_path, encoding="utf-8") as f:
                        file_data = json.load(f)
                    payload["skills"] = file_data if isinstance(file_data, list) else file_data.get("skills", [])

                else:
                    # 個別引数の処理
                    new_skills = list(cur_skills)

                    if args.remove_skill:
                        rem_name = args.remove_skill.strip().lower()
                        new_skills = [s for s in new_skills if s.get("name", "").lower() != rem_name]

                    if args.add_skill:
                        add_name = args.add_skill.strip()
                        # 重複チェック
                        exists = any(s.get("name", "").lower() == add_name.lower() for s in new_skills)
                        if exists:
                            ctx.log(f"[INFO] スキル '{add_name}' は既に登録されています。年数を更新します。")
                            for s in new_skills:
                                if s.get("name", "").lower() == add_name.lower():
                                    s["experienceYears"] = args.years
                        else:
                            new_skills.append({
                                "name": add_name,
                                "experienceYears": args.years,
                            })

                    if args.set_skill:
                        set_name = args.set_skill.strip()
                        matched = False
                        for s in new_skills:
                            if s.get("name", "").lower() == set_name.lower():
                                s["experienceYears"] = args.years
                                matched = True
                                break
                        if not matched:
                            new_skills.append({
                                "name": set_name,
                                "experienceYears": args.years,
                            })

                    if args.remove_skill or args.add_skill or args.set_skill:
                        payload["skills"] = new_skills

                # 職種
                if args.current_occupation:
                    val = args.current_occupation.strip()
                    payload["currentOccupation"] = int(val) if val.isdigit() else val

                # マネジメント
                if args.management_scale:
                    val = args.management_scale.strip()
                    if val in MANAGEMENT_SCALES_NAME_TO_ID:
                        payload["managementScale"] = MANAGEMENT_SCALES_NAME_TO_ID[val]
                    elif val.isdigit():
                        payload["managementScale"] = int(val)
                    else:
                        payload["managementScale"] = val

            # 更新実行
            ctx.log(f"[INFO] スキル変更操作を実行中... (dry_run={is_dry_run})")
            res = execute_manage_action(session, "update", payload=payload, dry_run=is_dry_run, timeout=60)

            # 差分比較
            prev_md = format_skill_markdown(prev_result, datetime.now())
            new_md = format_skill_markdown(res, datetime.now())
            display_diff(prev_md, new_md)

            if is_dry_run:
                ctx.log("[DRY-RUN] 変更は保存されていません。プレビューのみ表示しました。")
                return ctx.flush_outputs(
                    summary_fn=lambda: print_formatted_summary(res, is_dry_run=True),
                    json_data=res,
                )

            # 本番保存
            saved_paths = save_skill_result(res, output_dir=output_dir)
            ctx.add_result_paths(saved_paths)
            ctx.log("[SUCCESS] レバテックダイレクト 保有スキルを正常に更新・保存しました。")

            return ctx.flush_outputs(
                summary_fn=lambda: print_formatted_summary(res, is_dry_run=False),
                json_data=res,
            )

        else:
            ctx.error(f"未知のサブコマンド: {subcmd}")
            return 1

    except Exception as e:
        ctx.error(f"エラーが発生しました: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
