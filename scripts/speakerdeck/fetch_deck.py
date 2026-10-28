"""Speaker Deck のスライドを文字起こしして Markdown・JSON 保存する CLI.

Speaker Deck スライド文字起こし・取得モジュール.

Speaker Deck のURLからメタデータ、スライド別テキスト、画像URL、PDFダウンロードリンクを抽出し、
Markdown（transcript.md）および構造化JSON（deck.json）として保存します。
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from bs4 import BeautifulSoup

# プロジェクトルートパス (scripts/speakerdeck/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import EntrypointContext, create_base_parser, to_relative_path
from scripts.common.storage import add_material_refs, read_material_refs

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

HTTP_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


@dataclass
class SlideData:
    """スライド単体のデータモデル."""

    index: int
    image_url: str
    preview_url: str = ""
    note: str = ""
    text: str = ""
    local_image_path: str = ""


@dataclass
class DeckData:
    """スライドデッキ全体のデータモデル."""

    url: str
    username: str
    deck_slug: str
    title: str
    presentation_id: str
    author_name: str = ""
    description: str = ""
    published_at: str = ""
    pdf_url: str = ""
    slide_count: int = 0
    slides: list[SlideData] | None = None
    fetched_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換."""
        d = asdict(self)
        return d


def normalize_slide_text(raw_text: str) -> str:
    """スライドテキストの制御文字除去と空白・改行の正規化を行う."""
    if not raw_text:
        return ""
    # 改ページ制御文字 (\x0c / \f) の除去
    cleaned = raw_text.replace("\x0c", "").replace("\f", "")
    # 行頭・行末の不要な空白除去
    lines = [line.strip() for line in cleaned.splitlines()]
    # 連続する空行を1行に集約
    normalized_lines: list[str] = []
    prev_empty = False
    for line in lines:
        if not line:
            if not prev_empty:
                normalized_lines.append("")
                prev_empty = True
        else:
            normalized_lines.append(line)
            prev_empty = False

    return "\n".join(normalized_lines).strip()


def parse_speakerdeck_url(url: str) -> tuple[str, str]:
    """Speaker DeckのURLから username と deck_slug を抽出する.

    例: https://speakerdeck.com/loglass2019/whats-loglass -> ("loglass2019", "whats-loglass")
    """
    clean_url = url.split("?")[0].split("#")[0].rstrip("/")
    parsed = urllib.parse.urlparse(clean_url)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0] != "player":
        return parts[0], parts[1]
    if len(parts) == 2 and parts[0] == "player":
        return "player", parts[1]
    return "unknown", "unknown"


import ssl


def get_ssl_context() -> ssl.SSLContext:
    """SSLコンテキストを生成する. システム日付の差異（未来日時シミュレーション等）による期限切れに対応."""
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    return ctx


def fetch_url_content(url: str, headers: dict[str, str] | None = None) -> tuple[str | None, int]:
    """HTTP GETでテキストコンテンツを取得する."""
    h = headers or HTTP_HEADERS
    req = urllib.request.Request(url, headers=h)
    ctx = get_ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            return content, resp.getcode()
    except urllib.error.HTTPError as e:
        return None, e.code
    except (ssl.SSLCertVerificationError, urllib.error.URLError):
        # 証明書期限切れなどの検証エラー時は unverified context でリトライ
        try:
            unverified_ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=20, context=unverified_ctx) as resp:
                content = resp.read().decode("utf-8", errors="replace")
                return content, resp.getcode()
        except urllib.error.HTTPError as he:
            return None, he.code
        except Exception:
            return None, 0
    except Exception:
        return None, 0


def download_binary(url: str, dest_path: Path) -> bool:
    """指定URLからバイナリファイルをダウンロード保存する."""
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    ctx = get_ssl_context()
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp, open(dest_path, "wb") as f:
            f.write(resp.read())
        return True
    except (ssl.SSLCertVerificationError, urllib.error.URLError):
        try:
            unverified_ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=30, context=unverified_ctx) as resp, open(dest_path, "wb") as f:
                f.write(resp.read())
            return True
        except Exception as e:
            print(f"[警告] ダウンロード失敗: {url} ({e})", file=sys.stderr)
            return False
    except Exception as e:
        print(f"[警告] ダウンロード失敗: {url} ({e})", file=sys.stderr)
        return False


