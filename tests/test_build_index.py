"""SQLite 派生索引ビルダー (scripts/vault/build_index.py) の単体テスト."""

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.vault.build_index import build_index, connect, ensure_index, is_stale, search
from tests.test_vault_loader import (
    ARCHIVE,
    COMPANY,
    EMPLOYER,
    INTERVIEW,
    PIPELINE,
    RECRUITER,
    SCREENING,
    TECH_AREA,
    TECH_PROJECT,
)

# 圧縮済みの企業（archived-co）も紹介しているリクルーター
RECRUITER_WITH_ARCHIVED = RECRUITER.replace(
    "introduced_companies:\n", 'introduced_companies:\n  - company: "圧縮済み株式会社"\n    company_key: "archived-co"\n'
)

COMPANY_FULL = COMPANY.replace(
    'recruiter: "bizreach_yamada-taro"',
    'recruiter: "bizreach_yamada-taro"\n'
    'aliases:\n  - "Sample Inc."\n'
    'tags:\n  - "Go"\n  - "フルリモート"\n'
    "salary_min: 700\nsalary_max: 1000\n"
    'remote_type: "hybrid"\noffice_days_per_week: 1\n'
    'action_type: "scheduled"\nnext_action: "カジュアル面談"\nnext_due: "2026-10-25 10:00"',
)

TECH_PROJECT_FULL = (
    TECH_PROJECT.replace("areas:", 'tech_stack:\n  - "SQLite"\nareas:') + "FTS5 trigram で日本語の全文検索をしている。\n"
)

# 本音を含む internal のノートも索引には入れる
TECH_AREA_INTERNAL = TECH_AREA.replace("updated_at:", 'visibility: "internal"\nupdated_at:') + "埋め込みの評価が弱点。\n"

JOB = """---
id: job1
source: findy
company: 株式会社サンプル
title: バックエンドエンジニア（Go）
url: https://example.com/jobs/job1
fetched_at: '2026-10-16T13:46:16+09:00'
salary_min: 7000000
salary_max: 9500000
skills:
- Go
- AWS
remote_type: フルリモート
---

# バックエンドエンジニア（Go）

決済基盤の開発。
"""


class IndexFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = self.root / "data" / "vault_index.sqlite"
        self.write("vault/tracks/domestic/companies/sample/index.md", COMPANY_FULL)
        self.write("vault/tracks/domestic/companies/sample/2026-10-05_casual.md", INTERVIEW)
        self.write("vault/tracks/domestic/screening/2026-10-08_test.md", SCREENING)
        self.write("vault/tracks/domestic/pipeline.md", PIPELINE)
        self.write("vault/tracks/domestic/archive.md", ARCHIVE)
        self.write("vault/recruiters/bizreach_yamada-taro/index.md", RECRUITER_WITH_ARCHIVED)
        self.write("vault/profile/employers/prev.md", EMPLOYER)
        self.write("data/findy/jobs/job1.md", JOB)
        self.write("vault/profile/tech/projects/job-hunt.md", TECH_PROJECT_FULL)
        self.write("vault/profile/tech/areas/rag.md", TECH_AREA_INTERNAL)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def query(self, sql: str, *params):
        conn = connect(self.db)
        try:
            return [dict(r) for r in conn.execute(sql, params)]
        finally:
            conn.close()

    def search(self, q: str, **kwargs):
        conn = connect(self.db)
        try:
            return search(conn, q, **kwargs)
        finally:
            conn.close()


class TestBuildIndex(IndexFixture):
    def test_builds_all_tables(self):
        result = build_index(self.root, self.db)
        self.assertEqual(result.path, self.db)
        self.assertEqual(
            result.counts,
            {"companies": 1, "interviews": 1, "recruiters": 1, "screening_entries": 1, "archive_entries": 2,
             "jobs": 1, "issues": 0},
        )
        self.assertFalse(self.db.with_name(self.db.name + ".tmp").exists())

        (company,) = self.query("SELECT * FROM companies")
        self.assertEqual(company["status_label"], "カジュアル面談")
        self.assertEqual(company["status_category"], "active")
        self.assertEqual((company["salary_min"], company["salary_max"]), (700, 1000))
        self.assertEqual(company["next_due"], "2026-10-25 10:00")
        self.assertEqual(company["path"], "vault/tracks/domestic/companies/sample/index.md")
        self.assertEqual([r["tag"] for r in self.query("SELECT tag FROM company_tags")], ["Go", "フルリモート"])
        self.assertIn("サンプル", [r["normalized"] for r in self.query("SELECT normalized FROM company_aliases")])

        (interview,) = self.query("SELECT * FROM interviews")
        self.assertEqual((interview["company_id"], interview["stage_label"]), (company["id"], "カジュアル面談"))
        archived_intro, introduced = self.query("SELECT * FROM recruiter_companies ORDER BY rowid")
        self.assertEqual((introduced["company_id"], introduced["archive_id"]), (company["id"], None))

        (archived,) = self.query("SELECT * FROM archive_entries WHERE company_key = 'archived-co'")
        self.assertEqual((archived_intro["company_id"], archived_intro["archive_id"]), (None, archived["id"]))
        self.assertEqual((archived["status_label"], archived["reached_label"]), ("見送り・辞退", "カジュアル面談"))
        self.assertEqual((archived["considered_at"], archived["closed_at"]), ("2026-09-01", "2026-10-01"))
        self.assertEqual(archived["aliases"], "Archived Inc.")
        self.assertEqual([h.title for h in self.search("出社が週1", kinds=["archive"])], ["圧縮済み株式会社"])

    def test_jobs_are_converted_to_man_yen_and_linked(self):
        build_index(self.root, self.db)
        (job,) = self.query("SELECT * FROM jobs")
        self.assertEqual((job["salary_min"], job["salary_max"]), (700, 950))
        self.assertEqual((job["remote_type"], job["remote_text"]), ("full_remote", "フルリモート"))
        self.assertEqual(job["path"], "data/findy/jobs/job1.md")
        self.assertIsNotNone(job["company_id"])  # 「株式会社サンプル」→ 企業ログ sample
        self.assertEqual(sorted(r["skill"] for r in self.query("SELECT skill FROM job_skills")), ["AWS", "Go"])

    def test_without_data_dir_jobs_table_is_empty(self):
        (self.root / "data" / "findy" / "jobs" / "job1.md").unlink()
        result = build_index(self.root, self.db)
        self.assertEqual(result.counts["jobs"], 0)

    def test_schema_errors_go_to_issues_table(self):
        self.write(
            "vault/tracks/domestic/companies/broken/index.md",
            '---\ncompany: "壊れた株式会社"\ncompany_key: "broken"\nstatus: "interested"\n---\n',
        )
        result = build_index(self.root, self.db)
        self.assertEqual(result.counts["companies"], 1)
        issues = self.query("SELECT * FROM issues WHERE level = 'error'")
        self.assertTrue(any(i["path"].endswith("broken/index.md") for i in issues))


