import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from bs4 import BeautifulSoup

from scripts.findy.search_online import (
    OnlineJobItem,
    extract_job_hash_links,
    filter_online_jobs,
    parse_recommends_html,
)


def test_extract_job_hash_links():
    html = """
    <div>
        <a href="/companies/13/jobs/FyTVLvHVuEiQm">【Kaname.ax】AIネイティブエンジニア</a>
        <a href="/companies/13/jobs/b86n25tSyJTvH">生活者データ×AI</a>
        <a href="/other/link">関係ないリンク</a>
        <a href="/companies/13/jobs/FyTVLvHVuEiQm">重複リンク</a>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    links = extract_job_hash_links(soup)
    assert len(links) == 2
    assert links[0] == (13, "FyTVLvHVuEiQm", "【Kaname.ax】AIネイティブエンジニア")
    assert links[1] == (13, "b86n25tSyJTvH", "生活者データ×AI")


def test_parse_recommends_html():
    next_data = {
        "props": {
            "pageProps": {
                "jobDescriptionsData": {
                    "paginationInfo": {"totalCount": 1},
                    "list": [
                        {
                            "id": 44280,
                            "title": "【Kaname.ax】AIネイティブエンジニア",
                            "company": {"id": 13, "name": "アライドアーキテクツ株式会社"},
                            "numericSalaryMin": 6000000,
                            "numericSalaryMax": 9000000,
                            "skills": [{"name": "Python"}, {"name": "Go"}],
                            "jobRoles": [{"name": "フルスタックエンジニア"}],
                            "tags": [{"name": "AI"}],
                            "location": "東京都渋谷区",
                            "workHours": "9:30-18:30",
                            "description": "生活者データとAIを用いたプロダクト開発",
                        }
                    ],
                }
            }
        }
    }
    json_str = json.dumps(next_data)
    html = f"""
    <html>
    <head><script id="__NEXT_DATA__" type="application/json">{json_str}</script></head>
    <body>
        <a href="/companies/13/jobs/FyTVLvHVuEiQm">【Kaname.ax】AIネイティブエンジニア</a>
    </body>
    </html>
    """

    res = parse_recommends_html(html, keyword="アライドアーキテクツ", page=1)
    assert res.total_count == 1
    assert len(res.jobs) == 1
    job = res.jobs[0]
    assert job.id == "FyTVLvHVuEiQm"
    assert job.numeric_id == 44280
    assert job.company == "アライドアーキテクツ株式会社"
    assert job.company_id == 13
    assert job.url == "https://findy-code.io/companies/13/jobs/FyTVLvHVuEiQm"
    assert job.salary_min == 6000000
    assert job.salary_max == 9000000
    assert job.salary_text == "600万円〜900万円"
    assert "Python" in job.skills
    assert "Go" in job.skills
    assert "フルスタックエンジニア" in job.job_roles


def test_filter_online_jobs():
    j1 = OnlineJobItem(
        id="j1",
        numeric_id=1,
        company="Company A",
        company_id=1,
        title="Python Backend",
        url="https://example.com/1",
        salary_min=6000000,
        salary_max=8000000,
        skills=["Python", "AWS", "Docker"],
        remote_type="フルリモート",
    )
    j2 = OnlineJobItem(
        id="j2",
        numeric_id=2,
        company="Company B",
        company_id=2,
        title="Go Engineer",
        url="https://example.com/2",
        salary_min=9000000,
        salary_max=12000000,
        skills=["Go", "GCP", "Kubernetes"],
        remote_type="ハイブリッド",
    )
    jobs = [j1, j2]

    # 年収フィルタ
    res_sal = filter_online_jobs(jobs, min_salary=9000000)
    assert len(res_sal) == 1
    assert res_sal[0].id == "j2"

    # スキルフィルタ
    res_sk = filter_online_jobs(jobs, skills=["python"])
    assert len(res_sk) == 1
    assert res_sk[0].id == "j1"

    # 複数スキル
    res_sk_multi = filter_online_jobs(jobs, skills=["python", "aws"])
    assert len(res_sk_multi) == 1
    assert res_sk_multi[0].id == "j1"

    res_sk_miss = filter_online_jobs(jobs, skills=["python", "rust"])
    assert len(res_sk_miss) == 0

    # リモートフィルタ
    res_remote = filter_online_jobs(jobs, remote_type="フルリモート")
    assert len(res_remote) == 1
    assert res_remote[0].id == "j1"


if __name__ == "__main__":
    test_extract_job_hash_links()
    test_parse_recommends_html()
    test_filter_online_jobs()
    print("test_search_findy_online: すべてのテストが成功しました！")
