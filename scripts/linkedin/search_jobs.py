"""LinkedIn で求人をキーワード・勤務地で検索し一覧・詳細を保存する CLI.

LinkedIn 求人検索・取得CLIスクリプト.

LinkedIn（https://www.linkedin.com/jobs/search/）において、
キーワード、勤務地、リモート等の条件で求人を検索し、
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
    extract_skills_from_text,
    format_salary_display,
    parse_salary_arg,
    parse_salary_range,
)
from scripts.common.storage import save_search_result
from scripts.linkedin.fetch_job import (
    DEFAULT_OUTPUT_DIR as DEFAULT_JOB_OUTPUT_DIR,
)
from scripts.linkedin.fetch_job import (
    fetch_and_save_linkedin_job,
)

LINKEDIN_SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_SEARCH_OUTPUT_DIR = PROJECT_ROOT / "data" / "linkedin" / "searches"
LINKEDIN_SEARCH_BASE_URL = "https://www.linkedin.com/jobs/search/"


@dataclass
class LinkedInJobItem:
    """LinkedIn検索結果の求人アイテム."""

    id: str
    title: str
    company: str
    company_url: str
    url: str
    salary_text: str = ""
    salary_min: int | None = None
    salary_max: int | None = None
    location: str = ""
    remote_type: str = "出社"
    tags: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換する."""
        return asdict(self)


@dataclass
class LinkedInSearchResult:
    """検索結果データ."""

    keyword: str
    location: str
    page: int
    total_count: int
    jobs: list[LinkedInJobItem]

    def to_dict(self) -> dict[str, Any]:
        return {
            "keyword": self.keyword,
            "location": self.location,
            "page": self.page,
            "total_count": self.total_count,
            "returned_count": len(self.jobs),
            "jobs": [j.to_dict() for j in self.jobs],
        }


def build_search_url(
    keyword: str,
    location: str = "Tokyo, Japan",
    page: int = 1,
    remote: str | bool | None = None,
    sort_by: str = "relevance",
) -> str:
    """検索条件からLinkedInの検索URLを構築する."""
    params: dict[str, Any] = {}
    if keyword:
        params["keywords"] = keyword
    if location:
        params["location"] = location
    if page > 1:
        params["start"] = (page - 1) * 25

    # ソート順
    if sort_by == "recent":
        params["sortBy"] = "DD"
    else:
        params["sortBy"] = "R"

    # リモートフィルター (f_WT)
    # 1: On-site, 2: Remote, 3: Hybrid
    if remote:
        rem_str = str(remote).lower().strip()
        if rem_str in ("2", "remote", "フルリモート", "true"):
            params["f_WT"] = "2"
        elif rem_str in ("3", "hybrid", "ハイブリッド"):
            params["f_WT"] = "3"
        elif rem_str in ("1", "onsite", "on-site", "出社"):
            params["f_WT"] = "1"
        else:
            # 汎用リモート指定ならリモートまたはハイブリッド
            params["f_WT"] = "2,3"

    query_str = urlencode(params)
    return f"{LINKEDIN_SEARCH_BASE_URL}?{query_str}" if query_str else LINKEDIN_SEARCH_BASE_URL


