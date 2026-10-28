"""職務経歴書・英文レジュメを vault/profile から PDF 出力する CLI.

vault/profile/resume.md（日本語 SSOT）または vault/profile/en/resume.md（英語派生）から、
提出用の職務経歴書 PDF を data/exports/ に生成します。

- 載せる情報は allowlist で決める。フロントマターは氏名・リンク・資格・語学・主要スキルだけを使い、
  本文は ``SECTION_ALLOWLIST`` に一致する H2 節だけを使う（「基本情報」節は使わない）。
  一致しない H2 節は載せずに警告する（新しく書いた節が黙って外部に出ないようにするため）。
- 連絡先（フロントマター ``email`` / ``phone``）は ``--contact`` 指定時だけ載せる。
- 生成した HTML に、現在年収・生年月日・（--contact なしなら）連絡先・非公開ファイルの文章が
  混じっていたら PDF を作らずに終了コード 1 で止める（漏洩ガード）。
- 英語版は sync_en.py の同期判定が UP_TO_DATE でなければ止める（``--allow-stale`` で続行）。
- PDF 化はヘッドレス Chromium（既定はインストール済みの Edge → Chrome → Playwright 同梱 Chromium の順）。
"""

from __future__ import annotations

import datetime as dt
import html
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/profile/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markdown_it import MarkdownIt
from markupsafe import Markup

from scripts.common.cli import create_base_parser, entrypoint_guard, to_relative_path
from scripts.common.paths import PROFILE_EN_DIR, PROFILE_INTERNAL_DIR, RESUME_PATH, TRACKS_DIR
from scripts.profile.sync_en import check_sync_status
from scripts.vault import frontmatter

TEMPLATE_DIR = Path(__file__).resolve().parent / "pdf_templates"
EXPORT_DIR = PROJECT_ROOT / "data" / "exports"
BROWSER_CHANNELS = ("msedge", "chrome", None)  # None = Playwright 同梱 Chromium

SOURCES = {"ja": RESUME_PATH, "en": PROFILE_EN_DIR / "resume.md"}

# 本文から載せる H2 節（前方一致）。ここに無い節は載せない
SECTION_ALLOWLIST = {
    "ja": ("職務要約", "職務経歴", "学歴", "課外活動", "自己PR", "活かせる経験"),
    "en": ("Professional Summary", "Summary", "Work Experience", "Experience", "Education", "Extracurricular"),
}
# 意図的に載せない節（警告も出さない）
SECTION_SKIP = {
    "ja": ("基本情報",),
    "en": ("Basic Information",),
}

LABELS = {
    "ja": {
        "title": "職務経歴書",
        "skills": "主要スキル",
        "certifications": "資格",
        "language": "語学",
        "contact": "連絡先",
    },
    "en": {
        "title": "Resume",
        "skills": "Core Skills",
        "certifications": "Certifications",
        "language": "Languages",
        "contact": "Contact",
    },
}

LINK_LABELS = {"github": "GitHub", "zenn": "Zenn", "qiita": "Qiita", "linkedin": "LinkedIn"}

_HR_LINE = re.compile(r"^ {0,3}([-*_])(?:\s*\1){2,}\s*$", re.MULTILINE)

LEAK_MIN_LEN = 15  # 非公開ファイルの文章をこの文字数以上の断片で照合する


class LeakError(RuntimeError):
    """提出用 PDF に載せてはいけない情報が混じっている."""


@dataclass
class Section:
    heading: str
    body: str  # H2 見出し行を除いた Markdown


def split_sections(body: str) -> list[Section]:
    """本文を H2 単位に分ける. 最初の H2 より前（H1 タイトル等）は捨てる."""
    sections: list[Section] = []
    current: Section | None = None
    lines: list[str] = []
    for line in body.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            if current:
                current.body = "\n".join(lines).strip()
                sections.append(current)
            current, lines = Section(match.group(1), ""), []
        elif current:
            lines.append(line)
    if current:
        current.body = "\n".join(lines).strip()
        sections.append(current)
    return sections


def select_sections(sections: list[Section], lang: str) -> tuple[list[Section], list[str]]:
    """allowlist に一致する節と、どちらにも一致しなかった節名（警告用）を返す."""
    allowed, unknown = [], []
    for sec in sections:
        if sec.heading.startswith(SECTION_ALLOWLIST[lang]):
            allowed.append(sec)
        elif not sec.heading.startswith(SECTION_SKIP[lang]):
            unknown.append(sec.heading)
    return allowed, unknown


def _markdown() -> MarkdownIt:
    return MarkdownIt("commonmark", {"html": False, "linkify": False})


