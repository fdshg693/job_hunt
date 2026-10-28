"""add_material.py / fetch_deck.py の material・生データ相互参照のオフラインテスト（HTTP はモック）."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.common.storage import RAW_MATERIALS_KEY, add_material_refs, read_material_refs
from scripts.vault import add_material as am
from scripts.vault import frontmatter
from scripts.vault.schema import CompanyDoc, MaterialDoc

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_INDEX = ROOT / "templates" / "vault" / "tracks" / "domestic" / "companies" / "sample" / "index.md"
DECK_URL = "https://speakerdeck.com/example/sample-deck"

DECK_PAGE_HTML = """
<html><head>
<meta property="og:title" content="サンプル会社紹介資料" />
<meta property="og:description" content="会社紹介スライド" />
</head><body>
<div class="speakerdeck-embed" data-id="abc123"></div>
</body></html>
"""

PLAYER_HTML = """
<html><body>
<div class="sd-player-slide js-sd-slide" data-url="https://files.speakerdeck.com/presentations/abc/slide_0.jpg">
  <h2 class="sd-player-slides--heading">Slide 1</h2>
  <div class="sd-player-slides--text">ミッション</div>
</div>
</body></html>
"""


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """tmp_path をプロジェクトルートに見立て、sample 企業ログと Speaker Deck のモックを置く."""
    company_dir = tmp_path / "vault" / "tracks" / "domestic" / "companies" / "sample"
    company_dir.mkdir(parents=True)
    shutil.copy(SAMPLE_INDEX, company_dir / "index.md")

    monkeypatch.setattr("scripts.common.cli.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("scripts.speakerdeck.fetch_deck.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(am, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(am, "RECRUITERS_DIR", tmp_path / "vault" / "recruiters")
    monkeypatch.setattr(am, "track_companies_dir", lambda track="domestic": tmp_path / "vault" / "tracks" / track / "companies")
    monkeypatch.setattr(
        "scripts.common.paths.track_companies_dir",
        lambda track="domestic": tmp_path / "vault" / "tracks" / track / "companies",
    )

    def fake_fetch(url: str, headers: dict[str, str] | None = None) -> tuple[str, int]:
        return (PLAYER_HTML if "/player/" in url else DECK_PAGE_HTML), 200

    monkeypatch.setattr("scripts.speakerdeck.fetch_deck.fetch_url_content", fake_fetch)
    return tmp_path


def _company(root: Path) -> Path:
    return root / "vault" / "tracks" / "domestic" / "companies" / "sample"


def test_add_material_writes_frontmatter_and_back_reference(sandbox: Path) -> None:
    ref_link, paths = am.add_material(DECK_URL, company_key="sample")

    material_path = _company(sandbox) / "materials" / "sample-deck.md"
    material = MaterialDoc.model_validate(frontmatter.read(material_path).data)
    assert material.source_url == DECK_URL
    assert material.raw_data == ["data/speakerdeck/sample/sample-deck/"]
    assert material.raw_fetched_at is not None

    # 本文には元URL・取得日・ローカル原本を書かない（フロントマターが正）
    body = frontmatter.read(material_path).body
    assert "取得日" not in body and "ローカル原本" not in body and DECK_URL not in body

    # 生データ側の逆参照
    deck_json = sandbox / "data" / "speakerdeck" / "sample" / "sample-deck" / "deck.json"
    assert deck_json in paths
    assert read_material_refs(deck_json) == ["vault/tracks/domestic/companies/sample/materials/sample-deck.md"]

    # material がある link には fetched_at を書かない
    assert ref_link.fetched_at is None
    company = CompanyDoc.model_validate(frontmatter.read(_company(sandbox) / "index.md").data)
    link = next(link for link in company.links if link.url == DECK_URL)
    assert link.material == "materials/sample-deck.md" and link.fetched_at is None


def test_add_material_without_material_keeps_link_date(sandbox: Path) -> None:
    ref_link, _ = am.add_material("https://example.com/about", company_key="sample", fetch=False, no_material=True)
    assert ref_link.material is None
    assert ref_link.fetched_at is not None


def test_add_material_does_not_overwrite_existing_summary(sandbox: Path) -> None:
    am.add_material(DECK_URL, company_key="sample")
    material_path = _company(sandbox) / "materials" / "sample-deck.md"
    doc = frontmatter.read(material_path)
    material_path.write_text(frontmatter.render(MaterialDoc.model_validate(doc.data), "\n# AI が書いた要約\n"), encoding="utf-8")

    am.add_material(DECK_URL, company_key="sample")
    assert "AI が書いた要約" in material_path.read_text(encoding="utf-8")


def test_refresh_updates_raw_dates_but_keeps_summary(sandbox: Path) -> None:
    am.add_material(DECK_URL, company_key="sample")
    material_path = _company(sandbox) / "materials" / "sample-deck.md"

    # 古い日付と別の場所の raw_data（既存資料の想定）に書き換え、要約本文を差し替える
    doc = frontmatter.read(material_path)
    model = MaterialDoc.model_validate(doc.data)
    model.fetched_at = model.fetched_at.replace(year=2020)
    model.raw_fetched_at = model.raw_fetched_at.replace(year=2020)  # type: ignore[union-attr]
    model.raw_data = ["data/speakerdeck/example/sample-deck/"]
    material_path.write_text(frontmatter.render(model, "\n# AI が書いた要約\n"), encoding="utf-8")

    resolved = am.resolve_material_path("sample-deck", company_key="sample")
    refreshed, paths = am.refresh_material(resolved)

    assert paths[0] == material_path
    # 既存の raw_data と同じ場所に取り直す
    assert refreshed.raw_data == ["data/speakerdeck/example/sample-deck/"]
    assert refreshed.raw_fetched_at is not None and refreshed.raw_fetched_at.year != 2020
    # 要約本文と要約の日付は変えない
    assert refreshed.fetched_at.year == 2020
    assert "AI が書いた要約" in material_path.read_text(encoding="utf-8")
    deck_json = sandbox / "data" / "speakerdeck" / "example" / "sample-deck" / "deck.json"
    assert read_material_refs(deck_json) == ["vault/tracks/domestic/companies/sample/materials/sample-deck.md"]


def test_refresh_rejects_material_without_raw_route(sandbox: Path) -> None:
    material_path = _company(sandbox) / "materials" / "about.md"
    material_path.parent.mkdir(parents=True)
    material_path.write_text(am.render_material("About", "https://example.com/about", "# About\n"), encoding="utf-8")
    with pytest.raises(ValueError, match="取得経路が無い"):
        am.refresh_material(material_path)


def test_fetch_deck_force_keeps_material_refs(sandbox: Path) -> None:
    from scripts.speakerdeck.fetch_deck import fetch_deck

    _, paths = fetch_deck(DECK_URL, company_key="sample")
    deck_json = next(p for p in paths if p.name == "deck.json")
    add_material_refs(deck_json, ["vault/recruiters/x/materials/a.md"])

    fetch_deck(DECK_URL, company_key="sample", force=True)
    assert read_material_refs(deck_json) == ["vault/recruiters/x/materials/a.md"]


def test_material_refs_on_markdown_raw(tmp_path: Path) -> None:
    raw = tmp_path / "article.md"
    raw.write_text("---\nid: n1\nfetched_at: '2026-10-28T10:00:00'\n---\n\n本文\n", encoding="utf-8")

    assert add_material_refs(raw, ["vault/a.md"]) is True
    assert add_material_refs(raw, ["vault/a.md"]) is False  # 重複は足さない
    assert read_material_refs(raw) == ["vault/a.md"]
    text = raw.read_text(encoding="utf-8")
    assert text.endswith("\n本文\n") and "fetched_at: '2026-10-28T10:00:00'" in text


def test_material_refs_on_json_raw(tmp_path: Path) -> None:
    raw = tmp_path / "deck.json"
    raw.write_text(json.dumps({"fetched_at": "2026-10-28T10:00:00"}), encoding="utf-8")
    add_material_refs(raw, ["vault/a.md", "vault/b.md"])
    assert json.loads(raw.read_text(encoding="utf-8"))[RAW_MATERIALS_KEY] == ["vault/a.md", "vault/b.md"]
