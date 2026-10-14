"""共通基盤 (Step 1) の単体テスト・検証スクリプト."""

import io
import sys
import tempfile
import unittest
from pathlib import Path

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import (
    EntrypointContext,
    create_base_parser,
    create_search_parser,
    to_relative_path,
)
from scripts.common.normalizers import (
    KNOWN_SKILL_KEYWORDS,
    detect_remote_type,
    extract_skills_from_text,
    format_salary_display,
    format_salary_text,
    normalize_url,
    parse_salary_arg,
    parse_salary_range,
)
from scripts.common.storage import (
    JobData,
    save_job_markdown,
    save_search_result,
)
from scripts.common.browser_auth import (
    random_sleep,
    run_code_snippet,
)


class TestCli(unittest.TestCase):
    def test_to_relative_path(self):
        sample = PROJECT_ROOT / "data" / "findy" / "jobs" / "sample.md"
        rel = to_relative_path(sample)
        self.assertEqual(rel, "data/findy/jobs/sample.md")

    def test_entrypoint_context_default(self):
        ctx = EntrypointContext(summary=False, json_mode=False)
        ctx.add_result_path(PROJECT_ROOT / "data" / "test.md")
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        old_stdout, old_stderr = sys.stdout, sys.stderr
        try:
            sys.stdout, sys.stderr = captured_stdout, captured_stderr
            ctx.log("logging to stderr")
            code = ctx.flush_outputs()
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

        self.assertEqual(code, 0)
        self.assertEqual(captured_stdout.getvalue().strip(), "data/test.md")
        self.assertIn("logging to stderr", captured_stderr.getvalue())

    def test_entrypoint_context_summary(self):
        ctx = EntrypointContext(summary=True, json_mode=False)
        called = []
        captured = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = captured
            ctx.flush_outputs(summary_fn=lambda: called.append(True))
        finally:
            sys.stdout = old_stdout

        self.assertTrue(called)

    def test_entrypoint_context_json(self):
        ctx = EntrypointContext(summary=False, json_mode=True)
        ctx.add_result_path(PROJECT_ROOT / "data" / "test.md")
        captured = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = captured
            ctx.flush_outputs()
        finally:
            sys.stdout = old_stdout

        self.assertIn('"paths": [', captured.getvalue())
        self.assertIn('"data/test.md"', captured.getvalue())

    def test_parsers(self):
        base_parser = create_base_parser("Test description", default_limit=10)
        base_args = base_parser.parse_args(["-s", "--limit", "5"])
        self.assertTrue(base_args.summary)
        self.assertEqual(base_args.limit, 5)

        search_parser = create_search_parser("Search description")
        s_args = search_parser.parse_args([
            "python", "engineer",
            "-c", "Google",
            "--skill", "Python",
            "--min-salary", "800",
            "-d",
        ])
        self.assertEqual(s_args.query, ["python", "engineer"])
        self.assertEqual(s_args.company, "Google")
        self.assertEqual(s_args.skills, ["Python"])
        self.assertEqual(s_args.min_salary, "800")
        self.assertTrue(s_args.download)


