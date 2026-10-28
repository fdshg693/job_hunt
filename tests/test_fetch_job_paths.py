"""6媒体 fetch_job の取得・キャッシュ（サマリ表示）実行経路回帰テスト.

Playwright・ネットワーク・外部API呼び出しをスタブ化し、
各媒体の取得パイプラインおよび fetch 関数の以下の2経路を検証します:
1. 未取得時: データ取得 -> JobData変換 -> Markdown保存 -> サマリ出力
2. 取得済時: キャッシュ検出 -> スキップ -> サマリ出力（to_relative_path 呼び出し）

意図せぬ外部プロセスの起動を防ぐため、テスト実行中の subprocess.run は番兵 fixture で遮断します。
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from scripts.bizreach.fetch_job import (
    BIZREACH_JOB_CONFIG,
    fetch_and_save_bizreach_job,
)
from scripts.common.crawlers.job_pipeline import run_job_pipeline
from scripts.findy.fetch_job import (
    FINDY_JOB_CONFIG,
    fetch_and_save_job as fetch_and_save_findy_job,
)
from scripts.forkwell.fetch_job import (
    FORKWELL_JOB_CONFIG,
    fetch_and_save_forkwell_job,
)
from scripts.green.fetch_job import (
    GREEN_JOB_CONFIG,
    fetch_job as fetch_green_job,
)
from scripts.linkedin.fetch_job import (
    LINKEDIN_JOB_CONFIG,
    fetch_and_save_linkedin_job,
)
from scripts.openwork.fetch_job import (
    OPENWORK_JOB_CONFIG,
    fetch_and_save_openwork_job,
)
from scripts.herp.fetch_job import (
    HERP_JOB_CONFIG,
    fetch_and_save_herp_job,
)


@pytest.fixture(autouse=True)
def guard_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """テスト中の予期せぬ外部プロセス起動（playwright-cli等）を遮断する番兵 fixture."""

    def forbidden_subprocess_run(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(f"Unexpected subprocess.run call in test: args={args}, kwargs={kwargs}")

    monkeypatch.setattr("subprocess.run", forbidden_subprocess_run)
    monkeypatch.setattr(
        "scripts.common.browser_auth.run_playwright_cmd",
        lambda *args, **kwargs: {"success": True, "output": ""},
    )
    monkeypatch.setattr(
        "scripts.common.crawlers.job_pipeline.run_playwright_cmd",
        lambda *args, **kwargs: {"success": True, "output": ""},
    )
    monkeypatch.setattr(
        "scripts.common.auth_engine.ensure_site_authenticated",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "scripts.common.crawlers.job_pipeline.ensure_site_authenticated",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "scripts.common.browser_auth.update_profile_last_used",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "scripts.common.crawlers.job_pipeline.update_profile_last_used",
        lambda *args, **kwargs: None,
    )


def test_bizreach_pipeline_and_fetch_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bizreach: 未取得保存およびキャッシュ済サマリ出力の回帰テスト."""
    mock_data = {
        "success": True,
        "company": "テスト企業",
        "title": "バックエンドエンジニア",
        "salaryText": "800万円〜1200万円",
        "location": "東京都",
        "tags": ["Python"],
        "sections": {
            "仕事内容": {"fullText": "Pythonでの開発"},
        },
    }
    monkeypatch.setattr("scripts.bizreach.fetch_job.run_code_snippet", lambda *args, **kwargs: mock_data)
    monkeypatch.setattr("scripts.common.crawlers.job_pipeline.run_code_snippet", lambda *args, **kwargs: mock_data)

    target = "12345"

    # 1. 未取得 -> 取得して保存 (パイプライン)
    ret1 = run_job_pipeline(BIZREACH_JOB_CONFIG, argv=[target, "-o", str(tmp_path), "--summary"])
    assert ret1 == 0
    saved_file = tmp_path / f"{target}.md"
    assert saved_file.exists()

    # 2. 取得済み（キャッシュ）-> サマリ出力 (to_relative_path 回帰検証)
    ret2 = run_job_pipeline(BIZREACH_JOB_CONFIG, argv=[target, "-o", str(tmp_path), "--summary"])
    assert ret2 == 0

    # 3. 直接関数 fetch_and_save_bizreach_job のキャッシュ経路と新規経路
    out_direct, meta_direct = fetch_and_save_bizreach_job(target, output_dir=tmp_path, summary=True)
    assert out_direct == saved_file
    assert meta_direct.get("status") == "skipped"


