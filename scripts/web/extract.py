"""Tavily で既知の URL（複数可）の本文を Markdown で取り、data/web/extracts/ に保存する CLI.

URL が分かっているときに使う。キーワードから探すなら search.py（判断フローは docs/web/README.md）。
``--query`` を付けると本文全体ではなく関連チャンクだけ返る（``[...]`` はチャンク境界）。全文が欲しいときは付けない。

stdout は保存した ``index.md`` のパスだけ。``index.md`` を読み、必要な結果ファイルだけ読む。
終了コード: 0 成功 / 1 エラー・0 件（stderr ``No results.``）/ 2 ``TAVILY_API_KEY`` 未設定。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import create_base_parser, entrypoint_guard, to_relative_path
from scripts.web import tavily_client
from scripts.web.tavily_client import EXIT_NO_API_KEY, MissingApiKeyError


def main() -> None:
    parser = create_base_parser(
        description="Tavily で既知の URL の本文を Markdown で取り、data/web/extracts/ に保存する",
        examples=[
            "uv run python scripts/web/extract.py https://example.com/page",
            "uv run python scripts/web/extract.py https://example.com/a https://example.com/b -s",
            'uv run python scripts/web/extract.py https://example.com/faq --query "申請期限"  # 関連チャンクだけ取る',
        ],
        related=[
            "scripts/web/search.py: URL が分からないときに先に探す",
            "scripts/vault/add_material.py: 企業の materials に要約を残す",
        ],
    )
    parser.add_argument("urls", nargs="+", help="取得する URL（複数可）")
    parser.add_argument("--query", help="関連チャンクだけ取るためのクエリ（全文が欲しいときは付けない）")
    args = parser.parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        try:
            api_key = tavily_client.get_api_key()
        except MissingApiKeyError as e:
            ctx.error(str(e))
            sys.exit(EXIT_NO_API_KEY)

        urls = args.urls[: args.limit] if args.limit else args.urls
        results = tavily_client.extract(urls, api_key=api_key, query=args.query)
        if not results:
            ctx.log("No results.")
            sys.exit(1)

        meta: dict[str, object] = {"kind": "extract", "urls": urls}
        if args.query:
            meta["query"] = args.query
        index_path = tavily_client.write_results(tavily_client.EXTRACTS_DIR, urls[0], results, meta)
        ctx.add_result_path(index_path)

        def print_summary() -> None:
            print(f"URL 本文抽出: {len(results)}/{len(urls)} 件")
            for i, r in enumerate(results, start=1):
                print(f"[{i}] {r.title}（{len(r.content)} chars）")
                print(f"    {r.url}")
            print(f"保存: {to_relative_path(index_path)}")

        json_data = {"index": to_relative_path(index_path), "results": [r.to_dict() for r in results]}
        sys.exit(ctx.flush_outputs(summary_fn=print_summary, json_data=json_data))


if __name__ == "__main__":
    main()
