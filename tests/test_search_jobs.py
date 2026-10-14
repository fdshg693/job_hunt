import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.common.search_jobs import (
    JobItem,
    filter_jobs,
    load_all_jobs,
    parse_salary_arg,
    sort_jobs,
)


def test_parse_salary_arg():
    assert parse_salary_arg(None) is None
    assert parse_salary_arg("700") == 7000000
    assert parse_salary_arg("700万") == 7000000
    assert parse_salary_arg("700万円") == 7000000
    assert parse_salary_arg("7,000,000") == 7000000
    assert parse_salary_arg("8500000") == 8500000


def test_job_item_from_file_and_filter():
    content = """---
id: job_001
source: findy
company: 株式会社テスト
title: フルスタックエンジニア
url: https://example.com/jobs/1
fetched_at: '2026-09-14T10:00:00+09:00'
salary_min: 5000000
salary_max: 8000000
salary_text: 500万円〜800万円
skills:
  - Python
  - React
  - Docker
job_roles:
  - フルスタックエンジニア
location: 東京都
remote_type: フルリモート
tags:
  - 自社サービス
company_url: https://example.com
---
# フルスタックエンジニア

## 概要
モダンなWebアプリケーション開発を行います。
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / "job_001.md"
        tmp_path.write_text(content, encoding="utf-8")

        job = JobItem.from_file(tmp_path)
        assert job is not None
        assert job.id == "job_001"
        assert job.salary_min == 5000000
        assert job.salary_max == 8000000
        assert "Python" in job.skills

        jobs = [job]

        # スキルマッチ
        res = filter_jobs(jobs, skills=["python"])
        assert len(res) == 1
        res = filter_jobs(jobs, skills=["rust"])
        assert len(res) == 0

        # 年収マッチ
        res = filter_jobs(jobs, min_salary=7000000)
        assert len(res) == 1
        res = filter_jobs(jobs, min_salary=9000000)
        assert len(res) == 0

        # キーワード
        res = filter_jobs(jobs, keywords=["モダン"])
        assert len(res) == 1
        res = filter_jobs(jobs, keywords=["レガシー"])
        assert len(res) == 0


def test_sort_jobs():
    def make_dummy(jid: str, salary_max: int, fetched: str) -> JobItem:
        return JobItem(
            file_path=Path(f"{jid}.md"),
            id=jid,
            source="findy",
            company="テスト",
            title="タイトル",
            url="",
            fetched_at=fetched,
            salary_min=None,
            salary_max=salary_max,
            salary_text="",
            skills=[],
            job_roles=[],
            location="",
            remote_type="",
            tags=[],
            company_url="",
            raw_metadata={},
            body="",
        )

    j1 = make_dummy("j1", 6000000, "2026-09-01T00:00:00")
    j2 = make_dummy("j2", 9000000, "2026-09-02T00:00:00")
    j3 = make_dummy("j3", 7500000, "2026-09-03T00:00:00")

    sorted_by_salary = sort_jobs([j1, j2, j3], sort_by="salary_max", reverse=True)
    assert [j.id for j in sorted_by_salary] == ["j2", "j3", "j1"]

    sorted_by_date = sort_jobs([j1, j2, j3], sort_by="fetched_at", reverse=True)
    assert [j.id for j in sorted_by_date] == ["j3", "j2", "j1"]


if __name__ == "__main__":
    test_parse_salary_arg()
    test_job_item_from_file_and_filter()
    test_sort_jobs()
    print("すべてのテストが成功しました！")
