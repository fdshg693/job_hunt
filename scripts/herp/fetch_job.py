"""HERP Careers の求人票を URL/ID から取得して Markdown 保存する CLI.

HERP求人票取得・Markdown保存モジュール (fetch_job.py).
HERP Careers（herp.careers）の求人URLまたはIDを受け取り、
本文を取得して data/herp/jobs/{company}_{jobId}.md に保存します。
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

# プロジェクトルートパス
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import to_relative_path
from scripts.common.crawlers.job_pipeline import (
    JobCrawlerConfig,
    JobPipelineContext,
    run_job_pipeline,
)
from scripts.common.normalizers import (
    detect_remote_type,
    extract_skills_from_text,
    parse_salary_range,
)
from scripts.common.storage import JobData, save_job_markdown

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "herp" / "jobs"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

HTTP_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

# URL & ID 正規表現パターン
NEW_FORMAT_RE = re.compile(r"herp\.careers/v1/([^/?#]+)/([^/?#]+)")
OLD_FORMAT_RE = re.compile(r"herp\.careers/careers/companies/([^/?#]+)/jobs/([^/?#]+)")
ID_FORMAT_RE = re.compile(r"^([a-zA-Z0-9_-]+)[_/]([a-zA-Z0-9_-]+)$")


def parse_herp_target(target: str) -> tuple[str, str]:
    """対象文字列から (company, job_id) のタプルを抽出する.

    新形式 URL、旧形式 URL、ID直指定（company_jobId または company/jobId）に対応します。
    """
    cleaned = target.strip()

    # 1. 新形式 URL (https://herp.careers/v1/{company}/{jobId})
    m_new = NEW_FORMAT_RE.search(cleaned)
    if m_new:
        return m_new.group(1), m_new.group(2)

    # 2. 旧形式 URL (https://herp.careers/careers/companies/{company}/jobs/{jobId})
    m_old = OLD_FORMAT_RE.search(cleaned)
    if m_old:
        return m_old.group(1), m_old.group(2)

    # 3. ID直指定 ({company}_{jobId} または {company}/{jobId})
    m_id = ID_FORMAT_RE.match(cleaned)
    if m_id:
        return m_id.group(1), m_id.group(2)

    raise ValueError(f"無効なHERP求人URLまたはIDです: {target}")


def extract_job_id(target: str) -> str:
    """求人URLまたはID文字列から統一ID ({company}_{jobId}) を抽出する."""
    company, job_id = parse_herp_target(target)
    return f"{company}_{job_id}"


def normalize_url(target: str) -> str:
    """求人URLまたはID文字列から正規化された新形式URL (https://herp.careers/v1/{company}/{jobId}) を返す."""
    company, job_id = parse_herp_target(target)
    return f"https://herp.careers/v1/{company}/{job_id}"


def fetch_job_html_via_http(url: str, timeout: int = 15) -> str:
    """urllib.request を用いて静的HTMLを取得する."""
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _node_to_markdown(elem: Any) -> str:
    """BeautifulSoupのタグまたはナビゲーション文字列をMarkdownテキストに再帰変換する."""
    if isinstance(elem, str):
        return str(elem)

    tag_name = getattr(elem, "name", None)
    if not tag_name:
        return ""

    if tag_name in ("script", "style"):
        return ""

    if tag_name == "br":
        return "\n"

    if tag_name in ("h3", "h4", "h5", "h6"):
        level = int(tag_name[1])
        inner = "".join(_node_to_markdown(c) for c in elem.children).strip()
        return f"\n\n{'#' * level} {inner}\n\n"

    if tag_name == "p":
        inner = "".join(_node_to_markdown(c) for c in elem.children).strip()
        return f"\n\n{inner}\n\n"

    if tag_name in ("ul", "ol"):
        lines = []
        for child in elem.children:
            if getattr(child, "name", None) == "li":
                li_text = "".join(_node_to_markdown(c) for c in child.children).strip()
                lines.append(f"- {li_text}")
        return "\n\n" + "\n".join(lines) + "\n\n"

    if tag_name == "li":
        inner = "".join(_node_to_markdown(c) for c in elem.children).strip()
        return f"- {inner}\n"

    if tag_name == "a":
        inner = "".join(_node_to_markdown(c) for c in elem.children).strip()
        href = elem.get("href", "")
        if href and inner:
            return f"[{inner}]({href})"
        return inner or href

    if tag_name in ("b", "strong"):
        inner = "".join(_node_to_markdown(c) for c in elem.children).strip()
        return f"**{inner}**" if inner else ""

    return "".join(_node_to_markdown(c) for c in elem.children)


def _clean_markdown(text: str) -> str:
    """連続改行を圧縮し、前後の空白を除去する."""
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def _table_to_markdown(table: Any) -> str:
    """table要素を ### 見出し + 本文 のMarkdownブロック列に変換する."""
    rows: list[str] = []
    for tr in table.find_all("tr"):
        th = tr.find("th")
        td = tr.find("td")
        if th and td:
            th_text = th.get_text(strip=True)
            a_tag = td.find("a")
            if a_tag and a_tag.get("href") and not td.get_text(strip=True).startswith("http"):
                td_text = f"[{td.get_text(strip=True)}]({a_tag['href']})"
            else:
                td_text = td.get_text(strip=True)
            rows.append(f"### {th_text}\n\n{td_text}")
    return "\n\n".join(rows)


def _normalize_heading(h2_text: str) -> str:
    """HERPの見出しを job-data-format.md の標準見出し体系に正規化する."""
    h = h2_text.strip()
    if any(k in h for k in ("仕事概要", "募集概要", "仕事内容", "業務内容")):
        return "## 概要・仕事内容"
    if any(k in h for k in ("必須スキル", "必須要件", "求めるスキル")):
        return "## 必須要件 (Must)"
    if any(k in h for k in ("歓迎スキル", "歓迎要件", "尚可")):
        return "## 歓迎要件 (Desired)"
    if any(k in h for k in ("求める人物像", "求める人物", "人物像")):
        return "## 求める人物像"
    if any(k in h for k in ("応募概要", "募集要項", "就業条件", "勤務条件")):
        return "## 勤務地・就業条件・福利厚生"
    if any(k in h for k in ("企業情報", "会社情報", "会社概要")):
        return "## 採用企業情報"
    return f"## {h}"


def parse_herp_job_data(
    html_content: str,
    target_url: str,
    job_id: str,
    now: datetime,
) -> JobData:
    """HERP求人HTMLをパースし、JobDataモデルを構築する."""
    soup = BeautifulSoup(html_content, "html.parser")
    company_slug, herp_job_id = parse_herp_target(target_url)

    # 1. JSON-LD の抽出（補助情報）
    json_ld_data: dict[str, Any] = {}
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            val = json.loads(script.string or "")
            if isinstance(val, dict) and val.get("@type") == "JobPosting":
                json_ld_data = val
                break
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict) and item.get("@type") == "JobPosting":
                        json_ld_data = item
                        break
        except Exception:
            continue

    # 2. タイトルとキャッチコピーの抽出
    title_el = soup.find("h1", class_="requisition-header__name")
    if title_el and title_el.get_text(strip=True):
        title = title_el.get_text(strip=True)
    elif json_ld_data.get("title"):
        title = str(json_ld_data["title"]).strip()
    else:
        first_h1 = soup.find("h1")
        title = first_h1.get_text(strip=True) if first_h1 else "（タイトルなし）"

    catchcopy_el = soup.find("h1", class_="requisition-title")
    catchcopy = catchcopy_el.get_text(strip=True) if catchcopy_el else ""

    # 3. 各セクションの走査とテーブルフィールドの抽出
    sections = soup.find_all("section", class_="with-heading")
    salary_text = ""
    location = ""
    remote_hint = ""
    company_from_table = ""
    company_url_from_table = ""

    for sec in sections:
        table = sec.find("table")
        if not table:
            continue
        for tr in table.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if not th or not td:
                continue
            th_key = th.get_text(strip=True)
            td_val = td.get_text(strip=True)
            if "給与" in th_key:
                salary_text = td_val
            elif "勤務地" in th_key:
                location = td_val
            elif any(k in th_key for k in ("勤務体系", "就業形態", "労働時間", "勤務形態")):
                remote_hint = td_val
            elif any(k in th_key for k in ("企業名", "会社名")):
                company_from_table = td_val
            elif any(k in th_key for k in ("企業サイトURL", "コーポレートサイト", "会社URL", "URL")):
                a_tag = td.find("a")
                company_url_from_table = a_tag["href"].strip() if a_tag and a_tag.get("href") else td_val

    # 4. 企業名・会社URL・勤務地のフォールバック
    org = json_ld_data.get("hiringOrganization") if isinstance(json_ld_data.get("hiringOrganization"), dict) else {}
    company = company_from_table or org.get("name") or company_slug or "（企業名非公開）"
    company_url = company_url_from_table or org.get("sameAs", "")

    if not location and json_ld_data.get("jobLocation"):
        job_loc = json_ld_data["jobLocation"]
        if isinstance(job_loc, dict):
            location = job_loc.get("address", "")
        elif isinstance(job_loc, str):
            location = job_loc

    # 5. 給与数値パース
    salary_min, salary_max = parse_salary_range(salary_text)

    # 6. 本文 Markdown (raw_body) の構築
    body_parts: list[str] = [f"# {title}"]
    if catchcopy:
        body_parts.append(f"> {catchcopy}")

    all_section_text_blobs: list[str] = []

    for sec in sections:
        h2 = sec.find("h2")
        if not h2:
            continue
        h2_text = h2.get_text(strip=True)
        md_heading = _normalize_heading(h2_text)
        body_parts.append(md_heading)

        content_div = sec.find(class_="with-heading__content")
        if content_div:
            table = content_div.find("table")
            if table:
                body_parts.append(_table_to_markdown(table))
                all_section_text_blobs.append(content_div.get_text(" ", strip=True))
            else:
                text_md = _clean_markdown(_node_to_markdown(content_div))
                if text_md:
                    body_parts.append(text_md)
                all_section_text_blobs.append(content_div.get_text(" ", strip=True))

    raw_body = "\n\n".join(body_parts).strip()

    # 7. スキル・リモート判定
    full_text_blob = f"{title} {catchcopy} {salary_text} {location} {remote_hint} {' '.join(all_section_text_blobs)}"
    remote_type = detect_remote_type(location, full_text_blob)
    skills = extract_skills_from_text(full_text_blob)

    # 8. 拡張メタデータ
    extra_metadata: dict[str, Any] = {
        "company_slug": company_slug,
        "herp_job_id": herp_job_id,
    }
    if catchcopy:
        extra_metadata["catchcopy"] = catchcopy
    if json_ld_data.get("datePosted"):
        extra_metadata["date_posted"] = json_ld_data["datePosted"]

    return JobData(
        id=job_id,
        source="herp",
        company=company,
        title=title,
        url=target_url,
        fetched_at=now.isoformat(timespec="seconds"),
        salary_min=salary_min,
        salary_max=salary_max,
        salary_text=salary_text,
        skills=skills,
        location=location,
        remote_type=remote_type,
        company_url=company_url,
        raw_body=raw_body,
        extra_metadata=extra_metadata,
    )


