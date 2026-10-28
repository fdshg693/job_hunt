"""note.com の記事をキーワードで検索し、一覧（任意で本文）を保存する CLI.

note.com 記事検索CLIスクリプト.

note.com（https://note.com/search）において、
キーワードまたは検索URLから記事一覧を検索・取得し、Markdown/JSONとして永続化します。
オプションで検索結果記事本文の一括取得（fetch_article.py）との連携も行います。
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

# プロジェクトルートパス (scripts/note/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import EntrypointContext, create_base_parser, to_relative_path
from scripts.note.fetch_article import (
    fetch_article,
    fetch_url_json,
)

DEFAULT_SEARCH_OUTPUT_DIR = PROJECT_ROOT / "data" / "note" / "searches"
NOTE_SEARCH_API_URL = "https://note.com/api/v3/searches"


@dataclass
class NoteSearchItem:
    """検索結果のnote記事アイテム."""

    key: str
    title: str
    url: str
    author_name: str
    author_urlname: str
    publish_at: str
    like_count: int
    comment_count: int
    price: int
    can_read: bool
    eyecatch: str | None
    description: str

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換する."""
        return asdict(self)


@dataclass
class NoteSearchResult:
    """note.com 検索結果."""

    query: str
    total_count: int
    returned_count: int
    searched_at: str
    company_key: str | None
    notes: list[NoteSearchItem]

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換する."""
        return {
            "query": self.query,
            "total_count": self.total_count,
            "returned_count": self.returned_count,
            "searched_at": self.searched_at,
            "company_key": self.company_key,
            "notes": [n.to_dict() for n in self.notes],
        }


def extract_query(query_or_url: str) -> str:
    """検索キーワードまたは検索URLからクエリ文字列を抽出する."""
    cleaned = query_or_url.strip()
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        parsed = urllib.parse.urlparse(cleaned)
        qs = urllib.parse.parse_qs(parsed.query)
        q_val = qs.get("q")
        if q_val and q_val[0].strip():
            return q_val[0].strip()
    return cleaned


def sanitize_filename(text: str) -> str:
    """ファイル名として安全な文字列に変換する."""
    cleaned = re.sub(r'[\\/*?:"<>| ]+', "_", text.strip())
    return cleaned[:40].strip("_") or "search"


def build_search_markdown(result: NoteSearchResult) -> str:
    """検索結果からフロントマター付きMarkdown文字列を構築する."""
    frontmatter_dict: dict[str, Any] = {
        "query": result.query,
        "total_count": result.total_count,
        "returned_count": result.returned_count,
        "searched_at": result.searched_at,
    }
    if result.company_key:
        frontmatter_dict["company_key"] = result.company_key

    yaml_header = yaml.dump(
        frontmatter_dict,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).strip()

    body_lines = [
        "---",
        yaml_header,
        "---",
        "",
        f"# note.com 検索結果: {result.query}",
        "",
        f"- **検索キーワード**: `{result.query}`",
        f"- **総ヒット件数**: {result.total_count:,} 件",
        f"- **取得件数**: {result.returned_count} 件",
        f"- **検索日時**: {result.searched_at}",
    ]
    if result.company_key:
        body_lines.append(f"- **関連企業キー**: `{result.company_key}`")
    body_lines.extend(["", "## 記事一覧", ""])

    if not result.notes:
        body_lines.append("*（該当する記事は見つかりませんでした）*")
        body_lines.append("")
        return "\n".join(body_lines)

    body_lines.extend(
        [
            "| # | タイトル | 著者 | スキ数 | 価格 | 公開日 | 記事URL |",
            "| ---: | --- | --- | ---: | ---: | --- | --- |",
        ]
    )

    for idx, item in enumerate(result.notes, start=1):
        escaped_title = item.title.replace("|", "\\|")
        name_str = f"{item.author_name} (@{item.author_urlname})" if item.author_urlname else item.author_name
        name_str = name_str.replace("|", "\\|")
        price_str = "無料" if item.price == 0 else f"{item.price:,}円"
        # 日付整形 (YYYY-MM-DD)
        pub_date = item.publish_at[:10] if item.publish_at and len(item.publish_at) >= 10 else item.publish_at
        body_lines.append(
            f"| {idx} | [{escaped_title}]({item.url}) | {name_str} | {item.like_count:,} | {price_str} | {pub_date} | [{item.url}]({item.url}) |"
        )

    body_lines.append("")
    return "\n".join(body_lines)


def search_notes(
    query_or_url: str,
    limit: int = 10,
    output_dir: Path | None = None,
    company_key: str | None = None,
    fetch_articles_content: bool = False,
    fetch_limit: int | None = None,
    force: bool = False,
    dry_run: bool = False,
    save_files: bool = True,
    ctx: EntrypointContext | None = None,
) -> tuple[NoteSearchResult, list[Path]]:
    """note.comの記事を検索し、一覧取得・保存および記事本文の一括取得連携を行う."""
    query = extract_query(query_or_url)
    if not query:
        raise ValueError(f"検索クエリが空です: {query_or_url}")

    all_notes: list[NoteSearchItem] = []
    seen_keys: set[str] = set()
    cursor: int | None = None
    total_count = 0
    total_pages_fetched = 0
    max_pages = 20  # 安全上限

    while len(all_notes) < limit and total_pages_fetched < max_pages:
        page_size = min(limit - len(all_notes), 20)
        params: dict[str, str] = {
            "q": query,
            "context": "note",
            "mode": "search",
            "size": str(page_size),
        }
        if cursor is not None:
            params["note_cursor"] = str(cursor)

        api_url = f"{NOTE_SEARCH_API_URL}?{urllib.parse.urlencode(params)}"
        if ctx:
            ctx.log(f"[INFO] 検索APIリクエスト中: {api_url}")

        data_json, status_code = fetch_url_json(api_url)
        if not data_json or status_code != 200:
            if ctx:
                ctx.warn(f"検索APIリクエストに失敗しました (status {status_code}): {api_url}")
            break

        total_pages_fetched += 1
        data = data_json.get("data") or {}
        notes_data = data.get("notes") or {}
        total_count = notes_data.get("total_count", total_count)
        contents = notes_data.get("contents") or []
        if not contents:
            break

        for item in contents:
            key = item.get("key")
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)

            user = item.get("user") or {}
            urlname = (user.get("urlname") or "").strip()
            nickname = (user.get("nickname") or user.get("name") or "").strip()
            custom_domain = item.get("custom_domain")

            if custom_domain:
                canonical_url = f"https://{custom_domain}/n/{key}"
            elif urlname:
                canonical_url = f"https://note.com/{urlname}/n/{key}"
            else:
                canonical_url = f"https://note.com/n/{key}"

            note_item = NoteSearchItem(
                key=key,
                title=(item.get("name") or "Untitled").strip(),
                url=canonical_url,
                author_name=nickname,
                author_urlname=urlname,
                publish_at=item.get("publish_at") or "",
                like_count=item.get("like_count") or 0,
                comment_count=item.get("comment_count") or 0,
                price=item.get("price") or 0,
                can_read=item.get("can_read", True),
                eyecatch=item.get("eyecatch") or item.get("thumbnail_external_url"),
                description=(item.get("description") or "").strip(),
            )
            all_notes.append(note_item)
            if len(all_notes) >= limit:
                break

        next_cursor = data.get("note_cursor")
        if next_cursor is None or next_cursor == cursor:
            break
        cursor = next_cursor

    now = datetime.now()
    result = NoteSearchResult(
        query=query,
        total_count=total_count,
        returned_count=len(all_notes),
        searched_at=now.isoformat(timespec="seconds"),
        company_key=company_key,
        notes=all_notes,
    )

    created_paths: list[Path] = []
    if dry_run or not save_files:
        return result, created_paths

    if output_dir:
        dest_dir = output_dir
    elif company_key:
        dest_dir = PROJECT_ROOT / "data" / "note" / "companies" / company_key / "searches"
    else:
        dest_dir = DEFAULT_SEARCH_OUTPUT_DIR

    dest_dir.mkdir(parents=True, exist_ok=True)

    timestamp_prefix = now.strftime("%Y%m%d_%H%M%S")
    safe_q = sanitize_filename(query)

    # 1. JSON保存
    json_path = dest_dir / f"{timestamp_prefix}_{safe_q}.json"
    if not json_path.exists() or force:
        json_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        created_paths.append(json_path)
    else:
        created_paths.append(json_path)

    # 2. Markdown保存
    md_content = build_search_markdown(result)
    md_path = dest_dir / f"{timestamp_prefix}_{safe_q}.md"
    if not md_path.exists() or force:
        md_path.write_text(md_content, encoding="utf-8")
        created_paths.append(md_path)
    else:
        created_paths.append(md_path)

    # 3. オプション: 記事詳細・本文一括取得 (--fetch-articles)
    if fetch_articles_content and all_notes:
        target_articles = all_notes
        if fetch_limit is not None and fetch_limit > 0:
            target_articles = all_notes[:fetch_limit]

        if ctx:
            ctx.log(f"[INFO] 検索結果 {len(target_articles)} 件の記事本文・詳細を取得します...")

        for idx, item in enumerate(target_articles, start=1):
            if ctx:
                ctx.log(f"[{idx}/{len(target_articles)}] 取得中: {item.title} ({item.url})")
            try:
                _, fetched_files = fetch_article(
                    url_or_key=item.key,
                    company_key=company_key,
                    force=force,
                    dry_run=dry_run,
                )
                for f in fetched_files:
                    if f not in created_paths:
                        created_paths.append(f)
            except Exception as e:
                if ctx:
                    ctx.warn(f"記事取得失敗: {item.url} ({e})")

    return result, created_paths


def main() -> None:
    """エントリポイントCLI."""
    parser = create_base_parser(
        description="note.com 記事検索CLIスクリプト",
        default_limit=10,
        examples=[
            'uv run python scripts/note/search_notes.py "<会社名> 転職" --summary',
            'uv run python scripts/note/search_notes.py "エンジニア採用" -n 5 --summary',
            'uv run python scripts/note/search_notes.py "<会社名>" -n 3 -c <company-key> --fetch-articles --summary  # 本文も取得',
        ],
        related=[
            "scripts/note/fetch_article.py: 次に使う（個別記事の本文を取る）",
        ],
    )
    parser.add_argument("query", nargs="*", help="検索キーワードまたは検索URL（例: '転職体験談' または https://note.com/search?q=...）")
    parser.add_argument("-q", "--query-param", dest="query_opt", help="検索キーワード（引数オプション形式）")
    parser.add_argument("-o", "--output-dir", type=Path, help="保存先ディレクトリ（デフォルト: data/note/searches/）")
    parser.add_argument("-c", "--company-key", help="関連付ける企業キー（data/note/companies/{company_key}/searches/ 配下に保存）")
    parser.add_argument("--no-save", action="store_true", help="ファイル保存をスキップ")
    parser.add_argument(
        "--fetch-articles",
        action="store_true",
        help="検索ヒットした各記事の本文・詳細（Markdown/JSON）を一括取得・保存",
    )
    parser.add_argument(
        "--fetch-limit",
        type=int,
        help="--fetch-articles 実行時の記事取得上限数（指定しない場合は取得した全件）",
    )
    parser.add_argument("--dry-run", action="store_true", help="ファイル保存を行わずに解析結果のみ確認")

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    raw_query = args.query_opt or (" ".join(args.query).strip() if args.query else "")
    if not raw_query:
        ctx.error("検索キーワードまたは検索URLを指定してください。")
        sys.exit(1)

    try:
        result, paths = search_notes(
            query_or_url=raw_query,
            limit=args.limit or 10,
            output_dir=args.output_dir,
            company_key=args.company_key,
            fetch_articles_content=args.fetch_articles,
            fetch_limit=args.fetch_limit,
            force=args.force,
            dry_run=args.dry_run,
            save_files=not args.no_save,
            ctx=ctx,
        )

        for p in paths:
            ctx.add_result_path(p)

        def print_summary() -> None:
            print("==================================================")
            print(f"note.com 検索結果: {result.query}")
            print(f"総ヒット件数: {result.total_count:,} 件 (取得: {result.returned_count} 件)")
            if result.company_key:
                print(f"関連企業キー: {result.company_key}")
            print("--------------------------------------------------")
            if not result.notes:
                print("該当する記事は見つかりませんでした。")
            else:
                for idx, n in enumerate(result.notes, start=1):
                    name_str = f"{n.author_name} (@{n.author_urlname})" if n.author_urlname else n.author_name
                    price_str = "無料" if n.price == 0 else f"{n.price:,}円"
                    pub_str = n.publish_at[:10] if len(n.publish_at) >= 10 else n.publish_at
                    print(f"[{idx}] {n.title}")
                    print(f"    著者:   {name_str}")
                    print(f"    公開日: {pub_str} | スキ: {n.like_count:,} | 価格: {price_str}")
                    print(f"    URL:    {n.url}")
            print("--------------------------------------------------")
            if paths:
                print("保存ファイル:")
                for p in paths:
                    print(f"  - {to_relative_path(p)}")
            print("==================================================")

        sys.exit(ctx.flush_outputs(summary_fn=print_summary, json_data=result.to_dict()))

    except Exception as e:
        ctx.error(f"{raw_query}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
