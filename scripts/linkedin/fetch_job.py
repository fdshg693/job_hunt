"""LinkedIn 求人詳細取得・Markdown保存モジュール.

LinkedInの求人URLまたはIDから求人詳細をPlaywright経由で取得し、
プロジェクト共通仕様（.agents/rules/job-data-format.md）に準拠したフロントマター付きMarkdownとして保存します。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

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
from scripts.common.cli import EntrypointContext, create_base_parser, to_relative_path
from scripts.common.normalizers import (
    detect_remote_type,
    extract_skills_from_text,
    format_salary_display,
    normalize_url,
    parse_salary_range,
)
from scripts.common.storage import JobData, save_job_markdown

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "linkedin" / "jobs"


def extract_job_id(url_or_id: str) -> str:
    """求人URLまたはID文字列からIDを抽出・正規化する."""
    cleaned = url_or_id.strip()
    # https://www.linkedin.com/jobs/view/4454473941/
    m_view = re.search(r"/jobs/view/(\d+)", cleaned)
    if m_view:
        return m_view.group(1)
    # currentJobId=4454473941
    m_param = re.search(r"currentJobId=(\d+)", cleaned)
    if m_param:
        return m_param.group(1)
    # job-id 属性値などの数字列
    m_num = re.search(r"\b(\d{7,12})\b", cleaned)
    if m_num:
        return m_num.group(1)
    if re.match(r"^[a-zA-Z0-9_-]+$", cleaned):
        return cleaned
    raise ValueError(f"無効なLinkedIn求人URLまたはIDです: {url_or_id}")


def normalize_job_url(url_or_id: str) -> tuple[str, str]:
    """(job_id, full_url) のタプルを返す."""
    job_id = extract_job_id(url_or_id)
    return job_id, f"https://www.linkedin.com/jobs/view/{job_id}/"


def generate_fetch_script_content(target_url: str) -> str:
    """求人詳細取得用PlaywrightスクリプトのJSコードを生成する."""
    js_target_url = json.dumps(target_url)
    return f"""async page => {{
  const targetUrl = {js_target_url};

  if (page.url() !== targetUrl) {{
    await page.goto(targetUrl, {{ waitUntil: 'domcontentloaded', timeout: 30000 }});
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

  // 詳細要素の待機
  try {{
    await page.waitForSelector(
      '#job-details, .jobs-description__content, .job-details-jobs-unified-top-card__job-title, h1',
      {{ timeout: 10000 }}
    );
  }} catch (_) {{}}

  const data = await page.evaluate(() => {{
    const textOf = el => (el ? el.textContent.trim() : '');

    // タイトル
    const docTitle = document.title || '';
    const titleParts = docTitle.split('|').map(p => p.trim()).filter(Boolean);

    const titleEl =
      document.querySelector('h1.job-details-jobs-unified-top-card__job-title') ||
      document.querySelector('h2.job-details-jobs-unified-top-card__job-title') ||
      document.querySelector('h1.top-card-layout__title') ||
      document.querySelector('h1');
    let title = textOf(titleEl);
    title = title.replace(/\\s*with verification\\s*/i, '').trim();
    if (!title && titleParts.length > 0 && titleParts[0] !== 'LinkedIn') {{
      title = titleParts[0];
    }}

    // 企業名
    let company = '';
    const compEl =
      document.querySelector('.job-details-jobs-unified-top-card__company-name') ||
      document.querySelector('a[href*="/company/"]') ||
      document.querySelector('.topcard__flavor--black-link') ||
      document.querySelector('.topcard__flavor');
    if (compEl) {{
      company = textOf(compEl);
    }}
    if (!company && titleParts.length >= 2 && titleParts[1] !== 'LinkedIn') {{
      company = titleParts[1];
    }}

    // 企業URL
    let companyUrl = '';
    const compLink = document.querySelector('a[href*="/company/"]');
    if (compLink) {{
      companyUrl = compLink.href;
    }}

    // 勤務地・メタ情報
    let location = '';
    const primaryDesc = document.querySelector(
      '.job-details-jobs-unified-top-card__primary-description, .topcard__flavor--bullet'
    );
    if (primaryDesc) {{
      location = textOf(primaryDesc);
    }}

    // 就業形態
    let remoteInfo = '';
    const tertiaryDesc = document.querySelector(
      '.job-details-jobs-unified-top-card__tertiary-description, .job-details-jobs-unified-top-card__job-insight'
    );
    if (tertiaryDesc) {{
      remoteInfo = textOf(tertiaryDesc);
    }}

    // 本文コンテナ
    const descEl =
      document.getElementById('job-details') ||
      document.querySelector('.jobs-description__content') ||
      document.querySelector('.jobs-box__html-content') ||
      document.querySelector('article');
    let rawBody = descEl ? descEl.innerText.trim() : '';
    if (!rawBody) {{
      const mainEl = document.querySelector('main');
      if (mainEl) {{
        const fullText = mainEl.innerText.trim();
        const aboutIdx = fullText.indexOf('About the job');
        if (aboutIdx !== -1) {{
          rawBody = fullText.slice(aboutIdx).trim();
        }} else {{
          rawBody = fullText;
        }}
      }}
    }}

    if (rawBody) {{
      const cutMarkers = [
        'Requirements added by the job poster',
        'Set alert for similar jobs',
        'Unlock hiring insights',
        'Looking for talent?',
      ];
      for (const marker of cutMarkers) {{
        const markerIdx = rawBody.indexOf(marker);
        if (markerIdx !== -1) {{
          rawBody = rawBody.slice(0, markerIdx).trim();
        }}
      }}
    }}

    // タグ・バッジ
    const tags = [];
    document
      .querySelectorAll('.job-details-jobs-unified-top-card__job-insight, .jobs-unified-top-card__job-insight')
      .forEach(el => {{
        const t = textOf(el);
        if (t && !tags.includes(t)) {{
          tags.push(t);
        }}
      }});

    return {{
      title,
      company,
      companyUrl,
      location,
      remoteInfo,
      rawBody,
      tags
    }};
  }});

  return {{
    success: true,
    url: page.url(),
    ...data
  }};
}}
"""


def fetch_and_save_linkedin_job(
    url_or_id: str,
    session: str = "job-hunt",
    output_dir: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
    summary: bool = False,
    initial_title: str = "",
    initial_location: str = "",
    initial_tags: list[str] | None = None,
) -> tuple[Path | None, bool]:
    """単体求人詳細を取得・Markdown保存する.

    戻り値: (保存されたファイルパス, 新規保存されたか)
    """
    job_id, job_url = normalize_job_url(url_or_id)
    target_dir = output_dir or DEFAULT_OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / f"{job_id}.md"

    if target_file.exists() and not force:
        if summary:
            print(f"[スキップ] 既に存在します: {to_relative_path(target_file)}", file=sys.stderr)
        return target_file, False

    # 認証状態確認
    ensure_site_authenticated(
        site="linkedin",
        session=session,
        target_url="https://www.linkedin.com/jobs/",
        exit_on_fail=True,
    )

    fetch_script_code = generate_fetch_script_content(job_url)
    res = run_code_snippet(session, fetch_script_code, timeout=35)

    if not res or not res.get("success"):
        err = res.get("error") if res else "timeout_or_empty"
        print(f"[エラー] 求人詳細の取得に失敗しました ({job_id}): {err}", file=sys.stderr)
        return None, False

    title = res.get("title") or initial_title or f"LinkedIn Job {job_id}"
    company = res.get("company") or "企業名非公開"
    company_url = res.get("companyUrl") or ""
    loc = res.get("location") or initial_location
    remote_info = res.get("remoteInfo") or ""
    raw_body = res.get("rawBody") or ""
    tags = res.get("tags") or initial_tags or []

    # リモート判定
    from scripts.linkedin.search_jobs import parse_linkedin_remote_type

    combined_text = f"{loc} {remote_info} {raw_body}"
    remote_type = parse_linkedin_remote_type(loc, combined_text)

    # 年収パース
    sal_min, sal_max = parse_salary_range(combined_text)

    # スキル抽出
    skills = extract_skills_from_text(combined_text)

    job_data = JobData(
        id=job_id,
        source="linkedin",
        company=company,
        title=title,
        url=job_url,
        salary_min=sal_min,
        salary_max=sal_max,
        salary_text=format_salary_display(sal_min, sal_max) if sal_min or sal_max else "",
        skills=skills,
        location=loc,
        remote_type=remote_type,
        tags=tags,
        company_url=company_url,
        raw_body=raw_body,
    )

    if dry_run:
        print(f"[プレビュー] {job_id}: {company} - {title}", file=sys.stderr)
        return target_file, True

    saved_path, is_new = save_job_markdown(job_data, output_dir=target_dir, force=force)
    update_profile_last_used(session)
    return saved_path, is_new


def main() -> None:
    parser = create_base_parser(description="LinkedIn 求人詳細取得CLI")
    parser.add_argument("url_or_id", help="LinkedIn求人URLまたは求人ID")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Markdown保存先ディレクトリ (デフォルト: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--session",
        default="job-hunt",
        help="Playwrightブラウザセッション名 (デフォルト: job-hunt)",
    )
    parser.add_argument("--dry-run", action="store_true", help="保存を行わずプレビューする")

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    try:
        path, is_new = fetch_and_save_linkedin_job(
            url_or_id=args.url_or_id,
            session=args.session,
            output_dir=args.output_dir,
            force=args.force,
            dry_run=args.dry_run,
            summary=args.summary,
        )

        if not path:
            ctx.error(f"求人詳細の保存に失敗しました: {args.url_or_id}")
            sys.exit(1)

        ctx.add_result_path(path)

        def summary_fn() -> None:
            status = "新規保存" if is_new else "既存"
            print(f"\n[LinkedIn 求人取得完了 ({status})]")
            print(f"  ファイル: {to_relative_path(path)}")

        sys.exit(ctx.flush_outputs(summary_fn=summary_fn))

    except Exception as ex:
        ctx.error(str(ex))
        sys.exit(1)


if __name__ == "__main__":
    main()
