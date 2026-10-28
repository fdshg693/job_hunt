"""vault Markdown のフロントマター読み書きヘルパー.

- 読み込み: 先頭の ``---`` 〜 ``---`` を YAML として dict にし、本文はそのまま返す。
- 書き出し: スキーマ（Pydantic モデル）のフィールド順でフロントマターを書き、本文は1文字も変えない。
  改行コード（LF / CRLF）は元ファイルに合わせる。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

_FM_PATTERN = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)


@dataclass
class MarkdownDoc:
    data: dict[str, Any]
    body: str  # フロントマター直後から末尾まで（改行コードも元のまま）
    newline: str  # "\n" または "\r\n"
    has_frontmatter: bool


def split(text: str) -> MarkdownDoc:
    """Markdown テキストをフロントマター dict と本文に分ける."""
    newline = "\r\n" if text.split("\n", 1)[0].endswith("\r") else "\n"
    match = _FM_PATTERN.match(text)
    if not match:
        return MarkdownDoc({}, text, newline, False)
    data = yaml.safe_load(match.group(1)) or {}
    if not isinstance(data, dict):
        raise ValueError("フロントマターが YAML の mapping ではない")
    return MarkdownDoc(data, text[match.end() :], newline, True)


def read(path: Path) -> MarkdownDoc:
    return split(path.read_bytes().decode("utf-8"))


class _Quoted(str):
    """ダブルクォートで書き出す文字列値（キーは素のまま書く）."""


class _Dumper(yaml.SafeDumper):
    """リストをキーより1段下げて書き、文字列値はダブルクォートで書く Dumper."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:  # noqa: ARG002
        super().increase_indent(flow, False)


def _str_representer(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style='"')


_Dumper.add_representer(_Quoted, _str_representer)


def _clean(value: Any) -> Any:
    """書き出し用に値を整える: None・空リストのキーを落とし、整数値の float は int にする."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if v is not None and v != []}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        return _Quoted(value)
    return value


def dump_frontmatter(model: BaseModel) -> str:
    """モデルをフィールド順の YAML 文字列にする（末尾改行あり、区切り線なし）.

    未記入（None）と空リストは書かない。enum の既定値（status, action_type 等）は
    「未記入」と区別するため常に書く。
    """
    data = _clean(model.model_dump(mode="json"))
    return yaml.dump(data, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=10**9)


def render(model: BaseModel, body: str, newline: str = "\n") -> str:
    fm = dump_frontmatter(model).rstrip("\n")
    if newline != "\n":
        fm = fm.replace("\n", newline)
    return f"---{newline}{fm}{newline}---{newline}{body}"


def write(path: Path, model: BaseModel, doc: MarkdownDoc) -> bool:
    """モデルのフロントマターと元の本文でファイルを書き直す. 内容が変わったら True."""
    text = render(model, doc.body, doc.newline)
    old = path.read_bytes().decode("utf-8")
    if text == old:
        return False
    path.write_bytes(text.encode("utf-8"))
    return True
