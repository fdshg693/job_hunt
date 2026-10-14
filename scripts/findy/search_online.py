"""Findyオンライン求人検索・一括取得スクリプト.

Findyの公開検索エンドポイントを利用して企業名や技術キーワードから求人一覧・詳細URLを検索し、
必要に応じてローカルMarkdownへのダウンロードまで一気通貫で行います。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

# プロジェクトルートパスを sys.path に追加して直接実行に対応
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx
from bs4 import BeautifulSoup

from scripts.common.cli import EntrypointContext, create_search_parser, to_relative_path
from scripts.common.normalizers import (
    detect_remote_type,
    format_salary_display,
    format_salary_text,
    parse_salary_arg,
)
from scripts.common.storage import save_search_result
from scripts.findy.fetch_job import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_USER_AGENT,
    fetch_and_save_job,
)

FINDY_RECOMMENDS_URL = "https://findy-code.io/recommends"


@dataclass
class OnlineJobItem:
    """オンライン検索で取得した求人情報アイテム."""

    id: str  # ハッシュID (例: FyTVLvHVuEiQm)
    numeric_id: int | None  # 内部数値ID (例: 44280)
    company: str  # 企業名
    company_id: int | None  # 企業ID (例: 13)
    title: str  # 求人タイトル
    url: str  # 求人URL
    salary_min: int | None = None  # 最低年収 (円)
    salary_max: int | None = None  # 最高年収 (円)
    salary_text: str | None = None  # 年収表示文字列 (例: "700万円〜1250万円")
    skills: list[str] = field(default_factory=list)  # スキル一覧
    job_roles: list[str] = field(default_factory=list)  # 職種カテゴリ一覧
    tags: list[str] = field(default_factory=list)  # 特徴タグ一覧
    remote_type: str = "不明"  # リモート方針
    work_hours: str | None = None  # 勤務時間
    description_snippet: str = ""  # 概要スニペット

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換する."""
        return asdict(self)


