"""scripts/dev/check_public_leak.py の単体テスト."""

from __future__ import annotations

import io
import sys
from pathlib import Path

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from scripts.dev.check_public_leak import (
    collect_target_files,
    load_denylist,
    scan_files,
)


def test_load_denylist_parses_patterns_and_ignores_comments(tmp_path: Path) -> None:
    """禁止語リストのパースとコメント・空行スキップの検証."""
    denylist_file = tmp_path / "denylist.txt"
    denylist_file.write_text(
        "# コメント行\n\n(?i)secret_token_\\d+\nFORBIDDEN_NAME\n",
        encoding="utf-8",
    )

    patterns = load_denylist(denylist_path=denylist_file)
    assert len(patterns) == 2
    rule_idx_1, pat_1 = patterns[0]
    rule_idx_2, pat_2 = patterns[1]

    assert rule_idx_1 == 3
    assert pat_1.search("SECRET_TOKEN_123") is not None
    assert pat_1.search("normal_text") is None

    assert rule_idx_2 == 4
    assert pat_2.search("This is FORBIDDEN_NAME in text") is not None


def test_scan_files_detects_leaks_without_exposing_secret_values(tmp_path: Path) -> None:
    """禁止語のヒット検出と、ログ出力に機密値自体が含まれないことの検証."""
    secret_value = "ULTRA_SENSITIVE_SECRET_12345"
    normal_file = tmp_path / "normal.py"
    normal_file.write_text("print('hello world')\n", encoding="utf-8")

    leaked_file = tmp_path / "leaked.py"
    leaked_file.write_text(
        f"# line 1\nSECRET = '{secret_value}'\n# line 3\n",
        encoding="utf-8",
    )

    patterns = load_denylist(raw_denylist=r"ULTRA_SENSITIVE_SECRET_\d+")
    files = [normal_file, leaked_file]

    hits = scan_files(files, patterns, base_dir=tmp_path)

    # ヒット数が1件であること
    assert len(hits) == 1
    hit_msg = hits[0]

    # leaked.py:2 (rule #1) の形式であること
    assert "leaked.py:2" in hit_msg
    assert "rule #1" in hit_msg

    # 機密値自体が出力文字列に含まれていないこと（最重要安全要件）
    assert secret_value not in hit_msg


def test_scan_files_no_hits_when_clean(tmp_path: Path) -> None:
    """禁止語を含まない場合にヒットが 0 件であることの検証."""
    clean_file = tmp_path / "clean.txt"
    clean_file.write_text("All safe text here.\nNo issues at all.\n", encoding="utf-8")

    patterns = load_denylist(raw_denylist=r"FORBIDDEN_KEYWORD")
    hits = scan_files([clean_file], patterns, base_dir=tmp_path)
    assert hits == []


def test_collect_target_files_respects_ignores(tmp_path: Path) -> None:
    """バイナリやキャッシュディレクトリが収集から除外されることの検証."""
    sync_dir = tmp_path / "sync"
    sync_dir.mkdir()

    valid_file = sync_dir / "valid.py"
    valid_file.write_text("print(1)", encoding="utf-8")

    pyc_file = sync_dir / "compiled.pyc"
    pyc_file.write_bytes(b"dummy")

    cache_dir = sync_dir / "__pycache__"
    cache_dir.mkdir()
    cached_file = cache_dir / "cached.py"
    cached_file.write_text("print(2)", encoding="utf-8")

    files = collect_target_files(sync_dir, is_standalone_sync_dir=True)
    assert valid_file in files
    assert pyc_file not in files
    assert cached_file not in files