def render_html(fm: dict[str, Any], sections: list[Section], lang: str, *, contact: bool, today: dt.date) -> str:
    """フロントマターの allowlist 項目と選んだ節から HTML を組み立てる."""
    md = _markdown()
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html", "j2"]))
    template = env.get_template("career.html.j2")
    css = (TEMPLATE_DIR / "career.css").read_text(encoding="utf-8")

    # 節区切りの水平線は h2 の罫線で足りるので落とす（段落直後の --- が見出し扱いになるのも防ぐ）
    rendered = [
        {"heading": s.heading, "html": Markup(md.render(_HR_LINE.sub("", s.body)))} for s in sections
    ]
    as_of = f"{today.year}年{today.month}月{today.day}日現在" if lang == "ja" else f"As of {today:%B} {today.day}, {today.year}"
    links = fm.get("links") or {}
    return template.render(
        lang=lang,
        css=Markup(css),
        labels=LABELS[lang],
        as_of=as_of,
        name=fm.get("name", ""),
        name_sub=fm.get("name_en") if lang == "ja" else None,
        location=fm.get("location") if lang == "en" else None,
        links=[{"label": LINK_LABELS.get(k, k.capitalize()), "url": v} for k, v in links.items() if v],
        skills=fm.get("primary_skills") or [],
        certifications=fm.get("certifications") or [],
        language=fm.get("english_skill"),
        contact={"email": fm.get("email"), "phone": fm.get("phone")} if contact else None,
        sections=rendered,
    )


def _html_to_text(markup: str) -> str:
    text = re.sub(r"<style.*?</style>", " ", markup, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text))


def _internal_fragments() -> list[str]:
    """非公開ファイル（profile/internal/・各 track の criteria.md / ratings.md）の本文断片."""
    paths = list(PROFILE_INTERNAL_DIR.rglob("*.md"))
    for name in ("criteria.md", "ratings.md"):
        paths.extend(TRACKS_DIR.glob(f"*/{name}"))
    fragments: list[str] = []
    for path in paths:
        body = frontmatter.read(path).body
        for line in body.splitlines():
            # 箇条書き記号・強調記号を落として、ある程度長い文だけ照合する
            line = re.sub(r"^[\s>#*\-|0-9.]+", "", line).replace("**", "").strip()
            if len(line) >= LEAK_MIN_LEN:
                fragments.append(re.sub(r"\s+", " ", line))
    return fragments


def check_leaks(markup: str, fm_ja: dict[str, Any], fm: dict[str, Any], *, contact: bool) -> list[str]:
    """提出用 HTML に載せてはいけない値が含まれていれば、その説明のリストを返す."""
    text = _html_to_text(markup)
    found: list[str] = []

    forbidden: dict[str, list[str]] = {}
    income = fm_ja.get("current_annual_income") or fm.get("current_annual_income")
    if income:
        income = int(income)
        forbidden["現在年収"] = [str(income), f"{income:,}", f"{income // 10000}万"]
    birth = fm_ja.get("birth_date") or fm.get("birth_date")
    if birth:
        d = dt.date.fromisoformat(str(birth))
        forbidden["生年月日"] = [d.isoformat(), f"{d.year}年{d.month}月{d.day}日", f"{d:%B} {d.day}, {d.year}"]
    if not contact:
        forbidden["連絡先"] = [str(v) for v in (fm.get("email"), fm.get("phone"), fm_ja.get("email"), fm_ja.get("phone")) if v]
        forbidden["連絡先"] += re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text)  # フロントマターに無いメールも拾う

    for label, values in forbidden.items():
        for value in values:
            if value and value in text:
                found.append(f"{label}（{value}）")
    for fragment in _internal_fragments():
        if fragment in text:
            found.append(f"非公開ファイルの文章（{fragment[:30]}…）")
    return found


