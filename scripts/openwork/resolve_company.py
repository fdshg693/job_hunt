"""OpenWork で会社名から企業 ID（m_id）・口コミ URL を解決する CLI.

OpenWork会社名解決モジュール.
会社名（例: 「SmartHR」「メルカリ」「セキュアナビ」）からOpenWorkを検索し、
企業ID（m_id）、企業ページURL、口コミページURL、および企業メタデータを解決します。
"""

from __future__ import annotations

import argparse
import difflib
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

# プロジェクトルートパス (scripts/openwork/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.auth_engine import ensure_site_authenticated
from scripts.common.browser_auth import (
    resolve_profile_path,
    run_code_snippet,
    run_playwright_cmd,
)
from scripts.common.cli import build_epilog
from scripts.common.normalizers import normalize_company_name

OPENWORK_COMPANY_SEARCH_URL = "https://www.openwork.jp/company_list"
OPENWORK_BASE_URL = "https://www.openwork.jp"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

HTTP_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


@dataclass
class OpenWorkCompanyCandidate:
    """OpenWork企業候補メタデータ."""

    m_id: str
    name: str
    url: str
    reviews_url: str
    score: float | None = None
    reviews_count: int | None = None
    industry: str = ""
    match_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換する."""
        return asdict(self)


def calculate_company_match_score(query: str, candidate_name: str, reviews_count: int | None = None) -> float:
    """入力社名と候補社名の類似度スコア（0.0〜1.0）を計算する."""
    q_raw = query.strip()
    c_raw = candidate_name.strip()
    if not q_raw or not c_raw:
        return 0.0

    # 完全一致（生文字列）
    if q_raw == c_raw:
        base_score = 1.0
    else:
        q_norm = normalize_company_name(q_raw).lower()
        c_norm = normalize_company_name(c_raw).lower()

        if q_norm == c_norm:
            # 正規化後完全一致（「SmartHR」と「株式会社SmartHR」等）
            base_score = 0.98
        elif c_norm.startswith(q_norm) or q_norm.startswith(c_norm):
            # 前方一致
            base_score = 0.85
        elif q_norm in c_norm or c_norm in q_norm:
            # 部分一致
            base_score = 0.70
        else:
            # 文字列類似度 (SequenceMatcher)
            base_score = difflib.SequenceMatcher(None, q_norm, c_norm).ratio() * 0.8

    # クチコミ件数が多いメジャー企業への微小タイブレーカー加点（最大 0.02）
    bonus = 0.0
    if reviews_count and reviews_count > 0:
        bonus = min(reviews_count, 1000) / 50000.0

    return min(1.0, round(base_score + bonus, 4))


def fetch_html_via_http(url: str) -> tuple[int, str, str | None]:
    """urllib経由で高速にHTMLを取得する.

    Returns:
        tuple[status_code, final_url, html_content]
    """
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            final_url = resp.geturl()
            html_content = resp.read().decode("utf-8", errors="replace")
            return resp.status, final_url, html_content
    except urllib.error.HTTPError as e:
        return e.code, e.geturl(), None
    except Exception:
        return 0, "", None


def fetch_search_html_via_playwright(
    search_url: str,
    session: str = "job-hunt",
    profile_path: str | Path | None = None,
    timeout: int = 60,
    no_notify: bool = False,
) -> tuple[int, str, str | None]:
    """Playwright CLIセッション経由で検索結果HTMLを取得する (フォールバック用).

    Returns:
        tuple[status_code, final_url, html_content]
    """
    profile_dir = resolve_profile_path(session, profile_path)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    # セッション起動確認
    open_args = [f"-s={session}", "open", "about:blank", f"--profile={profile_dir}"]
    run_playwright_cmd(open_args, timeout=30)

    js_url = json.dumps(search_url)
    # 注意: Playwright CLI run-code では末尾にセミコロンを付けないこと
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
}}"""

    res = run_code_snippet(session, script_code, timeout=35)
    if not res or not res.get("success"):
        return 0, "", None

    # CAPTCHA壁等の検知時は共通認証エンジンでハンドオフ
    if res.get("onAuthWall"):
        cleared = ensure_site_authenticated(
            site="openwork",
            session=session,
            target_url=search_url,
            timeout=timeout,
            no_notify=no_notify,
            profile_dir=profile_dir,
            exit_on_fail=False,
        )
        if not cleared:
            return 0, "", None

        res = run_code_snippet(session, script_code, timeout=35)
        if not res or not res.get("success"):
            return 0, "", None

    status_code = res.get("status", 200)
    final_url = res.get("url", "")
    html_content = res.get("html", "")
    return status_code, final_url, html_content


