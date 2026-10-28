"""履歴書（厚労省様式例準拠）を vault/profile から PDF 出力する CLI.

vault/profile/rirekisho.md（応募先に依らない項目）と vault/profile/resume.md（氏名・生年月日・連絡先）から
履歴書 PDF を data/exports/ に生成します。

- 志望動機は応募先ごとに vault/tracks/{track}/companies/{company-key}/application.md の
  ``## 志望動機`` 節に書き、``--company`` で差し込む。``## 本人希望記入欄`` 節があれば rirekisho.md の既定文を上書きする。
- 履歴書なので生年月日・住所・連絡先は載せる。現在年収と非公開ファイルの文章が混じっていたら
  PDF を作らずに終了コード 1 で止める（漏洩ガード。export_pdf.py と共通）。
- 写真欄は設けない。
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/profile/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from scripts.common.cli import create_base_parser, entrypoint_guard, to_relative_path
from scripts.common.paths import DEFAULT_TRACK, RESUME_PATH, RIREKISHO_PATH, TRACKS, track_companies_dir
from scripts.profile.export_pdf import (
    EXPORT_DIR,
    TEMPLATE_DIR,
    _html_to_text,
    _internal_fragments,
    count_pages,
    print_pdf,
    split_sections,
)
from scripts.vault import frontmatter

APPLICATION_FILE = "application.md"
HISTORY_ROWS = 18  # 学歴・職歴欄の最低行数（空行で埋めて様式の見た目にする）
LICENSE_ROWS = 6


def age_on(birth: dt.date, day: dt.date) -> int:
    return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


def _row(item: dict[str, Any], cls: str = "") -> dict[str, Any]:
    return {"year": item.get("year", ""), "month": item.get("month", ""), "text": item.get("text", ""), "cls": cls}


def _pad(rows: list[dict[str, Any]], size: int) -> list[dict[str, Any]]:
    return rows + [_row({}) for _ in range(max(0, size - len(rows)))]


def history_rows(fm: dict[str, Any]) -> list[dict[str, Any]]:
    """学歴・職歴欄の行. 見出し行・「現在に至る」「以上」を付け、最低行数まで空行で埋める."""
    rows = [_row({"text": "学歴"}, "heading")]
    rows += [_row(item) for item in fm.get("education") or []]
    rows.append(_row({}))
    rows.append(_row({"text": "職歴"}, "heading"))
    rows += [_row(item) for item in fm.get("work") or []]
    if fm.get("currently_employed"):
        rows.append(_row({"text": "現在に至る"}))
    rows.append(_row({"text": "以上"}, "end"))
    return _pad(rows, HISTORY_ROWS)


def section_text(body: str, heading: str) -> str | None:
    """本文から指定 H2 節のテキストを返す（無ければ None）. 1 行を 1 段落として改行を残し、空行は詰める."""
    for sec in split_sections(body):
        if sec.heading.startswith(heading):
            return "\n".join(line.strip() for line in sec.body.splitlines() if line.strip())
    return None


def render_html(
    resume_fm: dict[str, Any], fm: dict[str, Any], *, motivation: str, wishes: str, as_of_day: dt.date
) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html", "j2"]))
    template = env.get_template("rirekisho.html.j2")
    css = (TEMPLATE_DIR / "rirekisho.css").read_text(encoding="utf-8")
    birth = dt.date.fromisoformat(str(resume_fm["birth_date"]))
    return template.render(
        css=Markup(css),
        as_of=f"{as_of_day.year}年{as_of_day.month}月{as_of_day.day}日現在",
        name=resume_fm.get("name", ""),
        name_kana=fm.get("name_kana", ""),
        birth=f"{birth.year}年{birth.month}月{birth.day}日生（満{age_on(birth, as_of_day)}歳）",
        gender=fm.get("gender") or "",
        postal_code=fm.get("postal_code", ""),
        address=fm.get("address", ""),
        address_kana=fm.get("address_kana", ""),
        phone=resume_fm.get("phone", ""),
        email=resume_fm.get("email", ""),
        history=history_rows(fm),
        licenses=_pad([_row(item) for item in fm.get("licenses") or []], LICENSE_ROWS),
        motivation=motivation,
        wishes=wishes,
    )


def check_leaks(markup: str, resume_fm: dict[str, Any]) -> list[str]:
    """現在年収・非公開ファイルの文章が含まれていれば、その説明のリストを返す."""
    text = _html_to_text(markup)
    found: list[str] = []
    income = resume_fm.get("current_annual_income")
    if income:
        income = int(income)
        for value in (str(income), f"{income:,}", f"{income // 10000}万"):
            if value in text:
                found.append(f"現在年収（{value}）")
    for fragment in _internal_fragments():
        if fragment in text:
            found.append(f"非公開ファイルの文章（{fragment[:30]}…）")
    return found


def parse_args():
    parser = create_base_parser(
        description="履歴書を vault/profile/rirekisho.md から PDF 出力する",
        examples=[
            "uv run python scripts/profile/export_rirekisho.py -s  # 志望動機なし → data/exports/{日付}_rirekisho.pdf",
            "uv run python scripts/profile/export_rirekisho.py --company <company-key> -s  # application.md の志望動機を差し込む",
            "uv run python scripts/profile/export_rirekisho.py --company <company-key> --date 2026-11-01 --html",
        ],
        related=[
            "scripts/profile/export_pdf.py: 職務経歴書 PDF も一緒に出す",
        ],
    )
    parser.add_argument("--company", help="志望動機を差し込む企業キー（企業フォルダの application.md を読む）")
    parser.add_argument("--track", choices=TRACKS, default=DEFAULT_TRACK, help="--company の企業フォルダがある track")
    parser.add_argument("--date", help="記入日 YYYY-MM-DD（既定: 今日）")
    parser.add_argument("--html", action="store_true", help="PDF と同名の HTML も保存する（レイアウト確認用）")
    parser.add_argument("--out", help="出力 PDF パス（既定: data/exports/{日付}_rirekisho[_{company}].pdf）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    today = dt.date.today()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        as_of_day = dt.date.fromisoformat(args.date) if args.date else today
        resume_fm = frontmatter.read(RESUME_PATH).data
        doc = frontmatter.read(RIREKISHO_PATH)
        wishes = section_text(doc.body, "本人希望記入欄") or ""
        motivation = ""

        application = None
        if args.company:
            application = track_companies_dir(args.track) / args.company / APPLICATION_FILE
            if not application.exists():
                ctx.error(f"{to_relative_path(application)} がありません。`## 志望動機` 節を書いて作成してください。")
                sys.exit(1)
            app_body = frontmatter.read(application).body
            motivation = section_text(app_body, "志望動機") or ""
            wishes = section_text(app_body, "本人希望記入欄") or wishes
        if not motivation:
            ctx.warn("志望動機が空のまま出力します（--company と application.md の `## 志望動機` で差し込めます）。")

        markup = render_html(resume_fm, doc.data, motivation=motivation, wishes=wishes, as_of_day=as_of_day)
        leaks = check_leaks(markup, resume_fm)
        if leaks:
            for leak in leaks:
                ctx.error(f"提出用 PDF に載せてはいけない情報が含まれています: {leak}")
            sys.exit(1)

        suffix = f"_{args.company}" if args.company else ""
        out_path = Path(args.out) if args.out else EXPORT_DIR / f"{as_of_day.isoformat()}_rirekisho{suffix}.pdf"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if args.html:
            html_path = out_path.with_suffix(".html")
            html_path.write_text(markup, encoding="utf-8")
            ctx.add_result_path(html_path)
        print_pdf(markup, out_path, page_numbers=False, margin_mm=12)
        ctx.add_result_path(out_path)
        pages = count_pages(out_path)

        def print_summary() -> None:
            print(f"出力: {to_relative_path(out_path)}（{pages} ページ）")
            print(f"元データ: {to_relative_path(RIREKISHO_PATH)}（更新日: {doc.data.get('updated_at', '-')}）")
            print(f"志望動機: {to_relative_path(application) if application else 'なし'}（{len(motivation)} 字）")

        ctx.flush_outputs(
            summary_fn=print_summary,
            json_data={
                "path": to_relative_path(out_path),
                "pages": pages,
                "source": to_relative_path(RIREKISHO_PATH),
                "application": to_relative_path(application) if application else None,
                "motivation_chars": len(motivation),
            },
        )


if __name__ == "__main__":
    main()
