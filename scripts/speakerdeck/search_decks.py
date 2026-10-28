"""Speaker Deck のスライドを検索し、一覧（任意で文字起こし）を保存する CLI.

Speaker Deck 検索CLIスクリプト.

Speaker Deck（https://speakerdeck.com/search）において、
キーワード・言語等でスライドを検索し、一覧取得およびJSON/Markdownとしての永続化、
オプションでスライド文字起こし（fetch_deck.py）との連携を行います。
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

# プロジェクトルートパス (scripts/speakerdeck/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import EntrypointContext, create_base_parser, to_relative_path
from scripts.speakerdeck.fetch_deck import (
    fetch_deck,
    fetch_url_content,
)

DEFAULT_SEARCH_OUTPUT_DIR = PROJECT_ROOT / "data" / "speakerdeck" / "searches"
SPEAKERDECK_SEARCH_BASE_URL = "https://speakerdeck.com/search"


@dataclass
class DeckSearchItem:
    """検索結果のスライドアイテム."""

    id: str
    title: str
    url: str
    username: str
    author_name: str = ""
    slide_count: int = 0
    cover_image: str = ""
    views: int = 0
    views_text: str = ""
    stars: int = 0

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換する."""
        return asdict(self)


@dataclass
class SpeakerDeckSearchResult:
    """Speaker Deck検索結果."""

    query: str
    lang: str
    total_pages_fetched: int
    returned_count: int
    searched_at: str
    decks: list[DeckSearchItem]

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換する."""
        return {
            "query": self.query,
            "lang": self.lang,
            "total_pages_fetched": self.total_pages_fetched,
            "returned_count": self.returned_count,
            "searched_at": self.searched_at,
            "decks": [d.to_dict() for d in self.decks],
        }


def build_search_url(query: str, lang: str = "", page: int = 1) -> str:
    """Speaker Deckの検索URLを構築する."""
    params: dict[str, str] = {"q": query}
    if lang and lang.lower() not in ("all", "any"):
        params["lang"] = lang
    if page > 1:
        params["page"] = str(page)
    return f"{SPEAKERDECK_SEARCH_BASE_URL}?{urllib.parse.urlencode(params)}"


def parse_search_page_html(html_content: str) -> tuple[list[DeckSearchItem], bool]:
    """検索結果ページのHTMLをパースしてスライド一覧と次ページ有無を返す."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_content, "html.parser")
    # "card" かつ "deck-preview" クラスを持つdivを抽出（ハイフン付きサブクラス誤マッチ防止）
    cards = [
        d for d in soup.find_all("div")
        if {"card", "deck-preview"}.issubset(set(d.get("class") or []))
    ]
    decks: list[DeckSearchItem] = []

    for card in cards:
        deck_id = card.get("data-id") or ""
        cover_image = card.get("data-cover-image") or ""
        slide_count_raw = card.get("data-slide-count") or "0"
        try:
            slide_count = int(slide_count_raw)
        except ValueError:
            slide_count = 0

        # タイトル・デッキURL
        link_elem = card.find("a", class_=lambda c: c and "deck-preview-link" in (c.split() if isinstance(c, str) else c))
        href = link_elem.get("href", "") if link_elem else ""
        if href.startswith("/"):
            url = f"https://speakerdeck.com{href}"
        elif href.startswith("http"):
            url = href
        else:
            url = f"https://speakerdeck.com/{href.lstrip('/')}" if href else ""

        title = ""
        if link_elem and link_elem.get("title"):
            title = link_elem["title"].strip()
        if not title:
            title_elem = card.find(class_=lambda c: c and "deck-title" in (c.split() if isinstance(c, str) else c))
            if title_elem:
                title = title_elem.get_text(strip=True)

        # 発表者 / ユーザー名
        username = ""
        author_name = ""
        meta_elem = card.find("div", class_=lambda c: c and "deck-preview-meta" in (c.split() if isinstance(c, str) else c))
        if meta_elem:
            author_link = meta_elem.find("a", href=re.compile(r"^/[^/]+$"))
            if author_link:
                author_href = author_link.get("href", "").strip("/")
                username = author_href
                # aria-labelやテキストから著者名取得
                aria_label = author_link.get("aria-label", "")
                if aria_label and "profile" in aria_label:
                    author_name = aria_label.replace("profile", "").strip()
                if not author_name:
                    # img alt を確認
                    avatar_img = author_link.find("img")
                    if avatar_img and avatar_img.get("alt"):
                        alt_text = avatar_img["alt"]
                        if alt_text.startswith("Avatar for "):
                            author_name = alt_text[len("Avatar for ") :].strip()
                        else:
                            author_name = alt_text.strip()
                if not author_name:
                    author_name = author_link.get_text(strip=True)

        if not username and href:
            # URLからフォールバック抽出 (/username/deck-slug)
            clean_path = urllib.parse.urlparse(url).path.strip("/")
            parts = clean_path.split("/")
            if len(parts) >= 1:
                username = parts[0]

        # スター数
        stars = 0
        star_icon = card.find("svg", class_=re.compile(r"\bicon-star\b"))
        if star_icon and star_icon.parent:
            star_text = star_icon.parent.get_text(strip=True)
            m = re.search(r"(\d[\d,]*)", star_text)
            if m:
                try:
                    stars = int(m.group(1).replace(",", ""))
                except ValueError:
                    stars = 0

        # 閲覧数
        views = 0
        views_text = ""
        view_span = card.find("span", title=re.compile(r"views", re.IGNORECASE))
        if view_span:
            views_text = view_span.get_text(strip=True)
            title_attr = view_span.get("title", "")
            m = re.search(r"([\d,]+)\s*views", title_attr, re.IGNORECASE)
            if m:
                try:
                    views = int(m.group(1).replace(",", ""))
                except ValueError:
                    views = 0
        else:
            view_icon = card.find("svg", class_=re.compile(r"\bicon-eye\b"))
            if view_icon and view_icon.parent:
                views_text = view_icon.parent.get_text(strip=True)
                m = re.search(r"(\d[\d,]*)", views_text)
                if m:
                    try:
                        views = int(m.group(1).replace(",", ""))
                    except ValueError:
                        views = 0

        decks.append(
            DeckSearchItem(
                id=deck_id,
                title=title or deck_id,
                url=url,
                username=username,
                author_name=author_name or username,
                slide_count=slide_count,
                cover_image=cover_image,
                views=views,
                views_text=views_text,
                stars=stars,
            )
        )

    # 次ページの有無判定
    has_next_page = False
    pagy_nav = soup.find("nav", class_=re.compile(r"\bpagy-bootstrap-nav\b"))
    if pagy_nav:
        next_li = pagy_nav.find("li", class_=re.compile(r"\bnext\b"))
        if next_li and "disabled" not in (next_li.get("class") or []):
            if next_li.find("a"):
                has_next_page = True

    return decks, has_next_page


