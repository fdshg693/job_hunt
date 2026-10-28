"""主要求人サイト（Bizreach, Green, OpenWork, Forkwell, Levtech Direct）のパーサー単体テスト.

モックフィクスチャ（tests/fixtures/）を用いて、ネットワーク・ブラウザ起動なしで
オフラインかつ高速に各サイトのパース・データ変換ロジックを検証します。
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

from bs4 import BeautifulSoup

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.bizreach.fetch_job import build_job_data as build_bizreach_job_data
from scripts.common.models.message import MessageBatch
from scripts.forkwell.navigate_messages import (
    _format_summary_item as format_forkwell_summary_item,
)
from scripts.forkwell.navigate_messages import (
    _markdown_detail_item as markdown_forkwell_detail_item,
)
from scripts.forkwell.navigate_messages import (
    _markdown_table_row as markdown_forkwell_table_row,
)
from scripts.forkwell.navigate_messages import (
    generate_markdown as generate_forkwell_markdown,
)
from scripts.green.fetch_job import (
    build_job_data as build_green_job_data,
)
from scripts.green.fetch_job import (
    parse_qualification as parse_green_qualification,
)
from scripts.levtech_direct.search_jobs import parse_search_results as parse_levtech_search_results
from scripts.openwork.fetch_job import (
    build_openwork_job_data,
)
from scripts.openwork.fetch_job import (
    parse_job_detail_html as parse_openwork_job_detail,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class TestBizreachParser(unittest.TestCase):
    """ビズリーチ求人詳細パーサーのテスト."""

    def setUp(self) -> None:
        self.fixture_path = FIXTURES_DIR / "bizreach" / "job_detail_sample.json"
        self.assertTrue(self.fixture_path.exists(), f"Fixture not found: {self.fixture_path}")
        self.raw_data = json.loads(self.fixture_path.read_text(encoding="utf-8"))

    def test_build_job_data_success(self) -> None:
        now = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
        job_id = "br_job_12345"
        job_url = "https://www.bizreach.jp/jobs/br_job_12345/"

        job_data = build_bizreach_job_data(
            raw_data=self.raw_data,
            job_id=job_id,
            job_url=job_url,
            now=now,
        )

        # 基本プロパティ
        self.assertEqual(job_data.id, job_id)
        self.assertEqual(job_data.url, job_url)
        self.assertEqual(job_data.title, "シニアバックエンドエンジニア（Go / Python）")
        self.assertEqual(job_data.company, "Acme テクノロジー株式会社")
        self.assertEqual(job_data.company_url, "https://www.bizreach.jp/companies/12345/")

        # 給与パース
        self.assertEqual(job_data.salary_min, 8000000)
        self.assertEqual(job_data.salary_max, 12000000)
        self.assertIn("800万円〜1,200万円", job_data.salary_text)

        # リモート判定・スキル抽出
        self.assertIn(job_data.remote_type, ["リモート可", "フルリモート", "ハイブリッド"])
        self.assertIn("Go", job_data.skills)
        self.assertIn("Python", job_data.skills)

        # Markdown 生成の検証
        md = job_data.to_markdown()
        self.assertIn("## 概要・仕事内容", md)
        self.assertIn("マイクロサービスの設計・運用", md)
        self.assertIn("## 必須要件 (Must)", md)
        self.assertIn("## 歓迎要件 (Desired)", md)
        self.assertIn("GoまたはPythonによるWebバックエンド開発実務経験3年以上", md)


class TestGreenParser(unittest.TestCase):
    """Green 求人詳細パーサーのテスト."""

    def setUp(self) -> None:
        self.fixture_path = FIXTURES_DIR / "green" / "job_detail_sample.html"
        self.assertTrue(self.fixture_path.exists(), f"Fixture not found: {self.fixture_path}")
        html_content = self.fixture_path.read_text(encoding="utf-8")

        soup = BeautifulSoup(html_content, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        self.assertIsNotNone(script, "Green fixture missing __NEXT_DATA__")
        next_data = json.loads(script.string or "")
        page_props = next_data["props"]["pageProps"]
        self.raw_data = {
            "jobOffer": page_props["jobOffer"],
            "client": page_props["client"],
        }

    def test_parse_qualification(self) -> None:
        text = "【必須要件】\n・実務経験3年以上\n【歓迎要件】\n・AWS構築経験"
        must, desired = parse_green_qualification(text)
        self.assertIn("実務経験3年以上", must)
        self.assertIn("AWS構築経験", desired)

    def test_build_job_data_success(self) -> None:
        job_id = "196698"
        job_url = "https://www.green-japan.com/job/196698"

        job_data = build_green_job_data(
            raw_data=self.raw_data,
            job_id=job_id,
            job_url=job_url,
        )

        self.assertEqual(job_data.id, job_id)
        self.assertEqual(job_data.url, job_url)
        self.assertEqual(job_data.title, "フルスタックエンジニア（TypeScript / Python）")
        self.assertEqual(job_data.company, "Acme Corporation 株式会社")

        # 年収（750万円〜1100万円）
        self.assertEqual(job_data.salary_min, 750)
        self.assertEqual(job_data.salary_max, 1100)

        # スキル・タグ
        self.assertIn("TypeScript", job_data.skills)
        self.assertIn("Python", job_data.skills)
        self.assertIn("React", job_data.skills)

        # Markdown 生成の検証
        md = job_data.to_markdown()
        self.assertIn("事業概要・ビジョン", md)
        self.assertIn("自社SaaSプロダクトの開発", md)
        self.assertIn("開発環境・利用技術", md)


class TestOpenworkParser(unittest.TestCase):
    """OpenWork 求人詳細パーサーのテスト."""

    def setUp(self) -> None:
        self.fixture_path = FIXTURES_DIR / "openwork" / "job_detail_sample.html"
        self.assertTrue(self.fixture_path.exists(), f"Fixture not found: {self.fixture_path}")
        self.html_content = self.fixture_path.read_text(encoding="utf-8")

    def test_parse_job_detail_success(self) -> None:
        job_url = "https://www.openwork.jp/company_job/ow_98765"
        parsed = parse_openwork_job_detail(
            html_content=self.html_content,
            job_url=job_url,
        )

        self.assertEqual(parsed.get("id"), "ow_98765")
        self.assertEqual(parsed.get("title"), "クラウドアーキテクト（AWS / GCP / Kubernetes）")
        self.assertEqual(parsed.get("company"), "Acme Cloud Services 株式会社")
        self.assertEqual(parsed.get("company_url"), "https://example.com/acme-cloud")

        # 給与・勤務地
        self.assertIn("900万〜1,300万円", parsed.get("salary_text", ""))
        self.assertEqual(parsed.get("salary_min"), 9000000)
        self.assertEqual(parsed.get("salary_max"), 13000000)
        self.assertIn("東京都千代田区大手町", parsed.get("location", ""))

        # 仕事内容・要件
        self.assertIn("マルチクラウド基盤の設計・構築", parsed.get("description", ""))
        self.assertIn("Terraform", parsed.get("must_skills", ""))

        # 会社情報
        comp_info = parsed.get("company_info", {})
        self.assertEqual(comp_info.get("業界"), "IT・通信・クラウドサービス")
        self.assertEqual(comp_info.get("代表者"), "代表取締役 山田 太郎")

        # build_openwork_job_data による JobData モデル構築
        now = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
        job_data = build_openwork_job_data(parsed, now=now)
        self.assertEqual(job_data.id, "ow_98765")
        self.assertEqual(job_data.company, "Acme Cloud Services 株式会社")
        md = job_data.to_markdown()
        self.assertIn("## 概要・仕事内容", md)
        self.assertIn("## 必須要件 (Must)", md)


class TestForkwellParser(unittest.TestCase):
    """Forkwell メッセージ・スカウトパーサーのテスト."""

    def setUp(self) -> None:
        self.fixture_path = FIXTURES_DIR / "forkwell" / "message_list_sample.json"
        self.assertTrue(self.fixture_path.exists(), f"Fixture not found: {self.fixture_path}")
        self.raw_data = json.loads(self.fixture_path.read_text(encoding="utf-8"))

    def test_message_batch_validation(self) -> None:
        batch = MessageBatch.model_validate(self.raw_data)
        self.assertEqual(len(batch.messages), 2)

        msg1 = batch.messages[0]
        self.assertEqual(msg1.company, "Acme Digital Inc.")
        self.assertEqual(msg1.subject, "【特別スカウト】シニアバックエンドエンジニアのご提案")
        self.assertEqual(msg1.scout_type, "スカウト")
        self.assertEqual(msg1.deadline, "2026-10-31")
        self.assertEqual(msg1.job_title, "シニアバックエンドエンジニア")

        msg2 = batch.messages[1]
        self.assertEqual(msg2.company, "Beta Cloud Services 株式会社")
        self.assertEqual(msg2.scout_type, "話を聞いてみたい")

    def test_markdown_and_summary_formatting(self) -> None:
        batch = MessageBatch.model_validate(self.raw_data)
        now = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)

        # Markdown 生成
        md = generate_forkwell_markdown(batch, tab="active", now=now)
        self.assertIn("# Forkwell メッセージ・スカウト一覧", md)
        self.assertIn("Acme Digital Inc.", md)
        self.assertIn("Beta Cloud Services 株式会社", md)
        self.assertIn("シニアバックエンドエンジニア", md)

        # サマリフォーマッター
        summary_lines = format_forkwell_summary_item(batch.messages[0], 1)
        summary_text = "\n".join(summary_lines)
        self.assertIn("Acme Digital Inc.", summary_text)
        self.assertIn("提示年収: 850万円〜1,200万円", summary_text)

        # テーブル行
        table_row = markdown_forkwell_table_row(batch.messages[0], 1)
        self.assertIn("Acme Digital Inc.", table_row)

        # 詳細セクション
        detail_lines = markdown_forkwell_detail_item(batch.messages[0], 1)
        detail_text = "\n".join(detail_lines)
        self.assertIn("【特別スカウト】シニアバックエンドエンジニアのご提案", detail_text)
        self.assertIn("2026-10-31", detail_text)


class TestLevtechDirectParser(unittest.TestCase):
    """Levtech Direct 検索結果パーサーのテスト."""

    def setUp(self) -> None:
        self.fixture_path = FIXTURES_DIR / "levtech_direct" / "search_results_sample.json"
        self.assertTrue(self.fixture_path.exists(), f"Fixture not found: {self.fixture_path}")
        self.next_data_json = self.fixture_path.read_text(encoding="utf-8")
        # Next.js の script タグを含む HTML を組み立て
        self.mock_html = (
            '<!DOCTYPE html><html><head>'
            f'<script id="__NEXT_DATA__" type="application/json">{self.next_data_json}</script>'
            '</head><body></body></html>'
        )

    def test_parse_search_results_success(self) -> None:
        jobs, total_count = parse_levtech_search_results(self.mock_html)

        self.assertEqual(total_count, 150)
        self.assertEqual(len(jobs), 2)

        job1 = jobs[0]
        self.assertEqual(job1["id"], "10001")
        self.assertEqual(job1["title"], "バックエンドエンジニア（Python / Django / AWS）")
        self.assertEqual(job1["company"], "Acme Innovations 株式会社")
        self.assertEqual(job1["salary_min"], 7000000)
        self.assertEqual(job1["salary_max"], 10000000)
        self.assertIn("Python", job1["skills"])
        self.assertIn("Django", job1["skills"])
        self.assertIn("AWS", job1["skills"])
        self.assertIn("自社サービス開発", job1["tags"])

        job2 = jobs[1]
        self.assertEqual(job2["id"], "10002")
        self.assertEqual(job2["title"], "リードデータエンジニア（GCP / BigQuery）")
        self.assertEqual(job2["company"], "Global Data Systems 合同会社")
        self.assertEqual(job2["salary_min"], 9000000)
        self.assertEqual(job2["salary_max"], 14000000)
        self.assertIn("BigQuery", job2["skills"])


if __name__ == "__main__":
    unittest.main()