def test_findy_pipeline_and_fetch_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Findy: 未取得保存およびキャッシュ済サマリ出力の回帰テスト (parse_job_from_html)."""
    mock_html = (
        "<html><head><title>Findy Job</title>"
        "<meta property='og:title' content='Python Lead Engineer'/>"
        "<meta property='og:description' content='Python開発のリード'/>"
        "</head><body><h1>Python Lead Engineer</h1></body></html>"
    )
    monkeypatch.setattr("scripts.findy.fetch_job.fetch_job_html", lambda *args, **kwargs: mock_html)

    target_url = "https://findy-code.io/companies/123/jobs/456"

    # 1. 未取得 -> 取得して保存
    ret1 = run_job_pipeline(FINDY_JOB_CONFIG, argv=[target_url, "-o", str(tmp_path), "--summary"])
    assert ret1 == 0
    saved_file = tmp_path / "456.md"
    assert saved_file.exists()

    # 2. 取得済み（キャッシュ）-> サマリ出力
    ret2 = run_job_pipeline(FINDY_JOB_CONFIG, argv=[target_url, "-o", str(tmp_path), "--summary"])
    assert ret2 == 0

    # 3. fetch_and_save_job 直接呼び出し
    saved_direct, meta_direct = fetch_and_save_findy_job(target_url, output_dir=tmp_path, summary=True)
    assert saved_direct == saved_file


def test_forkwell_pipeline_and_fetch_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Forkwell: 未取得保存およびキャッシュ済サマリ出力の回帰テスト."""
    mock_api = {
        "id": 35714,
        "title": "SRE Engineer",
        "company": {"name": "Forkwell Co", "user_name": "forkwellco"},
        "base_salaries": [{"min_value": 700, "max_value": 1100}],
        "prefecture_name": "東京都",
    }
    monkeypatch.setattr("scripts.forkwell.fetch_job.fetch_job_detail_api", lambda *args, **kwargs: mock_api)

    target = "35714"

    # 1. 未取得 -> 取得して保存
    ret1 = run_job_pipeline(FORKWELL_JOB_CONFIG, argv=[target, "-o", str(tmp_path), "--summary"])
    assert ret1 == 0
    saved_file = tmp_path / f"{target}.md"
    assert saved_file.exists()

    # 2. 取得済み（キャッシュ）-> サマリ出力
    ret2 = run_job_pipeline(FORKWELL_JOB_CONFIG, argv=[target, "-o", str(tmp_path), "--summary"])
    assert ret2 == 0

    # 3. fetch_and_save_forkwell_job 直接呼び出し
    out_direct, modified = fetch_and_save_forkwell_job(target, output_dir=tmp_path, summary=True)
    assert out_direct == saved_file
    assert modified is False