class TestSearch(IndexFixture):
    def setUp(self):
        super().setUp()
        build_index(self.root, self.db)

    def test_fts_match_for_three_or_more_chars(self):
        kinds = {h.kind for h in self.search("サンプル")}
        self.assertEqual(kinds, {"company", "interview", "recruiter", "job"})
        self.assertEqual([h.kind for h in self.search("サンプル", kinds=["company"])], ["company"])
        self.assertEqual([h.kind for h in self.search("決済基盤")], ["job"])

    def test_tech_notes_are_searchable(self):
        self.assertEqual([(h.kind, h.ref_id, h.track) for h in self.search("全文検索", kinds=["tech"])],
                         [("tech", "job-hunt", None)])
        self.assertEqual([h.title for h in self.search("SQLite", kinds=["tech"])], ["就活サポートリポジトリ"])
        self.assertEqual([h.path for h in self.search("埋め込み")], ["vault/profile/tech/areas/rag.md"])
        # 関連キー（領域 rag ⇔ プロジェクト job-hunt）でも引ける
        self.assertEqual({h.ref_id for h in self.search("job-hunt", kinds=["tech"])}, {"job-hunt", "rag"})

    def test_terms_are_anded(self):
        self.assertEqual([h.kind for h in self.search("決済基盤 バックエンド")], ["job"])
        self.assertEqual(self.search("決済基盤 存在しない語"), [])

    def test_short_terms_fall_back_to_like(self):
        hits = self.search("Go", kinds=["company", "job"])
        self.assertEqual({h.kind for h in hits}, {"company", "job"})
        self.assertEqual([h.kind for h in self.search("打ち")], ["screening"])
        self.assertEqual(self.search("%"), [])  # LIKE のワイルドカードはエスケープする

    def test_query_is_nfkc_normalized_and_case_insensitive(self):
        self.assertIn("company", {h.kind for h in self.search("ｓａｍｐｌｅ ｉｎｃ")})

    def test_empty_query(self):
        self.assertEqual(self.search("  "), [])


class TestEnsureIndex(IndexFixture):
    def built_at(self) -> str:
        return self.query("SELECT value FROM meta WHERE key = 'built_at'")[0]["value"]

    def test_rebuilds_only_when_sources_change(self):
        self.assertTrue(is_stale(self.root, self.db))
        ensure_index(self.root, self.db)
        self.assertFalse(is_stale(self.root, self.db))

        mtime = self.db.stat().st_mtime_ns
        ensure_index(self.root, self.db)
        self.assertEqual(self.db.stat().st_mtime_ns, mtime)

        path = self.root / "vault/tracks/domestic/companies/sample/index.md"
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
        self.assertTrue(is_stale(self.root, self.db))

        ensure_index(self.root, self.db)
        (self.root / "data/findy/jobs/job1.md").unlink()  # 削除も件数で検知する
        self.assertTrue(is_stale(self.root, self.db))

    def test_old_schema_version_is_stale(self):
        ensure_index(self.root, self.db)
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")
        conn.commit()
        conn.close()
        self.assertTrue(is_stale(self.root, self.db))


class TestCli(IndexFixture):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "vault" / "build_index.py"), "--root", str(self.root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=PROJECT_ROOT,
        )

    def test_stdout_is_db_path_or_hit_paths(self):
        built = self.run_cli()
        self.assertEqual(built.returncode, 0, built.stderr)
        self.assertEqual(Path(built.stdout.strip()).resolve(), self.db.resolve())

        found = self.run_cli("-q", "決済基盤")
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertEqual(
            [Path(p).resolve() for p in found.stdout.split()], [(self.root / "data/findy/jobs/job1.md").resolve()]
        )


if __name__ == "__main__":
    unittest.main()
