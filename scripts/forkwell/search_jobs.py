"""Forkwell求人検索・取得CLIスクリプト.

Forkwell Jobs（https://jobs.forkwell.com/jobs/search）において、
キーワード、年収、リモート等の条件で求人を検索し、
結果一覧および求人詳細をローカルMarkdown/JSONとして永続化します。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

# プロジェクトルートパス (scripts/forkwell/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.auth_engine import SiteAuthConfig
from scripts.common.browser_auth import run_code_snippet
from scripts.common.cli import (
    EntrypointContext,
    create_search_parser,
    entrypoint_guard,
    to_relative_path,
)
from scripts.common.normalizers import (
    detect_remote_type,
    extract_skills_from_text,
    format_salary_display,
    format_salary_text,
    normalize_url,
    parse_salary_arg,
    parse_salary_range,
)
from scripts.common.storage import save_search_result

SITE_NAME = "Forkwell"
SITE_SOURCE = "forkwell"
SITE_BASE_URL = "https://jobs.forkwell.com"
SEARCH_BASE_URL = "https://jobs.forkwell.com/jobs/search"

DEFAULT_JOBS_DIR = PROJECT_ROOT / "data" / SITE_SOURCE / "jobs"
DEFAULT_SEARCHES_DIR = PROJECT_ROOT / "data" / SITE_SOURCE / "searches"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
HTTP_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

SITE_AUTH_CONFIG = SiteAuthConfig(
    site_name=SITE_NAME,
    login_url=f"{SITE_BASE_URL}/users/sign_in",
    target_url=SEARCH_BASE_URL,
    auth_wall_regex=r"/users/sign_in|/users/sign_up",
    logged_in_selectors=[
        'a[href*="/users/sign_out"]',
        'a[href*="/mypage"]',
        ".user-nav",
    ],
    is_captcha_site=False,
)

SORT_MAP = {
    "popular": "job_popularity_popularity desc",
    "new": "published_at desc",
    "salary_max": "content_yearly_base_salary_max_value desc",
    "salary_min": "content_yearly_base_salary_min_value desc",
}


def build_search_url(
    keyword: str = "",
    page: int = 1,
    min_salary_man: int | None = None,
    sort: str = "job_popularity_popularity desc",
) -> str:
    """Forkwell固有の検索URLを構築する."""
    params: dict[str, str] = {}
    if keyword:
        params["q[freeword]"] = keyword
    if min_salary_man:
        # Forkwell仕様: salaly 表記（サイト側スペル）
        params["q[yearly_base_salaly_min_value]"] = str(min_salary_man)
    if sort:
        params["q[sort]"] = sort
    if page > 1:
        params["page"] = str(page)

    query_str = urllib.parse.urlencode(params)
    return f"{SEARCH_BASE_URL}?{query_str}" if query_str else SEARCH_BASE_URL


def fetch_search_page_html(
    search_url: str,
    session: str = "job-hunt",
    timeout: int = 20,
) -> str | None:
    """検索ページのHTMLを取得する (HTTP GET優先、Playwrightフォールバック)."""
    # 1. urllib による HTTP GET (高速・軽量)
    req = urllib.request.Request(search_url, headers=HTTP_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"[DEBUG] HTTP GET failed ({e.code}): {search_url}", file=sys.stderr)
    except Exception as e:
        print(f"[DEBUG] HTTP GET error: {e}", file=sys.stderr)

    # 2. Playwright によるフォールバック
    try:
        js_code = f"""
        await page.goto({json.dumps(search_url)}, {{ waitUntil: 'domcontentloaded', timeout: {timeout * 1000} }});
        return await page.content();
        """
        html_content = run_code_snippet(session=session, js_code=js_code, timeout=timeout + 10)
        return html_content or None
    except Exception as e:
        print(f"[DEBUG] Playwright fallback failed: {e}", file=sys.stderr)
        return None


def extract_total_count(soup: BeautifulSoup) -> int | None:
    """HTMLから検索ヒット総件数を抽出する."""
    # 1. クラス指定
    count_elem = soup.select_one(".text-jumped-largest")
    if count_elem:
        text = count_elem.get_text(strip=True).replace(",", "")
        if text.isdigit():
            return int(text)

    # 2. 該当なしテキストのチェック
    for s in soup.stripped_strings:
        if "条件に一致する求人はありません" in s:
            return 0

    # 3. テキストから "XXX件" を探索
    for elem in soup.find_all(True):
        if elem.string and "件" in elem.string:
            p_text = elem.parent.get_text(strip=True).replace(",", "")
            m = re.search(r"(\d+)\s*件", p_text)
            if m:
                return int(m.group(1))

    return None


def parse_job_cards(html_content: str) -> list[dict[str, Any]]:
    """HTMLから求人カード一覧を抽出し、正規化された辞書リストを返す."""
    soup = BeautifulSoup(html_content, "html.parser")
    cards = soup.select(".job-list > .card")
    jobs: list[dict[str, Any]] = []

    for card in cards:
        # 詳細リンク・ID・URL
        link_elem = card.select_one("a.job-list__link")
        if not link_elem:
            continue

        title = link_elem.get_text(strip=True)
        rel_url = link_elem.get("href", "")
        url = normalize_url(rel_url, base_url=SITE_BASE_URL)

        id_match = re.search(r"/jobs/(\d+)", rel_url)
        job_id = id_match.group(1) if id_match else f"fk_{len(jobs) + 1}"

        # 企業名
        company_elem = card.select_one(".avatar__detail")
        company = company_elem.get_text(strip=True) if company_elem else "（企業名非公開）"
        # 不要な装飾のトリミング（例: " < VPoE..." 等を保持しつつ正規化）
        company = re.sub(r"\s+", " ", company).strip()

        # 属性リスト（雇用形態、職種、勤務地）
        job_role = ""
        user_icon = card.select_one("i.fa-user, i.fas.fa-user")
        if user_icon:
            li = user_icon.find_parent("li")
            if li:
                job_role = li.get_text(strip=True)

        location = ""
        loc_icon = card.select_one("i.fa-map-marker-alt, i.fas.fa-map-marker-alt")
        if loc_icon:
            li = loc_icon.find_parent("li")
            if li:
                location = li.get_text(strip=True)

        # 年収表示
        salary_text = ""
        for li in card.select("ul.list-inline li"):
            text = li.get_text(strip=True)
            if "年収" in text:
                salary_text = text
                break
        salary_min, salary_max = parse_salary_range(salary_text)

        # 特徴・タグ
        features: list[str] = [
            li.get_text(strip=True) for li in card.select(".feature-table__desc li")
        ]

        # スキルタグ
        skills: list[str] = []
        for tag_elem in card.select("a.tag"):
            tag_name = tag_elem.get_text(strip=True)
            if tag_name and tag_name != "…":
                skills.append(tag_name)

        # 本文・タイトル・特徴からスキルを正規化補完
        extracted_skills = extract_skills_from_text(
            f"{title} {' '.join(skills)} {' '.join(features)}"
        )
        for s in extracted_skills:
            if s not in skills:
                skills.append(s)

        # リモート判定
        remote_type = detect_remote_type(location, " ".join(features))

        jobs.append({
            "id": job_id,
            "title": title,
            "company": company,
            "url": url,
            "salary_text": salary_text or format_salary_text(salary_min, salary_max) or "非公開",
            "salary_min": salary_min,
            "salary_max": salary_max,
            "location": location,
            "remote_type": remote_type,
            "job_roles": [job_role] if job_role else [],
            "skills": skills,
            "features": features,
        })

    return jobs


def fetch_and_save_job_detail(
    job_id: str,
    job_url: str,
    session: str = "job-hunt",
    force: bool = False,
    output_dir: Path | None = None,
) -> tuple[Path, bool]:
    """単体求人の詳細を取得しMarkdownとして保存する（Step 3連携フック）."""
    # Step 3 で実装される fetch_job.py からの呼び出しを試みる
    try:
        from scripts.forkwell.fetch_job import fetch_and_save_forkwell_job

        return fetch_and_save_forkwell_job(
            job_id=job_id,
            job_url=job_url,
            session=session,
            force=force,
            output_dir=output_dir,
        )
    except ImportError:
        # fetch_job.py がまだ作成されていない場合のフォールバック（スタブ保存）
        target_dir = output_dir or DEFAULT_JOBS_DIR
        target_file = target_dir / f"{job_id}.md"
        target_dir.mkdir(parents=True, exist_ok=True)
        if target_file.exists() and not force:
            return target_file, False
        target_file.write_text(
            f"---\nid: '{job_id}'\nsource: forkwell\nurl: '{job_url}'\n---\n\n# Job {job_id}\n",
            encoding="utf-8",
        )
        return target_file, True


def search_forkwell(
    keyword: str = "",
    min_salary_man: int | None = None,
    remote: str | None = None,
    limit: int = 20,
    sort: str = "popular",
    session: str = "job-hunt",
    ctx: EntrypointContext | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    """Forkwell求人を検索し、指定条件・上限件数まで取得する."""
    sort_param = SORT_MAP.get(sort, sort)
    all_jobs: list[dict[str, Any]] = []
    page = 1
    total_count: int | None = None

    while True:
        search_url = build_search_url(
            keyword=keyword,
            page=page,
            min_salary_man=min_salary_man,
            sort=sort_param,
        )
        if ctx:
            ctx.info(f"検索ページ取得中 (page {page}): {search_url}")

        html_content = fetch_search_page_html(search_url, session=session)
        if not html_content:
            if ctx:
                ctx.warn(f"ページ {page} の取得に失敗しました。")
            break

        soup = BeautifulSoup(html_content, "html.parser")
        if page == 1:
            total_count = extract_total_count(soup)
            if ctx and total_count is not None:
                ctx.info(f"検索総件数: {total_count} 件")

        page_jobs = parse_job_cards(html_content)
        if not page_jobs:
            # 求人カードが0件なら終了
            break

        # リモートフィルタの適用（引数 -r/--remote 指定時）
        if remote:
            rem_lower = remote.lower()
            page_jobs = [
                j for j in page_jobs if rem_lower in j.get("remote_type", "").lower()
            ]

        all_jobs.extend(page_jobs)

        # 上限件数に達した場合
        if len(all_jobs) >= limit:
            all_jobs = all_jobs[:limit]
            break

        # 次のページリンクが存在するか確認
        next_link = soup.select_one('a[rel="next"], .pagination .next a, a.next_page')
        if not next_link and (total_count is not None and len(all_jobs) >= total_count):
            break

        page += 1
        time.sleep(0.5)  # 礼儀正しいクロール間隔

    return all_jobs, total_count


def main() -> None:
    """CLIエントリポイント (scripts-entrypoint.md 準拠)."""
    parser = create_search_parser(
        description="Forkwell 求人検索・一覧取得CLI",
        default_limit=20,
        default_download_limit=5,
    )
    # 追加オプション
    parser.add_argument(
        "--sort",
        choices=["popular", "new", "salary_max", "salary_min"],
        default="popular",
        help="ソート順 (popular: 人気順, new: 新着順, salary_max: 年収上限順, salary_min: 年収下限順)",
    )

    args = parser.parse_args()

    # クエリキーワード組み立て
    query_parts: list[str] = []
    if args.query:
        query_parts.extend(args.query)
    if args.keywords:
        query_parts.extend(args.keywords)
    if args.skills:
        query_parts.extend(args.skills)
    if args.company:
        query_parts.append(args.company)
    if args.title:
        query_parts.append(args.title)
    if args.role:
        query_parts.append(args.role)

    query_str = " ".join(query_parts).strip()

    # 年収引数のパース
    min_sal_man: int | None = None
    if args.min_salary:
        min_sal_yen = parse_salary_arg(args.min_salary)
        if min_sal_yen is not None:
            min_sal_man = min_sal_yen // 10000

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        # 1. 検索実行
        jobs, total_count = search_forkwell(
            keyword=query_str,
            min_salary_man=min_sal_man,
            remote=args.remote,
            limit=args.limit or 20,
            sort=args.sort,
            session=args.session,
            ctx=ctx,
        )

        ctx.info(f"取得完了: {len(jobs)} 件 (全体: {total_count if total_count is not None else '不明'} 件)")

        # 2. 詳細ダウンロード保存（--download 指定時）
        if args.download and jobs:
            dl_targets = jobs[: args.download_limit]
            ctx.info(f"詳細Markdownを保存中（{len(dl_targets)} 件）...")
            for j in dl_targets:
                job_path, _ = fetch_and_save_job_detail(
                    job_id=j["id"],
                    job_url=j["url"],
                    session=args.session,
                    force=args.force,
                )
                ctx.add_result_path(job_path)

        # 3. 検索結果一覧ファイルの永続化（--no-save が指定されていない場合）
        if not args.no_save:
            metadata: dict[str, Any] = {
                "min_salary_man": min_sal_man,
                "remote": args.remote,
                "sort": args.sort,
            }
            md_path, _ = save_search_result(
                source=SITE_SOURCE,
                keyword=query_str,
                jobs=jobs,
                total_count=total_count,
                returned_count=len(jobs),
                output_dir=DEFAULT_SEARCHES_DIR,
                metadata=metadata,
            )
            ctx.add_result_path(md_path)

        # 4. サマリ表示関数
        def print_summary() -> None:
            print(f"\n=== {SITE_NAME} 求人検索結果 ===")
            print(f"検索条件: {query_str or '（指定なし）'}")
            if min_sal_man:
                print(f"下限年収: {min_sal_man}万円以上")
            if args.remote:
                print(f"リモート条件: {args.remote}")
            print(f"ソート: {args.sort}")
            print(f"表示件数: {len(jobs)} 件 (検索総数: {total_count if total_count is not None else '不明'} 件)\n")

            if not jobs:
                print("条件に一致する求人は見つかりませんでした。")
                return

            print(f"{'No':<3} | {'企業名':<22} | {'年収':<16} | {'リモート':<8} | {'タイトル'}")
            print("-" * 80)
            for idx, j in enumerate(jobs, start=1):
                company = j.get("company", "")[:20]
                sal = j.get("salary_text") or format_salary_display(j.get("salary_min"), j.get("salary_max"))
                remote_str = j.get("remote_type", "不明")
                title = j.get("title", "")
                if len(title) > 35:
                    title = title[:32] + "..."
                print(f"{idx:<3} | {company:<22} | {sal:<16} | {remote_str:<8} | {title}")

            print("\n生成ファイル:")
            for p in ctx.result_paths:
                print(f"  - {p}")

        # 5. 出力のフラッシュ
        json_output = {
            "source": SITE_SOURCE,
            "keyword": query_str,
            "total_count": total_count,
            "returned_count": len(jobs),
            "jobs": jobs,
            "paths": ctx.result_paths,
        } if args.json else None

        ctx.flush_outputs(summary_fn=print_summary, json_data=json_output)


if __name__ == "__main__":
    main()
