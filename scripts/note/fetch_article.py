"""note.com の記事 1 件を URL・key から取得して Markdown・JSON 保存する CLI.

note.com 単一記事取得スクリプト.

note.com の記事URLまたは note key からメタデータおよび本文HTMLを取得し、
Markdown（Frontmatter付き）および構造化JSONとして保存します。
"""

from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from bs4 import BeautifulSoup, NavigableString, Tag

# プロジェクトルートパス (scripts/note/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import EntrypointContext, create_base_parser, to_relative_path
from scripts.common.storage import add_material_refs, read_material_refs

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

HTTP_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


@dataclass
class NoteArticle:
    """note記事のデータモデル."""

    key: str
    title: str
    url: str
    author_name: str
    author_urlname: str
    author_id: int | None
    author_image: str | None
    publish_at: str
    fetched_at: str
    like_count: int
    comment_count: int
    price: int
    can_read: bool
    eyecatch: str | None
    tags: list[str]
    status: str
    body_markdown: str
    body_html: str = ""

    def to_dict(self, include_html: bool = False) -> dict[str, Any]:
        """辞書形式に変換."""
        d = asdict(self)
        if not include_html:
            d.pop("body_html", None)
        return d


def extract_note_key(url_or_key: str) -> str:
    """URLまたはキー文字列から note_key を抽出する.

    例:
      - https://note.com/narumiruna19/n/n24f8414083da -> n24f8414083da
      - https://my-domain.com/n/n24f8414083da?param=1 -> n24f8414083da
      - n24f8414083da -> n24f8414083da
    """
    clean = url_or_key.strip().split("?")[0].split("#")[0].rstrip("/")
    # /n/(n[a-zA-Z0-9]+) のパターン
    m = re.search(r"/n/(n[a-zA-Z0-9]+)", clean)
    if m:
        return m.group(1)
    # 単独の n[a-zA-Z0-9]{10,} パターン
    m2 = re.search(r"^(n[a-zA-Z0-9]{8,})$", clean)
    if m2:
        return m2.group(1)
    raise ValueError(f"noteの記事キー（note_key）を特定できませんでした: {url_or_key}")


