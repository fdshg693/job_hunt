"""Web 資料の要約を企業・リクルーターの materials/ に作り links に登録する CLI.

任意のWeb URL（Speaker Deck、note、Entrance Book、テックブログ、口コミ等）から
概要・要約Markdownを企業またはリクルーターの materials/{slug}.md に配置し、
index.md のフロントマター links に登録します。

material は MaterialDoc のフロントマター（source_url・fetched_at・raw_data・raw_fetched_at）付きで書き、
生データを data/ に保存する経路（Speaker Deck・note）では生データ側にも material への逆参照を書く。
--refresh は生データを取り直して日付を更新するだけで、要約本文は変えない。
"""

from __future__ import annotations

import datetime as dt
import re
import ssl
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

# プロジェクトルートパス (scripts/vault/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import EntrypointContext, create_base_parser, to_relative_path
from scripts.common.paths import RECRUITERS_DIR, track_companies_dir
from scripts.common.storage import add_material_refs
from scripts.vault import frontmatter
from scripts.vault.schema import (
    CompanyDoc,
    LinkCategory,
    MaterialDoc,
    RecruiterDoc,
    ReferenceLink,
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

HTTP_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


def get_ssl_context() -> ssl.SSLContext:
    """SSLコンテキストを生成する."""
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    return ctx


def fetch_html_content(url: str) -> tuple[str | None, int]:
    """指定URLのHTMLコンテンツを取得する."""
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    ctx = get_ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            return content, resp.getcode()
    except urllib.error.HTTPError as e:
        return None, e.code
    except (ssl.SSLCertVerificationError, urllib.error.URLError):
        try:
            unverified_ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=15, context=unverified_ctx) as resp:
                content = resp.read().decode("utf-8", errors="replace")
                return content, resp.getcode()
        except urllib.error.HTTPError as he:
            return None, he.code
        except Exception:
            return None, 0
    except Exception:
        return None, 0


def guess_link_category(url: str, title: str = "") -> LinkCategory:
    """URLやタイトルからリソース種別（LinkCategory）を自動推測する."""
    lower_url = url.lower()
    lower_title = title.lower()

    if any(d in lower_url for d in ["speakerdeck.com", "docswell.com", "slideshare.net"]):
        return LinkCategory.DECK
    if any(k in lower_url for k in ["entrance-book", "entrance_book", "entrancebook", "culture-deck", "handbook"]) or \
       any(k in lower_title for k in ["entrance book", "採用情報", "採用ハンドブック"]):
        return LinkCategory.ENTRANCE_BOOK
    if any(d in lower_url for d in ["openwork.jp", "vorkers.com", "en-hyouban.com", "jobtalk.jp"]):
        return LinkCategory.REVIEW
    if any(d in lower_url for d in ["zenn.dev", "qiita.com", "hatenablog.com", "dev.to"]) or \
       any(p in lower_url for p in ["/tech", "/engineering", "/dev", "tech.", "engineering.", "developer."]):
        return LinkCategory.BLOG
    if any(d in lower_url for d in ["prtimes.jp", "businesswire.com"]):
        return LinkCategory.NEWS
    if any(d in lower_url for d in ["twitter.com", "x.com", "facebook.com", "instagram.com", "youtube.com"]):
        return LinkCategory.SNS
    if any(d in lower_url for d in ["notion.site", "notion.so"]):
        return LinkCategory.ENTRANCE_BOOK
    if "note.com" in lower_url:
        return LinkCategory.BLOG

    return LinkCategory.OTHER


def generate_slug(url: str, title: str = "", category: LinkCategory = LinkCategory.OTHER) -> str:
    """ファイル名として安全なスラッグを生成する."""
    parsed = urllib.parse.urlparse(url)
    path_parts = [p for p in parsed.path.split("/") if p]
    if path_parts:
        last = path_parts[-1].split(".")[0]
        cleaned = re.sub(r"[^a-zA-Z0-9_\-]+", "-", last).strip("-").lower()
        if cleaned and len(cleaned) >= 3 and cleaned not in ["index", "home", "about"]:
            return cleaned[:50]

    # タイトルから英数字を抽出
    if title:
        cleaned = re.sub(r"[^a-zA-Z0-9_\-]+", "-", title).strip("-").lower()
        if cleaned and len(cleaned) >= 3:
            return cleaned[:50]

    date_str = dt.datetime.now().strftime("%Y%m%d_%H%M")
    return f"{category.value}_{date_str}"


