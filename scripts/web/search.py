"""Tavily で一般 Web を検索し、結果の抜粋を data/web/searches/ に保存する CLI.

公的機関の一次情報・ニュース・サービス比較・裏取りなど、媒体スクリプトの対象外の Web 調査に使う。
対象 URL が分かっているなら extract.py を使う（判断フローは docs/web/README.md）。

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
        description="Tavily で一般 Web を検索し、結果の抜粋を data/web/searches/ に保存する",
        default_limit=tavily_client.DEFAULT_MAX_RESULTS,
        examples=[
            'uv run python scripts/web/search.py "就労ビザ 申請 必要書類"',
            'uv run python scripts/web/search.py "skilled visa requirements" --include-domain immi.homeaffairs.gov.au',
            'uv run python scripts/web/search.py "リモートワーク 手当 相場" -n 10 -s',
        ],
        related=[
            "scripts/web/extract.py: 結果ファイルの URL: 行を渡して全文を取る",
        ],
    )
    parser.add_argument("query", help="検索クエリ（日本語可。弱ければ英語・日英混在で再実行）")
    parser.add_argument(
        "--include-domain",
        action="append",
        default=[],
        help="優先するドメイン（繰り返し可。完全な隔離フィルタではない。狭い host を優先）",
    )
    parser.add_argument("--exclude-domain", action="append", default=[], help="除外するドメイン（繰り返し可）")
    args = parser.parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        try:
            api_key = tavily_client.get_api_key()
        except MissingApiKeyError as e:
            ctx.error(str(e))
            sys.exit(EXIT_NO_API_KEY)

        results = tavily_client.search(
            args.query,
            api_key=api_key,
            max_results=args.limit or tavily_client.DEFAULT_MAX_RESULTS,
            include_domains=args.include_domain,
            exclude_domains=args.exclude_domain,
        )
        if not results:
            ctx.log("No results.")
            sys.exit(1)

        meta: dict[str, object] = {"kind": "search", "query": args.query}
        if args.include_domain:
            meta["include_domains"] = args.include_domain
        if args.exclude_domain:
            meta["exclude_domains"] = args.exclude_domain
        index_path = tavily_client.write_results(tavily_client.SEARCHES_DIR, args.query, results, meta)
        ctx.add_result_path(index_path)

        def print_summary() -> None:
            print(f"Web 検索: {args.query}（{len(results)} 件）")
            for i, r in enumerate(results, start=1):
                print(f"[{i}] {r.title}  score={r.score}")
                print(f"    {r.url}")
            print(f"保存: {to_relative_path(index_path)}")

        json_data = {"index": to_relative_path(index_path), "results": [r.to_dict() for r in results]}
        sys.exit(ctx.flush_outputs(summary_fn=print_summary, json_data=json_data))


if __name__ == "__main__":
    main()