def get_ssl_context() -> ssl.SSLContext:
    """SSLコンテキストを生成する."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def fetch_url_json(url: str, headers: dict[str, str] | None = None) -> tuple[dict[str, Any] | None, int]:
    """HTTP GETでJSONデータを取得する."""
    h = headers or HTTP_HEADERS
    req = urllib.request.Request(url, headers=h)
    ctx = get_ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            return json.loads(content), resp.getcode()
    except urllib.error.HTTPError as e:
        return None, e.code
    except (ssl.SSLCertVerificationError, urllib.error.URLError):
        # 証明書検証エラー時は unverified context でリトライ
        try:
            unverified_ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=20, context=unverified_ctx) as resp:
                content = resp.read().decode("utf-8", errors="replace")
                return json.loads(content), resp.getcode()
        except urllib.error.HTTPError as he:
            return None, he.code
        except Exception:
            return None, 0
    except Exception:
        return None, 0


def _parse_inline(node: Tag | NavigableString) -> str:
    """インライン要素を再帰的にパースしてMarkdownテキストを生成する."""
    if isinstance(node, NavigableString):
        return str(node)

    res: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            res.append(str(child))
        elif isinstance(child, Tag):
            tag_name = child.name.lower()
            if tag_name == "br":
                res.append("\n")
            elif tag_name in ("strong", "b"):
                inner = _parse_inline(child).strip()
                res.append(f"**{inner}**" if inner else "")
            elif tag_name in ("em", "i"):
                inner = _parse_inline(child).strip()
                res.append(f"*{inner}*" if inner else "")
            elif tag_name == "code":
                res.append(f"`{child.get_text()}`")
            elif tag_name == "a":
                href = child.get("href", "")
                inner = _parse_inline(child).strip()
                if inner and href:
                    res.append(f"[{inner}]({href})")
                elif inner:
                    res.append(inner)
                elif href:
                    res.append(href)
            elif tag_name == "img":
                src = child.get("src") or child.get("data-src") or ""
                alt = child.get("alt", "")
                if src:
                    res.append(f"![{alt}]({src})")
            else:
                res.append(_parse_inline(child))
    return "".join(res)


def html_to_markdown(html_str: str, embedded_contents: list[dict[str, Any]] | None = None) -> str:
    """noteの本文HTMLをGitHub Flavored Markdownに変換する."""
    if not html_str:
        return ""

    soup = BeautifulSoup(html_str, "html.parser")

    # 不要タグ・動的目次タグの削除
    for toc in soup.find_all("table-of-contents"):
        toc.decompose()

    # 埋め込みコンテンツ（key -> url）の辞書作成
    embedded_map: dict[str, str] = {}
    if embedded_contents:
        for emb in embedded_contents:
            emb_key = emb.get("key")
            emb_url = emb.get("url")
            if emb_key and emb_url:
                embedded_map[emb_key] = emb_url

    md_blocks: list[str] = []

    # トップレベルタグを順次処理
    # noteのbody直下には p, h2, h3, h4, figure, hr, blockquote, pre, ul, ol 等が並ぶ
    for elem in soup.children:
        if isinstance(elem, NavigableString):
            text = str(elem).strip()
            if text:
                md_blocks.append(text)
            continue

        if not isinstance(elem, Tag):
            continue

        tag_name = elem.name.lower()

        if tag_name == "h2":
            text = _parse_inline(elem).strip()
            if text:
                md_blocks.append(f"## {text}")

        elif tag_name == "h3":
            text = _parse_inline(elem).strip()
            if text:
                md_blocks.append(f"### {text}")

        elif tag_name == "h4":
            text = _parse_inline(elem).strip()
            if text:
                md_blocks.append(f"#### {text}")

        elif tag_name == "hr":
            md_blocks.append("---")

        elif tag_name == "blockquote":
            lines = elem.get_text().splitlines()
            quoted = "\n".join(f"> {line}" for line in lines if line.strip())
            if quoted:
                md_blocks.append(quoted)

        elif tag_name == "pre":
            code_tag = elem.find("code")
            code_text = code_tag.get_text() if code_tag else elem.get_text()
            md_blocks.append(f"```\n{code_text.rstrip()}\n```")

        elif tag_name == "ul":
            items: list[str] = []
            for li in elem.find_all("li", recursive=False):
                item_text = _parse_inline(li).strip()
                if item_text:
                    items.append(f"- {item_text}")
            if items:
                md_blocks.append("\n".join(items))

        elif tag_name == "ol":
            items = []
            for idx, li in enumerate(elem.find_all("li", recursive=False), 1):
                item_text = _parse_inline(li).strip()
                if item_text:
                    items.append(f"{idx}. {item_text}")
            if items:
                md_blocks.append("\n".join(items))

        elif tag_name == "figure":
            img = elem.find("img")
            caption_elem = elem.find("figcaption")
            caption = caption_elem.get_text().strip() if caption_elem else ""

            if img:
                src = img.get("src") or img.get("data-src") or ""
                alt = img.get("alt", "")
                if src:
                    fig_lines = [f"![{alt}]({src})"]
                    if caption:
                        fig_lines.append(f"*{caption}*")
                    md_blocks.append("\n\n".join(fig_lines))
            else:
                # 埋め込みカードまたは外部リンク
                data_src = elem.get("data-src")
                emb_key = elem.get("embedded-content-key")
                target_url = data_src or (embedded_map.get(emb_key) if emb_key else "")
                if target_url:
                    label = caption if caption else target_url
                    md_blocks.append(f"[{label}]({target_url})")

        elif tag_name == "p":
            text = _parse_inline(elem).strip()
            if text:
                md_blocks.append(text)

        else:
            # その他のブロック要素
            text = _parse_inline(elem).strip()
            if text:
                md_blocks.append(text)

    # 連続する空行を整える
    raw_md = "\n\n".join(md_blocks)
    cleaned = re.sub(r"\n{3,}", "\n\n", raw_md)
    return cleaned.strip()


def build_markdown(article: NoteArticle) -> str:
    """記事オブジェクトからFrontmatter付きMarkdown文字列を構築する."""
    frontmatter_dict: dict[str, Any] = {
        "id": article.key,
        "source": "note",
        "title": article.title,
        "author": article.author_name,
        "author_urlname": article.author_urlname,
        "url": article.url,
        "published_at": article.publish_at,
        "fetched_at": article.fetched_at,
        "likes": article.like_count,
        "comments": article.comment_count,
        "price": article.price,
        "can_read": article.can_read,
    }
    if article.tags:
        frontmatter_dict["tags"] = article.tags
    if article.eyecatch:
        frontmatter_dict["eyecatch"] = article.eyecatch

    # YAMLヘッダーをフォーマット
    fm_str = yaml.dump(
        frontmatter_dict,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).strip()

    return f"---\n{fm_str}\n---\n\n{article.body_markdown}\n"


def fetch_article(
    url_or_key: str,
    output_dir: Path | None = None,
    company_key: str | None = None,
    save_json: bool = True,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[NoteArticle, list[Path]]:
    """note記事の取得・Markdown/JSON保存を実行する.

    Returns:
        (NoteArticle, 保存したファイルのPath一覧)
    """
    key = extract_note_key(url_or_key)
    api_url = f"https://note.com/api/v3/notes/{key}"

    data_json, status_code = fetch_url_json(api_url)
    if not data_json or status_code != 200:
        if status_code == 404:
            raise RuntimeError(f"記事が見つかりませんでした (404 Not Found): {key}")
        raise RuntimeError(f"note APIからの記事データ取得に失敗しました (status {status_code}): {api_url}")

    data = data_json.get("data")
    if not data:
        raise RuntimeError(f"レスポンスに記事データが含まれていませんでした: {key}")

    user = data.get("user") or {}
    urlname = (user.get("urlname") or "unknown").strip()
    nickname = (user.get("nickname") or "").strip()
    author_id = user.get("id")
    author_image = user.get("user_profile_image_path")

    # タグ抽出
    hashtag_notes = data.get("hashtag_notes") or []
    tags: list[str] = []
    for h in hashtag_notes:
        ht = h.get("hashtag") or {}
        name = ht.get("name")
        if name:
            tags.append(name.lstrip("#"))

    embedded_contents = data.get("embedded_contents") or []
    body_html = data.get("body") or ""
    body_md = html_to_markdown(body_html, embedded_contents)

    # 記事URL（canonical）
    canonical_url = data.get("note_url") or f"https://note.com/{urlname}/n/{key}"

    now = datetime.now()
    article = NoteArticle(
        key=key,
        title=data.get("name") or "Untitled",
        url=canonical_url,
        author_name=nickname,
        author_urlname=urlname,
        author_id=author_id,
        author_image=author_image,
        publish_at=data.get("publish_at") or "",
        fetched_at=now.isoformat(timespec="seconds"),
        like_count=data.get("like_count") or 0,
        comment_count=data.get("comment_count") or 0,
        price=data.get("price") or 0,
        can_read=data.get("can_read", True),
        eyecatch=data.get("eyecatch"),
        tags=tags,
        status=data.get("status") or "published",
        body_markdown=body_md,
        body_html=body_html,
    )

    # 保存先ディレクトリの決定
    if output_dir:
        dest_dir = output_dir
    elif company_key:
        dest_dir = PROJECT_ROOT / "data" / "note" / "companies" / company_key
    else:
        dest_dir = PROJECT_ROOT / "data" / "note" / "articles" / urlname

    created_paths: list[Path] = []
    if dry_run:
        return article, created_paths

    dest_dir.mkdir(parents=True, exist_ok=True)

    # 1. Markdown保存
    md_content = build_markdown(article)
    md_path = dest_dir / f"{key}.md"
    if not md_path.exists() or force:
        # 上書きで material への逆参照（フロントマター materials）が消えないよう引き継ぐ
        material_refs = read_material_refs(md_path)
        md_path.write_text(md_content, encoding="utf-8")
        add_material_refs(md_path, material_refs)
        created_paths.append(md_path)
    else:
        created_paths.append(md_path)

    # 2. JSON保存（オプション）
    if save_json:
        json_path = dest_dir / f"{key}.json"
        if not json_path.exists() or force:
            json_path.write_text(
                json.dumps(article.to_dict(include_html=False), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            created_paths.append(json_path)
        else:
            created_paths.append(json_path)

    return article, created_paths


def main() -> None:
    """エントリポイントCLI."""
    parser = create_base_parser(
        description="note.com 単一記事取得スクリプト",
        examples=[
            'uv run python scripts/note/fetch_article.py "https://note.com/<user>/n/<note-key>" --summary',
            "uv run python scripts/note/fetch_article.py <note-key> --summary  # note key だけでも可",
            'uv run python scripts/note/fetch_article.py "https://note.com/<user>/n/<note-key>" -c <company-key> --summary  # 企業別に保存',
        ],
        related=[
            "scripts/note/search_notes.py: 前に使う（記事 URL を探す）",
        ],
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="note記事URLまたはnote key（例: https://note.com/narumiruna19/n/n24f8414083da または n24f8414083da）",
    )
    parser.add_argument("--url", help="note記事URL（位置引数の代替）")
    parser.add_argument("--key", help="note key（位置引数の代替）")
    parser.add_argument("-o", "--output-dir", type=Path, help="保存先ディレクトリ（指定しない場合は data/note/articles/...）")
    parser.add_argument("-c", "--company-key", help="関連付ける企業キー（data/note/companies/{company_key}/ 配下に保存）")
    parser.add_argument("--no-json", action="store_true", help="JSONメタデータの保存をスキップ（Markdownのみ保存）")
    parser.add_argument("--dry-run", action="store_true", help="ファイル保存を行わずに解析結果のみ確認")

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    target_str = args.target or args.url or args.key
    if not target_str:
        parser.error("記事URLまたはキーを指定してください（例: https://note.com/user/n/nXXXXXXXXXXXX）")

    try:
        article, paths = fetch_article(
            url_or_key=target_str,
            output_dir=args.output_dir,
            company_key=args.company_key,
            save_json=not args.no_json,
            force=args.force,
            dry_run=args.dry_run,
        )

        for p in paths:
            ctx.add_result_path(p)

        def print_summary() -> None:
            print("==================================================")
            print(f"タイトル:       {article.title}")
            print(f"著者:           {article.author_name} (@{article.author_urlname})")
            print(f"公開日時:       {article.publish_at}")
            print(f"スキ数:         {article.like_count} 件")
            print(f"コメント数:     {article.comment_count} 件")
            price_label = "無料" if article.price == 0 else f"{article.price} 円"
            if not article.can_read:
                price_label += " (一部有料・未購入)"
            print(f"価格:           {price_label}")
            if article.tags:
                print(f"タグ:           {', '.join(article.tags)}")
            print(f"記事URL:        {article.url}")
            print(f"本文文字数:     {len(article.body_markdown)} 文字")
            print("--------------------------------------------------")
            print("保存ファイル:")
            for p in paths:
                print(f"  - {to_relative_path(p)}")
            print("==================================================")

        sys.exit(ctx.flush_outputs(summary_fn=print_summary, json_data=article.to_dict()))

    except Exception as e:
        ctx.error(f"{target_str}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