def parse_deck_page_html(html_content: str, deck_url: str) -> dict[str, Any]:
    """通常デッキページのHTMLをパースしてメタデータを抽出する."""
    soup = BeautifulSoup(html_content, "html.parser")
    username, deck_slug = parse_speakerdeck_url(deck_url)

    # 1. プレゼンテーションID
    presentation_id = ""
    embed_div = soup.find(class_=re.compile(r"speakerdeck-embed"))
    if embed_div and embed_div.get("data-id"):
        presentation_id = embed_div["data-id"]
    if not presentation_id:
        iframe = soup.find("iframe", src=re.compile(r"/player/"))
        if iframe and iframe.get("src"):
            m = re.search(r"/player/([a-zA-Z0-9_-]+)", iframe["src"])
            if m:
                presentation_id = m.group(1)
    if not presentation_id:
        # data-id 属性を持つ要素全般
        elem = soup.find(attrs={"data-id": True})
        if elem and elem.get("data-id"):
            presentation_id = elem["data-id"]

    # 2. タイトル
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()

    # 3. 著者 / ユーザー名
    author_name = ""
    author_elem = soup.find("a", class_=re.compile(r"speakerdeck-author|author"))
    if author_elem:
        author_name = author_elem.get_text(strip=True)

    # 4. 説明文
    description = ""
    desc_elem = soup.find("div", class_=re.compile(r"description"))
    if desc_elem:
        description = desc_elem.get_text("\n", strip=True)
    if not description:
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            description = og_desc["content"].strip()

    # 5. 公開日
    published_at = ""
    time_elem = soup.find("time")
    if time_elem:
        published_at = time_elem.get("datetime") or time_elem.get_text(strip=True)

    # 6. PDFダウンロードリンク
    pdf_url = ""
    pdf_link = soup.find("a", title=re.compile(r"Download PDF", re.IGNORECASE))
    if not pdf_link:
        pdf_link = soup.find("a", href=re.compile(r"\.pdf(\?|$)", re.IGNORECASE))
    if pdf_link and pdf_link.get("href"):
        href = pdf_link["href"].strip()
        pdf_url = href if href.startswith("http") else urllib.parse.urljoin("https://speakerdeck.com", href)

    return {
        "url": deck_url,
        "username": username,
        "deck_slug": deck_slug,
        "title": title or deck_slug,
        "presentation_id": presentation_id,
        "author_name": author_name,
        "description": description,
        "published_at": published_at,
        "pdf_url": pdf_url,
    }


def parse_player_html(html_content: str) -> list[SlideData]:
    """埋め込みプレイヤーHTML（/player/{id}）をパースして各スライド情報を抽出する."""
    soup = BeautifulSoup(html_content, "html.parser")
    # プレゼンター枠（previous/current/next）を除外し、実スライド（js-sd-slide かつ data-url 保持）を抽出
    slide_elements = [
        s for s in soup.find_all(
            "div",
            class_=lambda c: c and "js-sd-slide" in c.split(),
        )
        if s.get("data-url")
    ]

    slides: list[SlideData] = []
    for idx, slide_elem in enumerate(slide_elements, start=1):
        image_url = slide_elem.get("data-url") or ""
        preview_url = slide_elem.get("data-preview-url") or ""
        note = slide_elem.get("data-slide-note") or ""

        # テキスト要素
        text_elem = slide_elem.find(class_=re.compile(r"sd-player-slides--text"))
        raw_text = text_elem.get_text("\n") if text_elem else ""
        cleaned_text = normalize_slide_text(raw_text)

        slides.append(
            SlideData(
                index=idx,
                image_url=image_url,
                preview_url=preview_url,
                note=note.strip(),
                text=cleaned_text,
            )
        )

    return slides