def _fetch_herp_job(ctx: JobPipelineContext) -> JobData:
    """求人パイプラインから呼び出されるフェッチ関数."""
    timeout = getattr(ctx.args, "timeout", 15) or 15
    try:
        html = fetch_job_html_via_http(ctx.target_url, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            ctx.entrypoint_ctx.error(
                f"求人が見つかりませんでした（掲載終了またはURL誤りの可能性があります）: {ctx.target_url}"
            )
            sys.exit(1)
        ctx.entrypoint_ctx.error(f"HTTPエラーが発生しました ({e.code} {e.reason}): {ctx.target_url}")
        sys.exit(1)
    except urllib.error.URLError as e:
        ctx.entrypoint_ctx.error(f"通信エラーが発生しました: {e.reason}")
        sys.exit(1)

    return parse_herp_job_data(html, target_url=ctx.target_url, job_id=ctx.job_id, now=ctx.now)


def fetch_and_save_herp_job(
    target: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    force: bool = False,
    dry_run: bool = False,
    summary: bool = False,
    timeout: int = 15,
) -> tuple[Path, dict[str, Any]]:
    """HERP求人票を直接取得・保存する関数."""
    job_id = extract_job_id(target)
    target_url = normalize_url(target)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{job_id}.md"

    if out_path.exists() and not force:
        if summary:
            print(f"[スキップ] 既に保存されています: {to_relative_path(out_path)}", file=sys.stderr)
        return out_path, {"id": job_id, "url": target_url, "status": "skipped", "modified": False}

    html = fetch_job_html_via_http(target_url, timeout=timeout)
    now = datetime.now()
    job = parse_herp_job_data(html, target_url=target_url, job_id=job_id, now=now)

    if not dry_run:
        saved_path, is_modified = save_job_markdown(job, output_dir=output_dir, force=force)
        if summary:
            print(f"[保存完了] {to_relative_path(saved_path)}", file=sys.stderr)
        return saved_path, {"id": job_id, "url": target_url, "status": "saved", "modified": is_modified, "job": job}

    return out_path, {"id": job_id, "url": target_url, "status": "dry_run", "modified": False, "job": job}


HERP_JOB_CONFIG = JobCrawlerConfig(
    examples=[
        "uv run python scripts/herp/fetch_job.py https://herp.careers/v1/<company>/<jobId> --summary",
        "uv run python scripts/herp/fetch_job.py <company>_<jobId> --force --summary  # 保存済みでも取り直す",
    ],
    related=[
        "scripts/common/search_local_jobs.py: 次に使う（保存済み求人を横断検索）",
    ],
    site_id="herp",
    site_name="HERP",
    default_output_dir=DEFAULT_OUTPUT_DIR,
    auth_site=None,
    extract_job_id_fn=extract_job_id,
    normalize_url_fn=normalize_url,
    custom_fetch_fn=_fetch_herp_job,
    default_timeout=15,
)


def main() -> None:
    """単体求人詳細取得CLIエントリポイント."""
    sys.exit(run_job_pipeline(HERP_JOB_CONFIG))


if __name__ == "__main__":
    main()