@dataclass
class OnlineSearchResult:
    """オンライン検索の検索結果."""

    keyword: str
    page: int
    total_count: int
    jobs: list[OnlineJobItem]

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換する."""
        return {
            "keyword": self.keyword,
            "page": self.page,
            "total_count": self.total_count,
            "returned_count": len(self.jobs),
            "jobs": [j.to_dict() for j in self.jobs],
        }


def extract_job_hash_links(soup: BeautifulSoup) -> list[tuple[int, str, str]]:
    """HTMLから求人カードリンク (company_id, job_hash, link_text) のリストを抽出する."""
    links: list[tuple[int, str, str]] = []
    seen_hashes: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        match = re.match(r"^/companies/(\d+)/jobs/([a-zA-Z0-9_-]+)$", href)
        if match:
            cid = int(match.group(1))
            jhash = match.group(2)
            if jhash not in seen_hashes:
                seen_hashes.add(jhash)
                links.append((cid, jhash, a.get_text(strip=True)))
    return links


def _parse_job_card(card: BeautifulSoup, company_id: int, job_hash: str) -> OnlineJobItem:
    """HTMLカード要素から各属性を抽出して OnlineJobItem を生成する."""
    full_url = f"https://findy-code.io/companies/{company_id}/jobs/{job_hash}"

    # タイトル
    title_tag = card.find(["h2", "h3", "h4"])
    title = title_tag.get_text(strip=True) if title_tag else "タイトル不明"

    # 企業名
    company = "企業名非公開"
    comp_tag = card.find(attrs={"data-test": re.compile(r"company-name|company", re.I)})
    if comp_tag:
        company = comp_tag.get_text(strip=True)
    else:
        for a in card.find_all("a", href=True):
            if re.match(rf"^/companies/{company_id}$", a["href"]):
                company = a.get_text(strip=True)
                break

    # 年収テキスト・パース
    salary_text: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    card_text = card.get_text(separator=" ", strip=True)
    sal_match = re.search(r"(\d+(?:\.\d+)?)\s*万(?:円)?\s*[〜~～-]\s*(\d+(?:\.\d+)?)\s*万(?:円)?", card_text)
    if sal_match:
        salary_min = int(float(sal_match.group(1)) * 10000)
        salary_max = int(float(sal_match.group(2)) * 10000)
        salary_text = f"{sal_match.group(1)}万円〜{sal_match.group(2)}万円"

    # リモート判定
    remote_type = detect_remote_type(None, card_text)

    # スキル・タグ抽出
    skills: list[str] = []
    tags: list[str] = []
    for tag_el in card.find_all(["span", "li", "div"], class_=re.compile(r"tag|badge|skill", re.I)):
        text = tag_el.get_text(strip=True)
        if text and len(text) < 30:
            if any(s in text for s in ["React", "Vue", "Go", "Python", "TypeScript", "AWS", "Ruby", "Java"]):
                if text not in skills:
                    skills.append(text)
            elif text not in tags:
                tags.append(text)

    return OnlineJobItem(
        id=job_hash,
        numeric_id=None,
        company=company,
        company_id=company_id,
        title=title,
        url=full_url,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_text=salary_text,
        skills=skills,
        remote_type=remote_type,
        tags=tags,
    )


def search_findy_online(keyword: str, page: int = 1) -> OnlineSearchResult:
    """Findyのオンライン推薦/検索ページから求人一覧を取得する."""
    params: dict[str, Any] = {"page": page}
def parse_recommends_html(html: str, keyword: str = "", page: int = 1) -> OnlineSearchResult:
    """Findy検索結果HTMLをパースして OnlineSearchResult を生成する."""
    soup = BeautifulSoup(html, "html.parser")
    links = extract_job_hash_links(soup)

    # 企業IDとハッシュの対応マップ
    cid_to_hash: dict[int, str] = {cid: h for cid, h, _ in links}

    # __NEXT_DATA__ が存在する場合はJSONからパース
    next_data_tag = soup.find("script", id="__NEXT_DATA__")
    if next_data_tag and next_data_tag.string:
        try:
            next_data = json.loads(next_data_tag.string)
            page_props = next_data.get("props", {}).get("pageProps", {})
            jd_data = page_props.get("jobDescriptionsData") or {}
            total_count = (
                jd_data.get("paginationInfo", {}).get("totalCount")
                or page_props.get("totalCount", 0)
            )
            jobs_raw = (
                jd_data.get("list", [])
                or page_props.get("jobs", [])
                or page_props.get("jobDescriptions", [])
            )

            jobs: list[OnlineJobItem] = []
            for idx, j in enumerate(jobs_raw):
                c_obj = j.get("company") or {}
                cid = c_obj.get("id")
                # リンクからハッシュIDを取得、なければインデックス順または数値ID
                jhash = cid_to_hash.get(cid) if cid else None
                if not jhash and idx < len(links):
                    jhash = links[idx][1]
                if not jhash:
                    jhash = str(j.get("id") or j.get("numericId", ""))

                sal_min = j.get("numericSalaryMin")
                sal_max = j.get("numericSalaryMax")
                sal_text = format_salary_text(sal_min, sal_max, j.get("salary"))
                skills = [s["name"] for s in j.get("skills", []) if isinstance(s, dict) and s.get("name")]
                roles = [r["name"] for r in j.get("jobRoles", []) if isinstance(r, dict) and r.get("name")]
                tags = [t["name"] for t in j.get("tags", []) if isinstance(t, dict) and t.get("name")]
                remote = detect_remote_type(j.get("location"), f"{j.get('description', '')}")

                full_url = f"https://findy-code.io/companies/{cid}/jobs/{jhash}" if cid else f"https://findy-code.io/jobs/{jhash}"
                jobs.append(
                    OnlineJobItem(
                        id=str(jhash),
                        numeric_id=j.get("numericId") or j.get("id"),
                        company=c_obj.get("name") or "企業名非公開",
                        company_id=cid,
                        title=j.get("title") or "タイトルなし",
                        url=full_url,
                        salary_min=sal_min,
                        salary_max=sal_max,
                        salary_text=sal_text,
                        skills=skills,
                        job_roles=roles,
                        tags=tags,
                        remote_type=remote,
                        description_snippet=j.get("description", "")[:120].replace("\n", " "),
                    )
                )

            return OnlineSearchResult(keyword=keyword, page=page, total_count=total_count, jobs=jobs)
        except Exception:
            pass

    # HTMLフォールバックパース
    jobs = []
    for cid, jhash, text in links:
        full_url = f"https://findy-code.io/companies/{cid}/jobs/{jhash}"
        jobs.append(
            OnlineJobItem(
                id=jhash,
                numeric_id=None,
                company=f"企業ID: {cid}",
                company_id=cid,
                title=text or "タイトルなし",
                url=full_url,
                remote_type="不明",
            )
        )

    return OnlineSearchResult(keyword=keyword, page=page, total_count=len(jobs), jobs=jobs)


def search_findy_online(keyword: str, page: int = 1) -> OnlineSearchResult:
    """Findyのオンライン推薦/検索ページから求人一覧を取得する."""
    params: dict[str, Any] = {"page": page}
    if keyword:
        params["keyword"] = keyword

    url = f"{FINDY_RECOMMENDS_URL}?{urlencode(params)}"
    headers = {"User-Agent": DEFAULT_USER_AGENT}

    with httpx.Client(headers=headers, follow_redirects=True, timeout=15.0) as client:
        response = client.get(url)
        response.raise_for_status()
        html = response.text

    return parse_recommends_html(html, keyword=keyword, page=page)


def filter_online_jobs(
    jobs: list[OnlineJobItem],
    min_salary: int | None = None,
    skills: list[str] | None = None,
    remote_type: str | None = None,
) -> list[OnlineJobItem]:
    """取得したオンライン求人を条件で絞り込む."""
    matched: list[OnlineJobItem] = []

    for job in jobs:
        if min_salary is not None:
            effective_max = job.salary_max if job.salary_max is not None else job.salary_min
            if effective_max is not None and effective_max < min_salary:
                continue

        if skills:
            job_skills_lower = [s.lower() for s in job.skills]
            has_all_skills = True
            for req_skill in skills:
                req_lower = req_skill.lower()
                if not any(req_lower in js for js in job_skills_lower):
                    has_all_skills = False
                    break
            if not has_all_skills:
                continue

        if remote_type:
            if remote_type.lower() not in job.remote_type.lower():
                continue

        matched.append(job)

    return matched


def print_search_results(
    result: OnlineSearchResult,
    jobs: list[OnlineJobItem],
    detail: bool = False,
    limit: int | None = None,
) -> None:
    """検索結果をコンソールに出力する."""
    kw_disp = f"'{result.keyword}'" if result.keyword else "（全件）"
    print("\n========================================================")
    print(f" Findy 公開求人検索結果: {kw_disp}")
    print(f" 該当件数: 全 {result.total_count} 件 (このページ: {len(result.jobs)} 件 / 条件一致: {len(jobs)} 件)")
    print("========================================================\n")

    display_jobs = jobs[:limit] if limit else jobs
    if not display_jobs:
        print("条件に一致する求人は見つかりませんでした。")
        return

    for idx, job in enumerate(display_jobs, start=1):
        salary_disp = format_salary_display(job.salary_min, job.salary_max, job.salary_text)
        skills_disp = ", ".join(job.skills[:8]) if job.skills else "未指定"
        if len(job.skills) > 8:
            skills_disp += f" 他{len(job.skills) - 8}件"

        print(f"[{idx}] {job.company} | {job.title}")
        print(f"    - URL:    {job.url} (ID: {job.id})")
        print(f"    - 年収:   {salary_disp} | リモート: {job.remote_type}")
        print(f"    - スキル: {skills_disp}")
        if job.tags:
            print(f"    - タグ:   {', '.join(job.tags[:6])}")
        if detail and job.description_snippet:
            print(f"    - 概要:   {job.description_snippet}")
        print("-" * 56)


def main() -> None:
    parser = create_search_parser(
        description="Findyの公開求人検索エンドポイントから求人一覧を取得・フィルタ・保存します。",
        default_limit=20,
        default_download_limit=5,
    )
    parser.add_argument(
        "--page",
        type=int,
        default=1,
        help="取得対象ページ番号 (デフォルト: 1)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"ダウンロード時の求人Markdown保存先 (デフォルト: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--searches-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "findy" / "searches",
        help="検索結果ファイル保存先ディレクトリ",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="ダウンロード時に実際のファイル書き込みを行わずプレビューする",
    )

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    # 検索クエリの結合
    keywords = list(args.query)
    if args.keywords:
        keywords.extend(args.keywords)
    keyword = " ".join(keywords).strip()

    min_salary_int = parse_salary_arg(args.min_salary) if args.min_salary else None

    # オンライン検索実行
    try:
        search_res = search_findy_online(keyword=keyword, page=args.page)
    except Exception as e:
        ctx.error(f"Findy求人検索リクエストに失敗しました: {e}")
        sys.exit(1)

    # フィルタリング
    matched_jobs = filter_online_jobs(
        search_res.jobs,
        min_salary=min_salary_int,
        skills=args.skills,
        remote_type=args.remote,
    )
    display_jobs = matched_jobs[: args.limit] if args.limit else matched_jobs

    # 検索結果の永続化
    saved_search_md: Path | None = None
    if not args.no_save and not args.dry_run:
        saved_search_md, _ = save_search_result(
            source="findy",
            keyword=keyword,
            jobs=[j.to_dict() for j in display_jobs],
            total_count=search_res.total_count,
            returned_count=len(search_res.jobs),
            output_dir=args.searches_dir,
            metadata={"page": args.page},
        )
        ctx.add_result_path(saved_search_md)

    # ダウンロード対象の実行
    if args.download:
        targets = display_jobs[: args.download_limit]
        if not targets:
            ctx.log("[ダウンロード] 保存対象の求人がありません。")
        else:
            if args.summary:
                ctx.log(f"\n>>> ヒットした求人をダウンロード中 (上限: {args.download_limit} 件) <<<")
            success_cnt = 0
            error_cnt = 0

            for j in targets:
                try:
                    res, _ = fetch_and_save_job(
                        url=j.url,
                        output_dir=args.output_dir,
                        force=args.force,
                        dry_run=args.dry_run,
                        summary=args.summary,
                    )
                    if res is not None:
                        ctx.add_result_path(res)
                        success_cnt += 1
                    elif args.dry_run:
                        success_cnt += 1
                except Exception as ex:
                    ctx.error(f"{j.url}: {ex}")
                    error_cnt += 1

            if args.summary:
                ctx.log(f"\nダウンロード完了: 成功 {success_cnt} 件 / エラー {error_cnt} 件")
            if error_cnt > 0 and success_cnt == 0:
                ctx.set_exit_code(1)

    json_payload = {
        "keyword": keyword,
        "page": args.page,
        "total_count": search_res.total_count,
        "returned_count": len(search_res.jobs),
        "matched_count": len(matched_jobs),
        "jobs": [j.to_dict() for j in display_jobs],
    }

    def summary_fn() -> None:
        print_search_results(
            result=search_res,
            jobs=matched_jobs,
            detail=args.detail,
            limit=args.limit,
        )
        if saved_search_md:
            ctx.log(f"\n[検索結果保存] {to_relative_path(saved_search_md)}")

    sys.exit(ctx.flush_outputs(summary_fn=summary_fn, json_data=json_payload))


if __name__ == "__main__":
    main()
