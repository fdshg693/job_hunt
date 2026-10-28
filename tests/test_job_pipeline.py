"""求人共通パイプライン (job_pipeline) および JobPosting 連携の単体テスト."""

from __future__ import annotations

import io
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.bizreach.fetch_job import BIZREACH_JOB_CONFIG
from scripts.common.crawlers.job_pipeline import (
    JobCrawlerConfig,
    JobPipelineContext,
    build_job_parser,
    run_job_pipeline,
)
from scripts.common.models.job import JobPosting
from scripts.common.storage import JobData, save_job_markdown
from scripts.findy.fetch_job import FINDY_JOB_CONFIG
from scripts.forkwell.fetch_job import FORKWELL_JOB_CONFIG
from scripts.green.fetch_job import GREEN_JOB_CONFIG
from scripts.linkedin.fetch_job import LINKEDIN_JOB_CONFIG
from scripts.openwork.fetch_job import OPENWORK_JOB_CONFIG


class TestJobPipelineAndStorage(unittest.TestCase):
    """JobPosting モデル、storage.py 拡張、job_pipeline のテスト."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_job_posting_save_markdown(self) -> None:
        """JobPosting インスタンスを save_job_markdown で直接保存できることを確認."""
        posting = JobPosting(
            id="test-job-001",
            source="test_source",
            company="テスト株式会社",
            title="シニアエンジニア",
            url="https://example.com/jobs/001",
            salary_min=8000000,
            salary_max=12000000,
            salary_text="800万〜1200万円",
            skills=["Python", "FastAPI", "TypeScript"],
            job_roles=["バックエンドエンジニア"],
            location="東京都千代田区",
            remote_type="フルリモート",
            tags=["急募", "自社プロダクト"],
            description="サービスのバックエンド開発を担当します。",
            must_skills="Python 3年以上の実務経験",
        )

        saved_path, is_saved = save_job_markdown(posting, output_dir=self.output_dir)
        self.assertTrue(is_saved)
        self.assertTrue(saved_path.exists())
        self.assertEqual(saved_path.name, "test-job-001.md")

        content = saved_path.read_text(encoding="utf-8")
        self.assertIn("company: テスト株式会社", content)
        self.assertIn("title: シニアエンジニア", content)
        self.assertIn("Python 3年以上の実務経験", content)
        self.assertIn("remote_type: フルリモート", content)

    def test_pipeline_cache_skip(self) -> None:
        """既存ファイルが存在し --force がない場合、取得がスキップされることを確認."""
        existing_file = self.output_dir / "job123.md"
        existing_file.write_text("existing content", encoding="utf-8")

        mock_fetch = MagicMock()
        config = JobCrawlerConfig(
            site_id="test",
            site_name="テストサイト",
            default_output_dir=self.output_dir,
            extract_job_id_fn=lambda t: t,
            custom_fetch_fn=mock_fetch,
        )

        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            ret = run_job_pipeline(
                config,
                argv=["job123", "-o", str(self.output_dir)],
            )

        self.assertEqual(ret, 0)
        # 既存があるため custom_fetch_fn は呼ばれないはず
        mock_fetch.assert_not_called()
        self.assertIn("job123.md", stdout_buf.getvalue())

    def test_pipeline_normal_fetch_and_save(self) -> None:
        """custom_fetch_fn で取得した JobPosting が保存され、stdout にパスが出力されることを確認."""
        def dummy_fetch(ctx: JobPipelineContext) -> JobPosting:
            return JobPosting(
                id=ctx.job_id,
                source=ctx.config.site_id,
                company="新規企業",
                title="AIリサーチャー",
                url=ctx.target_url,
                salary_text="1000万円〜",
            )

        config = JobCrawlerConfig(
            site_id="test",
            site_name="テストサイト",
            default_output_dir=self.output_dir,
            extract_job_id_fn=lambda t: f"id_{t}",
            normalize_url_fn=lambda t: f"https://example.com/job/{t}",
            custom_fetch_fn=dummy_fetch,
        )

        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            ret = run_job_pipeline(
                config,
                argv=["999", "-o", str(self.output_dir)],
            )

        self.assertEqual(ret, 0)
        expected_path = self.output_dir / "id_999.md"
        self.assertTrue(expected_path.exists())
        self.assertIn("id_999.md", stdout_buf.getvalue())

    def test_pipeline_dry_run(self) -> None:
        """--dry-run の場合、ファイルが書き込まれないことを確認."""
        def dummy_fetch(ctx: JobPipelineContext) -> JobPosting:
            return JobPosting(
                id=ctx.job_id,
                source=ctx.config.site_id,
                company="DryRun企業",
                title="リードエンジニア",
                url=ctx.target_url,
            )

        config = JobCrawlerConfig(
            site_id="test",
            site_name="テストサイト",
            default_output_dir=self.output_dir,
            extract_job_id_fn=lambda t: t,
            custom_fetch_fn=dummy_fetch,
        )

        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            ret = run_job_pipeline(
                config,
                argv=["dry001", "-o", str(self.output_dir), "--dry-run"],
            )

        self.assertEqual(ret, 0)
        expected_path = self.output_dir / "dry001.md"
        self.assertFalse(expected_path.exists())

    def test_all_site_configs(self) -> None:
        """全6サイトの JobCrawlerConfig が適切に定義されていることを確認."""
        configs = [
            (BIZREACH_JOB_CONFIG, "bizreach", "https://www.bizreach.jp/jobs/12345/"),
            (GREEN_JOB_CONFIG, "green", "196698"),
            (FORKWELL_JOB_CONFIG, "forkwell", "35714"),
            (OPENWORK_JOB_CONFIG, "openwork", "https://www.openwork.jp/company_job.php?j=abc1234"),
            (FINDY_JOB_CONFIG, "findy", "https://findy-code.io/companies/123/jobs/456"),
            (LINKEDIN_JOB_CONFIG, "linkedin", "https://www.linkedin.com/jobs/view/4454473941/"),
        ]

        for cfg, expected_site_id, sample_target in configs:
            self.assertEqual(cfg.site_id, expected_site_id)
            self.assertTrue(bool(cfg.site_name))
            self.assertIsNotNone(cfg.default_output_dir)
            self.assertIsNotNone(cfg.extract_job_id_fn)

            # extract_job_id_fn が例外を起こさず動作することを確認
            job_id = cfg.extract_job_id_fn(sample_target)
            self.assertTrue(len(job_id) > 0)


if __name__ == "__main__":
    unittest.main()
