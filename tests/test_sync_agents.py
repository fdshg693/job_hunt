""".agents/ → .claude/ 同期 (scripts/dev/sync_agents.py) の同期設定まわりの単体テスト."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.dev.sync_agents import CONFIG_PATH, DST, TARGETS, build_expected, is_excluded, load_config


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_config_means_no_excludes(tmp_path: Path) -> None:
    assert load_config(tmp_path / "none.yaml") == {t: [] for t in TARGETS}


def test_load_config_reads_excludes(tmp_path: Path) -> None:
    path = _write(tmp_path / "c.yaml", "skills:\n  exclude: ['antigravity-*']\nrules:\n")
    assert load_config(path) == {"rules": [], "skills": ["antigravity-*"], "agents": []}


@pytest.mark.parametrize(
    "text",
    [
        "commands:\n  exclude: []\n",  # 未知のターゲット
        "skills:\n  include: ['x']\n",  # 未知のキー
        "skills:\n  exclude: 'x'\n",  # リストでない
        "skills: ['x']\n",  # マッピングでない
    ],
)
def test_load_config_rejects_invalid(tmp_path: Path, text: str) -> None:
    with pytest.raises(ValueError):
        load_config(_write(tmp_path / "c.yaml", text))


def test_is_excluded_matches_top_level_name_and_records_pattern() -> None:
    used: set[str] = set()
    assert is_excluded("antigravity-docs", ["antigravity-*", "foo"], used)
    assert not is_excluded("writing-skill", ["antigravity-*"], used)
    assert used == {"antigravity-*"}


def test_repo_config_is_valid() -> None:
    load_config(CONFIG_PATH)


def test_build_expected_skips_excluded_skill(capsys: pytest.CaptureFixture[str]) -> None:
    excludes = {"rules": [], "skills": ["writing-skill", "no-such-*"], "agents": []}
    expected = build_expected(excludes)
    skills = {p.relative_to(DST / "skills").parts[0] for p in expected if p.is_relative_to(DST / "skills")}
    assert "writing-skill" not in skills
    assert "writing-rules" in skills
    # どのソースにも一致しないパターンは警告だけ
    assert "'no-such-*'" in capsys.readouterr().err
