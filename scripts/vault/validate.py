"""vault のフロントマターをスキーマと配置ルールで検証する CLI.

スキーマ（scripts/vault/schema/）と配置ルールに照らして vault 全件を検査する。
- エラー（型・許容値・必須キー・フォルダ名/ファイル名との不一致）があれば終了コード1。
- 警告（幅の無い fit_score、期限切れの next_due、リンク先キーが無い等）は ``--strict`` のときだけ失敗にする。

.agents/rules/scripts-entrypoint.md に従い、stdout には問題のあったファイルのパスだけを出す
（問題の内容は stderr、``--summary`` で一覧、``--json`` で構造化出力）。
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

# プロジェクトルートパス (scripts/vault/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import create_base_parser, entrypoint_guard
from scripts.vault.loader import IssueLevel, load_vault


def main() -> None:
    parser = create_base_parser(
        description="vault のフロントマターをスキーマで検証する",
        examples=[
            "uv run python scripts/vault/validate.py  # エラーがあれば exit 1（問題のあったファイルのパスを出す）",
            "uv run python scripts/vault/validate.py --summary --strict  # 警告も失敗扱いにして一覧表示",
            "uv run python scripts/vault/validate.py --root templates  # 公開用雛形を検証",
        ],
        related=[
            "scripts/vault/build_pipeline.py: 検証後に pipeline.md を再生成する",
            "scripts/vault/find_chores.py: 期限切れ等の警告を雑務として整理する",
        ],
    )
    parser.add_argument("--strict", action="store_true", help="警告も失敗扱いにする（終了コード1）")
    parser.add_argument(
        "--root",
        type=Path,
        default=PROJECT_ROOT,
        help="vault/ を含むディレクトリ（既定: リポジトリルート。雛形を検証するなら templates）",
    )
    parser.add_argument(
        "--today",
        type=dt.date.fromisoformat,
        default=dt.date.today(),
        help="期限切れ判定の基準日（YYYY-MM-DD、既定: 今日）",
    )
    args = parser.parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        root = args.root if args.root.is_absolute() else PROJECT_ROOT / args.root
        vault = load_vault(root, today=args.today)
        errors, warnings = vault.errors, vault.warnings

        for issue in errors:
            ctx.error(str(issue))
        for issue in warnings:
            ctx.warn(str(issue))
        n_docs = sum(1 for _ in vault.docs())
        ctx.info(f"{n_docs} ファイルを検証: エラー {len(errors)} 件 / 警告 {len(warnings)} 件")

        failing = errors + (warnings if args.strict else [])
        if failing:
            ctx.set_exit_code(1)
        for path in dict.fromkeys(i.path for i in vault.issues):
            ctx.add_result_path(root / path)

        def print_summary() -> None:
            print(f"検証対象: {n_docs} ファイル（{root}）")
            print(f"エラー: {len(errors)} 件 / 警告: {len(warnings)} 件{'（--strict: 警告も失敗扱い）' if args.strict else ''}")
            for level, title in ((IssueLevel.ERROR, "エラー"), (IssueLevel.WARNING, "警告")):
                items = [i for i in vault.issues if i.level == level]
                if items:
                    print(f"\n[{title}]")
                    for i in items:
                        print(f"  - {i}")

        json_data = {
            "root": str(root),
            "files": n_docs,
            "strict": args.strict,
            "ok": not failing,
            "issues": [{"level": str(i.level), "path": i.path, "message": i.message} for i in vault.issues],
        }
        sys.exit(ctx.flush_outputs(summary_fn=print_summary, json_data=json_data))


if __name__ == "__main__":
    main()
