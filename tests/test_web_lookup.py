"""Web 調査スクリプト (scripts/web/) のオフラインテスト. Tavily クライアントはモックする."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from scripts.common import data_retention
from scripts.web import extract as extract_cli
from scripts.web import search as search_cli
from scripts.web import tavily_client


class FakeClient:
    """TavilyClient の代わり. 呼び出し引数を記録して固定の応答を返す."""

    def __init__(self, search_results: list[dict[str, Any]], extract_results: list[dict[str, Any]]) -> None:
        self.search_results = search_results
        self.extract_results = extract_results
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def search(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("search", kwargs))
        return {"results": self.search_results}

    def extract(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("extract", kwargs))
        return {"results": self.extract_results}


SEARCH_RESULTS = [
    {"title": "Example  Visa\nGuide", "url": "https://example.gov/visa", "score": 0.91, "content": "必要書類の抜粋"},
    {"title": "", "url": "https://example.org/news", "score": 0.5, "content": "ニュース抜粋"},
]
EXTRACT_RESULTS = [{"url": "https://example.com/page", "raw_content": "# 本文\n\n全文テキスト"}]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeClient:
    client = FakeClient(SEARCH_RESULTS, EXTRACT_RESULTS)
    monkeypatch.setattr(tavily_client, "_client", lambda api_key: client)
    monkeypatch.setattr(tavily_client, "SEARCHES_DIR", tmp_path / "web" / "searches")
    monkeypatch.setattr(tavily_client, "EXTRACTS_DIR", tmp_path / "web" / "extracts")
    monkeypatch.setattr(tavily_client, "ENV_PATH", tmp_path / ".env")  # 実リポジトリの .env を読まない
    monkeypatch.setenv(tavily_client.API_KEY_ENV, "dummy-key")
    return client


def _run(monkeypatch: pytest.MonkeyPatch, module: Any, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", ["prog", *argv])
    with pytest.raises(SystemExit) as exc:
        module.main()
    return int(exc.value.code or 0)


def test_search_saves_index_and_prints_only_path(
    fake: FakeClient, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code = _run(monkeypatch, search_cli, ["visa requirements", "--include-domain", "example.gov", "-n", "3"])
    assert code == 0

    out = capsys.readouterr().out.strip().splitlines()
    index = next((tmp_path / "web" / "searches").glob("*/index.md"))
    assert out == [index.as_posix()]  # tmp_path はリポジトリ外なので絶対パスのまま出る
    text = index.read_text(encoding="utf-8")
    assert "kind: search" in text and "fetched_at:" in text
    assert "[Example Visa Guide](0001.md)" in text and "chars)" in text

    first = (index.parent / "0001.md").read_text(encoding="utf-8")
    assert "URL: https://example.gov/visa" in first and "Score: 0.91" in first
    assert "(untitled)" not in (index.parent / "0002.md").read_text(encoding="utf-8")  # 空タイトルは URL で補う

    _, kwargs = fake.calls[0]
    assert kwargs["max_results"] == 3 and kwargs["include_domains"] == ["example.gov"]
    assert kwargs["exclude_domains"] is None


def test_extract_with_query_passes_chunks(fake: FakeClient, monkeypatch: pytest.MonkeyPatch) -> None:
    code = _run(monkeypatch, extract_cli, ["https://example.com/page", "--query", "申請期限"])
    assert code == 0

    _, kwargs = fake.calls[0]
    assert kwargs["urls"] == ["https://example.com/page"]
    assert kwargs["query"] == "申請期限" and kwargs["chunks_per_source"] == 3
    folder = next(tavily_client.EXTRACTS_DIR.iterdir())
    body = (folder / "0001.md").read_text(encoding="utf-8")
    assert body.startswith("# https://example.com/page") and "Score:" not in body


def test_missing_api_key_exits_2_without_network(
    fake: FakeClient, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(tavily_client.API_KEY_ENV)
    code = _run(monkeypatch, search_cli, ["anything"])
    captured = capsys.readouterr()
    assert code == tavily_client.EXIT_NO_API_KEY
    assert captured.out == "" and tavily_client.API_KEY_ENV in captured.err
    assert fake.calls == []


def test_no_results_exits_1(fake: FakeClient, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake.search_results = []
    code = _run(monkeypatch, search_cli, ["nothing"])
    captured = capsys.readouterr()
    assert code == 1 and captured.out == "" and "No results." in captured.err
    assert not tavily_client.SEARCHES_DIR.exists()


def test_same_second_calls_do_not_overwrite(tmp_path: Path) -> None:
    now = datetime(2026, 10, 1, 12, 0, 0)
    result = [tavily_client.WebResult(title="t", url="https://example.com", content="c")]
    a = tavily_client.write_results(tmp_path, "q", result, {"kind": "search"}, now=now)
    b = tavily_client.write_results(tmp_path, "q", result, {"kind": "search"}, now=now)
    assert a.parent != b.parent and a.parent.name == "20261001_120000_q"


def test_web_folders_are_retention_units(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    folder = data_dir / "web" / "searches" / "20260101_000000_q"
    folder.mkdir(parents=True)
    (folder / "index.md").write_text("---\nfetched_at: '2026-01-01T00:00:00+09:00'\n---\n", encoding="utf-8")
    (folder / "0001.md").write_text("x", encoding="utf-8")

    units = data_retention.collect_units(data_dir)
    assert [(u.key.as_posix(), u.is_dir) for u in units] == [("web/searches/20260101_000000_q", True)]
    assert data_retention.is_retained_ref("data/web/extracts/20260101_000000_x/index.md")
