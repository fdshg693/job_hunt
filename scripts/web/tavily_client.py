"""Tavily（一般 Web 検索・URL 本文抽出）の共通部.

`search.py` / `extract.py` から使う。API キーの解決、Tavily 呼び出し、結果フォルダの保存を持つ。
仕様・判断フローは docs/web/README.md。

- API キーは環境変数 `TAVILY_API_KEY`。未設定ならリポジトリ直下の `.env` から読む（既存の環境変数を優先）。
- 1 回の呼び出しで `data/web/{kind}/{YYYYMMDD_HHMMSS}_{slug}/` を作り、`index.md`（各結果の文字数付き一覧）と
  結果ごとの `NNNN.md`（先頭付近に `URL:`、search は `Score:` も）を置く。呼び出し側は `index.md` を読んで必要な結果だけ読む。
- map / crawl / research は実装しない（docs/web/README.md）。
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from scripts.common.paths import DATA_DIR

API_KEY_ENV = "TAVILY_API_KEY"
ENV_PATH = DATA_DIR.parent / ".env"
WEB_DATA_DIR = DATA_DIR / "web"
SEARCHES_DIR = WEB_DATA_DIR / "searches"
EXTRACTS_DIR = WEB_DATA_DIR / "extracts"

TIMEOUT = 60.0
DEFAULT_MAX_RESULTS = 5
EXIT_NO_API_KEY = 2

_SLUG_SEPARATOR = re.compile(r"[^\w]+", re.UNICODE)


class MissingApiKeyError(RuntimeError):
    """`TAVILY_API_KEY` が環境変数にも `.env` にも無い."""


@dataclass
class WebResult:
    """保存する 1 件分の結果."""

    title: str
    url: str
    content: str
    score: float | None = None

    def to_markdown(self) -> str:
        lines = [f"# {self.title}", "", f"URL: {self.url}"]
        if self.score is not None:
            lines.append(f"Score: {self.score}")
        return "\n".join([*lines, "", self.content])

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "url": self.url, "score": self.score, "content": self.content}


def get_api_key() -> str:
    """API キーを返す. 無ければ ``MissingApiKeyError``（ネットワークは叩かない）."""
    load_dotenv(ENV_PATH, override=False)
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise MissingApiKeyError(f"{API_KEY_ENV} が未設定です（環境変数またはリポジトリ直下の .env に書く）")
    return key


def _client(api_key: str) -> Any:
    from tavily import TavilyClient

    return TavilyClient(api_key=api_key)


def _clean_title(text: str) -> str:
    return " ".join(text.split()) or "(untitled)"


def search(
    query: str,
    *,
    api_key: str,
    max_results: int = DEFAULT_MAX_RESULTS,
    include_domains: Sequence[str] | None = None,
    exclude_domains: Sequence[str] | None = None,
) -> list[WebResult]:
    """Web 検索し、各結果の関連抜粋（chunk）を返す."""
    response = _client(api_key).search(
        query=query,
        search_depth="advanced",
        topic="general",
        max_results=max_results,
        chunks_per_source=3,
        include_answer=False,
        include_raw_content=False,
        include_images=False,
        include_favicon=False,
        include_usage=False,
        timeout=TIMEOUT,
        include_domains=list(include_domains or []) or None,
        exclude_domains=list(exclude_domains or []) or None,
    )
    results = []
    for position, raw in enumerate(response.get("results") or [], start=1):
        url = raw.get("url", "")
        results.append(
            WebResult(
                title=_clean_title(raw.get("title") or url or f"result-{position}"),
                url=url,
                score=raw.get("score"),
                content=raw.get("content") or "",
            )
        )
    return results


def extract(urls: Sequence[str], *, api_key: str, query: str | None = None) -> list[WebResult]:
    """URL の本文を Markdown で取る. ``query`` を渡すと関連チャンクだけになる."""
    options: dict[str, Any] = {
        "extract_depth": "advanced",
        "format": "markdown",
        "timeout": TIMEOUT,
        "include_images": False,
        "include_favicon": False,
        "include_usage": False,
    }
    if query:
        options["chunks_per_source"] = 3
    response = _client(api_key).extract(urls=list(urls), query=query, **options)
    results = []
    for position, raw in enumerate(response.get("results") or [], start=1):
        url = raw.get("url", "")
        results.append(
            WebResult(
                title=_clean_title(raw.get("title") or url or f"result-{position}"),
                url=url,
                content=raw.get("raw_content") or "",
            )
        )
    return results


def slugify(text: str | None, *, max_length: int = 50) -> str:
    slug = _SLUG_SEPARATOR.sub("-", (text or "").strip().lower()).strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug or "item"


def _fresh_folder(base_dir: Path, now: datetime, label: str) -> Path:
    """同じ秒・同じラベルでも上書きしないよう、衝突したら連番を付ける."""
    stem = f"{now.strftime('%Y%m%d_%H%M%S')}_{slugify(label)}"
    folder = base_dir / stem
    seq = 2
    while folder.exists():
        folder = base_dir / f"{stem}-{seq}"
        seq += 1
    folder.mkdir(parents=True)
    return folder


def write_results(
    base_dir: Path,
    label: str,
    results: Sequence[WebResult],
    meta: dict[str, Any],
    now: datetime | None = None,
) -> Path:
    """結果を新しいフォルダに書き、``index.md`` のパスを返す."""
    now = now or datetime.now().astimezone()
    folder = _fresh_folder(base_dir, now, label)

    frontmatter = {**meta, "fetched_at": now.isoformat(timespec="seconds"), "result_count": len(results)}
    header = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False, sort_keys=False).strip()
    lines = ["---", header, "---", "", f"# {label}", ""]
    for position, result in enumerate(results, start=1):
        filename = f"{position:04d}.md"
        content = result.to_markdown()
        (folder / filename).write_text(content, encoding="utf-8")
        lines.append(f"- [{result.title}]({filename}) ({len(content)} chars)")

    index_path = folder / "index.md"
    index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return index_path
