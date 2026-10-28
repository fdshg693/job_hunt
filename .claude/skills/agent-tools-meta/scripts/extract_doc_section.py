"""output/claude/llms-full.txt から、指定した URL に対応するセクションを抜き出す。

llms-full.txt は「# タイトル」行の次に「Source: <URL>」行が続く形式で
複数セクションが連結されている。
指定した URL（または slug）に一致するセクションを見つけて、
output/claude/temp/<slug>.txt として書き出す。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
INPUT_FILE = SKILL_DIR / "output" / "claude" / "llms-full.txt"
OUTPUT_DIR = SKILL_DIR / "output" / "claude" / "temp"

BASE_URL = "https://code.claude.com/docs/en/"

SECTION_RE = re.compile(
    r"^# (?P<title>[^\n]+)\nSource: (?P<source>\S+)\n\n(?P<body>.*?)(?=\n# [^\n]+\nSource: \S+\n|\Z)",
    re.DOTALL | re.MULTILINE,
)


def parse_sections(text: str) -> dict[str, tuple[str, str, str]]:
    """source URL -> (title, source, body) の辞書を返す。"""
    sections: dict[str, tuple[str, str, str]] = {}
    for match in SECTION_RE.finditer(text):
        title = match.group("title").strip()
        source = match.group("source").strip()
        body = match.group("body").strip()
        sections[source] = (title, source, body)
    return sections


def resolve_url(url_or_slug: str) -> str:
    if url_or_slug.startswith("http://") or url_or_slug.startswith("https://"):
        return url_or_slug
    return BASE_URL + url_or_slug.strip("/")


def slug_from_url(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "urls",
        nargs="+",
        help="対象の URL（例: https://code.claude.com/docs/en/admin-setup）または slug（例: admin-setup）",
    )
    args = parser.parse_args()

    if not INPUT_FILE.is_file():
        raise SystemExit(f"入力ファイルが見つかりません: {INPUT_FILE}")

    text = INPUT_FILE.read_text(encoding="utf-8")
    sections = parse_sections(text)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for raw in args.urls:
        url = resolve_url(raw)
        section = sections.get(url)
        if section is None:
            print(f"見つかりませんでした: {url}")
            continue

        title, source, body = section
        slug = slug_from_url(source)
        out_path = OUTPUT_DIR / f"{slug}.txt"
        out_path.write_text(f"# {title}\nSource: {source}\n\n{body}\n", encoding="utf-8")
        print(f"Wrote {out_path.relative_to(SKILL_DIR)}")


if __name__ == "__main__":
    main()
