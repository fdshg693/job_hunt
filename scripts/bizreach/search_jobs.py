"""ビズリーチの求人を条件検索し、一覧と詳細を Markdown 保存する CLI.

ビズリーチ求人検索・取得CLIスクリプト.
ビズリーチ（https://www.bizreach.jp/jobs/search/）において、
キーワード、年収、勤務地、リモート等の条件で求人を検索し、
結果一覧および求人詳細をローカルMarkdownとして永続化します。
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

# プロジェクトルートパス
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.bizreach.fetch_job import (
    DEFAULT_OUTPUT_DIR as DEFAULT_JOB_OUTPUT_DIR,
)
from scripts.bizreach.fetch_job import (
    fetch_and_save_bizreach_job,
)
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

BIZREACH_SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_SEARCH_OUTPUT_DIR = PROJECT_ROOT / "data" / "bizreach" / "searches"
BIZREACH_SEARCH_BASE_URL = "https://www.bizreach.jp/jobs/search/"

# 最低年収コードの対応テーブル（円単位）
INCOME_CODE_MAP: list[tuple[int, str]] = [
    (3000000, "A"),
    (4000000, "B"),
    (5000000, "C"),
    (6000000, "D"),
    (7000000, "E"),
    (8000000, "F"),
    (9000000, "G"),
    (10000000, "H"),
    (11000000, "I"),
    (12000000, "J"),
    (13000000, "K"),
    (14000000, "L"),
    (15000000, "M"),
    (16000000, "N"),
    (17000000, "O"),
    (18000000, "P"),
    (19000000, "Q"),
    (20000000, "R"),
    (25000000, "S"),
    (30000000, "T"),
    (50000000, "U"),
]


def salary_to_income_code(salary_yen: int) -> str | None:
    """円単位の年収数値をビズリーチの incomeCode に変換する."""
    matched_code = None
    for threshold, code in INCOME_CODE_MAP:
        if salary_yen >= threshold:
            matched_code = code
        else:
            break
    return matched_code


@dataclass
class BizreachJobItem:
    """ビズリーチ検索結果の求人アイテム."""

    id: str
    title: str
    company: str
    company_url: str
    url: str
    salary_text: str
    salary_min: int | None = None
    salary_max: int | None = None
    location: str = ""
    remote_type: str = "不明"
    appeals: list[str] = field(default_factory=list)
    job_role: str = ""
    industry: str = ""
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換する."""
        return asdict(self)


@dataclass
class BizreachSearchResult:
    """検索結果データ."""

    keyword: str
    page: int
    total_count: int
    jobs: list[BizreachJobItem]

    def to_dict(self) -> dict[str, Any]:
        return {
            "keyword": self.keyword,
            "page": self.page,
            "total_count": self.total_count,
            "returned_count": len(self.jobs),
            "jobs": [j.to_dict() for j in self.jobs],
        }


def build_search_url(
    keyword: str,
    page: int = 1,
    min_salary: int | None = None,
    remote: bool = False,
    recruitment_type: str | None = None,
) -> str:
    """検索条件からビズリーチの検索URLを構築する."""
    params: dict[str, Any] = {}
    if keyword:
        params["keyword"] = keyword
    if page > 1:
        params["pageNumber"] = page
    if min_salary is not None:
        code = salary_to_income_code(min_salary)
        if code:
            params["incomeCode"] = code
    if remote:
        params["specialConditionCodes"] = "REMOTE_WORK_AVAILABLE"
    if recruitment_type:
        params["recruitmentTypeCodes"] = recruitment_type

    params["sort"] = "RECOMMENDED"

    query_str = urlencode(params)
    return f"{BIZREACH_SEARCH_BASE_URL}?{query_str}" if query_str else BIZREACH_SEARCH_BASE_URL


