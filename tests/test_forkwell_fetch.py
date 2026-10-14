"""Forkwell求人詳細取得機能の単体テスト."""

import unittest
from scripts.forkwell.fetch_job import (
    extract_job_id,
    parse_api_response_to_job_data,
    parse_job_posting_ld_json,
)


class TestForkwellFetch(unittest.TestCase):
    """Forkwell求人詳細のパース・モデル変換テスト."""

    def test_extract_job_id(self):
        self.assertEqual(extract_job_id("35714"), "35714")
        self.assertEqual(
            extract_job_id("https://jobs.forkwell.com/mil/jobs/35714"),
            "35714",
        )
        self.assertEqual(
            extract_job_id("/companies/test/jobs/12345"),
            "12345",
        )
        self.assertEqual(
            extract_job_id("https://jobs.forkwell.com/jobs/search?id=9999"),
            "9999",
        )

    def test_parse_api_response_to_job_data(self):
        sample_api_data = {
            "id": 99999,
            "title": "シニアPythonエンジニア",
            "company": {
                "name": "テスト株式会社",
                "user_name": "test-corp",
            },
            "base_salaries": [
                {"min_value": 700, "max_value": 1000}
            ],
            "primary_base_salary": {
                "min_value": 600,
                "max_value": 900,
            },
            "prefecture_name": "東京",
            "profession": {
                "name": "バックエンドエンジニア",
                "slug": "backend-engineer",
            },
            "job_tags": [
                {"name": "フルリモート可"},
                {"name": "自社サービスを開発"},
            ],
            "selections": [
                {"name": "下限年収700万円以上"}
            ],
            "technology": {
                "practical_skilltags": {
                    "言語": [{"name": "python", "real_name": "Python"}]
                },
                "not_practical_skilltags": {
                    "データベース": [{"name": "postgresql", "real_name": "PostgreSQL"}]
                }
            },
            "service_and_product": "自社サービスの開発・運用を行います。",
            "required_experience_and_skills": "Python実務3年以上",
            "preferred_experience_and_skills": "AWS実務経験",
            "employment_types": ["正社員"],
            "working_condition": "フレックスタイム制（コアタイムなし）",
            "insurance": "各種社会保険完備。フルリモート勤務。",
            "job_environment_categories": [
                {
                    "name": "アジャイル実践状況",
                    "environments": [{"name": "デイリースクラムを実施"}]
                }
            ]
        }

        job = parse_api_response_to_job_data(sample_api_data)
        self.assertEqual(job.id, "99999")
        self.assertEqual(job.source, "forkwell")
        self.assertEqual(job.company, "テスト株式会社")
        self.assertEqual(job.title, "シニアPythonエンジニア")
        self.assertEqual(job.url, "https://jobs.forkwell.com/test-corp/jobs/99999")
        self.assertEqual(job.salary_min, 7000000)
        self.assertEqual(job.salary_max, 10000000)
        self.assertEqual(job.salary_text, "700万円〜1000万円")
        self.assertEqual(job.remote_type, "フルリモート")
        self.assertIn("Python", job.skills)
        self.assertIn("PostgreSQL", job.skills)
        self.assertIn("バックエンドエンジニア", job.job_roles)
        self.assertIn("フルリモート可", job.tags)
        self.assertIn("下限年収700万円以上", job.tags)
        self.assertIn("自社サービスの開発・運用", job.description)
        self.assertIn("Python実務3年以上", job.must_skills)
        self.assertIn("AWS実務経験", job.desired_skills)
        self.assertIn("デイリースクラムを実施", job.development_environment)
        self.assertIn("正社員", job.conditions)

    def test_parse_job_posting_ld_json(self):
        sample_html = """
        <html>
        <head>
        <script type="application/ld+json">
        {
          "@context": "http://schema.org/",
          "@type": "JobPosting",
          "title": "SREエンジニア",
          "hiringOrganization": {
            "@type": "Organization",
            "name": "フォールバック株式会社"
          },
          "jobLocation": {
            "@type": "Place",
            "address": {
              "addressRegion": "京都"
            }
          },
          "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "JPY",
            "value": {
              "minValue": 8000000,
              "maxValue": 12000000
            }
          },
          "jobLocationType": "TELECOMMUTE",
          "description": "<p>インフラ基盤の設計・運用。AWS, Kubernetes利用。</p>"
        }
        </script>
        </head>
        <body></body>
        </html>
        """
        job = parse_job_posting_ld_json(
            sample_html,
            job_id="11111",
            url="https://jobs.forkwell.com/fallback/jobs/11111",
        )
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job.id, "11111")
        self.assertEqual(job.company, "フォールバック株式会社")
        self.assertEqual(job.title, "SREエンジニア")
        self.assertEqual(job.salary_min, 8000000)
        self.assertEqual(job.salary_max, 12000000)
        self.assertEqual(job.remote_type, "フルリモート")
        self.assertIn("AWS", job.skills)
        self.assertIn("Kubernetes", job.skills)


if __name__ == "__main__":
    unittest.main()