def build_markdown(deck: DeckData, use_local_images: bool = False) -> str:
    """DeckData からフロントマター付き Markdown 文字列を構築する."""
    frontmatter_dict: dict[str, Any] = {
        "title": deck.title,
        "author": deck.username,
        "author_name": deck.author_name or None,
        "url": deck.url,
        "presentation_id": deck.presentation_id,
        "slide_count": deck.slide_count,
        "pdf_url": deck.pdf_url or None,
        "published_at": deck.published_at or None,
        "fetched_at": deck.fetched_at,
    }

    # Noneのキーも保持または除去（可読性重視でNoneも残す）
    yaml_header = yaml.dump(frontmatter_dict, allow_unicode=True, sort_keys=False).strip()

    body_lines = [
        "---",
        yaml_header,
        "---",
        "",
        f"# {deck.title}",
        "",
    ]

    meta_details: list[str] = []
    if deck.author_name or deck.username:
        name_str = f"{deck.author_name} (@{deck.username})" if deck.author_name else f"@{deck.username}"
        meta_details.append(f"- **発表者**: {name_str}")
    meta_details.append(f"- **スライドURL**: [{deck.url}]({deck.url})")
    meta_details.append(f"- **スライド枚数**: {deck.slide_count} 枚")
    if deck.pdf_url:
        meta_details.append(f"- **原本PDF**: [ダウンロードリンク]({deck.pdf_url})")
    if deck.published_at:
        meta_details.append(f"- **公開日**: {deck.published_at}")

    body_lines.extend(meta_details)
    body_lines.append("")

    if deck.description:
        body_lines.append("## 概要")
        body_lines.append(deck.description)
        body_lines.append("")

    body_lines.append("---")
    body_lines.append("")
    body_lines.append("## スライド詳細・文字起こし")
    body_lines.append("")

    for slide in deck.slides or []:
        body_lines.append(f"### Slide {slide.index}")
        body_lines.append("")

        img_target = slide.local_image_path if (use_local_images and slide.local_image_path) else slide.image_url
        if img_target:
            body_lines.append(f"![Slide {slide.index}]({img_target})")
            body_lines.append("")

        if slide.text:
            body_lines.append(slide.text)
        else:
            body_lines.append("*（スライドテキストなし）*")
        body_lines.append("")

        if slide.note:
            body_lines.append(f"> **登壇者ノート**: {slide.note}")
            body_lines.append("")

    return "\n".join(body_lines).strip() + "\n"