class TestNormalizers(unittest.TestCase):
    def test_parse_salary_range(self):
        self.assertEqual(parse_salary_range("800万円〜1500万円"), (8000000, 15000000))
        self.assertEqual(parse_salary_range("800万 ～ 2200万円"), (8000000, 22000000))
        self.assertEqual(parse_salary_range("800万円以上"), (8000000, None))
        self.assertEqual(parse_salary_range("〜1200万円"), (None, 12000000))
        self.assertEqual(parse_salary_range("1000万円"), (10000000, 10000000))
        self.assertEqual(parse_salary_range("6000000円〜9000000円"), (6000000, 9000000))
        self.assertEqual(parse_salary_range(""), (None, None))
        self.assertEqual(parse_salary_range(None), (None, None))

    def test_parse_salary_arg(self):
        self.assertEqual(parse_salary_arg("800"), 8000000)
        self.assertEqual(parse_salary_arg("800万"), 8000000)
        self.assertEqual(parse_salary_arg("8000000"), 8000000)
        self.assertIsNone(parse_salary_arg(None))
        self.assertIsNone(parse_salary_arg(""))

    def test_detect_remote_type(self):
        self.assertEqual(detect_remote_type("東京", "フルリモート勤務可能です"), "フルリモート")
        self.assertEqual(detect_remote_type("東京", "週2日リモート、ハイブリッドワーク"), "ハイブリッド")
        self.assertEqual(detect_remote_type("東京", "出社のみ。リモート不可"), "出社")
        self.assertEqual(detect_remote_type("東京", "オフィス勤務"), "出社")

    def test_extract_skills_from_text(self):
        text = "バックエンド開発（Python, Go, Docker, AWS）およびフロントエンド（Next.js / TypeScript）"
        skills = extract_skills_from_text(text)
        self.assertIn("Python", skills)
        self.assertIn("Go", skills)
        self.assertIn("Docker", skills)
        self.assertIn("AWS", skills)
        self.assertIn("Next.js", skills)
        self.assertIn("TypeScript", skills)
        # 単語境界のテスト: 'Go' は 'Google' に反応しないこと
        text2 = "Google Search Console の利用経験"
        skills2 = extract_skills_from_text(text2)
        self.assertNotIn("Go", skills2)

    def test_format_salary(self):
        self.assertEqual(format_salary_text(6000000, 9000000), "600万円〜900万円")
        self.assertEqual(format_salary_display(6000000, 9000000), "600万〜900万円")
        self.assertEqual(format_salary_display(salary_text="応相談"), "応相談")
        self.assertEqual(format_salary_display(), "非公開/未設定")

    def test_normalize_url(self):
        raw = "https://example.com/job/123?utm_source=twitter&utm_medium=cpc&id=999"
        clean = normalize_url(raw)
        self.assertEqual(clean, "https://example.com/job/123?id=999")
        rel = "/job/456"
        abs_url = normalize_url(rel, base_url="https://example.com")
        self.assertEqual(abs_url, "https://example.com/job/456")


class TestStorage(unittest.TestCase):
    def test_save_job_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            job = JobData(
                id="test-job-001",
                source="bizreach",
                company="テスト株式会社",
                title="シニアソフトウェアエンジニア",
                url="https://example.com/test-001",
                salary_min=8000000,
                salary_max=12000000,
                salary_text="800万〜1200万円",
                skills=["Python", "AWS"],
                remote_type="フルリモート",
                description="新機能の開発を行います。",
                must_skills="Python実務経験3年以上",
            )
            saved_path, created = save_job_markdown(job, output_dir=tmp_path)
            self.assertTrue(created)
            self.assertTrue(saved_path.exists())

            # 既存スキップ
            _, created2 = save_job_markdown(job, output_dir=tmp_path, force=False)
            self.assertFalse(created2)

            # 強制上書き
            _, created3 = save_job_markdown(job, output_dir=tmp_path, force=True)
            self.assertTrue(created3)

            # 保存された内容の検証
            content = saved_path.read_text(encoding="utf-8")
            self.assertIn("id: test-job-001", content)
            self.assertIn("source: bizreach", content)
            self.assertIn("salary_min: 8000000", content)
            self.assertIn("salary_max: 12000000", content)
            self.assertIn("## 概要・仕事内容", content)
            self.assertIn("新機能の開発を行います。", content)
            self.assertIn("## 必須要件 (Must)", content)

    def test_save_search_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            jobs = [
                {
                    "company": "会社A",
                    "title": "エンジニア",
                    "salary_text": "700万〜900万円",
                    "remote_type": "ハイブリッド",
                    "url": "https://example.com/1",
                }
            ]
            md_path, json_path = save_search_result(
                source="findy",
                keyword="Python",
                jobs=jobs,
                total_count=1,
                output_dir=tmp_path,
            )
            self.assertTrue(md_path.exists())
            self.assertTrue(json_path.exists())
            md_content = md_path.read_text(encoding="utf-8")
            self.assertIn("type: searches", md_content)
            self.assertIn("| 会社A | エンジニア |", md_content)


if __name__ == "__main__":
    unittest.main()
