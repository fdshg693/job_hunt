"""レバテックダイレクト求人検索・取得CLIスクリプト.

レバテックダイレクト（https://levtech-direct.jp/search）において、
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

# プロジェクトルートパス (scripts/levtech_direct/ の2階層上)
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
from scripts.common.storage import (
    JobData,
    save_job_markdown,
    save_search_result,
)

# ==============================================================================
# サイト定数・設定
# ==============================================================================

SITE_NAME = "Levtech Direct"
SITE_SOURCE = "levtech_direct"
SITE_BASE_URL = "https://levtech-direct.jp"
SEARCH_BASE_URL = "https://levtech-direct.jp/search"

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

# 認証設定（求人検索・詳細は公開されているが将来の機能拡張用）
SITE_AUTH_CONFIG = SiteAuthConfig(
    site_name=SITE_NAME,
    login_url=f"{SITE_BASE_URL}/signin",
    target_url=SEARCH_BASE_URL,
    auth_wall_regex=r"/signin|/signup",
    logged_in_selectors=[
        'a[href*="/mypage"]',
        'button[aria-label*="user"]',
    ],
    is_captcha_site=False,
)

SORT_MAP = {
    "new": "1",          # 新着順
    "salary_max": "2",   # 年収上限が高い順
    "salary_min": "3",   # 年収上限が低い順
}


# ==============================================================================
# URL生成 & HTML取得
# ==============================================================================

def build_search_url(
    keyword: str = "",
    page: int = 1,
    min_salary_man: int | None = None,
    sort: str = "1",
) -> str:
    """レバテックダイレクトの検索URLを構築する."""
    params: dict[str, str] = {
        "from_type": "header",
    }
    if keyword:
        params["freeWord"] = keyword
    if min_salary_man:
        params["annualIncome"] = str(min_salary_man)
    if sort:
        params["sort"] = str(sort)
    if page > 1:
        params["page"] = str(page)

    query_str = urllib.parse.urlencode(params)
    return f"{SEARCH_BASE_URL}?{query_str}"


def fetch_html(
    url: str,
    session: str = "job-hunt",
    timeout: int = 20,
) -> str | None:
    """HTMLを取得する (HTTP GET優先、Playwrightフォールバック)."""
    # 1. urllib による HTTP GET (高速・軽量)
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"[DEBUG] HTTP GET failed ({e.code}): {url}", file=sys.stderr)
    except Exception as e:
        print(f"[DEBUG] HTTP GET error: {e}", file=sys.stderr)

    # 2. Playwright によるフォールバック
    try:
        js_code = f"""
        await page.goto({json.dumps(url)}, {{ waitUntil: 'domcontentloaded', timeout: {timeout * 1000} }});
        return {{ html: await page.content() }};
        """
        res = run_code_snippet(session=session, code_str=js_code, timeout=timeout + 10)
        return res.get("html") if isinstance(res, dict) else None
    except Exception as e:
        print(f"[DEBUG] Playwright fallback failed: {e}", file=sys.stderr)
        return None


def extract_next_data(html_content: str) -> dict[str, Any] | None:
    """HTMLから <script id="__NEXT_DATA__"> を抽出してJSON辞書として返す."""
    soup = BeautifulSoup(html_content, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return None
    try:
        return json.loads(script.string)
    except Exception as e:
        print(f"[DEBUG] Failed to parse __NEXT_DATA__: {e}", file=sys.stderr)
        return None


def clean_html_text(html_text: str | None) -> str:
    """HTML文字列からタグを除去し、改行を適切に保持したプレーンテキストを返す."""
    if not html_text:
        return ""
    # <br> や <p> を改行に置換
    text = re.sub(r"<br\s*/?>", "\n", html_text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text().strip()


# ==============================================================================
# 検索結果パース
# ==============================================================================

def parse_search_results(html_content: str) -> tuple[list[dict[str, Any]], int | None]:
    """検索結果HTMLから求人カード一覧および総件数を抽出する."""
    next_data = extract_next_data(html_content)
    if next_data:
        try:
            page_props = next_data.get("props", {}).get("pageProps", {})
            search_result = page_props.get("initialSearchResult", {})
            total_count = (
                search_result.get("totalRecruitingResults")
                or search_result.get("totalResults")
                or search_result.get("totalCount")
            )
            raw_job_list = search_result.get("jobList", [])

            jobs: list[dict[str, Any]] = []
            for item in raw_job_list:
                job_id = str(item.get("id"))
                title = item.get("title", "")
                company = item.get("companyName", "（企業名非公開）")
                url = f"{SITE_BASE_URL}/job/{job_id}"

                min_income = item.get("minAnnualIncome")
                max_income = item.get("maxAnnualIncome")
                salary_min = int(min_income) * 10000 if min_income is not None else None
                salary_max = int(max_income) * 10000 if max_income is not None else None
                salary_text = format_salary_text(salary_min, salary_max) or "非公開"

                location = item.get("prefecture", "")
                skills = [s.get("name") for s in item.get("skillList", []) if isinstance(s, dict) and s.get("name")]
                job_roles = [o.get("name") for o in item.get("occupationList", []) if isinstance(o, dict) and o.get("name")]
                appeals = [a.get("name") for a in item.get("appealPointList", []) if isinstance(a, dict) and a.get("name")]

                # リモート判定
                combined_text = f"{title} {' '.join(skills)} {' '.join(appeals)} {location}"
                remote_type = detect_remote_type(location, combined_text)

                # 本文・タイトルからスキルを補完
                for s in extract_skills_from_text(combined_text):
                    if s not in skills:
                        skills.append(s)

                jobs.append({
                    "id": job_id,
                    "title": title,
                    "company": company,
                    "url": url,
                    "salary_text": salary_text,
                    "salary_min": salary_min,
                    "salary_max": salary_max,
                    "location": location,
                    "remote_type": remote_type,
                    "job_roles": job_roles,
                    "skills": skills,
                    "tags": appeals,
                })

            return jobs, total_count
        except Exception as e:
            print(f"[DEBUG] Error parsing initialSearchResult from __NEXT_DATA__: {e}", file=sys.stderr)

    # DOM フォールバック
    soup = BeautifulSoup(html_content, "html.parser")
    jobs = []
    # 総件数
    total_count = None
    for s in soup.stripped_strings:
        m = re.search(r"(\d+)\s*件", s)
        if m:
            total_count = int(m.group(1))
            break

    cards = soup.select('a[href^="/job/"]')
    seen_ids = set()
    for card in cards:
        rel_url = card.get("href", "")
        m = re.search(r"/job/(\d+)", rel_url)
        if not m:
            continue
        job_id = m.group(1)
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        title_elem = card.select_one("h2, [class*='title']")
        title = title_elem.get_text(strip=True) if title_elem else ""

        company_elem = card.select_one("[class*='company']")
        company = company_elem.get_text(strip=True) if company_elem else "（企業名非公開）"

        salary_elem = card.select_one("[class*='salary']")
        raw_salary = salary_elem.get_text(strip=True) if salary_elem else ""
        salary_min, salary_max = parse_salary_range(raw_salary)
        salary_text = raw_salary or format_salary_text(salary_min, salary_max) or "非公開"

        card_text = card.get_text(" ", strip=True)
        remote_type = detect_remote_type(None, card_text)
        skills = extract_skills_from_text(card_text)

        jobs.append({
            "id": job_id,
            "title": title,
            "company": company,
            "url": f"{SITE_BASE_URL}/job/{job_id}",
            "salary_text": salary_text,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "location": "",
            "remote_type": remote_type,
            "job_roles": [],
            "skills": skills,
            "tags": [],
        })

    return jobs, total_count


# ==============================================================================
# 求人詳細の取得・保存
# ==============================================================================

def fetch_and_save_job_detail(
    job_id: str,
    job_url: str,
    session: str = "job-hunt",
    force: bool = False,
    output_dir: Path | None = None,
) -> tuple[Path, bool]:
    """単体求人の詳細を取得し、Markdownとして保存する (job-data-format.md 仕様準拠)."""
    target_dir = output_dir or DEFAULT_JOBS_DIR
    target_file = target_dir / f"{job_id}.md"

    if target_file.exists() and not force:
        return target_file, False

    html_content = fetch_html(job_url, session=session)
    if not html_content:
        # 取得失敗時はスタブで作成せず例外または未作成とする
        raise RuntimeError(f"求人詳細HTMLの取得に失敗しました: {job_url}")

    next_data = extract_next_data(html_content)
    if next_data:
        try:
            page_props = next_data.get("props", {}).get("pageProps", {})
            job_detail = page_props.get("jobDetail", {})
            base = job_detail.get("base", {})

            title = base.get("title", "")
            company = base.get("companyName", "（企業名非公開）")

            min_inc = base.get("minAnnualIncome")
            max_inc = base.get("maxAnnualIncome")
            salary_min = int(min_inc) * 10000 if min_inc is not None else None
            salary_max = int(max_inc) * 10000 if max_inc is not None else None

            salary_detail = base.get("salaryDetail", "")
            salary_text = salary_detail or format_salary_text(salary_min, salary_max) or ""

            work_loc = base.get("workLocation", "")
            prefecture = base.get("prefecture", "")
            location = work_loc or prefecture or ""

            # リモートスタイル判定
            job_work_style = base.get("jobWorkStyle", "")
            remote_freq = base.get("remoteWorkFrequency", "")
            if job_work_style == "full_remote":
                remote_type = "フルリモート"
            elif job_work_style == "partial_remote":
                remote_type = "ハイブリッド"
            elif job_work_style == "office":
                remote_type = "出社"
            else:
                remote_type = detect_remote_type(location, f"{title} {remote_freq} {base.get('workDetail', '')}")

            # スキル・タグ
            main_skills = [
                s if isinstance(s, str) else s.get("name", "")
                for s in job_detail.get("mainSkills", [])
            ]
            appeals = [
                a if isinstance(a, str) else a.get("name", "")
                for a in job_detail.get("appeals", [])
            ]
            tags = [t for t in list(dict.fromkeys(main_skills + appeals)) if t]

            # 職種カテゴリ
            job_roles = []
            for occ in base.get("occupationList", []):
                if isinstance(occ, dict) and occ.get("name"):
                    job_roles.append(occ["name"])

            # 本文セクション
            description = clean_html_text(base.get("workDetail", ""))
            must_skills = clean_html_text(base.get("requiredSkill", ""))
            desired_skills = clean_html_text(base.get("optionalSkill", ""))
            dev_env = clean_html_text(base.get("developmentEnvironment", ""))
            business_summary = clean_html_text(base.get("businessSummary", ""))
            benefit = clean_html_text(base.get("benefit", ""))
            holiday = clean_html_text(base.get("holiday", ""))
            selection = clean_html_text(base.get("selectionProcess", ""))
            emp_status = base.get("employmentStatus", "")

            # 就業条件まとめ
            cond_lines: list[str] = []
            if emp_status:
                cond_lines.append(f"- 雇用形態: {emp_status}")
            if location:
                cond_lines.append(f"- 勤務地: {location}")
            if remote_freq:
                cond_lines.append(f"- リモートワーク: {remote_freq} ({remote_type})")
            elif remote_type:
                cond_lines.append(f"- リモート区分: {remote_type}")
            if salary_detail:
                cond_lines.append(f"- 給与備考: {salary_detail}")
            if holiday:
                cond_lines.append(f"- 休日・休暇: {holiday}")
            if benefit:
                cond_lines.append(f"- 福利厚生・手当: {benefit}")
            if selection:
                cond_lines.append(f"- 選考プロセス: {selection}")
            conditions_text = "\n".join(cond_lines)

            # 説明文に事業概要を補足
            if business_summary:
                if description:
                    description = f"### 事業内容\n{business_summary}\n\n### 業務内容\n{description}"
                else:
                    description = f"### 事業内容\n{business_summary}"

            # スキル抽出補完
            all_text = f"{title} {must_skills} {desired_skills} {description} {dev_env}"
            extracted_skills = extract_skills_from_text(all_text)
            skills = list(dict.fromkeys(main_skills + extracted_skills))

            # メタデータ
            extra_metadata: dict[str, Any] = {}
            if base.get("companyId"):
                extra_metadata["company_id"] = base["companyId"]
            if base.get("publishedDate"):
                extra_metadata["published_date"] = base["publishedDate"]
            if base.get("updatedAt"):
                extra_metadata["updated_at"] = base["updatedAt"]

            job = JobData(
                id=job_id,
                source=SITE_SOURCE,
                company=company,
                title=title,
                url=job_url,
                salary_min=salary_min,
                salary_max=salary_max,
                salary_text=salary_text,
                skills=skills,
                job_roles=job_roles,
                location=location,
                remote_type=remote_type,
                tags=tags,
                description=description,
                must_skills=must_skills,
                desired_skills=desired_skills,
                development_environment=dev_env,
                conditions=conditions_text,
                extra_metadata=extra_metadata,
            )

            return save_job_markdown(job=job, output_dir=target_dir, force=force)
        except Exception as e:
            print(f"[DEBUG] Error parsing job detail from __NEXT_DATA__: {e}", file=sys.stderr)

    # DOM フォールバック
    soup = BeautifulSoup(html_content, "html.parser")
    title_elem = soup.select_one("h1")
    title = title_elem.get_text(strip=True) if title_elem else f"Job {job_id}"

    # 企業名
    company_elem = soup.select_one("[class*='companyName'], [class*='company']")
    company = company_elem.get_text(strip=True) if company_elem else "（企業名非公開）"

    full_text = soup.get_text(" ", strip=True)
    salary_min, salary_max = parse_salary_range(full_text)
    salary_text = format_salary_text(salary_min, salary_max) or ""
    remote_type = detect_remote_type(None, full_text)
    skills = extract_skills_from_text(full_text)

    job = JobData(
        id=job_id,
        source=SITE_SOURCE,
        company=company,
        title=title,
        url=job_url,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_text=salary_text,
        skills=skills,
        remote_type=remote_type,
        raw_body=full_text,
    )

    return save_job_markdown(job=job, output_dir=target_dir, force=force)


# ==============================================================================
# 検索ループ処理
# ==============================================================================

def search_levtech_direct(
    keyword: str = "",
    min_salary_man: int | None = None,
    remote: str | None = None,
    limit: int = 20,
    sort: str = "1",
    session: str = "job-hunt",
    ctx: EntrypointContext | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    """レバテックダイレクト求人を検索し、指定条件・上限件数まで取得する."""
    all_jobs: list[dict[str, Any]] = []
    page = 1
    total_count: int | None = None
    seen_ids: set[str] = set()

    while True:
        search_url = build_search_url(
            keyword=keyword,
            page=page,
            min_salary_man=min_salary_man,
            sort=sort,
        )
        if ctx:
            ctx.info(f"検索ページ取得中 (page {page}): {search_url}")

        html_content = fetch_html(search_url, session=session)
        if not html_content:
            if ctx:
                ctx.warn(f"ページ {page} の取得に失敗しました。")
            break

        page_jobs, page_total = parse_search_results(html_content)
        if page == 1:
            total_count = page_total
            if ctx and total_count is not None:
                ctx.info(f"検索総件数: {total_count} 件")

        if not page_jobs:
            break

        # 重複除外 & リモートフィルタ適用
        for job in page_jobs:
            jid = job["id"]
            if jid in seen_ids:
                continue
            seen_ids.add(jid)

            if remote:
                rem_lower = remote.lower()
                job_rem = job.get("remote_type", "").lower()
                matched_remote = False
                if rem_lower in job_rem:
                    matched_remote = True
                elif rem_lower in ("full", "fullremote", "full-remote", "完全在宅") and "フルリモート" in job_rem:
                    matched_remote = True
                elif rem_lower in ("hybrid", "リモート可") and "ハイブリッド" in job_rem:
                    matched_remote = True
                elif rem_lower in ("office", "onsite") and "出社" in job_rem:
                    matched_remote = True
                elif rem_lower in ("remote", "リモート") and any(k in job_rem for k in ("フルリモート", "ハイブリッド")):
                    matched_remote = True

                if not matched_remote:
                    continue

            all_jobs.append(job)
            if len(all_jobs) >= limit:
                break

        if len(all_jobs) >= limit:
            all_jobs = all_jobs[:limit]
            break

        # 安全上限: 最大15ページ（約180件）まで走査して見つからない場合は打ち切り
        if page >= 15:
            if ctx:
                ctx.warn(f"最大検索ページ数（15ページ）に達したため走査を終了します。")
            break

        # 総件数に達した場合
        if total_count is not None and len(seen_ids) >= total_count:
            break

        # ページネーション進行
        page += 1
        time.sleep(0.5)

    return all_jobs, total_count


# ==============================================================================
# CLI エントリポイント
# ==============================================================================

def main() -> None:
    """CLIエントリポイント (scripts-entrypoint.md 規約準拠)."""
    parser = create_search_parser(
        description="レバテックダイレクト 求人検索・一覧取得CLI",
        default_limit=20,
        default_download_limit=5,
    )
    # 追加オプション
    parser.add_argument(
        "--sort",
        choices=["new", "salary_max", "salary_min"],
        default="new",
        help="ソート順 (new: 新着順, salary_max: 年収上限が高い順, salary_min: 年収下限が低い順)",
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

    sort_val = SORT_MAP.get(args.sort, "1")

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        # 1. 検索実行
        jobs, total_count = search_levtech_direct(
            keyword=query_str,
            min_salary_man=min_sal_man,
            remote=args.remote,
            limit=args.limit or 20,
            sort=sort_val,
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
