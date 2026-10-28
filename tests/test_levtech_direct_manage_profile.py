"""scripts/levtech_direct/manage_profile.py および互換ラッパーの単体テスト."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from unittest.mock import MagicMock, patch

import pytest

from scripts.common.profile_sync import VaultProfile
from scripts.levtech_direct.manage_profile import (
    ALL_SECTIONS,
    extract_sync_payload,
    format_basic_markdown,
    format_resume_markdown,
    run_section_cli,
    setup_cli_parser,
)


def test_setup_cli_parser():
    """CLIパーサーの各サブコマンド構造をテスト."""
    parser = setup_cli_parser()

    # basic
    args = parser.parse_args(["basic", "fetch"])
    assert args.section == "basic"
    assert args.action == "fetch"

    # resume update
    args = parser.parse_args(["resume", "update", "--dry-run", "--resume", "テスト職務経歴テキスト10文字以上"])
    assert args.section == "resume"
    assert args.action == "update"
    assert args.dry_run is True
    assert args.resume == "テスト職務経歴テキスト10文字以上"

    # sync all
    args = parser.parse_args(["sync", "--dry-run", "--sections", "basic,skill"])
    assert args.section == "sync"
    assert args.dry_run is True
    assert args.sections == "basic,skill"


def test_extract_sync_payload():
    """VaultProfile から各セクションのペイロードが正しく抽出されるかをテスト."""
    profile = VaultProfile(
        name="山田 太郎",
        kana_last="ヤマダ",
        kana_first="タロウ",
        birth_date="1990-01-01",
        current_annual_income=7000000,
        target_annual_income_min=8000000,
        location="東京都",
        phone="090-1234-5678",
        summary="職務要約テキストです。",
    )

    # basic
    basic_payload = extract_sync_payload("basic", profile)
    assert basic_payload["lastName"] == "山田"
    assert basic_payload["firstName"] == "太郎"
    assert basic_payload["kanaLastName"] == "ヤマダ"
    assert basic_payload["birthday"] == "1990-01-01"
    assert basic_payload["currentAnnualIncome"] == 700

    # resume
    resume_payload = extract_sync_payload("resume", profile)
    assert "職務要約" in resume_payload["resume"]

    # condition
    cond_payload = extract_sync_payload("condition", profile)
    assert cond_payload["annualIncome"] == 800
    assert cond_payload["workPlaces"] == ["p_1"]


def test_format_markdowns():
    """Markdown出力フォーマットが崩れていないかをテスト."""
    from datetime import datetime

    now = datetime(2026, 10, 24, 12, 0, 0)
    basic_data = {
        "data": {
            "lastName": "山田",
            "firstName": "太郎",
            "birthday": "1990-01-01",
            "currentAnnualIncome": 700,
        }
    }
    md = format_basic_markdown(basic_data, now)
    assert "source: levtech_direct" in md
    assert "山田 太郎" in md
    assert "700万円" in md

    resume_data = {
        "data": {
            "resume": "サンプル職務経歴書テキスト",
            "charCount": 13,
            "updatedAtText": "2026/10/24",
        }
    }
    rmd = format_resume_markdown(resume_data, now)
    assert "type: profile_resume" in rmd
    assert "13 / 30,000文字" in rmd


def test_compat_wrapper_invocation():
    """互換ラッパー経由で run_section_cli が呼ばれた際の引数展開をテスト."""
    captured_argv = []

    def fake_main():
        captured_argv.extend(sys.argv)
        return 0

    with patch("scripts.levtech_direct.manage_profile.main", side_effect=fake_main):
        ret = run_section_cli("basic", ["fetch", "--summary"])
        assert ret == 0
        assert captured_argv[1] == "basic"
        assert captured_argv[2] == "fetch"
        assert captured_argv[3] == "--summary"
