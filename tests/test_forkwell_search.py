"""Forkwell求人検索機能の単体テスト."""

import unittest
from bs4 import BeautifulSoup

from scripts.forkwell.search_jobs import (
    build_search_url,
    extract_total_count,
    parse_job_cards,
)


class TestForkwellSearch(unittest.TestCase):
    """Forkwell求人検索のロジックテスト."""

    def test_build_search_url_default(self):
        url = build_search_url()
        self.assertIn("https://jobs.forkwell.com/jobs/search", url)
        self.assertIn("job_popularity_popularity+desc", url)

    def test_build_search_url_with_params(self):
        url = build_search_url(
            keyword="Python",
            page=2,
            min_salary_man=800,
            sort="published_at desc",
        )
        self.assertIn("q%5Bfreeword%5D=Python", url)
        # サイト固有仕様: salaly 表記
        self.assertIn("q%5Byearly_base_salaly_min_value%5D=800", url)
        self.assertIn("page=2", url)
        self.assertIn("q%5Bsort%5D=published_at+desc", url)

    def test_extract_total_count(self):
        html = """
        <div class="float-start">
            <span class="text-jumped-largest text-gray-dark">123</span>
            <span>件</span>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        count = extract_total_count(soup)
        self.assertEqual(count, 123)

    def test_extract_total_count_zero(self):
        html = """
        <div class="empty-state">
            <p>条件に一致する求人はありません</p>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        count = extract_total_count(soup)
        self.assertEqual(count, 0)

    def test_parse_job_cards(self):
        sample_html = """
        <div class="job-list">
            <div class="card">
                <div class="card-body">
                    <a class="job-list__link" href="/sample-corp/jobs/99999">
                        <span>シニアPythonエンジニア</span>
                    </a>
                    <div class="avatar__detail">サンプル株式会社</div>
                    <ul class="list-inline">
                        <li class="list-inline-item">
                            <i class="fas fa-user"></i>バックエンドエンジニア
                        </li>
                        <li class="list-inline-item">
                            <i class="fas fa-map-marker-alt"></i>東京
                        </li>
                        <li class="list-inline-item">
                            <span>年収</span><strong>800</strong><span>万円</span><span>〜</span><strong>1200</strong><span>万円</span>
                        </li>
                    </ul>
                    <div class="feature-table__desc">
                        <ul class="list-inline">
                            <li class="list-inline-item">フルリモート可</li>
                        </ul>
                    </div>
                    <ul class="list-inline">
                        <li><a class="tag" href="/t/python">python</a></li>
                        <li><a class="tag" href="/t/aws">aws</a></li>
                    </ul>
                </div>
            </div>
        </div>
        """
        jobs = parse_job_cards(sample_html)
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job["id"], "99999")
        self.assertEqual(job["title"], "シニアPythonエンジニア")
        self.assertEqual(job["company"], "サンプル株式会社")
        self.assertEqual(job["url"], "https://jobs.forkwell.com/sample-corp/jobs/99999")
        self.assertEqual(job["location"], "東京")
        self.assertEqual(job["remote_type"], "フルリモート")
        self.assertEqual(job["salary_min"], 8000000)
        self.assertEqual(job["salary_max"], 12000000)
        self.assertIn("Python", job["skills"])
        self.assertIn("AWS", job["skills"])


if __name__ == "__main__":
    unittest.main()