def generate_search_script_content(target_url: str, limit: int) -> str:
    """LinkedIn検索画面用のPlaywright実行スクリプトを動的生成する."""
    js_target_url = json.dumps(target_url)
    return f"""async page => {{
  const targetUrl = {js_target_url};
  const limit = {limit};

  if (page.url() !== targetUrl) {{
    await page.goto(targetUrl, {{ waitUntil: 'domcontentloaded', timeout: 35000 }});
  }}

  // 認証壁・リダイレクト判定
  const currentUrl = page.url();
  const isAuthWall = /linkedin\\.com\\/(?:authwall|login|checkpoint|uas\\/login)/i.test(currentUrl);
  if (isAuthWall) {{
    return {{
      success: false,
      error: 'auth_required',
      url: currentUrl
    }};
  }}

  // 求人カードまたは結果コンテナの出現待機
  try {{
    await page.waitForSelector(
      'ul.scaffold-layout__list-container, li[data-occludable-job-id], div.job-card-container, .jobs-search-results-list, div:has-text("No matching jobs found"), div:has-text("一致する求人は見つかりませんでした")',
      {{ timeout: 15000 }}
    );
  }} catch (_) {{}}

  // LinkedInのリストはバーチャルスクロールを採用しているため、リストコンテナをスクロールしてDOMをロードさせる
  try {{
    const scrollContainer = await page.$('.jobs-search-results-list');
    if (scrollContainer) {{
      for (let s = 0; s < 4; s++) {{
        await page.evaluate(el => {{
          el.scrollTop += el.clientHeight * 0.8;
        }}, scrollContainer);
        await page.waitForTimeout(600);
      }}
    }}
  }} catch (_) {{}}

  const result = await page.evaluate(limitCount => {{
    const textOf = el => (el ? el.textContent.trim() : '');

    // 総件数の抽出
    let totalCount = 0;
    const countEl =
      document.querySelector('.jobs-search-results-list__subtitle') ||
      document.querySelector('small.jobs-search-results-list__text') ||
      document.querySelector('.jobs-search-results-list__title-heading');
    if (countEl) {{
      const countText = textOf(countEl).replace(/,/g, '');
      const m = countText.match(/(\\d+)\\s*(?:件|results)/i) || countText.match(/(\\d+)/);
      if (m) {{
        totalCount = parseInt(m[1], 10);
      }}
    }}

    // 求人カードの収集
    let cardEls = Array.from(
      document.querySelectorAll('li.scaffold-layout__list-item[data-occludable-job-id], div.job-card-container')
    );

    if (cardEls.length === 0) {{
      cardEls = Array.from(document.querySelectorAll('li[data-occludable-job-id]'));
    }}

    const jobs = [];
    const seenIds = new Set();

    for (const card of cardEls) {{
      if (jobs.length >= limitCount) {{
        break;
      }}

      // ID抽出
      let id = card.getAttribute('data-occludable-job-id') || card.getAttribute('data-job-id') || '';
      if (!id) {{
        const linkWithId = card.querySelector('a[href*="/jobs/view/"], a[data-control-name="job_card_click"]');
        if (linkWithId) {{
          const href = linkWithId.getAttribute('href') || '';
          const m = href.match(/\\/jobs\\/view\\/(\\d+)/) || href.match(/currentJobId=(\\d+)/);
          if (m) {{
            id = m[1];
          }}
        }}
      }}

      if (id && seenIds.has(id)) {{
        continue;
      }}
      if (id) {{
        seenIds.add(id);
      }}

      // タイトル & URL
      const titleLink =
        card.querySelector('a.job-card-list__title--link') ||
        card.querySelector('a.job-card-container__link') ||
        card.querySelector('a[href*="/jobs/view/"]');
      let title = '';
      const strongEl = card.querySelector('a.job-card-list__title--link strong, a.job-card-container__link strong');
      if (strongEl) {{
        title = textOf(strongEl);
      }} else if (titleLink) {{
        title = titleLink.getAttribute('aria-label') || textOf(titleLink);
      }}
      title = title.replace(/\\s*with verification\\s*/i, '').trim();
      if (title.includes('\\n')) {{
        const lines = title.split('\\n').map(s => s.trim()).filter(Boolean);
        title = lines[0] || title;
      }}

      const href = titleLink ? titleLink.getAttribute('href') || '' : '';
      const fullUrl = id ? `https://www.linkedin.com/jobs/view/${{id}}/` : (href.startsWith('http') ? href : `https://www.linkedin.com${{href}}`);

      // 企業名 & URL
      const compEl =
        card.querySelector('.artdeco-entity-lockup__subtitle') ||
        card.querySelector('[class*="company-name"]') ||
        card.querySelector('.job-card-container__company-name');
      const company = textOf(compEl);

      const compLink = card.querySelector('a[href*="/company/"]');
      const compHref = compLink ? compLink.getAttribute('href') || '' : '';
      const companyUrl = compHref.startsWith('http') ? compHref : compHref ? `https://www.linkedin.com${{compHref}}` : '';

      // 勤務地
      const locEl =
        card.querySelector('.artdeco-entity-lockup__caption') ||
        card.querySelector('[class*="metadata-item"]') ||
        card.querySelector('.job-card-container__metadata-item');
      const location = textOf(locEl);

      // タグ・バッジ
      const tagEls = Array.from(card.querySelectorAll('.job-card-container__footer-item, [class*="footer-item"]'));
      const tags = tagEls.map(el => textOf(el)).filter(t => t.length > 0 && !t.includes('\\n'));

      // スニペット・付加情報
      const snippetEl = card.querySelector('.job-card-list__insight, [class*="job-insight"]');
      const snippet = textOf(snippetEl);

      if (id || title) {{
        jobs.push({{
          id: id || `linkedin_${{jobs.length + 1}}`,
          title,
          company,
          companyUrl,
          url: fullUrl,
          location,
          tags,
          snippet
        }});
      }}
    }}

    return {{
      totalCount: totalCount || jobs.length,
      jobs
    }};
  }}, limit);

  return {{
    success: true,
    url: page.url(),
    ...result
  }};
}}
"""


