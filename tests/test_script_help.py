"""エントリポイントの docstring・--help 規約の静的テスト.

scripts/ 配下の ``if __name__ == "__main__"`` を持つスクリプトを AST で走査し、
.agents/rules/scripts-entrypoint.md §6 の規約を検査する（スクリプトは起動しない）。

- モジュール docstring の 1 行目が「何をする CLI か」の 1 文（70 字以内、``CLI`` を含む。
  非推奨スクリプトは ``非推奨:`` で始めて代わりのスクリプトを書く）。1 行目はスクリプト一覧の生成元になる
- パーサー生成時に使用例・関連スクリプトが渡っている
  （``create_base_parser`` / ``create_search_parser`` / ``JobCrawlerConfig`` / ``MessageCrawlerConfig`` の ``examples=``、
  または ``argparse.ArgumentParser`` の ``epilog=``。非推奨の互換ラッパーは委譲先の --help に任せる）
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

SUMMARY_MAX_LEN = 70
DEPRECATED_PREFIX = "非推奨:"
EXAMPLES_CALLS = {"create_base_parser", "create_search_parser", "JobCrawlerConfig", "MessageCrawlerConfig"}


def _is_main_guard(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    names = [node.test.left, *node.test.comparators]
    return any(isinstance(n, ast.Name) and n.id == "__name__" for n in names) and any(
        isinstance(n, ast.Constant) and n.value == "__main__" for n in names
    )


def _entrypoints() -> list[Path]:
    paths = []
    for path in sorted(SCRIPTS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(_is_main_guard(node) for node in tree.body):
            paths.append(path)
    return paths


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _has_help_epilog(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        keywords = {kw.arg for kw in node.keywords}
        if name in EXAMPLES_CALLS and "examples" in keywords:
            return True
        if name == "ArgumentParser" and "epilog" in keywords:
            return True
    return False


ENTRYPOINTS = _entrypoints()


def _id(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def test_entrypoints_found() -> None:
    assert len(ENTRYPOINTS) > 50


@pytest.mark.parametrize("path", ENTRYPOINTS, ids=_id)
def test_docstring_summary(path: Path) -> None:
    doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    assert doc, "モジュール docstring が無い"
    lines = doc.splitlines()
    summary = lines[0].strip()
    assert summary, "docstring の 1 行目が空"
    assert len(summary) <= SUMMARY_MAX_LEN, f"docstring 1 行目が {len(summary)} 字（{SUMMARY_MAX_LEN} 字以内）: {summary}"
    assert "CLI" in summary or summary.startswith(DEPRECATED_PREFIX), (
        f"docstring 1 行目は「〜を…する CLI」か「{DEPRECATED_PREFIX} 代わりに X」の形にする: {summary}"
    )
    if len(lines) > 1:
        assert not lines[1].strip(), "docstring の 1 行目の後は空行を入れる（1 行目だけで一覧に載せる）"


@pytest.mark.parametrize("path", ENTRYPOINTS, ids=_id)
def test_help_has_examples(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    doc = ast.get_docstring(tree) or ""
    if doc.startswith(DEPRECATED_PREFIX):
        return
    assert _has_help_epilog(tree), (
        "--help に使用例・関連スクリプトが無い（create_base_parser(examples=..., related=...) か "
        "ArgumentParser(epilog=build_epilog(...))）"
    )
