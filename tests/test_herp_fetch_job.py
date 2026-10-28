"""HERP求人取得スクリプト (scripts/herp/fetch_job.py) の単体テスト."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from typing import Any
import urllib.error

import pytest

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.crawlers.job_pipeline import run_job_pipeline
from scripts.herp.fetch_job import (
    HERP_JOB_CONFIG,
    extract_job_id,
    fetch_and_save_herp_job,
    normalize_url,
    parse_herp_job_data,
    parse_herp_target,
)

FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "herp"
SAMPLE_HTML_PATH = FIXTURES_DIR / "sample_job.html"


def test_extract_job_id() -> None:
    """新旧URL形式・ID直指定からのjob_id抽出テスト."""
    # 新形式
    assert extract_job_id("https://herp.careers/v1/sample/job123") == "sample_job123"
    assert extract_job_id("https://herp.careers/v1/sample/job123/") == "sample_job123"
    assert extract_job_id("https://herp.careers/v1/sample/job123?utm_source=test#sec") == "sample_job123"

    # 旧形式
    assert extract_job_id("https://herp.careers/careers/companies/sample/jobs/job123") == "sample_job123"
    assert extract_job_id("https://herp.careers/careers/companies/sample/jobs/job123/") == "sample_job123"

    # ID直指定
    assert extract_job_id("sample_job123") == "sample_job123"
    assert extract_job_id("sample/job123") == "sample_job123"

    # 大文字小文字・ハイフン・アンダースコア維持
    assert extract_job_id("https://herp.careers/v1/finatext/p9U6eu0-JgVR") == "finatext_p9U6eu0-JgVR"

    # 不正形式
    with pytest.raises(ValueError):
        extract_job_id("https://example.com/jobs/123")

    with pytest.raises(ValueError):
        extract_job_id("invalid-target")


def test_normalize_url() -> None:
    """新旧形式いずれからも新形式URLに正規化されることのテスト."""
    expected = "https://herp.careers/v1/sample/job123"
    assert normalize_url("https://herp.careers/v1/sample/job123") == expected
    assert normalize_url("https://herp.careers/careers/companies/sample/jobs/job123") == expected
    assert normalize_url("https://herp.careers/v1/sample/job123?utm=1") == expected
    assert normalize_url("sample_job123") == expected
    assert normalize_url("sample/job123") == expected


def test_parse_herp_html() -> None:
    """ダミーHTMLフィクスチャを用いたHTMLパース・フィールド抽出テスト."""
    assert SAMPLE_HTML_PATH.exists(), f"フィクスチャが見つかりません: {SAMPLE_HTML_PATH}"
    html_content = SAMPLE_HTML_PATH.read_text(encoding="utf-8")

    now = datetime(2026, 1, 16, 12, 0, 0)
    job = parse_herp_job_data(
        html_content,
        target_url="https://herp.careers/v1/sample/job123",
        job_id="sample_job123",
        now=now,
    )

    assert job.id == "sample_job123"
    assert job.source == "herp"
    assert job.title == "ソフトウェアエンジニア"
    assert job.company == "株式会社テストテクノロジーズ"
    assert job.url == "https://herp.careers/v1/sample/job123"
    assert job.salary_min == 8000000
    assert job.salary_max == 14000000
    assert "年収800万円～1400万円" in job.salary_text
    assert "東京都千代田区1-1-1" in job.location
    assert job.remote_type == "フルリモート"
    assert job.company_url == "https://example.com"

    # スキル抽出確認
    assert "Python" in job.skills or "Go" in job.skills or "AWS" in job.skills

    # 本文見出し体系確認
    assert "# ソフトウェアエンジニア" in job.raw_body
    assert "> 【CTO直下】最先端技術で社会を革新するバックエンド基盤開発" in job.raw_body
    assert "## 概要・仕事内容" in job.raw_body
    assert "## 必須要件 (Must)" in job.raw_body
    assert "## 歓迎要件 (Desired)" in job.raw_body
    assert "## 求める人物像" in job.raw_body
    assert "## 勤務地・就業条件・福利厚生" in job.raw_body
    assert "## 採用企業情報" in job.raw_body

    # extra_metadata
    assert job.extra_metadata.get("company_slug") == "sample"
    assert job.extra_metadata.get("herp_job_id") == "job123"
    assert "CTO直下" in job.extra_metadata.get("catchcopy", "")
    assert job.extra_metadata.get("date_posted") == "2026-01-15"


def test_herp_pipeline_and_fetch_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """HERP: 未取得保存およびキャッシュ済サマリ出力の回帰テスト."""
    html_content = SAMPLE_HTML_PATH.read_text(encoding="utf-8")
    monkeypatch.setattr("scripts.herp.fetch_job.fetch_job_html_via_http", lambda *args, **kwargs: html_content)

    target = "https://herp.careers/v1/sample/job123"

    # 1. 未取得 -> 取得して保存 (パイプライン)
    ret1 = run_job_pipeline(HERP_JOB_CONFIG, argv=[target, "-o", str(tmp_path), "--summary"])
    assert ret1 == 0
    saved_file = tmp_path / "sample_job123.md"
    assert saved_file.exists()

    # 2. 取得済み（キャッシュ）-> サマリ出力
    ret2 = run_job_pipeline(HERP_JOB_CONFIG, argv=[target, "-o", str(tmp_path), "--summary"])
    assert ret2 == 0

    # 3. fetch_and_save_herp_job 直接呼び出し
    saved_direct, meta_direct = fetch_and_save_herp_job(target, output_dir=tmp_path, summary=True)
    assert saved_direct == saved_file
    assert meta_direct.get("status") == "skipped"


def test_404_error_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    """404エラー発生時のハンドリングテスト."""
    def mock_fetch_404(*args: Any, **kwargs: Any) -> str:
        raise urllib.error.HTTPError("https://herp.careers/v1/sample/job123", 404, "Not Found", {}, None)  # type: ignore

    monkeypatch.setattr("scripts.herp.fetch_job.fetch_job_html_via_http", mock_fetch_404)

    target = "https://herp.careers/v1/sample/job123"
    with pytest.raises(SystemExit) as excinfo:
        run_job_pipeline(HERP_JOB_CONFIG, argv=[target])
    assert excinfo.value.code == 1