def extract_page_info(html: str, url: str) -> dict[str, str]:
    """HTMLからタイトル、説明文、メインテキストを抽出する."""
    soup = BeautifulSoup(html, "html.parser")

    # タイトル
    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()

    # 説明文
    description = ""
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        description = og_desc["content"].strip()
    else:
        meta_desc = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
        if meta_desc and meta_desc.get("content"):
            description = meta_desc["content"].strip()

    # 不要タグ除去
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg"]):
        tag.decompose()

    # 主要コンテンツの探索
    main_elem = soup.find(["main", "article"]) or soup.find(class_=re.compile(r"content|entry|post|body|article", re.I)) or soup.body
    text_content = ""
    if main_elem:
        lines: list[str] = []
        for element in main_elem.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
            t = element.get_text(strip=True)
            if not t:
                continue
            if element.name in ["h1", "h2"]:
                lines.append(f"\n## {t}\n")
            elif element.name in ["h3", "h4"]:
                lines.append(f"\n### {t}\n")
            elif element.name == "li":
                lines.append(f"- {t}")
            else:
                lines.append(f"{t}\n")
        text_content = "\n".join(lines).strip()

    return {
        "title": title or url,
        "description": description,
        "content": text_content,
    }


def create_material_body(
    title: str,
    summary: str,
    body_text: str = "",
    extra_meta: dict[str, Any] | None = None,
) -> str:
    """materials/ 用 Markdown の本文（フロントマター無し）を構築する.

    元URL・取得日は material のフロントマター（source_url / fetched_at）に書くので本文には書かない。
    """
    lines = [f"# {title}", ""]
    if extra_meta:
        for k, v in extra_meta.items():
            if v:
                lines.append(f"- **{k}**: {v}")
        lines.append("")

    if summary:
        lines.append("## 概要・要約")
        lines.append("")
        lines.append(summary)
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 詳細・抜粋")
    lines.append("")

    if body_text:
        lines.append(body_text)
    else:
        lines.append("*（詳細テキスト未取得 / 必要に応じて要約を追記してください）*")

    return "\n".join(lines).strip() + "\n"


def render_material(
    title: str,
    source_url: str | None,
    body: str,
    raw_data: list[str] | None = None,
    raw_fetched_at: dt.date | None = None,
) -> str:
    """MaterialDoc のフロントマター付きで materials/*.md の全文を組み立てる（fetched_at は今日）."""
    model = MaterialDoc(
        title=title,
        source_url=source_url,
        fetched_at=dt.date.today(),
        raw_data=raw_data or [],
        raw_fetched_at=raw_fetched_at if raw_data else None,
    )
    return frontmatter.render(model, "\n" + body.lstrip("\n"))


def raw_ref(path: Path) -> str:
    """material の raw_data に書く生データの場所（ディレクトリは末尾 / 付き）."""
    rel = to_relative_path(path)
    return rel.rstrip("/") + "/" if path.is_dir() else rel


def write_material(
    material_path: Path,
    *,
    title: str,
    source_url: str | None,
    body: str,
    raw_data: list[str] | None = None,
    raw_fetched_at: dt.date | None = None,
    raw_files: list[Path] | None = None,
    force: bool = False,
) -> bool:
    """material を新規作成する（既存は force 時のみ上書き）. 書いたら生データ側に逆参照を足して True.

    既存の要約は AI が書き直したものなので、force が無ければ触らない（生データの取り直しは --refresh）。
    """
    if material_path.exists() and not force:
        return False
    material_path.parent.mkdir(parents=True, exist_ok=True)
    material_path.write_text(render_material(title, source_url, body, raw_data, raw_fetched_at), encoding="utf-8")
    for f in raw_files or []:
        add_material_refs(f, [to_relative_path(material_path)])
    return True


def upsert_link(index_path: Path, ref_link: ReferenceLink) -> None:
    """index.md のフロントマター links に登録する（同URLまたは同materialの既存リンクは置き換える）."""
    doc = frontmatter.read(index_path)
    is_recruiter = index_path.resolve().is_relative_to(RECRUITERS_DIR.resolve())
    model = (RecruiterDoc if is_recruiter else CompanyDoc).model_validate(doc.data)
    for i, link in enumerate(model.links):
        if link.url == ref_link.url or (ref_link.material and link.material == ref_link.material):
            model.links[i] = ref_link
            break
    else:
        model.links.append(ref_link)
    frontmatter.write(index_path, model, doc)


