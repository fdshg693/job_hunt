"""ビズリーチ求人詳細取得・Markdown保存モジュール.

ビズリーチの求人URLまたはIDから求人詳細をPlaywright経由で取得し、
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

from scripts.common.browser_auth import (
    resolve_profile_path,
    run_code_snippet,
    run_playwright_cmd,
)
from scripts.common.cli import EntrypointContext, create_base_parser, to_relative_path
from scripts.common.normalizers import (
    detect_remote_type,
    extract_skills_from_text,
    parse_salary_range,
)
from scripts.common.storage import JobData, save_job_markdown

BIZREACH_SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "bizreach" / "jobs"


def extract_job_id(url_or_id: str) -> str:
    """求人URLまたはID文字列からIDを抽出・正規化する."""
    cleaned = url_or_id.strip()
    m = re.search(r"/jobs/([a-zA-Z0-9_-]+)", cleaned)
    if m:
        return m.group(1)
    if re.match(r"^[a-zA-Z0-9_-]+$", cleaned):
        return cleaned
    raise ValueError(f"無効なビズリーチ求人URLまたはIDです: {url_or_id}")


def normalize_job_url(url_or_id: str) -> tuple[str, str]:
    """(job_id, full_url) のタプルを返す."""
    job_id = extract_job_id(url_or_id)
    return job_id, f"https://www.bizreach.jp/jobs/{job_id}/"


def generate_fetch_script_content(target_url: str) -> str:
    """求人詳細取得用PlaywrightスクリプトのJSコードを生成する."""
    js_target_url = json.dumps(target_url)
    return f"""async page => {{
  const targetUrl = {js_target_url};

  if (page.url() !== targetUrl) {{
    await page.goto(targetUrl, {{ waitUntil: 'domcontentloaded', timeout: 30000 }});
  }}

  // 認証壁・ログイン判定
  const currentUrl = page.url();
  const isAuthWall = /auth\\.id\\.bizreach\\.jp|\\/login|\\/signin/i.test(currentUrl);
  if (isAuthWall) {{
    return {{
      success: false,
      error: 'auth_required',
      url: currentUrl
    }};
  }}

  // 求人詳細要素の待機
  try {{
    await page.waitForSelector('.o_job-detail, .job-detail, main, h1', {{ timeout: 10000 }});
  }} catch (_) {{}}

  const data = await page.evaluate(() => {{
    const textOf = el => (el ? el.textContent.trim() : '');

    // タイトル
    const h1 = document.querySelector('h1.o_job-detail__title, h1');
    const title = textOf(h1);

    // 企業名
    let company = '';
    const compEl = document.querySelector('.o_job-detail__company-name, .company-name, [class*="company"]');
    if (compEl) {{
      company = textOf(compEl);
    }}

    // 企業URL
    let companyUrl = '';
    const compLink = document.querySelector('a[href*="/companies/"]');
    if (compLink) {{
      companyUrl = compLink.href;
    }}

    // 想定年収
    let salaryText = '';
    const salaryEl = document.querySelector('.o_job-detail__salary, [class*="salary"]');
    if (salaryEl) {{
      salaryText = textOf(salaryEl);
    }}

    // 勤務地
    let location = '';
    const locEl = document.querySelector('.o_job-detail__location, [class*="location"]');
    if (locEl) {{
      location = textOf(locEl);
    }}

    // 特徴・タグ
    const tags = [];
    document.querySelectorAll('.o_job-detail__tag, .o_tag, [class*="tag"]').forEach(el => {{
      const t = textOf(el);
      if (t && t.length < 30 && !tags.includes(t)) {{
        tags.push(t);
      }}
    }});

    // セクション構造の抽出
    const sections = {{}};
    const secElements = document.querySelectorAll('section, .o_job-detail__section, .job-section');
    secElements.forEach(sec => {{
      const heading = sec.querySelector('h2, h3, .heading');
      const hText = textOf(heading);
      if (hText) {{
        const dlItems = {{}};
        sec.querySelectorAll('dl').forEach(dl => {{
          const dt = textOf(dl.querySelector('dt'));
          const dd = textOf(dl.querySelector('dd'));
          if (dt && dd) {{
            dlItems[dt] = dd;
          }}
        }});

        sections[hText] = {{
          fullText: textOf(sec),
          dlItems: Object.keys(dlItems).length > 0 ? dlItems : null
        }};
      }}
    }});

    // フォールバック: dlItemsが取れずテーブルがある場合
    if (Object.keys(sections).length === 0) {{
      document.querySelectorAll('tr').forEach(tr => {{
        const th = textOf(tr.querySelector('th'));
        const td = textOf(tr.querySelector('td'));
        if (th && td) {{
          sections[th] = {{ fullText: td, dlItems: null }};
        }}
      }});
    }}

    return {{
      title,
      company,
      companyUrl,
      salaryText,
      location,
      tags,
      sections,
      pageText: document.body ? document.body.innerText : ''
    }};
  }});

  return {{
    success: true,
    ...data
  }};
}};
"""


def build_job_data(
    raw_data: dict[str, Any],
    job_id: str,
    job_url: str,
    now: datetime,
    initial_location: str | None = None,
    initial_tags: list[str] | None = None,
    extra_frontmatter: dict[str, Any] | None = None,
) -> JobData:
    """取得した raw_data から JobData モデルインスタンスを構築する."""
    title = raw_data.get("title") or "（タイトルなし）"
    company = raw_data.get("company") or "（企業名非公開）"
    company_url = raw_data.get("companyUrl") or ""
    salary_text = raw_data.get("salaryText") or ""
    location = raw_data.get("location") or initial_location or ""
    tags = raw_data.get("tags") or initial_tags or []
    sections: dict[str, Any] = raw_data.get("sections") or {}

    salary_min, salary_max = parse_salary_range(salary_text)

    # 全文テキスト結合によるスキル・リモート判定
    all_section_text = "\n".join(
        sec.get("fullText", "") for sec in sections.values() if isinstance(sec, dict)
    )
    remote_type = detect_remote_type(location, all_section_text)
    extracted_skills = extract_skills_from_text(all_section_text)

    # 本文セクション構築
    body_lines = [f"# {title}", ""]

    # 1. 仕事内容
    job_desc_content = ""
    for sec_name, sec in sections.items():
        if "仕事内容" in sec_name or "業務内容" in sec_name:
            job_desc_content = sec.get("fullText", "").strip()
            break
    if not job_desc_content:
        job_desc_content = "（記載なし）"

    body_lines.append("## 概要・仕事内容")
    body_lines.append(job_desc_content)
    body_lines.append("")

    # 2. 応募資格 (必須・歓迎)
    qual_sec = None
    for sec_name, sec in sections.items():
        if "応募資格" in sec_name or "スキル" in sec_name:
            qual_sec = sec
            break

    must_text = ""
    desired_text = ""
    if qual_sec and isinstance(qual_sec, dict):
        full_qual = qual_sec.get("fullText", "").strip()
        pattern = r"(必須\([A-Za-z]+\)|歓迎\([A-Za-z]+\)|その他\([A-Za-z]+\)|(?:^|\n)\s*(?:【|■)?(?:必須要件?|歓迎要件?|応募資格)(?:】|:)?)"
        tokens = re.split(pattern, full_qual)
        current_type = None
        for t in tokens:
            t_strip = t.strip()
            if not t_strip:
                continue

            is_heading = False
            if re.fullmatch(r"必須(?:\([A-Za-z]+\))?|【?必須要件?】?|応募資格", t_strip):
                current_type = "must"
                is_heading = True
            elif re.fullmatch(r"歓迎(?:\([A-Za-z]+\))?|【?歓迎要件?】?|尚可", t_strip):
                current_type = "desired"
                is_heading = True
            elif re.fullmatch(r"その他(?:\([A-Za-z]+\))?", t_strip):
                current_type = "other"
                is_heading = True

            if not is_heading:
                if current_type == "must":
                    must_text += f"{t_strip}\n\n"
                elif current_type == "desired":
                    desired_text += f"{t_strip}\n\n"
                elif current_type is None:
                    must_text += f"{t_strip}\n\n"
        if not must_text and not desired_text:
            must_text = full_qual

    body_lines.append("## 必須要件 (Must)")
    body_lines.append(must_text.strip() or "（記載なし）")
    body_lines.append("")

    body_lines.append("## 歓迎要件 (Desired)")
    body_lines.append(desired_text.strip() or "（記載なし）")
    body_lines.append("")

    # 3. 労働条件・福利厚生
    work_cond_text = ""
    for sec_name, sec in sections.items():
        if "労働条件" in sec_name or "勤務条件" in sec_name or "待遇" in sec_name:
            dl_items = sec.get("dlItems", {})
            if dl_items:
                dl_lines = [f"### {k}\n\n{v}" for k, v in dl_items.items()]
                work_cond_text = "\n\n".join(dl_lines)
            else:
                work_cond_text = sec.get("fullText", "").strip()
            break

    if work_cond_text:
        body_lines.append("## 勤務地・就業条件・福利厚生")
        body_lines.append(work_cond_text)
        body_lines.append("")

    # 4. 職場情報・その他
    workplace_text = ""
    for sec_name, sec in sections.items():
        if "職場情報" in sec_name or "環境" in sec_name:
            dl_items = sec.get("dlItems", {})
            if dl_items:
                dl_lines = [f"### {k}\n\n{v}" for k, v in dl_items.items()]
                workplace_text = "\n\n".join(dl_lines)
            else:
                workplace_text = sec.get("fullText", "").strip()
            break

    if workplace_text:
        body_lines.append("## 職場情報・その他")
        body_lines.append(workplace_text)
        body_lines.append("")

    # 5. 採用企業情報
    company_info_text = ""
    for sec_name, sec in sections.items():
        if "企業情報" in sec_name or "会社概要" in sec_name:
            dl_items = sec.get("dlItems", {})
            if dl_items:
                dl_lines = [f"### {k}\n\n{v}" for k, v in dl_items.items()]
                company_info_text = "\n\n".join(dl_lines)
            else:
                company_info_text = sec.get("fullText", "").strip()
            break

    if company_info_text:
        body_lines.append("## 採用企業情報")
        body_lines.append(company_info_text)
        body_lines.append("")

    return JobData(
        id=job_id,
        source="bizreach",
        company=company,
        title=title,
        url=job_url,
        fetched_at=now.isoformat(timespec="seconds"),
        salary_min=salary_min,
        salary_max=salary_max,
        salary_text=salary_text,
        skills=extracted_skills,
        location=location,
        remote_type=remote_type,
        tags=tags,
        company_url=company_url,
        raw_body="\n".join(body_lines).strip(),
        extra_metadata=extra_frontmatter or {},
    )


def format_job_markdown(
    raw_data: dict[str, Any],
    job_id: str,
    job_url: str,
    now: datetime,
    initial_location: str | None = None,
    initial_tags: list[str] | None = None,
    extra_frontmatter: dict[str, Any] | None = None,
) -> str:
    """JobData を経由して完全な Markdown 文字列を生成する."""
    job = build_job_data(
        raw_data=raw_data,
        job_id=job_id,
        job_url=job_url,
        now=now,
        initial_location=initial_location,
        initial_tags=initial_tags,
        extra_frontmatter=extra_frontmatter,
    )
    return job.to_markdown()


def fetch_and_save_bizreach_job(
    url_or_id: str,
    session: str = "job-hunt",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    force: bool = False,
    dry_run: bool = False,
    summary: bool = False,
    initial_location: str | None = None,
    initial_tags: list[str] | None = None,
    extra_frontmatter: dict[str, Any] | None = None,
) -> tuple[Path | None, dict[str, Any]]:
    """Playwrightセッション経由でビズリーチの求人詳細を取得・保存する."""
    job_id, job_url = normalize_job_url(url_or_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{job_id}.md"

    if out_path.exists() and not force:
        if summary:
            print(f"[スキップ] 既に保存されています: {to_relative_path(out_path)}", file=sys.stderr)
        return out_path, {"id": job_id, "url": job_url, "status": "skipped"}

    # run_code_snippet を使用して安全に一時スクリプトを実行
    script_content = generate_fetch_script_content(job_url)
    raw_res = run_code_snippet(session, script_content, timeout=30)

    if not raw_res or not raw_res.get("success"):
        err_msg = raw_res.get("error") if raw_res else "取得結果が空でした"
        raise RuntimeError(f"求人詳細取得に失敗しました ({job_url}): {err_msg}")

    now = datetime.now()
    job = build_job_data(
        raw_data=raw_res,
        job_id=job_id,
        job_url=job_url,
        now=now,
        initial_location=initial_location,
        initial_tags=initial_tags,
        extra_frontmatter=extra_frontmatter,
    )

    if not dry_run:
        saved_path, _ = save_job_markdown(job, output_dir=output_dir, force=force)
        if summary:
            print(f"[保存完了] {to_relative_path(saved_path)}", file=sys.stderr)
        return saved_path, raw_res

    return out_path, raw_res


def main() -> None:
    """単体求人詳細取得CLIエントリポイント."""
    parser = create_base_parser(description="ビズリーチ求人詳細取得スクリプト")
    parser.add_argument("target", help="ビズリーチ求人URLまたは求人ID")
    parser.add_argument("--session", default="job-hunt", help="Playwrightセッション名")
    parser.add_argument("-o", "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="保存先ディレクトリ")
    parser.add_argument("--dry-run", action="store_true", help="ファイル書き込みを行わない")
    parser.add_argument("--keep-open", action="store_true", help="ブラウザセッションを維持")

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)
    profile_dir = resolve_profile_path(args.session)

    # セッション確認/起動（固定URLを開く）
    run_playwright_cmd(
        [f"-s={args.session}", "open", "https://www.bizreach.jp/job-search/", f"--profile={profile_dir}"],
        timeout=30,
    )

    try:
        path, data = fetch_and_save_bizreach_job(
            args.target,
            session=args.session,
            output_dir=args.output_dir,
            force=args.force,
            dry_run=args.dry_run,
            summary=args.summary,
        )

        if path:
            ctx.add_result_path(path)

        def summary_fn() -> None:
            print(f"求人タイトル: {data.get('title')}")
            print(f"企業名:       {data.get('company')}")
            print(f"想定年収:     {data.get('salaryText')}")
            if path:
                print(f"保存パス:     {to_relative_path(path)}")

        sys.exit(ctx.flush_outputs(summary_fn=summary_fn, json_data=data))
    finally:
        if not args.keep_open:
            run_playwright_cmd([f"-s={args.session}", "close"], timeout=10)


if __name__ == "__main__":
    main()