def generate_search_script_content(target_url: str, limit: int) -> str:
    """検索画面用のPlaywright実行スクリプトを動的生成する."""
    js_target_url = json.dumps(target_url)
    return f"""async page => {{
  const targetUrl = {js_target_url};
  const limit = {limit};

  if (page.url() !== targetUrl) {{
    await page.goto(targetUrl, {{ waitUntil: 'domcontentloaded', timeout: 30000 }});
  }}

  try {{
    await page.waitForSelector(
      'div[class*="JobListItemWithCompanyLink"], div[class*="JobSearchResult"], h3:has-text("件"), div:has-text("該当する求人は見つかりませんでした")',
      {{ timeout: 15000 }}
    );
  }} catch (_) {{}}

  const result = await page.evaluate(limitCount => {{
    let totalCount = 0;
    const countCandidates = Array.from(document.querySelectorAll('h3, h2, p, span'));
    for (const el of countCandidates) {{
      const text = el.textContent ? el.textContent.trim() : '';
      const m = text.replace(/,/g, '').match(/^(\\d+)\\s*件$/) || text.replace(/,/g, '').match(/(\\d+)\\s*件/);
      if (m && (el.className.includes('JobSearch') || el.closest('section') || el.closest('main') || text.includes('件'))) {{
        const num = parseInt(m[1], 10);
        if (num > 0 && (totalCount === 0 || num > totalCount)) {{
          totalCount = num;
        }}
      }}
    }}

    let cardEls = Array.from(document.querySelectorAll('div[class*="JobListItemWithCompanyLink"][class*="card"]'));
    if (cardEls.length === 0) {{
      cardEls = Array.from(document.querySelectorAll('div[class*="card"]')).filter(el =>
        el.querySelector('a[href*="/jobs/"]')
      );
    }}

    const jobs = [];

    for (const card of cardEls) {{
      if (jobs.length >= limitCount) {{
        break;
      }}

      const linkEl =
        card.querySelector('a[class*="background-link"]') ||
        card.querySelector('a[href*="/jobs/"]');
      const href = linkEl ? linkEl.getAttribute('href') || '' : '';
      const idMatch = href.match(/\\/jobs\\/([a-zA-Z0-9_-]+)/);
      const id = idMatch ? idMatch[1] : '';
      const fullUrl = href.startsWith('http')
        ? href
        : href
        ? `https://www.bizreach.jp${{href}}`
        : '';

      const titleEl =
        card.querySelector('h3[class*="job-title"]') ||
        card.querySelector('h3') ||
        card.querySelector('a[class*="title"]');
      const title = titleEl ? titleEl.textContent.trim() : '';

      const salaryEl =
        card.querySelector('p[class*="color-accent-primary"]') ||
        card.querySelector('span[class*="color-accent-primary"]') ||
        card.querySelector('[class*="salary"]');
      const salaryText = salaryEl ? salaryEl.textContent.trim() : '';

      const compLinkEl =
        card.querySelector('a[class*="company-link"]') ||
        card.querySelector('a[href*="/company/view/"]');
      const compNameEl = compLinkEl
        ? compLinkEl.querySelector('p') || compLinkEl
        : card.querySelector('p[class*="company-name"]');
      const company = compNameEl ? compNameEl.textContent.trim() : '';
      const compHref = compLinkEl ? compLinkEl.getAttribute('href') || '' : '';
      const companyUrl = compHref.startsWith('http')
        ? compHref
        : compHref
        ? `https://www.bizreach.jp${{compHref}}`
        : '';

      const locEl =
        card.querySelector('div[aria-label="work-location"] p') ||
        card.querySelector('div[aria-label="work-location"]');
      const location = locEl ? locEl.textContent.trim() : '';

      const appealEls = Array.from(
        card.querySelectorAll('div[aria-label="appeals"] div[class*="Label"], div[aria-label="appeals"] span')
      );
      const appeals = appealEls
        .map(el => el.textContent.trim())
        .filter(t => t.length > 0 && !t.includes('\\n'));

      let jobRole = '';
      let industry = '';
      card.querySelectorAll('ul li, div[class*="meta"] span').forEach(li => {{
        const text = li.textContent.trim();
        if (text.includes('職種:') || text.includes('職種：')) {{
          jobRole = text.replace(/職種[:：]/, '').trim();
        }} else if (text.includes('業種:') || text.includes('業種：')) {{
          industry = text.replace(/業種[:：]/, '').trim();
        }}
      }});

      const snippetEl = card.querySelector('p[class*="snippet"], p[class*="description"]');
      const snippet = snippetEl ? snippetEl.textContent.trim() : '';

      if (id || title) {{
        jobs.append ? jobs.push({{
          id,
          title,
          company,
          companyUrl,
          url: fullUrl,
          salaryText,
          location,
          appeals,
          jobRole,
          industry,
          snippet
        }}) : jobs.push({{
          id,
          title,
          company,
          companyUrl,
          url: fullUrl,
          salaryText,
          location,
          appeals,
          jobRole,
          industry,
          snippet
        }});
      }}
    }}

    return {{
      totalCount,
      jobs
    }};
  }}, limit);

  return {{
    success: true,
    url: page.url(),
    ...result
  }};
}};
"""


