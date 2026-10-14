"""英語版プロフィール (profile_en/) 同期状態管理・チェックCLIスクリプト.

.agents/rules/user-profile.md および scripts-entrypoint.md 規約に準拠し、
profile/ (日本語SSOT) と profile_en/ (派生英語版) の差分検知・同期状態管理を提供します。
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/profile/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yaml

from scripts.common.cli import create_base_parser, entrypoint_guard, to_relative_path

PROFILE_DIR = PROJECT_ROOT / "profile"
PROFILE_EN_DIR = PROJECT_ROOT / "profile_en"

# 同期対象ファイル一覧（internal/ は外部非公開のため除外）
SYNC_TARGET_FILES = [
    "resume.md",
    "skills.md",
    "preferences.md",
]


def extract_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Frontmatter と本文を分離して解析する."""
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", content, re.DOTALL)
    if not match:
        return {}, content
    try:
        data = yaml.safe_load(match.group(1)) or {}
        return data, match.group(2)
    except yaml.YAMLError:
        return {}, content


def format_frontmatter_markdown(fm: dict[str, Any], body: str) -> str:
    """フロントマター辞書と本文からMarkdownテキストを再構成する."""
    fm_yaml = yaml.dump(
        fm,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()
    return f"---\n{fm_yaml}\n---\n\n{body.lstrip()}"


def get_profile_file_info(rel_path: str) -> dict[str, Any]:
    """profile/ 内のソースファイルのメタ情報を取得する."""
    src_file = PROFILE_DIR / rel_path
    if not src_file.exists():
        return {"exists": False, "updated_at": None}

    content = src_file.read_text(encoding="utf-8")
    fm, _ = extract_frontmatter(content)
    updated_at = str(fm.get("updated_at") or "")
    if not updated_at:
        # フロントマターになければファイル更新日（YYYY-MM-DD）
        mtime = datetime.fromtimestamp(src_file.stat().st_mtime)
        updated_at = mtime.strftime("%Y-%m-%d")

    return {
        "exists": True,
        "updated_at": updated_at,
        "path": src_file,
    }


def get_profile_en_file_info(rel_path: str) -> dict[str, Any]:
    """profile_en/ 内の英語版ファイルのメタ情報を取得する."""
    en_file = PROFILE_EN_DIR / rel_path
    if not en_file.exists():
        return {
            "exists": False,
            "source_updated_at": None,
            "synced_at": None,
            "status": "MISSING",
        }

    content = en_file.read_text(encoding="utf-8")
    fm, _ = extract_frontmatter(content)
    source_updated_at = str(fm.get("source_updated_at") or "")
    synced_at = str(fm.get("synced_at") or "")

    return {
        "exists": True,
        "source_updated_at": source_updated_at,
        "synced_at": synced_at,
        "path": en_file,
    }


def check_sync_status(target_files: list[str] | None = None) -> list[dict[str, Any]]:
    """対象ファイルの同期状態を評価する."""
    files = target_files or SYNC_TARGET_FILES
    results = []

    for fname in files:
        src_info = get_profile_file_info(fname)
        en_info = get_profile_en_file_info(fname)

        if not en_info["exists"]:
            status = "MISSING"
        elif not src_info["exists"]:
            status = "ORPHAN"
        elif not en_info["source_updated_at"]:
            status = "UNTRACKED"
        elif en_info["source_updated_at"] < src_info["updated_at"]:
            status = "STALE"
        else:
            status = "UP_TO_DATE"

        results.append({
            "file": fname,
            "source_path": f"profile/{fname}",
            "en_path": f"profile_en/{fname}",
            "source_updated_at": src_info.get("updated_at"),
            "target_source_updated_at": en_info.get("source_updated_at"),
            "synced_at": en_info.get("synced_at"),
            "status": status,
        })

    return results


def update_en_metadata(
    fname: str,
    synced_date: str | None = None,
) -> Path:
    """指定した英語版ファイルの source_updated_at と synced_at を最新に更新する."""
    src_info = get_profile_file_info(fname)
    if not src_info["exists"]:
        raise FileNotFoundError(f"ソースファイル profile/{fname} が存在しません。")

    en_path = PROFILE_EN_DIR / fname
    if not en_path.exists():
        raise FileNotFoundError(f"英語版ファイル profile_en/{fname} が存在しません。")

    today_str = synced_date or datetime.now().strftime("%Y-%m-%d")
    src_updated = src_info["updated_at"]

    content = en_path.read_text(encoding="utf-8")
    fm, body = extract_frontmatter(content)

    fm["source_file"] = f"profile/{fname}"
    fm["source_updated_at"] = src_updated
    fm["synced_at"] = today_str
    fm["language"] = "en"

    new_content = format_frontmatter_markdown(fm, body)
    en_path.write_text(new_content, encoding="utf-8")
    return en_path


def parse_args() -> argparse.Namespace:
    parser = create_base_parser(
        description="profile/ と profile_en/ の同期状態チェック・更新支援CLI"
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="check",
        choices=["check", "update-meta"],
        help="実行アクション (check: 同期確認, update-meta: フロントマター更新)",
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="対象ファイル名（例: resume.md, skills.md）。省略時は全対象ファイル",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="check時にSTALEまたはMISSINGがある場合、終了コード1を返す",
    )
    parser.add_argument(
        "--all-paths",
        action="store_true",
        help="stdoutに差分対象だけでなく全管理ファイルのパスを出力する",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        target_files = [args.target] if args.target else SYNC_TARGET_FILES

        if args.action == "update-meta":
            if not args.target:
                ctx.error("update-meta アクションには対象ファイル名の指定が必要です。（例: sync_en.py update-meta resume.md）")
                sys.exit(1)

            try:
                updated_path = update_en_metadata(args.target)
                ctx.add_result_path(updated_path)
                ctx.info(f"メタデータを更新しました: {to_relative_path(updated_path)}")
            except Exception as e:
                ctx.error(f"メタデータ更新エラー: {e}")
                sys.exit(1)

            ctx.flush_outputs()
            return

        # check アクション
        statuses = check_sync_status(target_files)
        has_issue = any(s["status"] in ("STALE", "MISSING", "UNTRACKED") for s in statuses)

        if args.all_paths:
            for s in statuses:
                ctx.add_result_path(s["en_path"])
        else:
            for s in statuses:
                if s["status"] in ("STALE", "MISSING", "UNTRACKED"):
                    ctx.add_result_path(s["en_path"])

        if args.strict and has_issue:
            ctx.set_exit_code(1)

        def print_summary() -> None:
            print("=" * 70)
            print(" 英語版プロフィール (profile_en/) 同期ステータス")
            print("=" * 70)
            fmt = "{:<16} | {:<12} | {:<14} | {:<12} | {:<10}"
            print(fmt.format("File", "Source Rev", "Synced Source", "Synced At", "Status"))
            print("-" * 70)
            for s in statuses:
                print(
                    fmt.format(
                        s["file"],
                        str(s["source_updated_at"] or "-"),
                        str(s["target_source_updated_at"] or "-"),
                        str(s["synced_at"] or "-"),
                        s["status"],
                    )
                )
            print("-" * 70)
            if has_issue:
                print("[!] 未同期または新規作成が必要なドキュメントが存在します。")
            else:
                print("[OK] 全ドキュメントが最新の日本語SSOTと同期されています。")

        ctx.flush_outputs(summary_fn=print_summary, json_data={"status": statuses})


if __name__ == "__main__":
    main()
