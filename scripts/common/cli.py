"""CLIおよびエントリポイント規約統一基盤モジュール.

エントリポイントスクリプト出力・運用規約（.agents/rules/scripts-entrypoint.md）を
厳格に遵守するためのパス変換、出力制御コンテキスト、共通引数パーサーを提供します。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/common/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def to_relative_path(path: Path | str) -> str:
    """プロジェクトルートからの相対パス文字列（スラッシュ区切り）を一元定義して返す.

    .agents/rules/scripts-entrypoint.md 規約に準拠した形式で出力します。
    プロジェクト外のパスや解決不能な場合はスラッシュ区切りのパス文字列を返します。
    """
    p = Path(path) if isinstance(path, str) else path
    try:
        return p.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


class EntrypointContext:
    """エントリポイント実行コンテキスト.

    .agents/rules/scripts-entrypoint.md 規約:
    1. 標準出力（stdout）はファイルパス専用（1行1パス）
    2. 人間向けサマリ表示は --summary オプション時のみ
    3. ログ・進捗・認証メッセージ・エラーはすべて sys.stderr に出力
    4. 終了コード（0: 正常, 1: エラー, 2: 認証ハンドオフ等の中断）
    """

    def __init__(self, summary: bool = False, json_mode: bool = False) -> None:
        self.summary = summary
        self.json_mode = json_mode
        self._result_paths: list[str] = []
        self._exit_code: int = 0

    @property
    def result_paths(self) -> list[str]:
        return list(self._result_paths)

    def add_result_path(self, path: Path | str) -> str:
        """結果ファイルパスを追加する（重複は保持、相対パスへ自動変換）."""
        rel = to_relative_path(path)
        self._result_paths.append(rel)
        return rel

    def add_result_paths(self, paths: Sequence[Path | str]) -> list[str]:
        """複数の結果ファイルパスを追加する."""
        return [self.add_result_path(p) for p in paths]

    def log(self, message: str) -> None:
        """進捗・ログメッセージを標準エラー出力へ出力."""
        print(message, file=sys.stderr)

    def info(self, message: str) -> None:
        """情報メッセージを標準エラー出力へ出力."""
        print(f"[INFO] {message}", file=sys.stderr)

    def warn(self, message: str) -> None:
        """警告メッセージを標準エラー出力へ出力."""
        print(f"[警告] {message}", file=sys.stderr)

    def error(self, message: str) -> None:
        """エラーメッセージを標準エラー出力へ出力."""
        print(f"[エラー] {message}", file=sys.stderr)

    def set_exit_code(self, code: int) -> None:
        """終了コードを設定する."""
        self._exit_code = code

    def flush_outputs(
        self,
        summary_fn: Callable[[], None] | None = None,
        json_data: Any = None,
    ) -> int:
        """規約に従って標準出力へ結果を出力し、終了コードを返す.

        - json_mode: json_data を stdout へ出力
        - summary: summary_fn を実行（内部でコンソール表示）
        - default: 記録された result_paths を 1 行ずつ stdout へ出力
        """
        if self.json_mode:
            if json_data is not None:
                if isinstance(json_data, str):
                    print(json_data)
                else:
                    print(json.dumps(json_data, ensure_ascii=False, indent=2))
            else:
                print(json.dumps({"paths": self._result_paths}, ensure_ascii=False, indent=2))
        elif self.summary:
            if summary_fn:
                summary_fn()
            else:
                for p in self._result_paths:
                    print(f"- {p}")
        else:
            for p in self._result_paths:
                print(p)

        return self._exit_code


def _auto_prune_data(ctx: EntrypointContext) -> None:
    """data/ の保持期間切れの生データを 1 日 1 回消す（scripts/common/data_retention.py）. 失敗しても本体は止めない."""
    try:
        # paths.py が cli.py を import するので循環を避けて遅延 import
        from scripts.common.data_retention import maybe_prune

        maybe_prune(ctx.log)
    except Exception as e:  # noqa: BLE001
        ctx.warn(f"data/ の自動プルーニングに失敗しました（処理は続行）: {e}")


@contextmanager
def entrypoint_guard(
    summary: bool = False,
    json_mode: bool = False,
) -> Generator[EntrypointContext]:
    """エントリポイント用の例外捕捉・コンテキストマネージャ.

    使用例:
    ```python
    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        # 処理...
        ctx.add_result_path(saved_path)
        ctx.flush_outputs(summary_fn=...)
    ```
    """
    ctx = EntrypointContext(summary=summary, json_mode=json_mode)
    _auto_prune_data(ctx)
    try:
        yield ctx
    except KeyboardInterrupt:
        ctx.warn("ユーザーによって処理が中断されました。")
        sys.exit(130)
    except Exception as e:
        ctx.error(str(e))
        sys.exit(1)


def build_epilog(
    examples: Sequence[str] | None = None,
    related: Sequence[str] | None = None,
) -> str | None:
    """--help 末尾に出す「使用例:」「関連:」節を組み立てる.

    examples は 1 要素 1 コマンド（``uv run python scripts/...`` から書く。補足は ``  # ...`` で行末に）、
    related は前後に使うスクリプト（``scripts/x/y.py: 一言``）。
    ``argparse.ArgumentParser`` を直接作るスクリプトは ``epilog=build_epilog(...)`` と
    ``formatter_class=argparse.RawDescriptionHelpFormatter`` を渡す。
    """
    sections: list[str] = []
    if examples:
        sections.append("使用例:\n" + "\n".join(f"  {e}" for e in examples))
    if related:
        sections.append("関連:\n" + "\n".join(f"  {r}" for r in related))
    return "\n\n".join(sections) or None


def _main_module_doc() -> str | None:
    """実行中スクリプト（__main__）のモジュール docstring."""
    doc = getattr(sys.modules.get("__main__"), "__doc__", None)
    return doc.strip() if doc else None


def create_base_parser(
    description: str | None = None,
    default_limit: int | None = None,
    *,
    examples: Sequence[str] | None = None,
    related: Sequence[str] | None = None,
) -> argparse.ArgumentParser:
    """全スクリプト共通の基底CLIパーサーを生成する.

    description 省略時は実行中スクリプトのモジュール docstring を使う。
    examples / related は build_epilog で「使用例:」「関連:」の epilog にする。
    """
    parser = argparse.ArgumentParser(
        description=description if description is not None else _main_module_doc(),
        epilog=build_epilog(examples, related),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-s",
        "--summary",
        action="store_true",
        help="コンソール向け整形サマリ表示（指定しない場合は生成/合致ファイルパスのみ出力）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="結果をJSON形式で標準出力に出力",
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=default_limit,
        help=f"処理/表示件数の上限 (デフォルト: {default_limit})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="既存ファイルを上書き・強制再取得",
    )
    return parser


def create_search_parser(
    description: str | None = None,
    default_limit: int = 20,
    default_download_limit: int = 5,
    default_session: str = "job-hunt",
    *,
    examples: Sequence[str] | None = None,
    related: Sequence[str] | None = None,
) -> argparse.ArgumentParser:
    """求人検索系スクリプト共通のCLIパーサーを生成する（引数の意味は create_base_parser と同じ）."""
    parser = create_base_parser(
        description=description, default_limit=default_limit, examples=examples, related=related
    )

    # 検索キーワード
    parser.add_argument(
        "query",
        nargs="*",
        help="フリーワード検索キーワード（AND一致、タイトル/企業名/スキル等を検索）",
    )
    parser.add_argument(
        "-k",
        "--keyword",
        action="append",
        dest="keywords",
        help="追加の検索キーワード（複数指定可）",
    )
    parser.add_argument(
        "-c",
        "--company",
        help="企業名（部分一致）",
    )
    parser.add_argument(
        "-t",
        "--title",
        help="求人タイトル（部分一致）",
    )
    parser.add_argument(
        "--skill",
        action="append",
        dest="skills",
        help="必要技術スタック・スキル（複数指定可、例: --skill Python --skill React）",
    )
    parser.add_argument(
        "--min-salary",
        help="最低希望年収（例: 800, 800万, 8000000）",
    )
    parser.add_argument(
        "--max-salary",
        help="最高希望年収（例: 1500, 1500万, 15000000）",
    )
    parser.add_argument(
        "-r",
        "--remote",
        help="リモート条件（例: フルリモート, ハイブリッド, 出社）",
    )
    parser.add_argument(
        "--role",
        help="職種カテゴリ（例: バックエンド, フルスタック）",
    )

    # 取得・保存オプション
    parser.add_argument(
        "-d",
        "--download",
        action="store_true",
        help="ヒットした求人の詳細をローカルMarkdownとして自動保存",
    )
    parser.add_argument(
        "--download-limit",
        type=int,
        default=default_download_limit,
        help=f"ダウンロード保存する求人の上限数 (デフォルト: {default_download_limit})",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="検索結果ファイル（searches/*.md）への保存をスキップ",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="概要抜粋を含む詳細サマリを表示",
    )

    # ブラウザ・セッションオプション
    parser.add_argument(
        "--session",
        default=default_session,
        help=f"ブラウザ永続セッション名 (デフォルト: {default_session})",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="デバッグ用: ブラウザを可視ウィンドウで起動（通常不要）",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="手動認証・待機のタイムアウト秒数 (デフォルト: 120)",
    )

    return parser
