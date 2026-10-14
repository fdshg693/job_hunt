"""Findy求人情報の取得・Markdown保存スクリプト.

Findyの求人URLから求人詳細を取得し、YAMLフロントマター付きMarkdownとして保存します。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# プロジェクトルートパスを sys.path に追加して直接実行に対応
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx
from bs4 import BeautifulSoup

from scripts.common.cli import EntrypointContext, create_base_parser, to_relative_path
from scripts.common.normalizers import detect_remote_type, format_salary_text, normalize_url
from scripts.common.storage import JobData, save_job_markdown

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "findy" / "jobs"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def extract_job_id_from_url(url: str) -> str:
    """Findyの求人URLからjob_idを抽出する."""
    parsed = urlparse(url)
    match = re.search(r"/jobs/([a-zA-Z0-9_-]+)", parsed.path)
    if not match:
        raise ValueError(
            f"無効なFindy求人URL形式です: {url}\n"
            "期待する形式: https://findy-code.io/companies/{company_id}/jobs/{job_id}"
        )
    return match.group(1)


def normalize_findy_url(url: str) -> str:
    """クエリパラメータを除去した正規化URLを返す."""
    return normalize_url(url)


def fetch_job_html(url: str) -> str:
    """HTTPリクエストを送信してHTMLを取得する."""
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    with httpx.Client(headers=headers, follow_redirects=True, timeout=15.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _parse_from_next_data(
    jd: dict[str, Any], page_props: dict[str, Any], url: str, job_id: str
) -> tuple[dict[str, Any], str]:
    """__NEXT_DATA__ の jobDescription からデータを構築."""
    company_obj = jd.get("company") or {}
    company_name = company_obj.get("name") or page_props.get("companyName") or "不明な企業"
    title = jd.get("title") or page_props.get("title") or "タイトルなし"
    company_url = company_obj.get("url")

    salary_min = jd.get("numericSalaryMin")
    salary_max = jd.get("numericSalaryMax")
    salary_remark = jd.get("salary") or jd.get("salaryRemark")
    salary_text = format_salary_text(salary_min, salary_max, salary_remark)

    skills_raw = jd.get("skills") or []
    skills = [s["name"] for s in skills_raw if isinstance(s, dict) and s.get("name")]

    job_roles_raw = jd.get("jobRoles") or []
    job_roles = [r["name"] for r in job_roles_raw if isinstance(r, dict) and r.get("name")]

    tags_raw = jd.get("tags") or []
    tags = [t["name"] for t in tags_raw if isinstance(t, dict) and t.get("name")]

    location = jd.get("location")
    remote_type = detect_remote_type(location, f"{jd.get('description', '')} {location or ''}")

    # フロントマター用辞書
    fetched_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    frontmatter: dict[str, Any] = {
        "id": job_id,
        "source": "findy",
        "company": company_name,
        "title": title,
        "url": normalize_findy_url(url),
        "fetched_at": fetched_at,
    }

    if salary_min is not None:
        frontmatter["salary_min"] = salary_min
    if salary_max is not None:
        frontmatter["salary_max"] = salary_max
    if salary_text:
        frontmatter["salary_text"] = salary_text
    if skills:
        frontmatter["skills"] = skills
    if job_roles:
        frontmatter["job_roles"] = job_roles
    if location:
        location_one_line = " ".join(location.splitlines()).strip()
        frontmatter["location"] = location_one_line
    if remote_type:
        frontmatter["remote_type"] = remote_type
    if tags:
        frontmatter["tags"] = tags
    if company_url:
        frontmatter["company_url"] = company_url

    # 本文Markdown構築
    body_sections: list[str] = [f"# {title}\n"]

    if jd.get("description"):
        body_sections.append(f"## 概要・仕事内容\n\n{jd['description'].strip()}\n")

    if jd.get("mustSkills"):
        body_sections.append(f"## 必須要件 (Must)\n\n{jd['mustSkills'].strip()}\n")

    if jd.get("desiredSkills"):
        body_sections.append(f"## 歓迎要件 (Desired)\n\n{jd['desiredSkills'].strip()}\n")

    if jd.get("developmentEnvironment"):
        body_sections.append(f"## 開発環境\n\n{jd['developmentEnvironment'].strip()}\n")

    if jd.get("rewarding"):
        body_sections.append(f"## 仕事の魅力・特徴\n\n{jd['rewarding'].strip()}\n")

    if jd.get("personality"):
        body_sections.append(f"## 求める人物像\n\n{jd['personality'].strip()}\n")

    conditions: list[str] = []
    if location:
        conditions.append(f"### 勤務地\n\n{location.strip()}")
    if jd.get("workHours"):
        conditions.append(f"### 勤務時間\n\n{jd['workHours'].strip()}")
    if jd.get("holidays"):
        conditions.append(f"### 休日・休暇\n\n{jd['holidays'].strip()}")
    if jd.get("welfare"):
        conditions.append(f"### 福利厚生・手当\n\n{jd['welfare'].strip()}")
    if jd.get("trialPeriod"):
        conditions.append(f"### 試用期間\n\n{jd['trialPeriod'].strip()}")

    if conditions:
        body_sections.append("## 勤務条件・福利厚生\n\n" + "\n\n".join(conditions) + "\n")

    if jd.get("screeningProcess"):
        body_sections.append(f"## 選考プロセス\n\n{jd['screeningProcess'].strip()}\n")

    if jd.get("others"):
        body_sections.append(f"## その他・関連リンク\n\n{jd['others'].strip()}\n")

    body_markdown = "\n".join(body_sections)
    return frontmatter, body_markdown


def _parse_from_dom_fallback(soup: BeautifulSoup, url: str, job_id: str) -> tuple[dict[str, Any], str]:
    """Next.jsデータが無い場合のフォールバックパース."""
    og_title = soup.find("meta", property="og:title")
    title = og_title.get("content", "").strip() if og_title else ""
    if not title and soup.title:
        title = soup.title.string.strip() if soup.title.string else "タイトルなし"

    description_meta = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
    description = description_meta.get("content", "").strip() if description_meta else ""

    fetched_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    frontmatter: dict[str, Any] = {
        "id": job_id,
        "source": "findy",
        "company": "不明な企業",
        "title": title or "タイトルなし",
        "url": normalize_findy_url(url),
        "fetched_at": fetched_at,
    }

    body = f"# {title}\n\n## 概要\n\n{description}\n"
    return frontmatter, body


def parse_job_from_html(html: str, url: str, job_id: str) -> tuple[dict[str, Any], str]:
    """HTMLからフロントマター辞書とMarkdown本文を抽出・構築する."""
    soup = BeautifulSoup(html, "html.parser")
    next_data_tag = soup.find("script", id="__NEXT_DATA__")

    if next_data_tag and next_data_tag.string:
        try:
            next_data = json.loads(next_data_tag.string)
            page_props = next_data.get("props", {}).get("pageProps", {})
            jd = page_props.get("jobDescription")
            if jd and isinstance(jd, dict):
                return _parse_from_next_data(jd, page_props, url, job_id)
        except json.JSONDecodeError:
            pass

    return _parse_from_dom_fallback(soup, url, job_id)


def fetch_and_save_job(
    url: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    force: bool = False,
    dry_run: bool = False,
    summary: bool = False,
) -> tuple[Path | None, dict[str, Any] | None]:
    """求人情報を取得してMarkdownファイルに保存する."""
    job_id = extract_job_id_from_url(url)
    output_path = output_dir / f"{job_id}.md"

    if output_path.exists() and not force and not dry_run:
        print(f"[スキップ] 既にファイルが存在します: {to_relative_path(output_path)} (上書きには --force を指定)", file=sys.stderr)
        return output_path, None

    print(f"[取得中] {url}", file=sys.stderr)
    html = fetch_job_html(url)
    frontmatter, body = parse_job_from_html(html, url, job_id)

    job = JobData(
        id=job_id,
        source="findy",
        company=frontmatter.get("company", ""),
        title=frontmatter.get("title", ""),
        url=frontmatter.get("url", ""),
        fetched_at=frontmatter.get("fetched_at"),
        salary_min=frontmatter.get("salary_min"),
        salary_max=frontmatter.get("salary_max"),
        salary_text=frontmatter.get("salary_text", ""),
        skills=frontmatter.get("skills", []),
        job_roles=frontmatter.get("job_roles", []),
        location=frontmatter.get("location", ""),
        remote_type=frontmatter.get("remote_type", "出社"),
        tags=frontmatter.get("tags", []),
        company_url=frontmatter.get("company_url", ""),
        raw_body=body,
    )

    if dry_run:
        print(f"[DRY-RUN] 保存先: {to_relative_path(output_path)}", file=sys.stderr)
        print("---", file=sys.stderr)
        print(job.to_markdown()[:500] + "\n...(省略)...", file=sys.stderr)
        return None, frontmatter

    saved_path, is_saved = save_job_markdown(job, output_dir=output_dir, force=force)
    if summary:
        print(f"[保存完了] {frontmatter.get('company')} - {frontmatter.get('title')}", file=sys.stderr)
        print(f"         -> {to_relative_path(saved_path)}", file=sys.stderr)
    return saved_path, frontmatter


def main() -> None:
    parser = create_base_parser(
        description="Findyの求人URLから求人情報を取得し、フロントマター付きMarkdownとして保存します。"
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="Findy求人URL (複数指定可)",
    )
    parser.add_argument(
        "-f",
        "--file",
        type=Path,
        help="URLを行ごとに記述したテキストファイルのパス",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"保存先ディレクトリ (デフォルト: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="ファイルに保存せず内容をプレビューする",
    )

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    target_urls: list[str] = list(args.urls)
    if args.file:
        if not args.file.exists():
            ctx.error(f"指定されたファイルが見つかりません: {args.file}")
            sys.exit(1)
        for line in args.file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                target_urls.append(line)

    if not target_urls:
        parser.print_help(sys.stderr)
        sys.exit(1)

    success_count = 0
    error_count = 0

    for url in target_urls:
        try:
            saved_path, meta = fetch_and_save_job(
                url=url,
                output_dir=args.output_dir,
                force=args.force,
                dry_run=args.dry_run,
                summary=args.summary,
            )
            if saved_path is not None:
                ctx.add_result_path(saved_path)
                success_count += 1
            elif args.dry_run:
                success_count += 1
        except Exception as e:
            ctx.error(f"{url}: {e}")
            error_count += 1

    def summary_fn() -> None:
        print(f"\n完了: 成功 {success_count} 件 / エラー {error_count} 件")
        for p in ctx.result_paths:
            print(f"  - {p}")

    if error_count > 0 and success_count == 0:
        ctx.set_exit_code(1)

    sys.exit(ctx.flush_outputs(summary_fn=summary_fn))


if __name__ == "__main__":
    main()
