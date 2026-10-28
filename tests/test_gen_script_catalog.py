"""スクリプト一覧生成 (scripts/dev/gen_script_catalog.py) の単体テスト."""

from __future__ import annotations

from pathlib import Path

from scripts.dev.gen_script_catalog import CATALOG_PATH, collect_entries, render_catalog


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


MAIN = '\n\nif __name__ == "__main__":\n    pass\n'


def _fake_repo(tmp_path: Path) -> tuple[Path, Path]:
    scripts = tmp_path / "scripts"
    docs = tmp_path / "docs"
    _write(scripts / "findy" / "fetch_job.py", '"""Findy の求人を保存する CLI.\n\n詳細。\n"""' + MAIN)
    _write(scripts / "findy" / "old.py", '"""非推奨: 代わりに scripts/findy/fetch_job.py を使う."""' + MAIN)
    _write(scripts / "findy" / "helper.py", '"""import されるだけのモジュール."""\n')
    _write(scripts / "vault" / "validate.py", '"""vault を検証する CLI。"""' + MAIN)
    _write(scripts / "newsite" / "fetch.py", '"""新媒体 | 取得する CLI."""' + MAIN)
    _write(docs / "findy" / "README.md", "# findy\n")
    _write(docs / "vault" / "schema.md", "# schema\n")
    return scripts, docs


def test_collect_entries_only_entrypoints(tmp_path: Path) -> None:
    scripts, _ = _fake_repo(tmp_path)
    entries = collect_entries(scripts)
    paths = [e.path for e in entries]
    assert "scripts/findy/helper.py" not in paths
    assert "scripts/findy/fetch_job.py" in paths
    fetch = next(e for e in entries if e.path == "scripts/findy/fetch_job.py")
    assert fetch.group == "findy"
    assert fetch.summary == "Findy の求人を保存する CLI"  # 1 行目だけ・末尾の句点を落とす


def test_render_groups_links_and_deprecated_last(tmp_path: Path) -> None:
    scripts, docs = _fake_repo(tmp_path)
    text = render_catalog(collect_entries(scripts), docs)

    assert text.startswith("<!-- 自動生成ファイル")
    assert "[`docs/findy/README.md`](../findy/README.md)" in text
    # docs/vault/ は README ではなく個別文書へのリンク（存在するものだけ）
    assert "[`docs/vault/schema.md`](../vault/schema.md)" in text
    assert "docs/vault/chores.md" not in text
    # 非推奨は表の末尾
    assert text.index("scripts/findy/fetch_job.py") < text.index("scripts/findy/old.py")
    # 未分類のディレクトリは「その他」に載り、セル内の | はエスケープ
    assert "## その他" in text
    assert "新媒体 \\| 取得する CLI" in text
    # カテゴリ順: 求人媒体 → vault → その他
    assert (
        text.index("### `scripts/findy/`") < text.index("### `scripts/vault/`") < text.index("### `scripts/newsite/`")
    )


def test_catalog_is_up_to_date() -> None:
    assert CATALOG_PATH.exists()
    assert CATALOG_PATH.read_text(encoding="utf-8") == render_catalog(collect_entries()), (
        "docs/scripts/catalog.md が古い。`uv run python scripts/dev/gen_script_catalog.py` で再生成する"
    )
