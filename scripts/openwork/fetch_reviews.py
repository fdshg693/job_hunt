"""OpenWork の社員クチコミを会社名・企業 ID から取得して保存する CLI.

OpenWork 会社口コミ取得・Markdown保存モジュール.
会社名、企業ID（m_id）、または口コミURLからOpenWorkの社員クチコミを取得し、
構造化フロントマター付きMarkdown（data/openwork/reviews/{m_id}.md）として永続化します。
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from bs4 import BeautifulSoup

# プロジェクトルートパス (scripts/openwork/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.auth_engine import ensure_site_authenticated
from scripts.common.browser_auth import (
    random_sleep,
    resolve_profile_path,
    run_code_snippet,
    run_playwright_cmd,
)
from scripts.common.cli import EntrypointContext, create_base_parser, to_relative_path
from scripts.openwork.resolve_company import (
    OpenWorkCompanyCandidate,
    resolve_company_by_name,
)

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "openwork" / "reviews"
OPENWORK_ANSWER_BASE_URL = "https://www.openwork.jp/company_answer.php"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

# 8項目レーティングのHighchartsデータ対応順序 (0-indexed)
RATING_KEYS = [
    ("treatment_satisfaction", "待遇面の満足度"),
    ("morale", "社員の士気"),
    ("openness", "風通しの良さ"),
    ("mutual_respect", "社員の相互尊重"),
    ("growth_20s", "20代成長環境"),
    ("long_term_nurture", "人材の長期育成"),
    ("compliance", "法令順守意識"),
    ("evaluation_fairness", "人事評価の適正感"),
]


def extract_m_id_from_target(target: str) -> str | None:
    """URLまたは文字列から企業ID（m_id）を抽出する."""
    t = target.strip()
    if not t:
        return None

    # URLクエリパラメータから取得
    if "openwork.jp" in t or "m_id=" in t:
        parsed = urllib.parse.urlparse(t)
        qs = urllib.parse.parse_qs(parsed.query)
        if "m_id" in qs and qs["m_id"]:
            return qs["m_id"][0]
        # パス部分や正規表現で抽出
        m = re.search(r"m_id=([a-zA-Z0-9]+)", t)
        if m:
            return m.group(1)

    # m_id の形式パターン（例: a0C10000017Qi17 等の英数字 10〜25 文字）
    if re.fullmatch(r"a0[A-Za-z0-9]{13,20}", t):
        return t

    return None


def fetch_reviews_page_via_playwright(
    m_id: str,
    page_num: int = 1,
    session: str = "job-hunt",
    timeout: int = 120,
    no_notify: bool = False,
) -> dict[str, Any] | None:
    """Playwright CLIセッション経由で指定ページのクチコミとメタデータを取得する."""
    profile_dir = resolve_profile_path(session)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    # セッション起動確認
    run_playwright_cmd(
        [f"-s={session}", "open", "about:blank", f"--profile={profile_dir}"],
        timeout=30,
    )

    target_url = f"{OPENWORK_ANSWER_BASE_URL}?m_id={m_id}"
    if page_num > 1:
        target_url += f"&next_page={page_num}"

    js_url = json.dumps(target_url)

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

  if (onAuthWall) {{
    return {{ success: true, onAuthWall: true, title, url: page.url() }};
  }}

  // 企業メタ情報の抽出
  const meta = await page.evaluate(() => {{
    // 会社名
    const h2List = Array.from(document.querySelectorAll('h2')).map(e => e.innerText.trim()).filter(Boolean);
    let companyName = '';
    if (h2List.length > 0) {{
      companyName = h2List[0];
    }}
    const headerEl = document.querySelector('.companyHeader_name, .companyName, .box-companyHeader h2');
    if (headerEl && headerEl.innerText.trim()) {{
      companyName = headerEl.innerText.trim();
    }}

    // 総合スコア
    const scoreEl = document.querySelector('.totalEvaluation_item.fs-15, .totalEvaluation_item');
    let overallScore = null;
    if (scoreEl) {{
      const val = parseFloat(scoreEl.innerText.trim());
      if (!isNaN(val)) overallScore = val;
    }}

    // Highcharts 8項目レーティング
    let radarRatings = null;
    if (window.Highcharts && window.Highcharts.charts) {{
      for (const c of window.Highcharts.charts) {{
        if (c && c.series && c.series.length > 0) {{
          radarRatings = c.series[0].data.map(d => typeof d.y === 'number' ? d.y : null);
          break;
        }}
      }}
    }}

    // 総クチコミ件数
    let reviewsCount = null;
    const countMatch = document.body.innerText.match(/社員クチコミ[（(]([0-9,]+)件[）)]/);
    if (countMatch) {{
      reviewsCount = parseInt(countMatch[1].replace(/,/g, ''), 10);
    }} else {{
      const pagingEl = document.querySelector('.paging, div[class*="paging"]');
      if (pagingEl) {{
        const m = pagingEl.innerText.match(/全\\s*([0-9,]+)\\s*件/);
        if (m) reviewsCount = parseInt(m[1].replace(/,/g, ''), 10);
      }}
    }}

    // 次ページの存在
    const hasNext = Boolean(document.querySelector('a.paging_link-more, a[href*="next_page=' + (window.location.search.match(/next_page=(\\d+)/) ? parseInt(RegExp.$1, 10) + 1 : 2) + '"]'));

    return {{
      companyName,
      overallScore,
      radarRatings,
      reviewsCount,
      hasNext
    }};
  }});

  // HTMLコンテンツ
  const html = await page.content();

  return {{
    success: true,
    onAuthWall: false,
    status: resp ? resp.status() : 200,
    meta,
    html,
    url: page.url()
  }};
}}"""

    res = run_code_snippet(session, script_code, timeout=35)
    if not res or not res.get("success"):
        return None

    # CAPTCHA壁等の検知時は共通認証エンジンでハンドオフ
    if res.get("onAuthWall"):
        cleared = ensure_site_authenticated(
            site="openwork",
            session=session,
            target_url=target_url,
            timeout=timeout,
            no_notify=no_notify,
            profile_dir=profile_dir,
            exit_on_fail=False,
        )
        if not cleared:
            return None

        # ハンドオフ後に再取得
        res = run_code_snippet(session, script_code, timeout=35)
        if not res or not res.get("success"):
            return None

    return res


