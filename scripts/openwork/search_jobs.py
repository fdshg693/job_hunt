"""OpenWork の求人を条件検索し、一覧と詳細を Markdown 保存する CLI.

OpenWork求人検索・取得CLIスクリプト.
OpenWork（https://www.openwork.jp/job_search_result）において、
キーワード、年収、勤務地、リモート等の条件で求人を検索し、
結果一覧および求人詳細をローカルMarkdownとして永続化します。
"""

from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/openwork/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.auth_engine import ensure_site_authenticated
from scripts.common.browser_auth import (
    resolve_profile_path,
    run_code_snippet,
    run_playwright_cmd,
    update_profile_last_used,
)
from scripts.common.cli import EntrypointContext, create_search_parser, to_relative_path
from scripts.common.normalizers import (
    detect_remote_type,
    format_salary_display,
    parse_salary_arg,
    parse_salary_range,
)
from scripts.common.storage import save_search_result
from scripts.openwork.fetch_job import (
    DEFAULT_OUTPUT_DIR as DEFAULT_JOB_OUTPUT_DIR,
)
from scripts.openwork.fetch_job import (
    HTTP_HEADERS,
    USER_AGENT,
    fetch_and_save_openwork_job,
)

OPENWORK_SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_SEARCH_OUTPUT_DIR = PROJECT_ROOT / "data" / "openwork" / "searches"
OPENWORK_SEARCH_BASE_URL = "https://www.openwork.jp/job_search_result"