def test_green_pipeline_and_fetch_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Green: 未取得保存およびキャッシュ済サマリ出力の回帰テスト."""
    mock_data = {
        "client": {"name": "Green Test Co"},
        "jobOffer": {
            "title": "Backend Architect",
            "minSalary": 9000000,
            "maxSalary": 13000000,
        },
    }
    monkeypatch.setattr("scripts.green.fetch_job.run_fetch_job", lambda *args, **kwargs: mock_data)

    target = "196698"

    # 1. 未取得 -> 取得して保存
    ret1 = run_job_pipeline(GREEN_JOB_CONFIG, argv=[target, "-o", str(tmp_path), "--summary"])
    assert ret1 == 0
    saved_file = tmp_path / f"{target}.md"
    assert saved_file.exists()

    # 2. 取得済み（キャッシュ）-> サマリ出力
    ret2 = run_job_pipeline(GREEN_JOB_CONFIG, argv=[target, "-o", str(tmp_path), "--summary"])
    assert ret2 == 0

    # 3. fetch_job 直接呼び出し
    out_direct, modified, job_data = fetch_green_job(target, output_dir=tmp_path)
    assert out_direct == saved_file
    assert modified is False


def test_linkedin_pipeline_and_fetch_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """LinkedIn: 未取得保存およびキャッシュ済サマリ出力の回帰テスト."""
    mock_data = {
        "success": True,
        "title": "Staff Software Engineer",
        "company": "LinkedIn Test Co",
        "location": "Tokyo",
        "rawBody": "Staff Software Engineer requirements",
        "tags": ["Go", "Distributed Systems"],
    }
    monkeypatch.setattr("scripts.linkedin.fetch_job.run_code_snippet", lambda *args, **kwargs: mock_data)
    monkeypatch.setattr("scripts.common.crawlers.job_pipeline.run_code_snippet", lambda *args, **kwargs: mock_data)

    target = "4454473941"

    # 1. 未取得 -> 取得して保存
    ret1 = run_job_pipeline(LINKEDIN_JOB_CONFIG, argv=[target, "-o", str(tmp_path), "--summary"])
    assert ret1 == 0
    saved_file = tmp_path / f"{target}.md"
    assert saved_file.exists()

    # 2. 取得済み（キャッシュ）-> サマリ出力
    ret2 = run_job_pipeline(LINKEDIN_JOB_CONFIG, argv=[target, "-o", str(tmp_path), "--summary"])
    assert ret2 == 0

    # 3. fetch_and_save_job 直接呼び出し
    out_direct, is_new = fetch_and_save_linkedin_job(target, output_dir=tmp_path, summary=True)
    assert out_direct == saved_file
    assert is_new is False


def test_openwork_pipeline_and_fetch_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenWork: 未取得保存およびキャッシュ済サマリ出力の回帰テスト."""
    mock_html = (
        "<html><head><title>OpenWork Job</title></head>"
        "<body><h1>オープンワーク企業の「プラットフォームエンジニア」求人</h1>"
        "<dl><dt>社名</dt><dd>オープンワーク株式会社</dd>"
        "<dt>仕事内容</dt><dd>クラウド基盤構築</dd></dl></body></html>"
    )
    monkeypatch.setattr("scripts.openwork.fetch_job.fetch_html_via_http", lambda *args, **kwargs: (mock_html, 200))

    target = "https://www.openwork.jp/company_job.php?j=abc1234"

    # 1. 未取得 -> 取得して保存
    ret1 = run_job_pipeline(OPENWORK_JOB_CONFIG, argv=[target, "-o", str(tmp_path), "--summary"])
    assert ret1 == 0
    saved_file = tmp_path / "abc1234.md"
    assert saved_file.exists()

    # 2. 取得済み（キャッシュ）-> サマリ出力
    ret2 = run_job_pipeline(OPENWORK_JOB_CONFIG, argv=[target, "-o", str(tmp_path), "--summary"])
    assert ret2 == 0

    # 3. fetch_and_save_job 直接呼び出し
    out_direct, parsed = fetch_and_save_openwork_job(target, output_dir=tmp_path, summary=True)
    assert out_direct == saved_file
    assert parsed.get("status") == "skipped"


def test_herp_pipeline_and_fetch_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """HERP: 未取得保存およびキャッシュ済サマリ出力の回帰テスト."""
    mock_html = (
        "<html><head><title>HERP Job</title></head>"
        "<body>"
        "<h1 class=\"requisition-header__name\">プラットフォームエンジニア</h1>"
        "<section class=\"with-heading\">"
        "<h2>企業情報</h2>"
        "<div class=\"with-heading__content\">"
        "<table><tr><th>企業名</th><td>HERPテスト企業</td></tr></table>"
        "</div>"
        "</section>"
        "</body></html>"
    )
    monkeypatch.setattr("scripts.herp.fetch_job.fetch_job_html_via_http", lambda *args, **kwargs: mock_html)

    target = "https://herp.careers/v1/herptest/job999"

    # 1. 未取得 -> 取得して保存
    ret1 = run_job_pipeline(HERP_JOB_CONFIG, argv=[target, "-o", str(tmp_path), "--summary"])
    assert ret1 == 0
    saved_file = tmp_path / "herptest_job999.md"
    assert saved_file.exists()

    # 2. 取得済み（キャッシュ）-> サマリ出力
    ret2 = run_job_pipeline(HERP_JOB_CONFIG, argv=[target, "-o", str(tmp_path), "--summary"])
    assert ret2 == 0

    # 3. fetch_and_save_herp_job 直接呼び出し
    out_direct, meta_direct = fetch_and_save_herp_job(target, output_dir=tmp_path, summary=True)
    assert out_direct == saved_file
    assert meta_direct.get("status") == "skipped"