def parse_linkedin_remote_type(location_text: str, combined_text: str) -> str:
    """LinkedIn特有の英語表記（Hybrid, Remote, On-site）を考慮したリモート判定."""
    blob = f"{location_text or ''} {combined_text or ''}".lower()
    if "(hybrid)" in blob or "hybrid" in blob:
        return "ハイブリッド"
    if "(remote)" in blob or "remote" in blob or "フルリモート" in blob:
        return "フルリモート"
    if "(on-site)" in blob or "on-site" in blob or "onsite" in blob:
        return "出社"
    return detect_remote_type(location_text, combined_text)


def filter_jobs(
    jobs: list[LinkedInJobItem],
    min_salary: int | None = None,
    skills: list[str] | None = None,
    remote_type: str | None = None,
) -> list[LinkedInJobItem]:
    """取得後のクライアント側フィルタリング."""
    matched = []
    for job in jobs:
        if min_salary is not None:
            effective_max = job.salary_max if job.salary_max is not None else job.salary_min
            if effective_max is not None and effective_max < min_salary:
                continue

        if skills:
            card_blob = f"{job.title} {' '.join(job.tags)} {job.snippet} {' '.join(job.skills)}".lower()
            if not all(sk.lower() in card_blob for sk in skills):
                continue

        if remote_type:
            if remote_type.lower() not in job.remote_type.lower():
                continue

        matched.append(job)

    return matched


def print_search_summary(
    result: LinkedInSearchResult,
    jobs: list[LinkedInJobItem],
    detail: bool = False,
    limit: int | None = None,
) -> None:
    """検索結果をコンソールに整形出力する."""
    kw_disp = f"'{result.keyword}'" if result.keyword else "（全件）"
    print("\n========================================================")
    print(f" LinkedIn 求人検索結果: {kw_disp} (勤務地: {result.location})")
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
        print(f"    - 勤務地:   {job.location or '未記載'} | リモート: {job.remote_type} | 年収: {salary_disp}")
        if job.tags:
            print(f"    - タグ:     {', '.join(job.tags[:5])}")
        if job.skills:
            print(f"    - スキル:   {', '.join(job.skills[:6])}")
        if detail and job.snippet:
            print(f"    - 概要:     {job.snippet[:120]}...")
        print("-" * 56)