def parse_page_reviews_html(html_content: str) -> list[dict[str, Any]]:
    """HTMLから回答カード（Review Card）の配列をパースする."""
    soup = BeautifulSoup(html_content, "html.parser")
    reviews: list[dict[str, Any]] = []

    articles = soup.select("article.article")
    for a in articles:
        # カテゴリ名 & q_no
        cat_el = a.select_one("h3 a[href*='q_no='], h3 a.fs-16")
        if not cat_el:
            h3_links = a.select("h3 a")
            if h3_links:
                cat_el = h3_links[-1]

        category = ""
        q_no = None
        if cat_el:
            category = cat_el.get_text(strip=True)
            if cat_el.get("href"):
                m_q = re.search(r"q_no=(\d+)", cat_el["href"])
                if m_q:
                    q_no = int(m_q.group(1))

        # 投稿日
        date_str = ""
        time_el = a.select_one("p.article_asideRight time, time")
        if time_el:
            date_str = time_el.get("datetime") or time_el.get_text(strip=True)
            # 日本語表記「2026年09月18日」を YYYY-MM-DD に正規化
            m_date = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
            if m_date:
                date_str = f"{m_date.group(1)}-{int(m_date.group(2)):02d}-{int(m_date.group(3)):02d}"

        # 回答者属性
        user_el = a.select_one("dt a[href*='user_answer.php'], dt a")
        user_info = user_el.get_text(strip=True) if user_el else ""

        # 個人評価スコア
        user_score = None
        score_el = a.select_one("dt span.fs-14, dt span[class*='fs-']")
        if score_el:
            try:
                user_score = float(score_el.get_text(strip=True))
            except ValueError:
                pass

        # 回答本文
        ans_el = a.select_one("dd.article_answer")
        answer_text = ""
        is_masked = False
        if ans_el:
            # 改行を考慮して取得
            answer_text = ans_el.get_text(separator="\n", strip=True)
            if "続きを見る（全" in answer_text or "無料のユーザー登録をお願いします" in answer_text:
                is_masked = True

        # 回答ID (vid)
        vid = ""
        vid_link = a.select_one("footer a[data-vid], a[href*='vid=']")
        if vid_link:
            vid = vid_link.get("data-vid", "")
            if not vid and vid_link.get("href"):
                m_vid = re.search(r"vid=([a-zA-Z0-9]+)", vid_link["href"])
                if m_vid:
                    vid = m_vid.group(1)

        reviews.append({
            "category": category,
            "q_no": q_no,
            "date": date_str,
            "user_info": user_info,
            "user_score": user_score,
            "answer": answer_text,
            "vid": vid,
            "is_masked": is_masked,
        })

    return reviews


