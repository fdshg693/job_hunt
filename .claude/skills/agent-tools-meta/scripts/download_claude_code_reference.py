"""Download the reference

Output files are written to output/claude/ under the skill directory, with a YAML
frontmatter block recording each file's source URL and fetch time. On rerun,
a file is skipped (not re-downloaded) if it was fetched within the last 24
hours; pass --force to overwrite regardless of age.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

SKILL_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = SKILL_DIR / "output" / "claude"

TARGETS = [
    ("https://code.claude.com/docs/llms.txt", "llms.txt"),
    ("https://code.claude.com/docs/llms-full.txt", "llms-full.txt"),
]

FRESHNESS = timedelta(days=1)
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def read_fetched_at(path: Path) -> datetime | None:
    if not path.is_file():
        return None
    match = FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
    if not match:
        return None
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "fetched_at":
            try:
                return datetime.fromisoformat(value.strip())
            except ValueError:
                return None
    return None


def fetch_url(url: str) -> str:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def write_output(path: Path, url: str, body: str) -> None:
    fetched_at = datetime.now(timezone.utc).isoformat()
    frontmatter = f"---\nsource: {url}\nfetched_at: {fetched_at}\n---\n\n"
    path.write_text(frontmatter + body, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if the existing file was fetched less than a day ago.",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for url, filename in TARGETS:
        path = OUTPUT_DIR / filename
        if not args.force:
            fetched_at = read_fetched_at(path)
            if fetched_at is not None and datetime.now(timezone.utc) - fetched_at < FRESHNESS:
                print(
                    f"{filename}: すでに最新が取得済です（取得時刻: {fetched_at.isoformat()}）。--force で上書きできます。"
                )
                continue

        body = fetch_url(url)
        write_output(path, url, body)
        print(f"Wrote {path.relative_to(SKILL_DIR)}")


if __name__ == "__main__":
    main()
