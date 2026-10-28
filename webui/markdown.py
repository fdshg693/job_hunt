"""vault 本文の Markdown → HTML.

- 生 HTML は無効（エスケープされる）。本文にはスクレイプしたテキストや外部 URL が混じるため、XSS の経路を作らない。
- 相対リンクは文書の位置から解決し、UI で表示できるファイルなら UI 内の URL に書き換える。
  表示できないファイル（internal・プロフィール等）へのリンクはクリックできない <span> にする。
- 外部リンク（http/https/mailto）は新しいタブで開く。
"""

from __future__ import annotations

import posixpath
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token
from markupsafe import Markup, escape

from webui.links import ui_url

_EXTERNAL_SCHEMES = {"http", "https", "mailto"}


def _resolve(href: str, doc_rel: str) -> tuple[str | None, bool]:
    """href を (新しい href, 外部リンクか) にする. href が None ならリンクを無効化する."""
    parts = urlsplit(href)
    if parts.scheme:
        return (href, True) if parts.scheme.lower() in _EXTERNAL_SCHEMES else (None, False)
    if not parts.path:
        return (href, False) if parts.fragment else (None, False)  # ページ内アンカーはそのまま
    target = posixpath.normpath(posixpath.join(posixpath.dirname(doc_rel), unquote(parts.path)))
    url = ui_url(target)
    return (url, False)


def _rewrite_links(state) -> None:
    doc_rel: str = state.env.get("doc_rel", "")
    for block in state.tokens:
        if block.type != "inline" or not block.children:
            continue
        stack: list[Token] = []
        for tok in block.children:
            if tok.type == "link_open":
                href, external = _resolve(tok.attrGet("href") or "", doc_rel)
                if href is None:
                    tok.type = "dead_link_open"
                    tok.attrs = {"title": "Web UI では表示しないファイル"}
                else:
                    tok.attrSet("href", href)
                    if external:
                        tok.attrSet("target", "_blank")
                        tok.attrSet("rel", "noopener noreferrer")
                stack.append(tok)
            elif tok.type == "link_close" and stack:
                if stack.pop().type == "dead_link_open":
                    tok.type = "dead_link_close"


def _render_dead_open(self, tokens, idx, options, env) -> str:
    return f'<span class="dead-link" title="{escape(tokens[idx].attrGet("title") or "")}">'


def _render_dead_close(self, tokens, idx, options, env) -> str:
    return "</span>"


def _build() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False, "linkify": False, "breaks": True}).enable(["table", "strikethrough"])
    md.core.ruler.push("rewrite_vault_links", _rewrite_links)
    md.add_render_rule("dead_link_open", _render_dead_open)
    md.add_render_rule("dead_link_close", _render_dead_close)
    return md


_MD = _build()


def render(body: str, doc_rel: str) -> Markup:
    """本文を HTML にする. doc_rel は文書のリポジトリルート相対パス（相対リンクの起点）."""
    return Markup(_MD.render(body, {"doc_rel": doc_rel}))