def parse_work_environment_from_html(html_content: str) -> dict[str, float | None]:
    """残業時間および有休消化率をHTML内から抽出する."""
    overtime_val = None
    withpay_val = None

    ot_m = re.search(r"progressbar-series-1-overtime.*?value:\s*([0-9.]+)", html_content)
    if ot_m:
        try:
            overtime_val = float(ot_m.group(1))
        except ValueError:
            pass

    wp_m = re.search(r"progressbar-series-1-withpay.*?value:\s*([0-9.]+)", html_content)
    if wp_m:
        try:
            withpay_val = float(wp_m.group(1))
        except ValueError:
            pass

    return {
        "monthly_overtime_hours": overtime_val,
        "paid_holiday_rate": withpay_val,
    }


def fetch_all_reviews(
    m_id: str,
    limit: int = 25,
    session: str = "job-hunt",
    timeout: int = 120,
    no_notify: bool = False,
    summary: bool = False,
) -> dict[str, Any]:
    """複数ページを走査して指定件数までの口コミと企業情報を取得する."""
    all_reviews: list[dict[str, Any]] = []
    company_name = ""
    overall_score = None
    reviews_count = None
    radar_ratings = None
    work_env: dict[str, float | None] = {}

    current_page = 1
    has_next = True
    masked_count = 0

    while len(all_reviews) < limit and has_next:
        if summary:
            print(f"[取得中] OpenWork 口コミ ページ {current_page} (m_id={m_id})...", file=sys.stderr)

        res = fetch_reviews_page_via_playwright(
            m_id=m_id,
            page_num=current_page,
            session=session,
            timeout=timeout,
            no_notify=no_notify,
        )
        if not res:
            if summary:
                print(f"[警告] ページ {current_page} の取得に失敗しました", file=sys.stderr)
            break

        html = res.get("html", "")
        meta = res.get("meta", {})

        # 初回ページでメタ情報を保存
        if current_page == 1:
            company_name = meta.get("companyName") or company_name
            overall_score = meta.get("overallScore")
            reviews_count = meta.get("reviewsCount")
            radar_ratings = meta.get("radarRatings")
            work_env = parse_work_environment_from_html(html)

        reviews = parse_page_reviews_html(html)
        if not reviews:
            break

        for r in reviews:
            if r.get("is_masked"):
                masked_count += 1
            all_reviews.append(r)
            if len(all_reviews) >= limit:
                break

        has_next = meta.get("hasNext", False) and len(all_reviews) < limit
        current_page += 1

        if has_next:
            random_sleep(1.0, 2.0)

    # 8項目レーティングの整形
    ratings_dict: dict[str, float | None] = {}
    if radar_ratings and isinstance(radar_ratings, list):
        for idx, (key, _) in enumerate(RATING_KEYS):
            if idx < len(radar_ratings):
                ratings_dict[key] = radar_ratings[idx]
            else:
                ratings_dict[key] = None

    if masked_count > 0:
        print(
            f"[警告] 取得した口コミのうち {masked_count} 件にマスキング（伏せ字）が検知されました。"
            "OpenWorkアカウントの閲覧権限やログイン状態を確認してください。",
            file=sys.stderr,
        )

    return {
        "m_id": m_id,
        "company_name": company_name,
        "overall_score": overall_score,
        "reviews_count": reviews_count,
        "ratings": ratings_dict,
        "work_environment": work_env,
        "reviews": all_reviews,
        "reviews_fetched": len(all_reviews),
        "url": f"{OPENWORK_ANSWER_BASE_URL}?m_id={m_id}",
    }


