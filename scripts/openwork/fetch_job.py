"""OpenWork の求人詳細を URL/ID から取得して Markdown 保存する CLI.

OpenWork求人詳細取得・Markdown保存モジュール.
OpenWorkの求人URLまたはIDから求人詳細を取得し、
プロジェクト共通仕様（.agents/rules/job-data-format.md）に準拠したフロントマター付きMarkdownとして保存します。
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
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

OPENWORK_SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "openwork" / "jobs"
SEARCHES_DIR = PROJECT_ROOT / "data" / "openwork" / "searches"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

HTTP_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


def extract_job_id_from_url(url: str) -> str | None:
    """求人URLからjob tokenまたはクエリパラメータのj値を抽出する."""
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    if "j" in qs and qs["j"]:
        return qs["j"][0]
    return None


def resolve_job_url_by_id(job_id: str) -> str | None:
    """過去の検索結果JSONを探索し、求人IDに対応する詳細URLを取得する."""
    if not SEARCHES_DIR.exists():
        return None

    for json_file in sorted(SEARCHES_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            for job in data.get("jobs", []):
                if str(job.get("id")) == str(job_id) and job.get("url"):
                    u = job["url"]
                    return u if u.startswith("http") else f"https://www.openwork.jp{u}"
        except Exception:
            continue
    return None


def fetch_html_via_http(url: str) -> tuple[str | None, int]:
    """urllib.request 経由で静的HTMLを取得する."""
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            return html, resp.getcode()
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception:
        return None, 0


def fetch_html_via_playwright(
    url: str,
    session: str = "job-hunt",
    timeout: int = 120,
    no_notify: bool = False,
) -> str | None:
    """Playwright CLIセッション経由でページを取得する（CAPTCHA対応）."""
    profile_dir = resolve_profile_path(session)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    # セッション起動確認
    run_playwright_cmd(
        [f"-s={session}", "open", "about:blank", f"--profile={profile_dir}"],
        timeout=30,
    )

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

    # CAPTCHA壁の検知時は共通認証エンジンでハンドオフ
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

        # 再度取得
        res = run_code_snippet(session, script_code, timeout=35)
        if not res:
            return None

    return res.get("html")


def parse_job_detail_html(
    html_content: str,
    job_url: str,
    explicit_job_id: str | None = None,
    initial_company: str | None = None,
    initial_title: str | None = None,
) -> dict[str, Any]:
    """求人詳細ページのHTMLをパースし、構造化辞書を返す."""
    soup = BeautifulSoup(html_content, "html.parser")

    # 1. 求人IDの抽出
    job_id = explicit_job_id
    if not job_id:
        modal_btn = soup.find(attrs={"data-_vmodal-job-id": True})
        if modal_btn and modal_btn.get("data-_vmodal-job-id"):
            job_id = modal_btn["data-_vmodal-job-id"]
    if not job_id:
        job_id = extract_job_id_from_url(job_url) or "unknown"

    # 2. 職種名 / 求人タイトル
    title = initial_title or ""
    dt_role = None
    for dt in soup.find_all("dt"):
        if "職種名" in dt.get_text():
            dt_role = dt.find_next_sibling("dd")
            break
    if dt_role:
        title = dt_role.get_text(strip=True)
    if not title:
        h1 = soup.find("h1")
        if h1:
            raw_h1 = h1.get_text(strip=True)
            m_h1 = re.search(r"「(.+?)」", raw_h1)
            title = m_h1.group(1) if m_h1 else raw_h1

    # 3. 企業名
    company = initial_company or ""
    for dt in soup.find_all("dt"):
        if "社名" in dt.get_text():
            dd = dt.find_next_sibling("dd")
            if dd and dd.get_text(strip=True):
                company = dd.get_text(strip=True)
                break
    if not company:
        h1 = soup.find("h1")
        if h1:
            raw_h1 = h1.get_text(strip=True)
            m_comp = re.search(r"^(.+?)の「", raw_h1)
            if m_comp:
                company = m_comp.group(1).strip()
    if not company:
        for table in soup.find_all("table", class_=re.compile(r"definitionList")):
            for tr in table.find_all("tr"):
                th = tr.find("th")
                td = tr.find("td")
                if th and td and "社名" in th.get_text():
                    company = td.get_text(strip=True)
                    break

    # 4. 会社Wiki情報 (URL, 業界, 所在地, 社員数, 設立年, 代表者)
    company_url = ""
    company_info: dict[str, str] = {}
    for table in soup.find_all("table", class_=re.compile(r"definitionList")):
        for tr in table.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if th and td:
                k = th.get_text(strip=True)
                v = td.get_text(strip=True)
                if k and v:
                    company_info[k] = v
                if "URL" in k:
                    a = td.find("a")
                    if a and a.get("href"):
                        company_url = a["href"].strip()

    # 5. 仕事内容
    job_description = ""
    for dt in soup.find_all("dt"):
        if "仕事内容" in dt.get_text():
            dd = dt.find_next_sibling("dd")
            if dd:
                job_description = dd.get_text("\n", strip=True)
            break

    # 6. 求める経験・スキル (必須要件・尚可要件)
    must_skills = ""
    desired_skills = ""
    skills_text = ""
    for dt in soup.find_all("dt"):
        if "求める経験・スキル" in dt.get_text():
            dd = dt.find_next_sibling("dd")
            if dd:
                skills_text = dd.get_text("\n", strip=True)
            break

    if skills_text:
        pattern = r"((?:^|\n)\s*(?:【|■)?(?:必須要件?|尚可要件?|歓迎要件?|必須スキル?|歓迎スキル?)(?:】|:)?)"
        tokens = re.split(pattern, skills_text)
        current_type = "must"
        for t in tokens:
            t_strip = t.strip()
            if not t_strip:
                continue
            if re.search(r"必須", t_strip):
                current_type = "must"
            elif re.search(r"尚可|歓迎", t_strip):
                current_type = "desired"
            else:
                if current_type == "must":
                    must_skills += f"{t_strip}\n\n"
                elif current_type == "desired":
                    desired_skills += f"{t_strip}\n\n"
        if not must_skills and not desired_skills:
            must_skills = skills_text

    # 7. 給与・年収
    salary_text = ""
    for dt in soup.find_all("dt"):
        if "給与" in dt.get_text():
            dd = dt.find_next_sibling("dd")
            if dd:
                salary_text = dd.get_text("\n", strip=True)
            break

    # 8. 勤務地
    location = ""
    for dt in soup.find_all("dt"):
        if "勤務地" in dt.get_text():
            dd = dt.find_next_sibling("dd")
            if dd:
                location = dd.get_text(" ", strip=True)
            break

    # 9. 勤務時間・休日休暇・福利厚生などの諸条件
    conditions_dict: dict[str, str] = {}
    condition_keys = ["勤務時間", "休日・休暇", "待遇・福利厚生", "試用期間", "雇用形態", "選考プロセス"]
    for dt in soup.find_all("dt"):
        dt_text = dt.get_text(strip=True)
        for ck in condition_keys:
            if ck in dt_text:
                dd = dt.find_next_sibling("dd")
                if dd:
                    conditions_dict[ck] = dd.get_text("\n", strip=True)
                break

    # スキル・リモート・年収数値抽出 (normalizers 利用)
    full_text_blob = f"{title} {job_description} {skills_text} {salary_text} {location}"
    remote_type = detect_remote_type(location, full_text_blob)
    extracted_skills = extract_skills_from_text(full_text_blob)
    salary_min, salary_max = parse_salary_range(salary_text)

    return {
        "id": job_id,
        "title": title or "（タイトルなし）",
        "company": company or "（企業名非公開）",
        "url": job_url,
        "salary_text": salary_text,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "location": location,
        "remote_type": remote_type,
        "skills": extracted_skills,
        "company_url": company_url,
        "company_info": company_info,
        "description": job_description,
        "must_skills": must_skills.strip(),
        "desired_skills": desired_skills.strip(),
        "conditions": conditions_dict,
    }


def build_openwork_job_data(
    parsed: dict[str, Any],
    now: datetime,
    initial_score: str | None = None,
) -> JobData:
    """パース済み辞書から JobData モデルを構築する."""
    title = parsed.get("title") or "（タイトルなし）"
    company = parsed.get("company") or "（企業名非公開）"
    job_id = parsed.get("id") or "unknown"
    job_url = parsed.get("url") or ""

    # 本文 Markdown 構築
    body_lines = [f"# {title}", ""]

    if parsed.get("description"):
        body_lines.append("## 概要・仕事内容")
        body_lines.append(parsed["description"].strip())
        body_lines.append("")

    if parsed.get("must_skills"):
        body_lines.append("## 必須要件 (Must)")
        body_lines.append(parsed["must_skills"].strip())
        body_lines.append("")

    if parsed.get("desired_skills"):
        body_lines.append("## 歓迎要件 (Desired)")
        body_lines.append(parsed["desired_skills"].strip())
        body_lines.append("")

    # 勤務条件・福利厚生
    conditions_dict = parsed.get("conditions", {})
    if conditions_dict or parsed.get("salary_text") or parsed.get("location"):
        body_lines.append("## 勤務地・就業条件・福利厚生")
        if parsed.get("location"):
            body_lines.append(f"### 勤務地\n\n{parsed['location']}\n")
        if parsed.get("salary_text"):
            body_lines.append(f"### 給与・年収\n\n{parsed['salary_text']}\n")
        for k, v in conditions_dict.items():
            body_lines.append(f"### {k}\n\n{v}\n")

    # 企業情報
    comp_info = parsed.get("company_info", {})
    if comp_info:
        body_lines.append("## 採用企業情報")
        for k, v in comp_info.items():
            body_lines.append(f"### {k}\n\n{v}\n")

    extra_metadata: dict[str, Any] = {}
    if initial_score:
        extra_metadata["company_score"] = initial_score

    return JobData(
        id=job_id,
        source="openwork",
        company=company,
        title=title,
        url=job_url,
        fetched_at=now.isoformat(timespec="seconds"),
        salary_min=parsed.get("salary_min"),
        salary_max=parsed.get("salary_max"),
        salary_text=parsed.get("salary_text", ""),
        skills=parsed.get("skills", []),
        location=parsed.get("location", ""),
        remote_type=parsed.get("remote_type", "出社"),
        company_url=parsed.get("company_url", ""),
        raw_body="\n".join(body_lines).strip(),
        extra_metadata=extra_metadata,
    )


def format_openwork_job_markdown(
    parsed: dict[str, Any],
    now: datetime,
    initial_score: str | None = None,
) -> str:
    """構造化辞書をフロントマター付きMarkdownに整形する."""
    job = build_openwork_job_data(parsed, now, initial_score=initial_score)
    return job.to_markdown()


def fetch_and_save_openwork_job(
    url_or_id: str,
    session: str = "job-hunt",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    force: bool = False,
    dry_run: bool = False,
    summary: bool = False,
    initial_company: str | None = None,
    initial_title: str | None = None,
    initial_score: str | None = None,
    timeout: int = 120,
    no_notify: bool = False,
) -> tuple[Path | None, dict[str, Any]]:
    """OpenWork求人詳細を取得・保存する."""
    target = url_or_id.strip()
    job_url = ""
    job_id = None

    if target.startswith("http"):
        job_url = target
        job_id = extract_job_id_from_url(target)
    elif target.startswith("/"):
        job_url = f"https://www.openwork.jp{target}"
        job_id = extract_job_id_from_url(target)
    else:
        job_id = target
        resolved_url = resolve_job_url_by_id(target)
        if resolved_url:
            job_url = resolved_url
        else:
            raise ValueError(
                f"求人ID '{target}' の詳細URLを解決できませんでした。"
                f"完全なURL（例: https://www.openwork.jp/.../recruit?j=...）を指定するか、"
                f"先に search_jobs.py で検索を実行してください。"
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{job_id}.md"

    if out_path.exists() and not force:
        if summary:
            print(f"[スキップ] 既に保存されています: {to_relative_path(out_path)}", file=sys.stderr)
        return out_path, {"id": job_id, "url": job_url, "status": "skipped"}

    # 1. 静的HTTPリクエストを試行
    html_content, status_code = fetch_html_via_http(job_url)
    is_blocked = (
        not html_content
        or "画像認証" in html_content
        or "403 Forbidden" in html_content
        or status_code in (403, 429)
    )

    # 2. ブロックされた場合は Playwright 経由で取得
    if is_blocked:
        html_content = fetch_html_via_playwright(
            url=job_url,
            session=session,
            timeout=timeout,
            no_notify=no_notify,
        )

    if not html_content or "画像認証" in html_content:
        raise RuntimeError(f"求人詳細HTMLの取得に失敗しました: {job_url}")

    parsed = parse_job_detail_html(
        html_content,
        job_url=job_url,
        explicit_job_id=job_id,
        initial_company=initial_company,
        initial_title=initial_title,
    )

    now = datetime.now()
    job = build_openwork_job_data(parsed, now, initial_score=initial_score)

    if not dry_run:
        saved_path, _ = save_job_markdown(job, output_dir=output_dir, force=force)
        if summary:
            print(f"[保存完了] {to_relative_path(saved_path)}", file=sys.stderr)
        return saved_path, parsed

    return out_path, parsed


def _extract_openwork_job_id(target: str) -> str:
    if target.startswith("http"):
        jid = extract_job_id_from_url(target)
        if jid:
            return jid
        m = re.search(r"j=([a-zA-Z0-9_-]+)", target)
        if m:
            return m.group(1)
        return "openwork_job"
    return target


def _fetch_openwork_job(ctx: JobPipelineContext) -> JobData:
    target = ctx.target
    if target.startswith("http"):
        job_url = target
        extracted_id = extract_job_id_from_url(job_url)
        job_id = extracted_id or "job"
    else:
        job_id = target
        resolved = resolve_job_url_by_id(job_id)
        if not resolved:
            job_url = f"https://www.openwork.jp/company_job.php?j={job_id}"
        else:
            job_url = resolved

    html_content, status_code = fetch_html_via_http(job_url)
    is_blocked = (
        not html_content
        or "画像認証" in html_content
        or "403 Forbidden" in html_content
        or status_code in (403, 429)
    )
    if is_blocked:
        html_content = fetch_html_via_playwright(
            url=job_url,
            session=ctx.session,
            timeout=ctx.args.timeout,
            no_notify=ctx.args.no_notify,
        )

    if not html_content or "画像認証" in html_content:
        raise RuntimeError(f"求人詳細HTMLの取得に失敗しました: {job_url}")

    parsed = parse_job_detail_html(html_content, job_url=job_url, explicit_job_id=job_id)
    return build_openwork_job_data(parsed, ctx.now)


OPENWORK_JOB_CONFIG = JobCrawlerConfig(
    examples=[
        'uv run python scripts/openwork/fetch_job.py "https://www.openwork.jp/<m_id>/recruit?j=<jobId>"',
        "uv run python scripts/openwork/fetch_job.py <jobId> --summary",
    ],
    related=[
        "scripts/openwork/search_jobs.py: 前に使う（求人を検索で探す）",
    ],
    site_id="openwork",
    site_name="OpenWork",
    default_output_dir=DEFAULT_OUTPUT_DIR,
    extract_job_id_fn=_extract_openwork_job_id,
    normalize_url_fn=lambda t: t if t.startswith("http") else (resolve_job_url_by_id(t) or f"https://www.openwork.jp/company_job.php?j={t}"),
    custom_fetch_fn=_fetch_openwork_job,
    default_timeout=120,
)


def main() -> None:
    """単体求人詳細取得CLIエントリポイント."""
    sys.exit(run_job_pipeline(OPENWORK_JOB_CONFIG))


if __name__ == "__main__":
    main()