def main() -> None:
    parser = create_search_parser(
        description="LinkedIn 求人検索CLIスクリプト",
        default_limit=20,
        default_download_limit=5,
        examples=[
            'uv run python scripts/linkedin/search_jobs.py "Python Engineer" -n 10 --summary',
            'uv run python scripts/linkedin/search_jobs.py "AI Engineer" -n 5 --download  # 求人詳細も保存',
            'uv run python scripts/linkedin/search_jobs.py "Backend" --location "Singapore" --sort recent --summary',
        ],
        related=[
            "scripts/linkedin/fetch_job.py: 次に使う（個別の求人詳細を取る）",
        ],
    )
    parser.add_argument(
        "-l",
        "--location",
        default="Tokyo, Japan",
        help="勤務地エリア (デフォルト: 'Tokyo, Japan')",
    )
    parser.add_argument("--page", type=int, default=1, help="ページ番号 (デフォルト: 1)")
    parser.add_argument(
        "--sort",
        choices=["relevance", "recent"],
        default="relevance",
        help="ソート順 (relevance: 関連度順, recent: 新着順, デフォルト: relevance)",
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
        location=args.location,
        page=args.page,
        remote=args.remote,
        sort_by=args.sort,
    )

    profile_dir = resolve_profile_path(args.session)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. 共通認証エンジンによる認証状態確認・ハンドオフ
        ensure_site_authenticated(
            site="linkedin",
            session=args.session,
            target_url="https://www.linkedin.com/jobs/",
            headed=args.headed,
            timeout=args.timeout,
            profile_dir=profile_dir,
            exit_on_fail=True,
        )

        # 2. 求人検索・一覧データ抽出（run_code_snippetで安全に実行）
        search_script_code = generate_search_script_content(search_url, args.limit)
        search_raw = run_code_snippet(args.session, search_script_code, timeout=40)
        if not search_raw or not search_raw.get("success"):
            ctx.error("求人検索画面のナビゲートまたはデータ取得に失敗しました。")
            sys.exit(1)

        # LinkedInJobItem への変換とフィールド補正
        raw_jobs = search_raw.get("jobs", [])
        job_items: list[LinkedInJobItem] = []
        for rj in raw_jobs:
            loc = rj.get("location", "")
            title = rj.get("title", "")
            tags = rj.get("tags", [])
            snippet = rj.get("snippet", "")

            # リモート判定
            combined_text = f"{loc} {title} {' '.join(tags)} {snippet}"
            r_type = parse_linkedin_remote_type(loc, combined_text)

            # 年収パース
            s_min, s_max = parse_salary_range(combined_text)

            # スキル抽出
            skills = extract_skills_from_text(combined_text)

            item = LinkedInJobItem(
                id=rj.get("id", ""),
                title=title,
                company=rj.get("company", ""),
                company_url=rj.get("companyUrl", ""),
                url=rj.get("url", ""),
                salary_text=format_salary_display(s_min, s_max) if s_min or s_max else "",
                salary_min=s_min,
                salary_max=s_max,
                location=loc,
                remote_type=r_type,
                tags=tags,
                skills=skills,
                snippet=snippet,
            )
            job_items.append(item)

        search_result = LinkedInSearchResult(
            keyword=keyword,
            location=args.location,
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
                source="linkedin",
                keyword=f"{keyword}_{args.location}" if keyword else args.location,
                jobs=[j.to_dict() for j in display_jobs],
                total_count=search_result.total_count,
                returned_count=len(search_result.jobs),
                output_dir=args.searches_dir,
                metadata={
                    "page": args.page,
                    "location": args.location,
                    "sort": args.sort,
                    "remote": args.remote,
                },
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
                        p, _ = fetch_and_save_linkedin_job(
                            url_or_id=t.url or t.id,
                            session=args.session,
                            output_dir=args.output_dir,
                            force=args.force,
                            dry_run=args.dry_run,
                            summary=args.summary,
                            initial_title=t.title,
                            initial_location=t.location,
                            initial_tags=t.tags,
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
            "location": args.location,
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