def build_reviews_markdown(data: dict[str, Any]) -> str:
    """構造化辞書からフロントマター付きMarkdownテキストを生成する."""
    m_id = data.get("m_id", "")
    company_name = data.get("company_name", "") or "企業名不明"
    overall_score = data.get("overall_score")
    reviews_count = data.get("reviews_count")
    ratings = data.get("ratings", {})
    work_env = data.get("work_environment", {})
    reviews = data.get("reviews", [])

    frontmatter_dict: dict[str, Any] = {
        "company_id": m_id,
        "company_name": company_name,
        "source": "openwork",
        "url": data.get("url", f"{OPENWORK_ANSWER_BASE_URL}?m_id={m_id}"),
        "overall_score": overall_score,
        "reviews_count": reviews_count,
        "ratings": ratings,
        "work_environment": work_env,
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "reviews_fetched": len(reviews),
    }

    yaml_str = yaml.dump(frontmatter_dict, allow_unicode=True, sort_keys=False).strip()

    # テーブル用ヘルパー
    def fmt_val(val: Any, unit: str = "") -> str:
        if val is None or val == "":
            return "-"
        return f"{val}{unit}"

    md_lines = [
        "---",
        yaml_str,
        "---",
        "",
        f"# {company_name} 社員口コミ・評判",
        "",
        "## 企業概要・評価スコア",
        "",
        "| 評価項目 | スコア | 評価項目 | スコア |",
        "| --- | --- | --- | --- |",
        f"| **総合評価** | **{fmt_val(overall_score)}** | 口コミ総件数 | {fmt_val(reviews_count, '件')} |",
        f"| 待遇面の満足度 | {fmt_val(ratings.get('treatment_satisfaction'))} | 20代成長環境 | {fmt_val(ratings.get('growth_20s'))} |",
        f"| 社員の士気 | {fmt_val(ratings.get('morale'))} | 人材の長期育成 | {fmt_val(ratings.get('long_term_nurture'))} |",
        f"| 風通しの良さ | {fmt_val(ratings.get('openness'))} | 法令順守意識 | {fmt_val(ratings.get('compliance'))} |",
        f"| 社員の相互尊重 | {fmt_val(ratings.get('mutual_respect'))} | 人事評価の適正感 | {fmt_val(ratings.get('evaluation_fairness'))} |",
        f"| **月間残業時間** | {fmt_val(work_env.get('monthly_overtime_hours'), 'h')} | **有休消化率** | {fmt_val(work_env.get('paid_holiday_rate'), '%')} |",
        "",
        "---",
        "",
        f"## 社員口コミ一覧（取得: {len(reviews)}件）",
        "",
    ]

    for idx, r in enumerate(reviews, 1):
        cat = r.get("category") or "設問未指定"
        date_str = r.get("date") or "日付不明"
        user_info = r.get("user_info") or "回答者属性なし"
        user_score = r.get("user_score")
        score_display = f" (評価: {user_score})" if user_score is not None else ""
        answer = r.get("answer") or ""

        md_lines.append(f"### {idx}. [{cat}] {date_str}{score_display}")
        md_lines.append(f"- **回答者**: {user_info}")
        if r.get("vid"):
            md_lines.append(f"- **回答ID**: `{r['vid']}`")
        md_lines.append("")
        md_lines.append(answer)
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

    return "\n".join(md_lines)