def filter_jobs(
    jobs: list[BizreachJobItem],
    min_salary: int | None = None,
    skills: list[str] | None = None,
    remote_type: str | None = None,
) -> list[BizreachJobItem]:
    """クライアント側での追加フィルタリング."""
    matched = []
    for job in jobs:
        if min_salary is not None:
            effective_max = job.salary_max if job.salary_max is not None else job.salary_min
            if effective_max is not None and effective_max < min_salary:
                continue

        if skills:
            card_blob = f"{job.title} {' '.join(job.appeals)} {job.snippet}".lower()
            if not all(sk.lower() in card_blob for sk in skills):
                continue

        if remote_type:
            if remote_type.lower() not in job.remote_type.lower():
                continue

        matched.append(job)

    return matched


def print_search_summary(
    result: BizreachSearchResult,
    jobs: list[BizreachJobItem],
    detail: bool = False,
    limit: int | None = None,
) -> None:
    """検索結果をコンソールに整形出力する."""
    kw_disp = f"'{result.keyword}'" if result.keyword else "（全件）"
    print("\n========================================================")
    print(f" ビズリーチ 求人検索結果: {kw_disp}")
    print(f" 該当件数: 全 {result.total_count} 件 (このページ: {len(result.jobs)} 件 / 条件一致: {len(jobs)} 件)")
    print("========================================================\n")

    display_jobs = jobs[:limit] if limit else jobs
    if not display_jobs:
        print("条件に一致する求人は見つかりませんでした。")
        return

    for idx, job in enumerate(display_jobs, start=1):
        salary_disp = format_salary_display(job.salary_min, job.salary_max, job.salary_text)
        print(f"[{idx}] {job.company} | {job.title}")
        print(f"    - URL:      {job.url} (ID: {job.id})")
        print(f"    - 想定年収: {salary_disp} | 勤務地: {job.location or '未記載'} | リモート: {job.remote_type}")
        if job.appeals:
            print(f"    - 特徴:     {', '.join(job.appeals[:6])}")
        if job.job_role:
            print(f"    - 職種:     {job.job_role}")
        if detail and job.snippet:
            print(f"    - 概要:     {job.snippet[:120]}...")
        print("-" * 56)


