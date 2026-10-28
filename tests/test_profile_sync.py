"""scripts/common/profile_sync.py の単体テスト."""

from __future__ import annotations

import io
import json
import sys
from datetime import datetime
from pathlib import Path

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from scripts.common.profile_sync import (
    load_site_data,
    load_site_text,
    load_vault_profile,
    print_profile_diff,
    save_profile_backup,
)

FIXTURES_VAULT_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "vault_root"


def test_load_vault_profile_fixture() -> None:
    """フィクスチャの vault/profile/ が正しくロードできることを検証."""
    profile = load_vault_profile(vault_root=FIXTURES_VAULT_ROOT)

    # 基本情報
    assert profile.name == "山田 太郎"
    assert profile.name_en == "Taro Yamada"
    last, first = profile.get_name_parts()
    assert last == "山田"
    assert first == "太郎"
    assert profile.current_annual_income == 6000000
    assert profile.toeic_score == 800
    assert "東京都" in profile.location

    # ふりがな
    assert profile.kana_last == "ヤマダ"
    assert profile.kana_first == "タロウ"

    # links
    assert profile.links.get("github") == "https://github.com/example"
    assert profile.links.get("linkedin_slug") == "taro-yamada"

    # 職歴
    assert len(profile.companies) >= 2
    comp_names = [c.company_name for c in profile.companies]
    assert any("ダミー株式会社" in n for n in comp_names)
    assert any("サンプル株式会社" in n for n in comp_names)

    dummy = next(c for c in profile.companies if "ダミー株式会社" in c.company_name)
    assert dummy.is_current is True
    assert len(dummy.projects) >= 1

    # 学歴
    assert len(profile.education) >= 1
    latest_edu = profile.get_latest_education()
    assert latest_edu is not None
    assert "サンプル大学" in latest_edu.school_name
    assert "2020" in latest_edu.graduation_date

    # スキル
    assert len(profile.languages) >= 1
    py = next((lang for lang in profile.languages if lang.name == "Python"), None)
    assert py is not None
    assert py.years > 0

    # 希望条件
    assert len(profile.target_roles) >= 1
    assert profile.target_annual_income_min is not None
    assert profile.target_annual_income_min == 7000000

    # 統合レジュメテキスト生成
    resume_text = profile.generate_combined_resume_text()
    assert "【職務要約】" in resume_text
    assert "【保有スキル・活かせる技術スタック】" in resume_text
    assert "【職務経歴詳細】" in resume_text
    assert "ダミー株式会社" in resume_text


def test_load_site_text_and_data_fixture() -> None:
    """load_site_text および load_site_data の動作を検証."""
    data, text = load_site_data("youtrust", vault_root=FIXTURES_VAULT_ROOT)
    assert "updated_at" in data
    assert text == "テスト用YOUTRUST自己紹介文"

    text_direct = load_site_text("youtrust", vault_root=FIXTURES_VAULT_ROOT)
    assert text_direct == "テスト用YOUTRUST自己紹介文"

    with pytest.raises(FileNotFoundError):
        load_site_text("nonexistent_site", vault_root=FIXTURES_VAULT_ROOT)


def test_save_profile_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """バックアップファイルが指定フォーマットで正しく保存されることを検証."""
    test_data = {"user": "test_user", "score": 100}
    fixed_time = datetime(2026, 10, 24, 12, 34, 56)

    # 1. カスタム backup_dir 指定時
    saved_path = save_profile_backup(
        site="levtech_direct",
        section="basic",
        data=test_data,
        backup_dir=tmp_path,
        timestamp=fixed_time,
        silent=True,
    )

    assert saved_path.exists()
    assert saved_path.name == "basic_2026-10-24_123456.json"
    loaded = json.loads(saved_path.read_text(encoding="utf-8"))
    assert loaded == test_data

    # 2. デフォルト（PROJECT_ROOT/backups/site）のパス命名検証
    monkeypatch.setattr("scripts.common.profile_sync.PROJECT_ROOT", tmp_path)
    default_path = save_profile_backup(
        site="levtech_direct",
        section="skill",
        data=test_data,
        timestamp=fixed_time,
        silent=True,
    )
    assert default_path.exists()
    assert default_path.parent == tmp_path / "backups" / "levtech_direct"
    assert default_path.name == "2026-10-24_123456_profile_skill.json"


def test_print_profile_diff() -> None:
    """Unified Diff プレビューが差分を正しく検出し判定することを検証."""
    buf = io.StringIO()

    # 差分ありケース
    before = {"name": "太郎", "income": 500}
    after = {"name": "次郎", "income": 600}
    has_diff = print_profile_diff(before, after, title="テスト差分", stream=buf)

    assert has_diff is True
    output = buf.getvalue()
    assert "--- テスト差分 (Unified Diff) ---" in output
    assert "太郎" in output
    assert "次郎" in output

    # 差分なしケース
    buf_nodiff = io.StringIO()
    has_diff_none = print_profile_diff(before, before, title="テスト差分", stream=buf_nodiff)
    assert has_diff_none is False
    assert "差分なし" in buf_nodiff.getvalue()
