"""data_retention.py（data/ の保持期間プルーナー）のオフラインテスト（tmp ディレクトリ上のダミーデータ）."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from scripts.common import data_retention as dr

TODAY = dt.date(2026, 12, 31)
OLD = "2026-09-01T10:00:00+09:00"  # 保持期間（60 日）切れ
NEW = "2026-12-20T10:00:00"


def _md(path: Path, fetched_at: str | None = None, body: str = "本文") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = f"---\nid: x\nfetched_at: '{fetched_at}'\n---\n" if fetched_at else ""
    path.write_text(fm + body, encoding="utf-8")
    return path


def _json(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "data").mkdir()
    (tmp_path / "vault").mkdir()
    return tmp_path


def _expired_keys(root: Path) -> dict[str, str]:
    units = dr.find_expired(TODAY, data_dir=root / "data", vault_dir=root / "vault")
    return {u.key.as_posix(): u.protected_by for u in units}


def test_jobs_judged_by_fetched_at(root: Path) -> None:
    data = root / "data"
    _md(data / "findy/jobs/OLDJOB.md", OLD)
    _md(data / "findy/jobs/NEWJOB.md", NEW)
    assert _expired_keys(root) == {"findy/jobs/OLDJOB": ""}


def test_md_json_pair_is_one_unit_and_newest_date_wins(root: Path) -> None:
    data = root / "data"
    _md(data / "bizreach/searches/2026-09-01-101010_Python.md", OLD)
    _json(data / "bizreach/searches/2026-09-01-101010_Python.json", {"fetched_at": OLD})
    _md(data / "bizreach/searches/2026-09-02-101010_Go.md", OLD)
    _json(data / "bizreach/searches/2026-09-02-101010_Go.json", {"fetched_at": NEW})

    units = dr.find_expired(TODAY, data_dir=data, vault_dir=root / "vault")
    assert [u.key.as_posix() for u in units] == ["bizreach/searches/2026-09-01-101010_Python"]
    assert len(units[0].paths) == 2

    dr.delete_units(units)
    assert not list((data / "bizreach/searches").glob("2026-09-01-*"))
    assert len(list((data / "bizreach/searches").glob("2026-09-02-*"))) == 2


def test_filename_date_fallback_and_fixed_names_skipped(root: Path) -> None:
    data = root / "data"
    _json(data / "note/searches/20260901_010329_test.json", {"query": "x"})  # fetched_at なし → ファイル名
    _json(data / "findy/messages/messages_all.json", {"fetched_at": OLD})  # 固定名の現在値は対象外
    _json(data / "findy/messages/history/messages_all_20260901_104441.json", {"x": 1})
    assert set(_expired_keys(root)) == {
        "note/searches/20260901_010329_test",
        "findy/messages/history/messages_all_20260901_104441",
    }


def test_protected_paths_are_never_candidates(root: Path) -> None:
    data = root / "data"
    _json(data / "findy/profile/backups/backup_20260901_043228.json", {"fetched_at": OLD})
    _json(data / "openwork/resume/latest.json", {"fetched_at": OLD})
    _json(data / "linkedin/messages/backup_focused_20260901_234445.json", {"x": 1})
    _md(data / "levtech_direct/jobs/.gitkeep")
    (data / "exports").mkdir()
    (data / "exports/2026-09-01_career_ja.pdf").write_bytes(b"%PDF")
    _json(data / "unknown_site/stuff/2026-09-01.json", {"fetched_at": OLD})  # ポリシー表に無い
    assert _expired_keys(root) == {}


def test_speakerdeck_deck_dir_is_one_unit(root: Path) -> None:
    data = root / "data"
    deck = data / "speakerdeck/example/sample-deck"
    _json(deck / "deck.json", {"fetched_at": OLD})
    _md(deck / "transcript.md")
    _json(data / "speakerdeck/searches/20260901_002205_x.json", {"fetched_at": OLD})

    units = dr.find_expired(TODAY, data_dir=data, vault_dir=root / "vault")
    keys = {u.key.as_posix() for u in units}
    assert keys == {"speakerdeck/example/sample-deck", "speakerdeck/searches/20260901_002205_x"}
    dr.delete_units(units)
    assert not deck.exists()


def test_automation_runs_and_briefs(root: Path) -> None:
    data = root / "data"
    _md(data / "automation/briefs/2026-09-01_morning-brief.md")
    _json(data / "automation/briefs/2026-09-01_morning-brief.json", {})
    _md(data / "automation/briefs/2026-12-30_morning-brief.md")
    _md(data / "automation/runs/2026-09-01/morning-brief/run.md")
    _json(data / "automation/state.json", {})  # 状態・スケジューラ結果は対象外
    _md(data / "automation/scheduler/status.md")

    units = {u.key.as_posix(): u for u in dr.collect_units(data)}
    assert set(units) == {
        "automation/briefs/2026-09-01_morning-brief",
        "automation/briefs/2026-12-30_morning-brief",
        "automation/runs/2026-09-01",
    }
    assert len(units["automation/briefs/2026-09-01_morning-brief"].paths) == 2
    assert units["automation/runs/2026-09-01"].is_dir


def test_vault_body_reference_protects_but_material_raw_data_does_not(root: Path) -> None:
    data = root / "data"
    _md(data / "openwork/reviews/REVIEW1.md", OLD)
    _json(data / "speakerdeck/example/sample-deck/deck.json", {"fetched_at": OLD})
    company = root / "vault/tracks/domestic/companies/sample"
    _md(company / "index.md", body="口コミ: [OpenWork](../../../../../data/openwork/reviews/REVIEW1.md)\n")
    (company / "materials").mkdir()
    (company / "materials/sample-deck.md").write_text(
        "---\ntitle: x\nfetched_at: '2026-09-01'\nraw_data:\n  - \"data/speakerdeck/example/sample-deck/\"\n---\n# x\n",
        encoding="utf-8",
    )

    keys = _expired_keys(root)
    assert keys["openwork/reviews/REVIEW1"] == "vault/tracks/domestic/companies/sample/index.md"
    assert keys["speakerdeck/example/sample-deck"] == ""

    deleted = dr.delete_units(dr.find_expired(TODAY, data_dir=data, vault_dir=root / "vault"))
    assert [u.key.as_posix() for u in deleted] == ["speakerdeck/example/sample-deck"]
    assert (data / "openwork/reviews/REVIEW1.md").exists()


def test_directory_reference_in_prose_does_not_protect_everything(root: Path) -> None:
    _md(root / "data/findy/jobs/OLDJOB.md", OLD)
    _md(root / "vault/profile/README.md", body="`data/findy/` は自動取得したキャッシュ\n")
    assert _expired_keys(root) == {"findy/jobs/OLDJOB": ""}


def test_maybe_prune_runs_once_a_day(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(dr.DISABLE_ENV, raising=False)
    data = root / "data"
    state = data / ".prune_state.json"
    kwargs = {"data_dir": data, "vault_dir": root / "vault", "state_path": state}
    logs: list[str] = []
    now = dt.datetime(2026, 12, 31, 9, 0)

    _md(data / "findy/jobs/OLD1.md", OLD)
    assert [u.key.name for u in dr.maybe_prune(logs.append, now=now, **kwargs)] == ["OLD1"]
    assert dr.read_last_run(state) == now
    assert logs

    _md(data / "findy/jobs/OLD2.md", OLD)
    assert dr.maybe_prune(logs.append, now=now + dt.timedelta(hours=23), **kwargs) is None
    assert (data / "findy/jobs/OLD2.md").exists()

    assert len(dr.maybe_prune(logs.append, now=now + dt.timedelta(days=1), **kwargs)) == 1
    assert not (data / "findy/jobs/OLD2.md").exists()


def test_maybe_prune_disabled_by_env(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(dr.DISABLE_ENV, "1")
    _md(root / "data/findy/jobs/OLD1.md", OLD)
    result = dr.maybe_prune(
        print, data_dir=root / "data", vault_dir=root / "vault", state_path=root / "data/.prune_state.json"
    )
    assert result is None
    assert (root / "data/findy/jobs/OLD1.md").exists()


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("data/findy/jobs/abc.md", True),
        ("data/openwork/reviews/a0C1.md", True),
        ("data/speakerdeck/acme/deck/", True),
        ("data/speakerdeck/acme/deck/deck.json", True),
        ("data/findy/likes/2026-10-23-20.md", True),
        ("data/bizreach/profile/profile.json", False),  # 固定名の現在値
        ("data/bizreach/resume/latest.md", False),
        ("data/exports/2026-10-23_career.pdf", False),
        ("data/findy/", False),
        ("data/linkedin/jobs", False),
        ("data/vault_index.sqlite", False),
    ],
)
def test_is_retained_ref(ref: str, expected: bool) -> None:
    assert dr.is_retained_ref(ref) is expected


def test_vault_data_refs_by_file_skips_material_frontmatter(root: Path) -> None:
    vault = root / "vault"
    mat = vault / "tracks" / "domestic" / "companies" / "acme" / "materials"
    mat.mkdir(parents=True)
    (mat / "deck.md").write_text('---\nraw_data:\n  - "data/speakerdeck/acme/deck/"\n---\n\n本文\n', encoding="utf-8")
    (mat.parent / "index.md").write_text("a data/findy/jobs/x.md b data/findy/jobs/x.md\n", encoding="utf-8")
    assert dr.vault_data_refs_by_file(vault) == {
        "vault/tracks/domestic/companies/acme/index.md": ["data/findy/jobs/x.md"],
    }