def main() -> None:
    parser = create_search_parser(
        examples=[
            'uv run python scripts/bizreach/search_jobs.py "Python" -n 10 --summary',
            'uv run python scripts/bizreach/search_jobs.py "Go" --min-salary 800 --remote フルリモート --download --download-limit 5',
        ],
        related=[
            "scripts/bizreach/fetch_job.py: 次に使う（個別求人の詳細を取得）",
            "scripts/common/search_local_jobs.py: 次に使う（保存済み求人を横断検索）",
        ],
        description="ビズリーチ求人検索スクリプト",
        default_limit=20,
        default_download_limit=5,
    )
    parser.add_argument("--page", type=int, default=1, help="ページ番号 (デフォルト: 1)")
    parser.add_argument(
        "--recruitment-type",
        choices=["DIRECT_RECRUITMENT", "HEADHUNTER"],
        help="募集形態フィルタ (DIRECT_RECRUITMENT: 企業直募, HEADHUNTER: ヘッドハンター)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_JOB_OUTPUT_DIR,
        help=f"ダウンロード保存先 (デフォルト: {DEFAULT_JOB_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--searches-dir",
        type=Path,
        default=DEFAULT_SEARCH_OUTPUT_DIR,
        help=f"検索結果保存先 (デフォルト: {DEFAULT_SEARCH_OUTPUT_DIR})",
    )
    parser.add_argument("--dry-run", action="store_true", help="ファイル保存を行わずプレビューする")
    parser.add_argument("--keep-open", action="store_true", help="処理完了後にブラウザセッションを維持")

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    # 検索クエリの結合
    keywords = list(args.query)
    if args.keywords:
        keywords.extend(args.keywords)
    keyword = " ".join(keywords).strip()

    min_salary_int = parse_salary_arg(args.min_salary) if args.min_salary else None

    # 検索URLの構築
    search_url = build_search_url(
        keyword=keyword,
        page=args.page,
        min_salary=min_salary_int,
        remote=bool(args.remote),
        recruitment_type=args.recruitment_type,
    )

    profile_dir = resolve_profile_path(args.session)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. 共通認証エンジンによる認証状態確認・ハンドオフ
        ensure_site_authenticated(
            site="bizreach",
            session=args.session,
            target_url="https://www.bizreach.jp/jobs/search/",
            headed=args.headed,
            timeout=args.timeout,
            no_notify=args.no_notify,
            profile_dir=profile_dir,
            exit_on_fail=True,
        )

        # 2. 求人検索・一覧データ抽出（run_code_snippetで安全に実行）
        search_script_code = generate_search_script_content(search_url, args.limit)
        search_raw = run_code_snippet(args.session, search_script_code, timeout=30)
        if not search_raw or not search_raw.get("success"):
            ctx.error("求人検索画面のナビゲートまたはデータ取得に失敗しました。")
            sys.exit(1)

        # JobItem への変換とフィールド補正
        raw_jobs = search_raw.get("jobs", [])
        job_items: list[BizreachJobItem] = []
        for rj in raw_jobs:
            sal_text = rj.get("salaryText", "")
            s_min, s_max = parse_salary_range(sal_text)
            loc = rj.get("location", "")
            r_type = detect_remote_type(loc, f"{rj.get('title', '')} {' '.join(rj.get('appeals', []))} {rj.get('snippet', '')}")

            item = BizreachJobItem(
                id=rj.get("id", ""),
                title=rj.get("title", ""),
                company=rj.get("company", ""),
                company_url=rj.get("companyUrl", ""),
                url=rj.get("url", ""),
                salary_text=sal_text,
                salary_min=s_min,
                salary_max=s_max,
                location=loc,
                remote_type=r_type,
                appeals=rj.get("appeals", []),
                job_role=rj.get("jobRole", ""),
                industry=rj.get("industry", ""),
                snippet=rj.get("snippet", ""),
            )
            job_items.append(item)

        search_result = BizreachSearchResult(
            keyword=keyword,
            page=args.page,
            total_count=search_raw.get("totalCount", len(job_items)),
            jobs=job_items,
        )

        # 3. クライアント側フィルタリング
        matched_jobs = filter_jobs(
            search_result.jobs,
            min_salary=min_salary_int,
            skills=args.skills,
            remote_type="リモート" if args.remote else None,
        )
        display_jobs = matched_jobs[: args.limit] if args.limit else matched_jobs

        update_profile_last_used(args.session)

        # 4. 検索結果ファイル保存
        saved_md_path: Path | None = None
        if not args.no_save and not args.dry_run:
            saved_md_path, _ = save_search_result(
                source="bizreach",
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
            targets = [j for j in display_jobs[: args.download_limit] if j.id]
            if not targets:
                ctx.log("[ダウンロード] 保存対象の求人がありません。")
            else:
                if args.summary:
                    ctx.log(f"\n>>> 求人詳細をダウンロード中 (上限: {args.download_limit} 件) <<<")

                success_cnt = 0
                error_cnt = 0
                for t in targets:
                    try:
                        p, _ = fetch_and_save_bizreach_job(
                            url_or_id=t.url or t.id,
                            session=args.session,
                            output_dir=args.output_dir,
                            force=args.force,
                            dry_run=args.dry_run,
                            summary=args.summary,
                            initial_location=t.location,
                            initial_tags=t.appeals,
                        )
                        if p:
                            ctx.add_result_path(p)
                            success_cnt += 1
                        time.sleep(0.5)
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

        sys.exit(ctx.flush_outputs(summary_fn=summary_fn, json_data=json_payload))

    finally:
        if not args.keep_open:
            run_playwright_cmd([f"-s={args.session}", "close"], timeout=10)


if __name__ == "__main__":
    main()