@dataclass
class RawCapture:
    """生データを data/ に保存する取得経路（Speaker Deck・note）の結果."""

    title: str
    summary: str
    body: str  # material の本文の素
    extra_meta: dict[str, Any] = field(default_factory=dict)
    raw_data: list[str] = field(default_factory=list)  # material の raw_data に書く場所
    raw_files: list[Path] = field(default_factory=list)  # 逆参照を書く生データファイル
    raw_fetched_at: dt.date | None = None
    data_paths: list[Path] = field(default_factory=list)  # 保存した data/ のファイル


def _date_of(iso: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(iso[:10])
    except ValueError:
        return None


def capture_raw(
    url: str,
    company_key: str | None = None,
    output_dir: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> RawCapture | None:
    """生データを保存する取得経路があれば取得して data/ に保存する. 経路が無いURLは None."""
    if "speakerdeck.com" in url:
        from scripts.speakerdeck.fetch_deck import build_vault_material_markdown, fetch_deck

        deck, paths = fetch_deck(url, output_dir=output_dir, company_key=company_key, force=force, dry_run=dry_run)
        deck_json = next((p for p in paths if p.name == "deck.json"), None)
        return RawCapture(
            title=deck.title,
            summary=deck.description or f"Speaker Deckスライド（{deck.slide_count}枚）",
            body=build_vault_material_markdown(deck),
            raw_data=[raw_ref(deck_json.parent)] if deck_json else [],
            raw_files=[deck_json] if deck_json else [],
            raw_fetched_at=_date_of(deck.fetched_at),
            data_paths=paths,
        )
    if "note.com" in url:
        from scripts.note.fetch_article import fetch_article

        article, paths = fetch_article(
            url, output_dir=output_dir, company_key=company_key, save_json=False, force=force, dry_run=dry_run
        )
        md_path = next((p for p in paths if p.suffix == ".md"), None)
        return RawCapture(
            title=article.title,
            summary=f"note記事（スキ: {article.like_count}）",
            body=article.body_markdown,
            extra_meta={
                "著者": f"{article.author_name} (@{article.author_urlname})",
                "公開日": article.publish_at[:10] if article.publish_at else "",
            },
            raw_data=[raw_ref(md_path)] if md_path else [],
            raw_files=[md_path] if md_path else [],
            raw_fetched_at=_date_of(article.fetched_at),
            data_paths=paths,
        )
    return None


def owner_dir(company_key: str | None, recruiter_key: str | None, track: str = "domestic") -> Path:
    """企業フォルダまたはリクルーターフォルダ."""
    if not company_key and not recruiter_key:
        raise ValueError("--company-key または --recruiter-key のいずれかを指定してください")
    if company_key and recruiter_key:
        raise ValueError("--company-key と --recruiter-key は同時に指定できません")
    if company_key:
        return track_companies_dir(track) / company_key
    return RECRUITERS_DIR / recruiter_key  # type: ignore[operator]


def add_material(
    url: str,
    company_key: str | None = None,
    recruiter_key: str | None = None,
    track: str = "domestic",
    category: LinkCategory | None = None,
    title: str | None = None,
    summary: str | None = None,
    slug: str | None = None,
    fetch: bool = True,
    no_material: bool = False,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[ReferenceLink, list[Path]]:
    """外部リソースURLを登録し、必要に応じて materials/*.md を生成する."""
    target_dir = owner_dir(company_key, recruiter_key, track)
    index_path = target_dir / "index.md"
    if not index_path.exists():
        raise FileNotFoundError(f"ログが見つかりません: {to_relative_path(index_path)}")

    # 1. Web情報の取得（Speaker Deck・note は生データも data/ に保存する）
    final_title = title or ""
    final_summary = summary or ""
    raw: RawCapture | None = None

    if fetch:
        raw = capture_raw(url, company_key=company_key, dry_run=dry_run)
        if raw:
            final_title = final_title or raw.title
            final_summary = final_summary or raw.summary
            if "speakerdeck.com" in url:
                material_body = raw.body
            else:
                material_body = create_material_body(final_title, final_summary, raw.body, raw.extra_meta)
        else:
            html, _status = fetch_html_content(url)
            body_text = ""
            if html:
                info = extract_page_info(html, url)
                final_title = final_title or info["title"]
                final_summary = final_summary or info["description"]
                body_text = info["content"]
            final_title = final_title or url
            material_body = create_material_body(final_title, final_summary, body_text)
    else:
        final_title = final_title or url
        material_body = create_material_body(final_title, final_summary)

    final_category = category or guess_link_category(url, final_title)

    # 2. materials/*.md の生成（no_material が指定されていない場合）
    created_paths: list[Path] = list(raw.data_paths) if raw else []
    material_rel_path: str | None = None

    if not no_material:
        file_slug = (slug or generate_slug(url, final_title, final_category)).removesuffix(".md")
        material_path = target_dir / "materials" / f"{file_slug}.md"
        material_rel_path = f"materials/{file_slug}.md"

        if not dry_run:
            written = write_material(
                material_path,
                title=final_title,
                source_url=url,
                body=material_body,
                raw_data=raw.raw_data if raw else None,
                raw_fetched_at=raw.raw_fetched_at if raw else None,
                raw_files=raw.raw_files if raw else None,
                force=force,
            )
            if not written:
                print(
                    f"[スキップ] 既存の資料は上書きしない（生データの取り直しは --refresh）: {to_relative_path(material_path)}",
                    file=sys.stderr,
                )
        created_paths.append(material_path)

    # 3. index.md フロントマター links の更新（material があれば日付はその fetched_at が正）
    ref_link = ReferenceLink(
        category=final_category,
        title=final_title,
        url=url,
        summary=final_summary or None,
        material=material_rel_path,
        fetched_at=None if material_rel_path else dt.date.today(),
    )
    if not dry_run:
        upsert_link(index_path, ref_link)
    created_paths.append(index_path)

    return ref_link, created_paths


def resolve_material_path(
    target: str, company_key: str | None = None, recruiter_key: str | None = None, track: str = "domestic"
) -> Path:
    """--refresh の引数（material のパス、または -c/-r と組み合わせたスラッグ）を material のパスにする."""
    path = Path(target)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if path.is_file():
        return path
    candidate = owner_dir(company_key, recruiter_key, track) / "materials" / f"{target.removesuffix('.md')}.md"
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(f"資料が見つかりません: {target}")


def _raw_output_dir(raw_data: list[str]) -> Path | None:
    """既存の raw_data と同じ場所に取り直すための保存先ディレクトリ."""
    if not raw_data:
        return None
    first = raw_data[0]
    path = PROJECT_ROOT / first.rstrip("/")
    return path if first.endswith("/") else path.parent


def refresh_material(material_path: Path, dry_run: bool = False) -> tuple[MaterialDoc, list[Path]]:
    """material の元資料から生データを取り直し、raw_data・raw_fetched_at を更新する.

    要約本文と fetched_at は変えない（AI が生データと見比べて直し、そのとき fetched_at を更新する）。
    Returns: (更新後の MaterialDoc, [material, 保存した生データ...])
    """
    doc = frontmatter.read(material_path)
    model = MaterialDoc.model_validate(doc.data)
    if not model.source_url:
        raise ValueError(f"source_url が無い資料は取り直せない: {to_relative_path(material_path)}")

    owner = material_path.parent.parent
    company_key = owner.name if owner.parent.name == "companies" else None
    raw = capture_raw(
        model.source_url,
        company_key=company_key,
        output_dir=_raw_output_dir(model.raw_data),
        force=True,
        dry_run=dry_run,
    )
    if raw is None:
        raise ValueError(
            "生データを保存する取得経路が無い資料（Speaker Deck・note 以外）は --refresh できない。"
            "元ページを見て要約を直し、fetched_at を更新する"
        )
    if dry_run:
        return model, [material_path]

    model.raw_data = raw.raw_data
    model.raw_fetched_at = raw.raw_fetched_at
    frontmatter.write(material_path, model, doc)
    for f in raw.raw_files:
        add_material_refs(f, [to_relative_path(material_path)])
    return model, [material_path, *raw.data_paths]


def main() -> None:
    """エントリポイントCLI."""
    parser = create_base_parser(
        description="企業・リクルーターの materials/ に資料を追加し、index.md の links に登録するヘルパーCLI",
        examples=[
            "uv run python scripts/vault/add_material.py <URL> -c <company-key> -s  # 企業の material を作り links に登録",
            "uv run python scripts/vault/add_material.py <URL> -r <recruiter-key> -s  # リクルーターの material",
            "uv run python scripts/vault/add_material.py --refresh <material のパス>  # 生データを取り直す",
        ],
        related=[
            "scripts/speakerdeck/fetch_deck.py: Speaker Deck は --save-to-vault でも material を作れる",
            "scripts/vault/validate.py: 追加後にフロントマターを検証する",
        ],
    )
    parser.add_argument("url", nargs="?", help="対象外部リソースのURL（--refresh 時は不要）")
    parser.add_argument("-c", "--company-key", help="企業キー (例: canary, atama-plus)")
    parser.add_argument("-r", "--recruiter-key", help="リクルーターキー (例: r-ambient-shuto)")
    parser.add_argument("-t", "--track", choices=["domestic", "overseas"], default="domestic", help="企業 track (デフォルト: domestic)")
    parser.add_argument("--category", choices=[c.value for c in LinkCategory], help="リソース種別 (未指定時はURL等から自動推測)")
    parser.add_argument("--title", help="資料タイトル (未指定時はWebページ等から自動取得)")
    parser.add_argument("--link-summary", dest="link_summary", help="資料要約・着目ポイント")
    parser.add_argument("--slug", help="materials/ 内のファイル名スラッグ (未指定時は自動生成)")
    parser.add_argument("--fetch", dest="fetch", action="store_true", default=True, help="Webからコンテンツを取得して要約Markdownを生成 (デフォルト: 有効)")
    parser.add_argument("--no-fetch", dest="fetch", action="store_false", help="Web取得を行わずテンプレートのみ生成")
    parser.add_argument("--no-material", action="store_true", help="materials/ のMarkdownファイルを生成せず、index.md の links 登録のみ行う")
    parser.add_argument(
        "--refresh",
        metavar="MATERIAL",
        help="既存資料の生データを取り直す（material のパス、または -c/-r と組み合わせたスラッグ）。要約本文は変えない",
    )
    parser.add_argument("--dry-run", action="store_true", help="保存を行わずに登録内容のみ確認")

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    if args.refresh:
        try:
            material_path = resolve_material_path(args.refresh, args.company_key, args.recruiter_key, args.track)
            model, paths = refresh_material(material_path, dry_run=args.dry_run)
        except Exception as e:
            ctx.error(f"{args.refresh}: {e}")
            sys.exit(1)

        for p in paths:
            ctx.add_result_path(p)
        print(
            f"[次] 生データと見比べて要約本文を直し、fetched_at を今日にする: {to_relative_path(material_path)}",
            file=sys.stderr,
        )

        def print_refresh_summary() -> None:
            print("==================================================")
            print(f"資料:           {to_relative_path(material_path)}")
            print(f"元URL:          {model.source_url}")
            print(f"要約の日付:     {model.fetched_at}")
            print(f"生データ取得日: {model.raw_fetched_at}")
            for r in model.raw_data:
                print(f"生データ:       {r}")
            print("==================================================")

        sys.exit(ctx.flush_outputs(summary_fn=print_refresh_summary, json_data=model.model_dump(mode="json")))

    if not args.url:
        ctx.error("URL または --refresh を指定してください")
        sys.exit(1)

    try:
        cat_enum = LinkCategory(args.category) if args.category else None
        ref_link, paths = add_material(
            url=args.url,
            company_key=args.company_key,
            recruiter_key=args.recruiter_key,
            track=args.track,
            category=cat_enum,
            title=args.title,
            summary=args.link_summary,
            slug=args.slug,
            fetch=args.fetch,
            no_material=args.no_material,
            force=args.force,
            dry_run=args.dry_run,
        )

        for p in paths:
            ctx.add_result_path(p)

        def print_summary() -> None:
            print("==================================================")
            print(f"種別:           {ref_link.category.value}")
            print(f"タイトル:       {ref_link.title}")
            print(f"URL:            {ref_link.url}")
            if ref_link.summary:
                print(f"要約:           {ref_link.summary}")
            if ref_link.material:
                print(f"資料Markdown:   {ref_link.material}")
            if ref_link.fetched_at:
                print(f"確認日:         {ref_link.fetched_at}")
            print("--------------------------------------------------")
            print("更新/生成ファイル:")
            for p in paths:
                print(f"  - {to_relative_path(p)}")
            print("==================================================")

        sys.exit(ctx.flush_outputs(summary_fn=print_summary, json_data=ref_link.model_dump(mode="json")))

    except Exception as e:
        ctx.error(f"{args.url}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