def fetch_search_page(
    search_url: str,
    session: str = "job-hunt",
    profile_path: str | Path | None = None,
    timeout: int = 60,
    no_notify: bool = False,
) -> tuple[int, str, str | None]:
    """HTTP経由で取得を試み、必要に応じてPlaywrightへフォールバックする."""
    status_code, final_url, html_content = fetch_html_via_http(search_url)

    # 404や /search/addcompany はOpenWork未登録の正常な応答（ブラウザ不要）
    if status_code == 404 or "/search/addcompany" in final_url:
        return status_code, final_url, None

    # ブロック（403, 429）やHTML不正、画像認証の兆候がある場合はPlaywrightへフォールバック
    is_blocked = (
        status_code in (403, 429)
        or not html_content
        or "画像認証" in (html_content or "")
        or "403 Forbidden" in (html_content or "")
    )

    if is_blocked:
        return fetch_search_html_via_playwright(
            search_url,
            session=session,
            profile_path=profile_path,
            timeout=timeout,
            no_notify=no_notify,
        )

    return status_code, final_url, html_content


def parse_company_cards_from_html(html_content: str, query: str = "") -> list[OpenWorkCompanyCandidate]:
    """検索結果HTMLから企業候補カード配列をパースする."""
    soup = BeautifulSoup(html_content, "html.parser")
    candidates: list[OpenWorkCompanyCandidate] = []

    # 企業一覧コンテナ
    items = soup.select("ul.testCompanyList > li")
    if not items:
        # 代替セレクタ
        items = soup.select(".testCompanyList li.box-15, .searchCompanyName")

    for item in items:
        # 社名 & m_id リンク
        link = item.select_one("h3 a, .searchCompanyName h3 a, a[href*='company.php?m_id=']")
        if not link:
            continue

        raw_name = link.get_text(strip=True)
        raw_name = html.unescape(raw_name)
        href = link.get("href", "")

        # m_id 抽出
        m_id_match = re.search(r"[?&]m_id=([a-zA-Z0-9]+)", href)
        if not m_id_match:
            continue
        m_id = m_id_match.group(1)

        company_url = f"{OPENWORK_BASE_URL}/company.php?m_id={m_id}"
        reviews_url = f"{OPENWORK_BASE_URL}/company_answer.php?m_id={m_id}"

        # 総合評価スコア
        score: float | None = None
        for s_el in item.select(".totalEvaluation_item, .score"):
            txt = s_el.get_text(strip=True)
            try:
                score = float(txt)
                break
            except (ValueError, TypeError):
                continue

        # 口コミ件数
        reviews_count: int | None = None
        rc_elem = item.select_one("a[href*='company_answer.php'] dd span, .reviewCount")
        if rc_elem:
            rc_text = re.sub(r"[^\d]", "", rc_elem.get_text(strip=True))
            if rc_text.isdigit():
                reviews_count = int(rc_text)

        # 業界
        ind_elem = item.select_one("p.gray, .industry")
        industry = ind_elem.get_text(strip=True) if ind_elem else ""

        match_score = calculate_company_match_score(query, raw_name, reviews_count)

        candidate = OpenWorkCompanyCandidate(
            m_id=m_id,
            name=raw_name,
            url=company_url,
            reviews_url=reviews_url,
            score=score,
            reviews_count=reviews_count,
            industry=industry,
            match_score=match_score,
        )
        candidates.append(candidate)

    # マッチスコア降順、同点の場合はクチコミ数降順でソート
    candidates.sort(key=lambda c: (c.match_score, c.reviews_count or 0), reverse=True)
    return candidates