def fetch_and_save_reviews(
    target: str,
    limit: int = 25,
    session: str = "job-hunt",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    force: bool = False,
    dry_run: bool = False,
    summary: bool = False,
    timeout: int = 120,
    no_notify: bool = False,
) -> tuple[Path | None, dict[str, Any]]:
    """会社名、ID、またはURLを受け取り、口コミを取得・Markdown保存する."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. m_id の特定
    m_id = extract_m_id_from_target(target)
    resolved_name = None

    if not m_id:
        # 会社名とみなして解決
        if summary:
            print(f"[検索中] 会社名「{target}」のOpenWork企業IDを特定しています...", file=sys.stderr)
        candidate: OpenWorkCompanyCandidate | None = resolve_company_by_name(
            query=target,
            session=session,
            timeout=timeout,
            no_notify=no_notify,
        )
        if not candidate:
            raise RuntimeError(f"「{target}」に一致する企業がOpenWork上に見つかりませんでした。")
        m_id = candidate.m_id
        resolved_name = candidate.name
        if summary:
            print(f"[特定完了] {candidate.name} (m_id: {m_id}, スコア: {candidate.score})", file=sys.stderr)

    out_path = output_dir / f"{m_id}.md"

    # 既存ファイルのチェック
    if out_path.exists() and not force:
        if summary:
            print(f"[スキップ] 既に保存されています: {to_relative_path(out_path)}", file=sys.stderr)
        # 既存フロントマターからメタ情報を抽出して返す
        existing_data: dict[str, Any] = {"m_id": m_id, "status": "skipped", "path": str(out_path)}
        try:
            content = out_path.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    fm = yaml.safe_load(parts[1])
                    if isinstance(fm, dict):
                        existing_data.update(fm)
        except Exception:
            pass
        return out_path, existing_data

    # 口コミデータ取得
    data = fetch_all_reviews(
        m_id=m_id,
        limit=limit,
        session=session,
        timeout=timeout,
        no_notify=no_notify,
        summary=summary,
    )

    if resolved_name and not data.get("company_name"):
        data["company_name"] = resolved_name

    md_content = build_reviews_markdown(data)

    if not dry_run:
        out_path.write_text(md_content, encoding="utf-8")
        if summary:
            print(f"[保存完了] {to_relative_path(out_path)}", file=sys.stderr)
        return out_path, data

    return out_path, data


def main() -> None:
    """CLIエントリポイント."""
    parser = create_base_parser(
        examples=[
            'uv run python scripts/openwork/fetch_reviews.py "SmartHR" --summary',
            "uv run python scripts/openwork/fetch_reviews.py --m-id <m_id> --summary  # 企業 ID で直接指定",
        ],
        related=[
            "scripts/openwork/resolve_company.py: 前に使う（会社名から企業 ID を確かめる）",
        ],
        description="OpenWork 社員口コミ取得・Markdown保存CLI",
        default_limit=25,
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="対象会社名、OpenWork企業ID (m_id)、または口コミURL",
    )
    parser.add_argument(
        "-c",
        "--company",
        dest="company_opt",
        help="対象会社名（オプション指定）",
    )
    parser.add_argument(
        "--m-id",
        dest="m_id_opt",
        help="OpenWork企業ID（m_id）",
    )
    parser.add_argument(
        "--url",
        dest="url_opt",
        help="OpenWork口コミURL",
    )
    parser.add_argument(
        "--session",
        default="job-hunt",
        help="Playwrightセッション名 (デフォルト: job-hunt)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="保存先ディレクトリ (デフォルト: data/openwork/reviews/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="ファイル書き込みを行わない",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="手動認証待機タイムアウト秒数",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="認証待機時のOS通知を送信しない",
    )

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    # ターゲットの優先順位決定
    target = args.company_opt or args.m_id_opt or args.url_opt or args.target
    if not target:
        parser.print_help(sys.stderr)
        ctx.error("対象会社名、m_id、またはURLを指定してください。")
        sys.exit(1)

    try:
        path, data = fetch_and_save_reviews(
            target=target,
            limit=args.limit,
            session=args.session,
            output_dir=args.output_dir,
            force=args.force,
            dry_run=args.dry_run,
            summary=args.summary,
            timeout=args.timeout,
            no_notify=args.no_notify,
        )

        if path:
            ctx.add_result_path(path)

        def summary_fn() -> None:
            c_name = data.get("company_name") or target
            m_id = data.get("m_id")
            score = data.get("overall_score")
            total = data.get("reviews_count")
            fetched = data.get("reviews_fetched", 0)
            work_env = data.get("work_environment", {})
            ot = work_env.get("monthly_overtime_hours")
            wp = work_env.get("paid_holiday_rate")

            print(f"企業名:       {c_name}")
            print(f"企業ID (m_id): {m_id}")
            print(f"総合スコア:   {score} (口コミ総件数: {total}件)")
            print(f"残業/有休:    残業 {ot}h/月, 有休消化率 {wp}%")
            print(f"取得件数:     {fetched}件")
            if path:
                print(f"保存先パス:   {to_relative_path(path)}")

        sys.exit(ctx.flush_outputs(summary_fn=summary_fn, json_data=data))

    except Exception as e:
        ctx.error(f"{target}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