@dataclass
class OpenWorkJobItem:
    """OpenWork検索結果の求人アイテム."""

    id: str
    title: str
    company: str
    company_score: str = ""
    company_id: str = ""
    url: str = ""
    salary_text: str = ""
    salary_min: int | None = None
    salary_max: int | None = None
    location: str = ""
    remote_type: str = "不明"
    job_role: str = ""
    industry: str = ""
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換する."""
        return asdict(self)


@dataclass
class OpenWorkSearchResult:
    """OpenWork検索結果."""

    keyword: str
    page: int
    total_count: int
    jobs: list[OpenWorkJobItem]

    def to_dict(self) -> dict[str, Any]:
        return {
            "keyword": self.keyword,
            "page": self.page,
            "total_count": self.total_count,
            "returned_count": len(self.jobs),
            "jobs": [j.to_dict() for j in self.jobs],
        }


def build_search_url(
    keyword: str = "",
    page: int = 1,
    min_salary_man: int | None = None,
    remote: bool = False,
    recruitment_type: str = "all",
    sort: str = "std",
) -> str:
    """OpenWorkの求人検索URLを生成する."""
    params: dict[str, Any] = {}
    if keyword:
        params["keyword"] = keyword
    if page > 1:
        params["p"] = page
    if min_salary_man:
        params["sa"] = min_salary_man
    if remote:
        params["cond_remote"] = 1

    if recruitment_type == "direct":
        params["rec_type"] = 1
    elif recruitment_type == "agent":
        params["rec_type"] = 2

    if sort == "new":
        params["sort"] = 2
    elif sort == "total":
        params["sort"] = 3

    query_str = urllib.parse.urlencode(params)
    return f"{OPENWORK_SEARCH_BASE_URL}?{query_str}" if query_str else OPENWORK_SEARCH_BASE_URL


def fetch_search_via_http(url: str) -> tuple[str | None, int]:
    """urllib.request 経由で静的HTMLを取得する."""
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html_content = resp.read().decode("utf-8", errors="replace")
            return html_content, resp.getcode()
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception:
        return None, 0


def fetch_search_via_playwright(
    url: str,
    session: str = "job-hunt",
    profile_path: str | None = None,
    timeout: int = 120,
    no_notify: bool = False,
) -> str | None:
    """Playwright CLIセッション経由で検索ページを取得する（CAPTCHA対応）."""
    profile_dir = resolve_profile_path(session, profile_path)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    # 1. セッション起動確認
    open_args = [f"-s={session}", "open", "about:blank", f"--profile={profile_dir}"]
    run_playwright_cmd(open_args, timeout=30)

    # 2. 検索画面アクセス用JSコード生成
    js_url = json.dumps(url)
    script_code = f"""async page => {{
  const client = await page.context().newCDPSession(page);
  await client.send('Network.setUserAgentOverride', {{
    userAgent: {json.dumps(USER_AGENT)},
    acceptLanguage: 'ja,en-US;q=0.9,en;q=0.8',
    platform: 'Win32'
  }});

  const resp = await page.goto({js_url}, {{ waitUntil: 'domcontentloaded', timeout: 30000 }});
  const title = await page.title();
  const onAuthWall = title.includes('画像認証') || title.includes('403 Forbidden');

  return {{
    success: true,
    status: resp ? resp.status() : 0,
    title,
    onAuthWall,
    html: await page.content(),
    url: page.url()
  }};
}};"""

    res = run_code_snippet(session, script_code, timeout=35)
    if not res or not res.get("success"):
        return None

    # CAPTCHA壁の検知
    if res.get("onAuthWall"):
        cleared = ensure_site_authenticated(
            site="openwork",
            session=session,
            target_url=url,
            timeout=timeout,
            no_notify=no_notify,
            profile_dir=profile_dir,
            exit_on_fail=False,
        )
        if not cleared:
            return None

        # 解除後に再リクエスト
        res = run_code_snippet(session, script_code, timeout=35)
        if not res:
            return None

    return res.get("html")


def extract_search_data_from_html(html_content: str) -> tuple[int, list[dict[str, Any]]]:
    """検索結果HTMLから総件数と求人カード配列を抽出する."""
    total_count = 0
    m_count = re.search(r"該当件数\s*[:：]?\s*([0-9,]+)\s*件", html_content)
    if m_count:
        total_count = int(m_count.group(1).replace(",", ""))
    else:
        m_count2 = re.search(r'class="[^"]*searchResult_count[^"]*"[^>]*>([0-9,]+)<', html_content)
        if m_count2:
            total_count = int(m_count2.group(1).replace(",", ""))

    raw_items: list[dict[str, Any]] = []
    card_pattern = re.compile(
        r'<article[^>]*class="[^"]*jobSearch_item[^"]*"[^>]*>(.*?)</article>',
        re.DOTALL | re.IGNORECASE,
    )
    cards = card_pattern.findall(html_content)

    if not cards:
        card_pattern2 = re.compile(
            r'<div[^>]*class="[^"]*jobSearch_item[^"]*"[^>]*>(.*?)</div>\s*(?=<div[^>]*class="[^"]*jobSearch_item|<footer|</main|$)',
            re.DOTALL | re.IGNORECASE,
        )
        cards = card_pattern2.findall(html_content)

    for c in cards:
        # 求人ID
        m_id = re.search(r'data-_vmodal-job-id="([0-9]+)"', c)
        job_id = m_id.group(1) if m_id else ""
        if not job_id:
            m_j = re.search(r'href="[^"]*[?&]j=([a-zA-Z0-9_-]+)', c)
            job_id = m_j.group(1) if m_j else ""

        # 企業名
        m_comp = re.search(r'<a[^>]*class="[^"]*jobSearch_companyName[^"]*"[^>]*>(.*?)</a>', c, re.DOTALL)
        company = re.sub(r"<[^>]+>", "", m_comp.group(1)).strip() if m_comp else ""
        company = html.unescape(company)

        # 企業スコア
        m_score = re.search(r'<span[^>]*class="[^"]*score[^"]*"[^>]*>(.*?)</span>', c, re.DOTALL)
        company_score = re.sub(r"<[^>]+>", "", m_score.group(1)).strip() if m_score else ""

        # 企業ID
        m_cid = re.search(r'href="/company/m/([a-zA-Z0-9_-]+)"', c)
        company_id = m_cid.group(1) if m_cid else ""

        # 求人タイトル
        m_title = re.search(r'<h3[^>]*class="[^"]*jobSearch_jobTitle[^"]*"[^>]*>(.*?)</h3>', c, re.DOTALL)
        if not m_title:
            m_title = re.search(r'<a[^>]*class="[^"]*jobSearch_jobTitle[^"]*"[^>]*>(.*?)</a>', c, re.DOTALL)
        title = re.sub(r"<[^>]+>", "", m_title.group(1)).strip() if m_title else ""
        title = html.unescape(title)

        # 求人URL
        m_url = re.search(r'<a[^>]*href="(/company/[^"]*recruit\?j=[^"]*)"', c)
        if not m_url:
            m_url = re.search(r'<a[^>]*href="(/company/[^"]*recruit/[^"]*)"', c)
        rel_url = m_url.group(1) if m_url else ""
        full_url = f"https://www.openwork.jp{rel_url}" if rel_url.startswith("/") else rel_url

        # 給与・年収
        m_sal = re.search(r'<dl[^>]*class="[^"]*jobSearch_salary[^"]*"[^>]*>.*?<dd[^>]*>(.*?)</dd>', c, re.DOTALL)
        salary_text = re.sub(r"<[^>]+>", "", m_sal.group(1)).strip() if m_sal else ""
        salary_text = html.unescape(salary_text)

        # 勤務地
        m_loc = re.search(r'<dl[^>]*class="[^"]*jobSearch_location[^"]*"[^>]*>.*?<dd[^>]*>(.*?)</dd>', c, re.DOTALL)
        location = re.sub(r"<[^>]+>", "", m_loc.group(1)).strip() if m_loc else ""
        location = html.unescape(location)

        # 職種・業種
        m_role = re.search(r'<dl[^>]*class="[^"]*jobSearch_role[^"]*"[^>]*>.*?<dd[^>]*>(.*?)</dd>', c, re.DOTALL)
        job_role = re.sub(r"<[^>]+>", "", m_role.group(1)).strip() if m_role else ""
        job_role = html.unescape(job_role)

        # 概要・スニペット
        m_snip = re.search(r'<p[^>]*class="[^"]*jobSearch_snippet[^"]*"[^>]*>(.*?)</p>', c, re.DOTALL)
        snippet = re.sub(r"<[^>]+>", "", m_snip.group(1)).strip() if m_snip else ""
        snippet = html.unescape(snippet)

        if title or company:
            raw_items.append({
                "id": job_id,
                "title": title,
                "company": company,
                "company_score": company_score,
                "company_id": company_id,
                "url": full_url,
                "salary_text": salary_text,
                "location": location,
                "job_role": job_role,
                "snippet": snippet,
                "card_html": c,
            })

    return total_count, raw_items


def convert_raw_items_to_job_items(raw_items: list[dict[str, Any]]) -> list[OpenWorkJobItem]:
    """生抽出データを OpenWorkJobItem リストに正規化変換する."""
    job_items: list[OpenWorkJobItem] = []
    for r in raw_items:
        sal_min, sal_max = parse_salary_range(r["salary_text"])
        r_type = detect_remote_type(r["location"], f"{r['title']} {r['snippet']}")

        job_items.append(
            OpenWorkJobItem(
                id=r["id"],
                title=r["title"],
                company=r["company"],
                company_score=r["company_score"],
                company_id=r["company_id"],
                url=r["url"],
                salary_text=r["salary_text"],
                salary_min=sal_min,
                salary_max=sal_max,
                location=r["location"],
                remote_type=r_type,
                job_role=r["job_role"],
                snippet=r["snippet"],
            )
        )
    return job_items


def filter_jobs(
    jobs: list[OpenWorkJobItem],
    min_salary: int | None = None,
    skills: list[str] | None = None,
    remote_only: bool = False,
) -> list[OpenWorkJobItem]:
    """クライアント側での追加フィルタリング."""
    matched: list[OpenWorkJobItem] = []
    for job in jobs:
        if min_salary is not None:
            effective_max = job.salary_max if job.salary_max is not None else job.salary_min
            if effective_max is not None and effective_max < min_salary:
                continue

        if skills:
            card_blob = f"{job.title} {job.snippet}".lower()
            if not all(sk.lower() in card_blob for sk in skills):
                continue

        if remote_only:
            if "リモート" not in job.remote_type:
                continue

        matched.append(job)

    return matched


def print_search_summary(
    result: OpenWorkSearchResult,
    jobs: list[OpenWorkJobItem],
    detail: bool = False,
    limit: int | None = None,
) -> None:
    """コンソールに検索結果サマリを整形出力する."""
    kw_disp = f"'{result.keyword}'" if result.keyword else "（全件）"
    print("\n========================================================")
    print(f" OpenWork 求人検索結果: {kw_disp}")
    print(f" 該当件数: 全 {result.total_count} 件 (取得: {len(result.jobs)} 件 / 条件一致: {len(jobs)} 件)")
    print("========================================================\n")

    display_jobs = jobs[:limit] if limit else jobs
    if not display_jobs:
        print("条件に一致する求人は見つかりませんでした。")
        return

    for idx, job in enumerate(display_jobs, start=1):
        salary_disp = format_salary_display(job.salary_min, job.salary_max, job.salary_text)
        score_disp = f"★{job.company_score}" if job.company_score else "スコアなし"

        print(f"[{idx}] {job.company} ({score_disp}) | {job.title}")
        print(f"    - URL:    {job.url} (ID: {job.id})")
        print(f"    - 年収:   {salary_disp} | 勤務地: {job.location or '未設定'} | リモート: {job.remote_type}")
        if job.job_role or job.industry:
            print(f"    - カテゴリ: {job.job_role} / {job.industry}")
        if detail and job.snippet:
            print(f"    - 概要:   {job.snippet}")
        print("-" * 56)


def main() -> None:
    """CLIエントリポイント."""
    parser = create_search_parser(
        examples=[
            'uv run python scripts/openwork/search_jobs.py "Python" -n 10 --summary',
            'uv run python scripts/openwork/search_jobs.py "Go" --min-salary 800 --remote フルリモート -n 5 --download',
        ],
        related=[
            "scripts/openwork/fetch_job.py: 次に使う（個別求人の詳細を取得）",
            "scripts/openwork/fetch_reviews.py: 次に使う（企業の口コミを確認）",
        ],
        description="OpenWorkの求人を検索し、結果一覧・詳細Markdownを保存します。",
        default_limit=20,
        default_download_limit=5,
    )
    parser.add_argument("-p", "--page", type=int, default=1, help="ページ番号 (デフォルト: 1)")
    parser.add_argument(
        "--recruitment-type",
        choices=["all", "direct", "agent"],
        default="all",
        help="応募タイプ (all: すべて, direct: 直接応募, agent: エージェント)",
    )
    parser.add_argument(
        "--sort",
        choices=["std", "new", "total"],
        default="std",
        help="並び順 (std: 標準, new: 新着, total: スコア順)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_JOB_OUTPUT_DIR,
        help=f"求人詳細保存先ディレクトリ (デフォルト: {DEFAULT_JOB_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--searches-dir",
        type=Path,
        default=DEFAULT_SEARCH_OUTPUT_DIR,
        help=f"検索結果保存先 (デフォルト: {DEFAULT_SEARCH_OUTPUT_DIR})",
    )
    parser.add_argument("--dry-run", action="store_true", help="ファイル保存を行わずプレビューする")
    parser.add_argument("--profile-path", default=None, help="ブラウザプロファイルパス（省略時は自動解決）")
    parser.add_argument("--keep-open", action="store_true", help="処理完了後にブラウザセッションを維持")

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    # 検索クエリの結合
    keywords = list(args.query)
    if args.keywords:
        keywords.extend(args.keywords)
    keyword = " ".join(keywords).strip()

    min_salary_int = parse_salary_arg(args.min_salary) if args.min_salary else None
    min_salary_man = int(min_salary_int / 10000) if min_salary_int else None

    search_url = build_search_url(
        keyword=keyword,
        page=args.page,
        min_salary_man=min_salary_man,
        remote=bool(args.remote),
        recruitment_type=args.recruitment_type,
        sort=args.sort,
    )

    # 1. 静的HTTPリクエストを試行
    html_content, status_code = fetch_search_via_http(search_url)

    if status_code == 404:
        total_count = 0
        raw_items: list[dict[str, Any]] = []
    else:
        is_blocked = (
            not html_content
            or "画像認証" in html_content
            or "403 Forbidden" in html_content
            or status_code in (403, 429)
        )

        # 2. ブロックされた場合は Playwright 経由で取得
        if is_blocked:
            html_content = fetch_search_via_playwright(
                url=search_url,
                session=args.session,
                profile_path=args.profile_path,
                timeout=args.timeout,
                no_notify=args.no_notify,
            )

        if not html_content or "画像認証" in html_content:
            ctx.error("求人検索画面のナビゲートまたはデータ取得に失敗しました。")
            sys.exit(1)

        total_count, raw_items = extract_search_data_from_html(html_content)

    job_items = convert_raw_items_to_job_items(raw_items)

    search_result = OpenWorkSearchResult(
        keyword=keyword,
        page=args.page,
        total_count=total_count or len(job_items),
        jobs=job_items,
    )

    # 3. クライアント側フィルタリング
    matched_jobs = filter_jobs(
        search_result.jobs,
        min_salary=min_salary_int,
        skills=args.skills,
        remote_only=bool(args.remote),
    )
    display_jobs = matched_jobs[: args.limit] if args.limit else matched_jobs

    update_profile_last_used(args.session)

    # 4. 検索結果ファイル保存
    saved_md_path: Path | None = None
    if not args.no_save and not args.dry_run:
        saved_md_path, _ = save_search_result(
            source="openwork",
            keyword=keyword,
            jobs=[j.to_dict() for j in display_jobs],
            total_count=search_result.total_count,
            returned_count=len(search_result.jobs),
            output_dir=args.searches_dir,
            metadata={"page": args.page},
        )
        ctx.add_result_path(saved_md_path)

    # 5. 求人詳細ダウンロード (--download)
    if args.download:
        targets = [j for j in display_jobs[: args.download_limit] if j.url]
        if not targets:
            ctx.log("[ダウンロード] 保存対象の求人がありません。")
        else:
            if args.summary:
                ctx.log(f"\n>>> 求人詳細をダウンロード中 (上限: {args.download_limit} 件) <<<")

            success_cnt = 0
            error_cnt = 0
            for t in targets:
                try:
                    p, _ = fetch_and_save_openwork_job(
                        url_or_id=t.url,
                        session=args.session,
                        output_dir=args.output_dir,
                        force=args.force,
                        dry_run=args.dry_run,
                        summary=args.summary,
                        initial_company=t.company,
                        initial_title=t.title,
                        initial_score=t.company_score,
                        timeout=args.timeout,
                        no_notify=args.no_notify,
                    )
                    if p:
                        ctx.add_result_path(p)
                        success_cnt += 1
                    time.sleep(1.0)
                except Exception as ex:
                    ctx.error(f"{t.id} ({t.title}): {ex}")
                    error_cnt += 1

            if args.summary:
                ctx.log(f"\nダウンロード完了: 成功 {success_cnt} 件 / エラー {error_cnt} 件")
            if error_cnt > 0 and success_cnt == 0:
                ctx.set_exit_code(1)

    json_payload = {
        "keyword": keyword,
        "page": args.page,
        "total_count": search_result.total_count,
        "returned_count": len(search_result.jobs),
        "matched_count": len(matched_jobs),
        "jobs": [j.to_dict() for j in display_jobs],
    }

    def summary_fn() -> None:
        print_search_summary(
            result=search_result,
            jobs=matched_jobs,
            detail=args.detail,
            limit=args.limit,
        )
        if saved_md_path:
            ctx.log(f"\n[検索結果保存] {to_relative_path(saved_md_path)}")

    if not args.keep_open:
        run_playwright_cmd([f"-s={args.session}", "close"], timeout=10)

    sys.exit(ctx.flush_outputs(summary_fn=summary_fn, json_data=json_payload))


if __name__ == "__main__":
    main()