def search_companies(
    query: str,
    session: str = "job-hunt",
    profile_path: str | Path | None = None,
    timeout: int = 60,
    no_notify: bool = False,
) -> list[OpenWorkCompanyCandidate]:
    """会社名でOpenWorkを検索し、候補企業リストを取得する.

    Args:
        query: 検索社名（例: 'SmartHR', 'メルカリ'）
        session: Playwrightセッション名
        profile_path: プロファイルパス
        timeout: タイムアウト（秒）
        no_notify: 通知抑制フラグ

    Returns:
        候補企業のリスト（マッチスコア順）。該当なしの場合は空リスト。
    """
    clean_query = query.strip()
    if not clean_query:
        return []

    # 1. 指定クエリで検索
    encoded_query = urllib.parse.quote(clean_query)
    search_url = f"{OPENWORK_COMPANY_SEARCH_URL}?src_str={encoded_query}&sort=1"

    status_code, final_url, html_content = fetch_search_page(
        search_url,
        session=session,
        profile_path=profile_path,
        timeout=timeout,
        no_notify=no_notify,
    )

    # 404レスポンスまたは /search/addcompany リダイレクト（未登録企業）
    if status_code == 404 or "/search/addcompany" in final_url or not html_content:
        # 正規化社名と元クエリが異なる場合は、正規化社名でフォールバック検索
        norm_query = normalize_company_name(clean_query)
        if norm_query and norm_query != clean_query:
            norm_encoded = urllib.parse.quote(norm_query)
            fallback_url = f"{OPENWORK_COMPANY_SEARCH_URL}?src_str={norm_encoded}&sort=1"
            f_status, f_url, f_html = fetch_search_page(
                fallback_url,
                session=session,
                profile_path=profile_path,
                timeout=timeout,
                no_notify=no_notify,
            )
            if f_status != 404 and "/search/addcompany" not in f_url and f_html:
                return parse_company_cards_from_html(f_html, query=clean_query)

        return []

    candidates = parse_company_cards_from_html(html_content, query=clean_query)

    # もし指定クエリで0件かつ正規化社名が異なるならフォールバック
    if not candidates:
        norm_query = normalize_company_name(clean_query)
        if norm_query and norm_query != clean_query:
            norm_encoded = urllib.parse.quote(norm_query)
            fallback_url = f"{OPENWORK_COMPANY_SEARCH_URL}?src_str={norm_encoded}&sort=1"
            f_status, f_url, f_html = fetch_search_page(
                fallback_url,
                session=session,
                profile_path=profile_path,
                timeout=timeout,
                no_notify=no_notify,
            )
            if f_status != 404 and "/search/addcompany" not in f_url and f_html:
                return parse_company_cards_from_html(f_html, query=clean_query)

    return candidates


def resolve_company_by_name(
    query: str,
    session: str = "job-hunt",
    profile_path: str | Path | None = None,
    timeout: int = 60,
    no_notify: bool = False,
    min_match_score: float = 0.5,
) -> OpenWorkCompanyCandidate | None:
    """会社名からOpenWork上で最も適合する企業（best match）を解決する.

    Args:
        query: 検索社名
        session: Playwrightセッション名
        profile_path: プロファイルパス
        timeout: タイムアウト（秒）
        no_notify: 通知抑制フラグ
        min_match_score: 採用する最低マッチスコアの閾値（0.0〜1.0）

    Returns:
        最良の企業候補、または閾値未満・見つからない場合は None。
    """
    candidates = search_companies(
        query=query,
        session=session,
        profile_path=profile_path,
        timeout=timeout,
        no_notify=no_notify,
    )
    if not candidates:
        return None

    top_candidate = candidates[0]
    if top_candidate.match_score >= min_match_score:
        return top_candidate

    return None