def build_search_markdown(result: SpeakerDeckSearchResult) -> str:
    """検索結果からフロントマター付きMarkdown文字列を構築する."""
    frontmatter_dict: dict[str, Any] = {
        "query": result.query,
        "lang": result.lang or "all",
        "returned_count": result.returned_count,
        "total_pages_fetched": result.total_pages_fetched,
        "searched_at": result.searched_at,
    }
    yaml_header = yaml.dump(frontmatter_dict, allow_unicode=True, sort_keys=False).strip()

    body_lines = [
        "---",
        yaml_header,
        "---",
        "",
        f"# Speaker Deck 検索結果: {result.query}",
        "",
        f"- **検索キーワード**: `{result.query}`",
        f"- **言語フィルタ**: `{result.lang or '全言語'}`",
        f"- **取得件数**: {result.returned_count} 件",
        f"- **検索日時**: {result.searched_at}",
        "",
        "## スライド一覧",
        "",
    ]

    if not result.decks:
        body_lines.append("*（該当するスライドは見つかりませんでした）*")
        body_lines.append("")
        return "\n".join(body_lines)

    body_lines.extend(
        [
            "| # | タイトル | 発表者 | 枚数 | 閲覧数 | ★ | スライドURL |",
            "| ---: | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )

    for idx, deck in enumerate(result.decks, start=1):
        name_str = f"{deck.author_name} (@{deck.username})" if deck.author_name else f"@{deck.username}"
        escaped_title = deck.title.replace("|", "\\|")
        views_display = deck.views_text or str(deck.views)
        body_lines.append(
            f"| {idx} | [{escaped_title}]({deck.url}) | {name_str} | {deck.slide_count} | {views_display} | {deck.stars} | [{deck.url}]({deck.url}) |"
        )

    body_lines.append("")
    return "\n".join(body_lines)


def sanitize_filename(text: str) -> str:
    """ファイル名として安全な文字列に変換する."""
    cleaned = re.sub(r'[\\/*?:"<>| ]+', "_", text.strip())
    return cleaned[:40].strip("_") or "search"


def search_decks(
    query: str,
    lang: str = "ja",
    limit: int = 20,
    max_pages: int = 10,
    output_dir: Path | None = None,
    fetch_decks_content: bool = False,
    download_pdf: bool = False,
    download_images: bool = False,
    force: bool = False,
    dry_run: bool = False,
    save_files: bool = True,
    ctx: EntrypointContext | None = None,
) -> tuple[SpeakerDeckSearchResult, list[Path]]:
    """Speaker Deckを検索し、一覧取得および保存・文字起こし連携を行う."""
    all_decks: list[DeckSearchItem] = []
    seen_ids: set[str] = set()
    current_page = 1
    total_pages_fetched = 0

    while current_page <= max_pages and len(all_decks) < limit:
        url = build_search_url(query=query, lang=lang, page=current_page)
        if ctx:
            ctx.log(f"[INFO] 検索URL取得中 (page {current_page}): {url}")

        html_content, status = fetch_url_content(url)
        if not html_content:
            if ctx:
                ctx.warn(f"ページ {current_page} の取得に失敗しました (status {status}): {url}")
            break

        total_pages_fetched += 1
        page_decks, has_next = parse_search_page_html(html_content)
        if not page_decks:
            break

        for d in page_decks:
            deck_key = d.id or d.url
            if deck_key not in seen_ids:
                seen_ids.add(deck_key)
                all_decks.append(d)
                if len(all_decks) >= limit:
                    break

        if not has_next or len(all_decks) >= limit:
            break

        current_page += 1

    now = datetime.now()
    result = SpeakerDeckSearchResult(
        query=query,
        lang=lang,
        total_pages_fetched=total_pages_fetched,
        returned_count=len(all_decks),
        searched_at=now.isoformat(timespec="seconds"),
        decks=all_decks,
    )

    created_paths: list[Path] = []
    if dry_run or not save_files:
        return result, created_paths

    dest_dir = output_dir or DEFAULT_SEARCH_OUTPUT_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    timestamp_prefix = now.strftime("%Y%m%d_%H%M%S")
    safe_q = sanitize_filename(query)

    # 1. JSON保存
    json_path = dest_dir / f"{timestamp_prefix}_{safe_q}.json"
    json_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    created_paths.append(json_path)

    # 2. Markdown保存
    md_content = build_search_markdown(result)
    md_path = dest_dir / f"{timestamp_prefix}_{safe_q}.md"
    md_path.write_text(md_content, encoding="utf-8")
    created_paths.append(md_path)

    # 3. オプション: スライド文字起こし一括取得 (--fetch-decks)
    if fetch_decks_content and all_decks:
        if ctx:
            ctx.log(f"[INFO] 検索結果 {len(all_decks)} 件のスライド文字起こしを取得します...")
        for idx, deck_item in enumerate(all_decks, start=1):
            if ctx:
                ctx.log(f"[{idx}/{len(all_decks)}] 取得中: {deck_item.title} ({deck_item.url})")
            try:
                _, fetched_files = fetch_deck(
                    url_or_id=deck_item.url,
                    download_pdf=download_pdf,
                    download_images=download_images,
                    force=force,
                    dry_run=dry_run,
                )
                for f in fetched_files:
                    if f not in created_paths:
                        created_paths.append(f)
            except Exception as e:
                if ctx:
                    ctx.warn(f"デッキ取得失敗: {deck_item.url} ({e})")

    return result, created_paths


def main() -> None:
    """エントリポイントCLI."""
    parser = create_base_parser(
        description="Speaker Deck スライド検索CLIスクリプト",
        default_limit=20,
        examples=[
            'uv run python scripts/speakerdeck/search_decks.py "<会社名> 会社説明資料" --summary',
            'uv run python scripts/speakerdeck/search_decks.py "Kubernetes" --lang ja -n 5 --summary',
            'uv run python scripts/speakerdeck/search_decks.py "<会社名>" -n 3 --fetch-decks --summary  # 文字起こしも取得',
        ],
        related=[
            "scripts/speakerdeck/fetch_deck.py: 次に使う（個別スライドを文字起こしする）",
        ],
    )
    parser.add_argument("query", nargs="+", help="検索キーワード（半角スペース区切りで複数指定可）")
    parser.add_argument(
        "--lang",
        default="ja",
        help="言語フィルタ (デフォルト: ja。'all' または空文字で全言語)",
    )
    parser.add_argument("-o", "--output-dir", type=Path, help="保存先ディレクトリ（デフォルト: data/speakerdeck/searches/）")
    parser.add_argument("--no-save", action="store_true", help="ファイル保存をスキップ")
    parser.add_argument(
        "--fetch-decks",
        action="store_true",
        help="検索ヒットした各スライドの文字起こし（transcript.md/deck.json）を一括取得・保存",
    )
    parser.add_argument(
        "--download-pdf",
        action="store_true",
        help="--fetch-decks 実行時に原本PDFもダウンロード保存",
    )
    parser.add_argument(
        "--download-images",
        action="store_true",
        help="--fetch-decks 実行時に全スライド画像（JPEG）もダウンロード保存",
    )
    parser.add_argument("--dry-run", action="store_true", help="ファイル保存を行わずに解析結果のみ確認")

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    full_query = " ".join(args.query).strip()
    if not full_query:
        ctx.error("検索キーワードを指定してください。")
        sys.exit(1)

    lang_param = "" if args.lang.lower() in ("all", "any", "") else args.lang

    try:
        result, paths = search_decks(
            query=full_query,
            lang=lang_param,
            limit=args.limit or 20,
            output_dir=args.output_dir,
            fetch_decks_content=args.fetch_decks,
            download_pdf=args.download_pdf,
            download_images=args.download_images,
            force=args.force,
            dry_run=args.dry_run,
            save_files=not args.no_save,
            ctx=ctx,
        )

        for p in paths:
            ctx.add_result_path(p)

        def print_summary() -> None:
            print("==================================================")
            print(f"Speaker Deck 検索結果: {result.query}")
            print(f"言語フィルタ: {result.lang or '全言語'}")
            print(f"取得件数:     {result.returned_count} 件 (取得ページ数: {result.total_pages_fetched})")
            print("--------------------------------------------------")
            if not result.decks:
                print("該当するスライドは見つかりませんでした。")
            else:
                for idx, d in enumerate(result.decks, start=1):
                    name_str = f"{d.author_name} (@{d.username})" if d.author_name else f"@{d.username}"
                    views_str = d.views_text or f"{d.views} views"
                    print(f"[{idx}] {d.title}")
                    print(f"    発表者:   {name_str}")
                    print(f"    スライド: {d.slide_count} 枚 | 閲覧数: {views_str} | ★: {d.stars}")
                    print(f"    URL:      {d.url}")
            print("--------------------------------------------------")
            if paths:
                print("保存ファイル:")
                for p in paths:
                    print(f"  - {to_relative_path(p)}")
            print("==================================================")

        sys.exit(ctx.flush_outputs(summary_fn=print_summary, json_data=result.to_dict()))

    except Exception as e:
        ctx.error(f"{full_query}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
