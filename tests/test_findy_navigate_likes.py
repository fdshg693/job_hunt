import sys
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.findy.navigate_likes import filter_matched_jobs, generate_markdown


def _sample_data() -> dict:
    return {
        "success": True,
        "url": "https://findy-code.io/likes",
        "totalCount": 4,
        "jobs": [
            {"company": "A社", "title": "判断待ち求人", "url": "https://findy-code.io/companies/1/jobs/a",
             "deadline": "2026-12-23", "match_status": "pending"},
            {"company": "B社", "title": "マッチ済み求人", "url": "https://findy-code.io/companies/2/jobs/b",
             "match_status": "matched"},
            {"company": "C社", "title": "判定不明求人", "url": "https://findy-code.io/companies/3/jobs/c",
             "match_status": "unknown"},
            # 過去の保存データ相当（match_status 欠落）
            {"company": "D社", "title": "旧データ求人", "url": "https://findy-code.io/companies/4/jobs/d"},
        ],
        "emptyMessage": None,
    }


def test_filter_matched_jobs_no_exclude_returns_all():
    data = _sample_data()
    assert filter_matched_jobs(data, exclude_matched=False) is data


def test_filter_matched_jobs_keeps_pending_and_unknown():
    result = filter_matched_jobs(_sample_data(), exclude_matched=True)
    assert [j["company"] for j in result["jobs"]] == ["A社", "C社", "D社"]
    assert result["totalCount"] == 3
    assert result["excludeMatched"] is True
    assert result["excludedCount"] == 1


def test_generate_markdown_status_column_all():
    md = generate_markdown(_sample_data(), datetime(2026, 10, 23, 12))
    assert "| # | 状態 | 企業名 |" in md
    assert "| 1 | 判断待ち | A社 |" in md
    assert "| 2 | マッチ済み | B社 |" in md
    assert "| 4 | 不明 | D社 |" in md
    assert "exclude_matched" not in md


def test_generate_markdown_excluded_frontmatter():
    data = filter_matched_jobs(_sample_data(), exclude_matched=True)
    md = generate_markdown(data, datetime(2026, 10, 23, 12))
    frontmatter = md.split("---")[1]
    assert "total_count: 3" in frontmatter
    assert "exclude_matched: true" in frontmatter
    assert "excluded_count: 1" in frontmatter
    assert "（マッチ済み 1 件を除外）" in md
    assert "B社" not in md