def main() -> int:
    """CLIエントリポイント."""
    parser = argparse.ArgumentParser(
        epilog=build_epilog(
            examples=[
                'uv run python scripts/openwork/resolve_company.py "SmartHR"',
                'uv run python scripts/openwork/resolve_company.py "メルカリ" --all --summary  # 候補をすべて表示',
            ],
            related=[
                "scripts/openwork/fetch_reviews.py: 次に使う（解決した企業の口コミを取得）",
            ],
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="OpenWork 会社名解決CLI（会社名から企業ID・URL・メタデータを特定）",
    )
    parser.add_argument("company", nargs="?", help="検索対象の会社名（例: SmartHR, メルカリ）")
    parser.add_argument("-c", "--company-name", dest="company_opt", help="検索対象の会社名（オプション指定）")
    parser.add_argument(
        "--session",
        default="job-hunt",
        help="ブラウザプロファイルセッション名 (デフォルト: job-hunt)",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.5,
        help="最小マッチスコア閾値 (デフォルト: 0.5)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="最上位だけでなく全候補企業を出力する",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON形式で出力する",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="人間向けのサマリ情報を表示する",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="タイムアウト秒数 (デフォルト: 60)",
    )

    args = parser.parse_args()
    target_company = args.company or args.company_opt
    if not target_company:
        parser.print_help(sys.stderr)
        return 1

    candidates = search_companies(
        query=target_company,
        session=args.session,
        timeout=args.timeout,
    )

    if not candidates:
        if args.json:
            print(json.dumps({"success": False, "query": target_company, "error": "Company not found"}, ensure_ascii=False))
        elif args.summary:
            print(f"[OpenWork] '{target_company}' に一致する企業は見つかりませんでした（未登録または検索ヒットなし）。")
        else:
            print(f"Company not found: {target_company}", file=sys.stderr)
        return 1

    best = candidates[0] if candidates[0].match_score >= args.min_score else None

    if args.json:
        result_payload = {
            "success": best is not None,
            "query": target_company,
            "best_match": best.to_dict() if best else None,
            "candidates": [c.to_dict() for c in candidates] if args.all else ([best.to_dict()] if best else []),
        }
        print(json.dumps(result_payload, ensure_ascii=False, indent=2))
        return 0

    if args.summary:
        print(f"=== OpenWork 企業検索結果: '{target_company}' ===")
        if best:
            print("【最有力候補】")
            print(f"  企業名:       {best.name}")
            print(f"  企業ID (m_id): {best.m_id}")
            print(f"  総合スコア:   {best.score if best.score is not None else 'N/A'}")
            print(f"  口コミ件数:   {best.reviews_count if best.reviews_count is not None else 'N/A'}")
            print(f"  業界:         {best.industry}")
            print(f"  マッチ度:     {best.match_score:.2f}")
            print(f"  企業URL:      {best.url}")
            print(f"  口コミURL:    {best.reviews_url}")
        else:
            print(f"閾値 ({args.min_score}) を満たす有力候補はありませんでした。")

        if args.all and len(candidates) > 1:
            print(f"\n【その他の候補 ({len(candidates)}件)】")
            for idx, c in enumerate(candidates, 1):
                print(f"  {idx}. {c.name} (m_id: {c.m_id}, スコア: {c.score}, マッチ度: {c.match_score:.2f})")
        return 0

    # デフォルト出力: 最有力候補の m_id のみを出力（CLIパイプ・自動化用）
    if best:
        print(best.m_id)
        return 0
    else:
        print(f"No high confidence match found for: {target_company}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