def build_vault_material_markdown(deck: DeckData) -> str:
    """DeckData から企業 materials/ 配下に保存する要約Markdownの本文（フロントマター無し）を生成する.

    画像バイナリは vault には置かないため、スライドURLや原本PDF、文字起こしテキストを中心に構成する。
    元URL・取得日・生データの場所は material のフロントマター（source_url / raw_fetched_at / raw_data）に書く。
    """
    lines = [
        f"# {deck.title}",
        "",
        f"- **発表者**: {deck.author_name or deck.username} (@{deck.username})",
        f"- **スライド枚数**: {deck.slide_count} 枚",
    ]
    if deck.pdf_url:
        lines.append(f"- **原本PDF**: [ダウンロードリンク]({deck.pdf_url})")
    if deck.published_at:
        lines.append(f"- **公開日**: {deck.published_at}")

    lines.append("")
    if deck.description:
        lines.append("## 概要")
        lines.append("")
        lines.append(deck.description)
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## スライド文字起こし・要約")
    lines.append("")

    for slide in deck.slides or []:
        lines.append(f"### Slide {slide.index}")
        lines.append("")
        if slide.image_url:
            lines.append(f"![Slide {slide.index}]({slide.image_url})")
            lines.append("")
        if slide.text:
            lines.append(slide.text)
        else:
            lines.append("*（テキストなし）*")
        lines.append("")
        if slide.note:
            lines.append(f"> **登壇者ノート**: {slide.note}")
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def save_deck_to_vault(
    deck: DeckData,
    company_key: str,
    track: str = "domestic",
    slug: str | None = None,
    link_title: str | None = None,
    link_summary: str | None = None,
    force: bool = False,
    raw_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Speaker Deck の要約Markdownを vault/tracks/{track}/companies/{company_key}/materials/ に保存し、
    index.md のフロントマター links に登録する.

    raw_dir（deck.json を保存したディレクトリ）を渡すと、material の raw_data に記録し、
    deck.json 側に material への逆参照を書く。

    Returns:
        (material_path, index_path)
    """
    from scripts.common.paths import track_companies_dir
    from scripts.vault.add_material import raw_ref, upsert_link, write_material
    from scripts.vault.schema import LinkCategory, ReferenceLink

    company_dir = track_companies_dir(track) / company_key
    index_path = company_dir / "index.md"
    if not index_path.exists():
        raise FileNotFoundError(f"企業ログが見つかりません: {to_relative_path(index_path)}")

    file_slug = (slug or deck.deck_slug).removesuffix(".md")
    material_path = company_dir / "materials" / f"{file_slug}.md"
    material_rel_path = f"materials/{file_slug}.md"

    # 1. materials/*.md 保存（既存の要約は force 時のみ上書き）
    deck_json = raw_dir / "deck.json" if raw_dir else None
    write_material(
        material_path,
        title=deck.title,
        source_url=deck.url,
        body=build_vault_material_markdown(deck),
        raw_data=[raw_ref(raw_dir)] if raw_dir else None,
        raw_fetched_at=dt.date.fromisoformat(deck.fetched_at[:10]) if deck.fetched_at else None,
        raw_files=[deck_json] if deck_json else None,
        force=force,
    )

    # 2. index.md のフロントマター更新（日付は material 側の fetched_at が正なので link には書かない）
    upsert_link(
        index_path,
        ReferenceLink(
            category=LinkCategory.DECK,
            title=link_title or deck.title,
            url=deck.url,
            summary=link_summary or deck.description or f"Speaker Deckスライド（{deck.slide_count}枚）",
            material=material_rel_path,
        ),
    )
    return material_path, index_path


def fetch_deck(
    url_or_id: str,
    output_dir: Path | None = None,
    company_key: str | None = None,
    download_pdf: bool = False,
    download_images: bool = False,
    force: bool = False,
    dry_run: bool = False,
    save_to_vault: bool = False,
    track: str = "domestic",
    vault_slug: str | None = None,
    link_title: str | None = None,
    link_summary: str | None = None,
) -> tuple[DeckData, list[Path]]:
    """Speaker Deckの情報を取得し、MarkdownおよびJSONとして永続化する."""
    raw_target = url_or_id.strip()

    # 1. デッキURLの特定
    if raw_target.startswith("http"):
        target_url = raw_target
    else:
        # IDまたはslugのみ指定された場合
        if "/" in raw_target:
            target_url = f"https://speakerdeck.com/{raw_target}"
        else:
            target_url = f"https://speakerdeck.com/player/{raw_target}"

    is_direct_player = "/player/" in target_url

    # 2. メタデータ取得
    if not is_direct_player:
        page_html, status = fetch_url_content(target_url)
        if not page_html:
            raise RuntimeError(f"デッキページの取得に失敗しました (status {status}): {target_url}")
        meta = parse_deck_page_html(page_html, target_url)
        presentation_id = meta["presentation_id"]
        if not presentation_id:
            # oembed から解決を試行
            oembed_url = f"https://speakerdeck.com/oembed.json?url={urllib.parse.quote(target_url)}"
            oembed_json_str, _ = fetch_url_content(oembed_url)
            if oembed_json_str:
                try:
                    oembed_data = json.loads(oembed_json_str)
                    html_embed = oembed_data.get("html", "")
                    m = re.search(r"/player/([a-zA-Z0-9_-]+)", html_embed)
                    if m:
                        presentation_id = m.group(1)
                        meta["presentation_id"] = presentation_id
                    if not meta.get("title") and oembed_data.get("title"):
                        meta["title"] = oembed_data["title"]
                    if not meta.get("author_name") and oembed_data.get("author_name"):
                        meta["author_name"] = oembed_data["author_name"]
                except Exception:
                    pass

        if not presentation_id:
            raise RuntimeError(f"プレゼンテーションID（data-id）を特定できませんでした: {target_url}")
    else:
        # 直接player URLの場合
        m = re.search(r"/player/([a-zA-Z0-9_-]+)", target_url)
        presentation_id = m.group(1) if m else "unknown"
        meta = {
            "url": target_url,
            "username": "player",
            "deck_slug": presentation_id,
            "title": f"SlideDeck {presentation_id}",
            "presentation_id": presentation_id,
            "author_name": "",
            "description": "",
            "published_at": "",
            "pdf_url": "",
        }

    # 3. プレイヤーHTMLの取得とスライド解析
    player_url = f"https://speakerdeck.com/player/{presentation_id}"
    player_html, player_status = fetch_url_content(player_url)
    if not player_html:
        raise RuntimeError(f"プレイヤーHTMLの取得に失敗しました (status {player_status}): {player_url}")

    slides = parse_player_html(player_html)

    now = datetime.now()
    deck = DeckData(
        url=meta["url"],
        username=meta["username"],
        deck_slug=meta["deck_slug"],
        title=meta["title"],
        presentation_id=presentation_id,
        author_name=meta.get("author_name", ""),
        description=meta.get("description", ""),
        published_at=meta.get("published_at", ""),
        pdf_url=meta.get("pdf_url", ""),
        slide_count=len(slides),
        slides=slides,
        fetched_at=now.isoformat(timespec="seconds"),
    )

    # 4. 出力先ディレクトリの決定
    if output_dir:
        dest_dir = output_dir
    elif company_key:
        dest_dir = PROJECT_ROOT / "data" / "speakerdeck" / company_key / deck.deck_slug
    else:
        dest_dir = PROJECT_ROOT / "data" / "speakerdeck" / deck.username / deck.deck_slug

    created_paths: list[Path] = []

    if dry_run:
        return deck, created_paths

    dest_dir.mkdir(parents=True, exist_ok=True)

    # 5. 画像・PDFのダウンロード（オプション）
    if download_images and deck.slides:
        img_dir = dest_dir / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        for slide in deck.slides:
            if slide.image_url:
                img_path = img_dir / f"slide_{slide.index}.jpg"
                if not img_path.exists() or force:
                    ok = download_binary(slide.image_url, img_path)
                    if ok:
                        slide.local_image_path = f"images/slide_{slide.index}.jpg"
                        created_paths.append(img_path)
                else:
                    slide.local_image_path = f"images/slide_{slide.index}.jpg"

    if download_pdf and deck.pdf_url:
        pdf_path = dest_dir / f"{deck.deck_slug}.pdf"
        if not pdf_path.exists() or force:
            ok = download_binary(deck.pdf_url, pdf_path)
            if ok:
                created_paths.append(pdf_path)

    # 6. Markdown保存
    md_content = build_markdown(deck, use_local_images=download_images)
    md_path = dest_dir / "transcript.md"
    if not md_path.exists() or force:
        md_path.write_text(md_content, encoding="utf-8")
        created_paths.insert(0, md_path)
    else:
        created_paths.insert(0, md_path)

    # 7. JSON保存
    json_path = dest_dir / "deck.json"
    if not json_path.exists() or force:
        # 上書きで material への逆参照が消えないよう引き継ぐ
        material_refs = read_material_refs(json_path)
        json_path.write_text(json.dumps(deck.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        add_material_refs(json_path, material_refs)
        created_paths.insert(1, json_path)
    else:
        created_paths.insert(1, json_path)

    # 8. Vault materials/ への保存・links登録（オプション）
    if save_to_vault:
        if not company_key:
            raise ValueError("--save-to-vault を使用する場合は --company-key を指定してください")
        mat_path, idx_path = save_deck_to_vault(
            deck=deck,
            company_key=company_key,
            track=track,
            slug=vault_slug,
            link_title=link_title,
            link_summary=link_summary,
            force=force,
            raw_dir=dest_dir,
        )
        created_paths.append(mat_path)
        created_paths.append(idx_path)

    return deck, created_paths


def main() -> None:
    """エントリポイントCLI."""
    parser = create_base_parser(
        description="Speaker Deck スライド文字起こし・取得スクリプト",
        examples=[
            'uv run python scripts/speakerdeck/fetch_deck.py "https://speakerdeck.com/<user>/<deck-slug>" --summary',
            'uv run python scripts/speakerdeck/fetch_deck.py "https://speakerdeck.com/<user>/<deck-slug>" --download-pdf',
            'uv run python scripts/speakerdeck/fetch_deck.py "https://speakerdeck.com/<user>/<deck-slug>" -c <company-key> --save-to-vault  # 企業の materials/ に要約を登録',
        ],
        related=[
            "scripts/speakerdeck/search_decks.py: 前に使う（スライド URL を探す）",
        ],
    )
    parser.add_argument("target", help="Speaker Deck URL（例: https://speakerdeck.com/loglass2019/whats-loglass）")
    parser.add_argument("-o", "--output-dir", type=Path, help="保存先ディレクトリ（指定しない場合は data/speakerdeck/...）")
    parser.add_argument("-c", "--company-key", help="関連付ける企業キー（data/speakerdeck/{company_key}/ 配下に保存）")
    parser.add_argument("--save-to-vault", action="store_true", help="企業フォルダ配下の materials/ に要約Markdownを保存し、index.md の links に登録")
    parser.add_argument("--track", choices=["domestic", "overseas"], default="domestic", help="Vault track (デフォルト: domestic)")
    parser.add_argument("--vault-slug", help="Vault materials/ 内のファイル名スラッグ (デフォルト: deck_slug)")
    parser.add_argument("--link-title", help="Vault links に登録するタイトル (未指定時はデッキタイトル)")
    parser.add_argument("--link-summary", help="Vault links に登録する要約 (未指定時はデッキ説明文)")
    parser.add_argument("--download-pdf", action="store_true", help="原本PDFをダウンロード保存（許可されている場合）")
    parser.add_argument("--download-images", action="store_true", help="全スライド画像（JPEG）をローカルにダウンロード保存")
    parser.add_argument("--dry-run", action="store_true", help="ファイル保存を行わずに解析結果のみ確認")

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    try:
        deck, paths = fetch_deck(
            url_or_id=args.target,
            output_dir=args.output_dir,
            company_key=args.company_key,
            download_pdf=args.download_pdf,
            download_images=args.download_images,
            force=args.force,
            dry_run=args.dry_run,
            save_to_vault=args.save_to_vault,
            track=args.track,
            vault_slug=args.vault_slug,
            link_title=args.link_title,
            link_summary=args.link_summary,
        )

        for p in paths:
            ctx.add_result_path(p)

        def print_summary() -> None:
            print("==================================================")
            print(f"タイトル:       {deck.title}")
            print(f"発表者:         {deck.author_name} (@{deck.username})")
            print(f"スライド枚数:   {deck.slide_count} 枚")
            print(f"スライドURL:    {deck.url}")
            if deck.pdf_url:
                print(f"PDF URL:        {deck.pdf_url}")
            total_chars = sum(len(s.text) for s in deck.slides or [])
            print(f"総文字数:       {total_chars} 文字")
            print("--------------------------------------------------")
            print("保存ファイル:")
            for p in paths:
                print(f"  - {to_relative_path(p)}")
            print("==================================================")

        sys.exit(ctx.flush_outputs(summary_fn=print_summary, json_data=deck.to_dict()))

    except Exception as e:
        ctx.error(f"{args.target}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