def print_pdf(markup: str, out_path: Path, *, page_numbers: bool = True, margin_mm: int = 16) -> None:
    """ヘッドレス Chromium で HTML を A4 PDF にする. ``page_numbers`` でフッターのページ番号を付ける."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    footer = (
        '<div style="width:100%;font-size:8px;color:#888;text-align:center;">'
        '<span class="pageNumber"></span> / <span class="totalPages"></span></div>'
    )
    with sync_playwright() as p:
        browser = None
        errors: list[str] = []
        for channel in BROWSER_CHANNELS:
            try:
                browser = p.chromium.launch(channel=channel) if channel else p.chromium.launch()
                break
            except PlaywrightError as exc:
                errors.append(f"{channel or 'chromium'}: {str(exc).splitlines()[0]}")
        if browser is None:
            raise RuntimeError("PDF 出力用のブラウザを起動できません: " + " / ".join(errors))
        try:
            page = browser.new_page()
            page.set_content(markup, wait_until="networkidle")
            page.pdf(
                path=str(out_path),
                format="A4",
                print_background=True,
                display_header_footer=page_numbers,
                header_template="<div></div>",
                footer_template=footer,
                margin={side: f"{margin_mm}mm" for side in ("top", "bottom", "left", "right")},
            )
        finally:
            browser.close()


def count_pages(pdf_path: Path) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf_path.read_bytes()))


def parse_args():
    parser = create_base_parser(
        description="職務経歴書・英文レジュメを vault/profile から PDF 出力する",
        examples=[
            "uv run python scripts/profile/export_pdf.py --lang ja -s  # 職務経歴書 → data/exports/{日付}_career_ja.pdf",
            "uv run python scripts/profile/export_pdf.py --lang en -s  # 英文レジュメ（英語版が同期済みであること）",
            "uv run python scripts/profile/export_pdf.py --lang ja --contact --html  # 連絡先を載せ、確認用 HTML も保存",
        ],
        related=[
            "scripts/profile/sync_en.py: --lang en の前に英語版の同期状態を確かめる",
            "scripts/profile/export_rirekisho.py: 履歴書 PDF も一緒に出す",
        ],
    )
    parser.add_argument("--lang", choices=sorted(SOURCES), default="ja", help="ja: 職務経歴書 / en: 英文レジュメ")
    parser.add_argument("--contact", action="store_true", help="連絡先（フロントマターの email / phone）を載せる")
    parser.add_argument("--html", action="store_true", help="PDF と同名の HTML も保存する（レイアウト確認用）")
    parser.add_argument("--allow-stale", action="store_true", help="英語版が日本語 SSOT より古くても出力する")
    parser.add_argument("--out", help="出力 PDF パス（既定: data/exports/{日付}_career_{lang}.pdf）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    today = dt.date.today()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        source = SOURCES[args.lang]
        if args.lang == "en":
            status = check_sync_status(["resume.md"])[0]
            if status["status"] != "UP_TO_DATE":
                msg = f"英語版 resume が日本語 SSOT と同期されていません（{status['status']}）"
                if not args.allow_stale:
                    ctx.error(msg + "。英訳を更新するか --allow-stale を付けてください。")
                    sys.exit(1)
                ctx.warn(msg)

        doc = frontmatter.read(source)
        fm_ja = frontmatter.read(RESUME_PATH).data
        if args.contact and not (doc.data.get("email") or doc.data.get("phone")):
            ctx.error(f"--contact 指定ですが {to_relative_path(source)} のフロントマターに email / phone がありません。")
            sys.exit(1)

        sections, unknown = select_sections(split_sections(doc.body), args.lang)
        for heading in unknown:
            ctx.warn(f"allowlist に無い節は載せません: 「{heading}」（載せるなら SECTION_ALLOWLIST に追加）")

        markup = render_html(doc.data, sections, args.lang, contact=args.contact, today=today)
        leaks = check_leaks(markup, fm_ja, doc.data, contact=args.contact)
        if leaks:
            for leak in leaks:
                ctx.error(f"提出用 PDF に載せてはいけない情報が含まれています: {leak}")
            sys.exit(1)

        out_path = Path(args.out) if args.out else EXPORT_DIR / f"{today.isoformat()}_career_{args.lang}.pdf"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if args.html:
            html_path = out_path.with_suffix(".html")
            html_path.write_text(markup, encoding="utf-8")
            ctx.add_result_path(html_path)
        print_pdf(markup, out_path)
        ctx.add_result_path(out_path)
        pages = count_pages(out_path)
        source_rev = str(doc.data.get("updated_at") or doc.data.get("source_updated_at") or "-")

        def print_summary() -> None:
            print(f"出力: {to_relative_path(out_path)}（{pages} ページ）")
            print(f"元データ: {to_relative_path(source)}（更新日: {source_rev}）")
            print(f"載せた節: {', '.join(s.heading for s in sections)}")
            print(f"連絡先: {'あり' if args.contact else 'なし'}")

        ctx.flush_outputs(
            summary_fn=print_summary,
            json_data={
                "path": to_relative_path(out_path),
                "pages": pages,
                "source": to_relative_path(source),
                "source_updated_at": source_rev,
                "sections": [s.heading for s in sections],
                "contact": args.contact,
            },
        )


if __name__ == "__main__":
    main()
