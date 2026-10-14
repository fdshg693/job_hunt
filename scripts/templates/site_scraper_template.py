"""新規求人サイトスクリプト開発用テンプレート (site_scraper_template.py).

Wantedly、Green、dodaなどの新規求人媒体を追加する際、
本ファイルをコピーしてサイト固有のURL・セレクタ・パース処理を実装してください。
共通の認証ハンドオフ、CLI規約、データ正規化、ファイル永続化はすべて共通基盤を活用できます。

【カスタマイズ手順】
1. `SITE_NAME`, `SITE_SOURCE`, `SITE_BASE_URL` などの定数を設定
2. `SITE_AUTH_CONFIG` に認証画面の判定セレクタ・URLを設定（非ログインサイトの場合は認証スキップ可）
3. `build_search_url` でサイト固有の検索クエリパラメータを構築
4. `extract_search_jobs` でHTML/JSONから求人一覧（JobDataまたは辞書）を抽出
5. 必要に応じて `fetch_and_save_job_detail` で詳細ページを取得・保存
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパスの解決とsys.pathへの追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.auth_engine import SiteAuthConfig, ensure_site_authenticated
from scripts.common.browser_auth import (
    resolve_profile_path,
    run_code_snippet,
    run_playwright_cmd,
    update_profile_last_used,
)
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
# 1. サイト固有の定数・認証設定（※ 新規サイトに合わせて変更してください）
# ==============================================================================

SITE_NAME = "新規サイト名"  # 例: "Wantedly", "Green"
SITE_SOURCE = "new_site"   # 小文字識別子。例: "wantedly", "green" (data/{source}/ に保存される)
SITE_BASE_URL = "https://example.com"
SEARCH_BASE_URL = "https://example.com/search"

DEFAULT_JOBS_DIR = PROJECT_ROOT / "data" / SITE_SOURCE / "jobs"
DEFAULT_SEARCHES_DIR = PROJECT_ROOT / "data" / SITE_SOURCE / "searches"

# サイトのログイン判定設定（不要なパブリックサイトの場合は None または認証呼び出しを省略）
SITE_AUTH_CONFIG = SiteAuthConfig(
    site_name=SITE_NAME,
    login_url=f"{SITE_BASE_URL}/login",
    target_url=SEARCH_BASE_URL,
    auth_wall_regex=r"/login|/signin|/auth",
    logged_in_selectors=[
        'header a[href*="/mypage"]',
        'nav button[aria-label*="user"]',
    ],
    is_captcha_site=False,  # CAPTCHAの検知が必要な場合は True
)


# ==============================================================================
# 2. URL生成 & データ取得ロジック（※ サイトに合わせて実装）
# ==============================================================================

def build_search_url(
    keyword: str = "",
    page: int = 1,
    min_salary_man: int | None = None,
    remote: bool = False,
) -> str:
    """サイト固有の検索URLを構築する."""
    # TODO: サイトのURLパラメータ仕様に合わせて修正してください
    params: list[str] = []
    if keyword:
        import urllib.parse
        params.append(f"q={urllib.parse.quote_plus(keyword)}")
    if page > 1:
        params.append(f"page={page}")
    if min_salary_man:
        params.append(f"salary_min={min_salary_man}")
    if remote:
        params.append("remote=1")

    query_str = "&".join(params)
    return f"{SEARCH_BASE_URL}?{query_str}" if query_str else SEARCH_BASE_URL


def fetch_search_page_html(
    search_url: str,
    session: str = "job-hunt",
    headed: bool = False,
    timeout: int = 30,
) -> str:
    """Playwrightセッション経由で検索ページのHTMLを取得する."""
    # run_code_snippet を使用してブラウザ内スクリプトを実行
    js_code = f"""
    await page.goto({json.dumps(search_url)}, {{ waitUntil: 'domcontentloaded', timeout: {timeout * 1000} }});
    // 必要に応じて要素の出現を待機:
    // await page.waitForSelector('.job-card', {{ timeout: 5000 }}).catch(() => {{}});
    return await page.content();
    """
    html_content = run_code_snippet(session=session, js_code=js_code, timeout=timeout + 10)
    return html_content or ""


def parse_job_cards(html_content: str) -> list[dict[str, Any]]:
    """HTMLから検索結果カードを抽出し、共通正規化処理を適用した辞書リストを返す."""
    from bs4 import BeautifulSoup  # または正規表現

    soup = BeautifulSoup(html_content, "html.parser")
    jobs: list[dict[str, Any]] = []

    # TODO: サイト固有のセレクタに合わせて抽出処理を記述してください
    cards = soup.select(".job-card") or []
    for card in cards:
        # 例: ID, タイトル, 企業名, URL
        title_elem = card.select_one(".job-title")
        company_elem = card.select_one(".company-name")
        link_elem = card.select_one("a[href*='/jobs/']")

        title = title_elem.get_text(strip=True) if title_elem else ""
        company = company_elem.get_text(strip=True) if company_elem else ""
        rel_url = link_elem.get("href", "") if link_elem else ""
        url = normalize_url(rel_url, base_url=SITE_BASE_URL)

        # 求人IDの抽出
        import re
        id_match = re.search(r"/jobs/([a-zA-Z0-9_-]+)", url)
        job_id = id_match.group(1) if id_match else f"job_{len(jobs)+1}"

        # 年収パース (共通 normalizers を活用)
        salary_elem = card.select_one(".salary-text")
        raw_salary = salary_elem.get_text(strip=True) if salary_elem else ""
        salary_min, salary_max = parse_salary_range(raw_salary)

        # リモート判定 (共通 normalizers を活用)
        location_elem = card.select_one(".location-text")
        location = location_elem.get_text(strip=True) if location_elem else ""
        remote_type = detect_remote_type(location, card.get_text(" ", strip=True))

        # スキル抽出 (共通 normalizers を活用)
        skills = extract_skills_from_text(card.get_text(" ", strip=True))

        jobs.append({
            "id": job_id,
            "title": title,
            "company": company,
            "url": url,
            "salary_text": raw_salary or format_salary_text(salary_min, salary_max),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "location": location,
            "remote_type": remote_type,
            "skills": skills,
        })

    return jobs


def fetch_and_save_job_detail(
    job_id: str,
    job_url: str,
    session: str = "job-hunt",
    force: bool = False,
    output_dir: Path | None = None,
) -> tuple[Path, bool]:
    """単体求人の詳細を取得し、Markdownとして保存する（job-data-format.md 仕様準拠）."""
    target_dir = output_dir or DEFAULT_JOBS_DIR
    target_file = target_dir / f"{job_id}.md"

    if target_file.exists() and not force:
        return target_file, False

    # 詳細ページのHTMLを取得
    js_code = f"""
    await page.goto({json.dumps(job_url)}, {{ waitUntil: 'domcontentloaded', timeout: 30000 }});
    return await page.content();
    """
    detail_html = run_code_snippet(session=session, js_code=js_code, timeout=40)

    # TODO: 詳細ページから各セクション（仕事内容、必須要件、歓迎要件など）を抽出
    # from bs4 import BeautifulSoup
    # soup = BeautifulSoup(detail_html, "html.parser")
    # ...

    # JobData モデルインスタンスを作成
    job = JobData(
        id=job_id,
        source=SITE_SOURCE,
        company="サンプル企業",
        title="サンプル職種",
        url=job_url,
        salary_min=7000000,
        salary_max=10000000,
        salary_text="700万円〜1000万円",
        skills=["Python", "AWS"],
        job_roles=["バックエンドエンジニア"],
        location="東京都渋谷区",
        remote_type="ハイブリッド",
        description="詳細な業務内容...",
        must_skills="PythonでのWeb開発経験3年以上",
        desired_skills="AWSを用いたクラウドインフラ運用経験",
    )

    # 共通 storage パイプラインで保存
    return save_job_markdown(job=job, output_dir=target_dir, force=force)


# ==============================================================================
# 3. CLI エントリポイント実装（scripts-entrypoint.md 規約準拠）
# ==============================================================================

def main() -> None:
    """CLIエントリポイント."""
    # 共通の検索用パーサーを生成（--limit, --summary, --json, --download, --min-salary 等を自動セット）
    parser = create_search_parser(
        description=f"{SITE_NAME} 求人検索・取得CLI",
        default_limit=20,
        default_download_limit=5,
    )

    args = parser.parse_args()

    query_str = " ".join(args.query) if args.query else ""
    min_sal_man = parse_salary_arg(args.min_salary) // 10000 if args.min_salary else None

    # EntrypointContext を用いて出力規約を制御
    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        # 1. 認証チェック・手動ハンドオフ（ログイン不要サイトなら省略可）
        ctx.info(f"{SITE_NAME} の認証状態を確認中...")
        ensure_site_authenticated(
            site=SITE_AUTH_CONFIG,
            session=args.session,
            headed=args.headed,
            timeout=args.timeout,
        )

        # 2. 検索実行
        search_url = build_search_url(
            keyword=query_str,
            min_salary_man=min_sal_man,
            remote=bool(args.remote),
        )
        ctx.info(f"検索ページを取得中: {search_url}")

        html = fetch_search_page_html(search_url, session=args.session, headed=args.headed)
        if not html:
            ctx.error("検索ページのHTML取得に失敗しました。")
            ctx.set_exit_code(1)
            return

        jobs = parse_job_cards(html)
        if args.limit:
            jobs = jobs[:args.limit]

        # 3. 詳細ダウンロード保存（--download 指定時）
        if args.download:
            dl_targets = jobs[:args.download_limit]
            ctx.info(f"ヒットした求人の詳細を保存中（上限: {len(dl_targets)} 件）...")
            for j in dl_targets:
                job_path, is_new = fetch_and_save_job_detail(
                    job_id=j["id"],
                    job_url=j["url"],
                    session=args.session,
                    force=args.force,
                )
                ctx.add_result_path(job_path)

        # 4. 検索結果ファイルへの永続化（--no-save が指定されていない場合）
        if not args.no_save:
            md_path, json_path = save_search_result(
                source=SITE_SOURCE,
                keyword=query_str,
                jobs=jobs,
                output_dir=DEFAULT_SEARCHES_DIR,
                metadata={"min_salary_man": min_sal_man, "remote": args.remote},
            )
            ctx.add_result_path(md_path)

        # 5. 出力のフラッシュ（規約に従い、デフォルトはパスのみstdout出力、--summary時は整形サマリ表示）
        def print_summary() -> None:
            print(f"\n=== {SITE_NAME} 検索結果サマリ ===")
            print(f"検索キーワード: {query_str or '（指定なし）'}")
            print(f"該当件数: {len(jobs)} 件\n")
            print(f"{'No':<3} | {'企業名':<20} | {'年収':<15} | {'タイトル'}")
            print("-" * 65)
            for idx, j in enumerate(jobs, start=1):
                sal = j.get("salary_text") or format_salary_display(j.get("salary_min"), j.get("salary_max"))
                print(f"{idx:<3} | {j['company'][:18]:<20} | {sal:<15} | {j['title']}")
            print("\n生成された結果ファイル:")
            for p in ctx.result_paths:
                print(f"  - {p}")

        ctx.flush_outputs(summary_fn=print_summary, json_data={"jobs": jobs} if args.json else None)


if __name__ == "__main__":
    main()
