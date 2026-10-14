"""Forkwell求人詳細取得・Markdown保存モジュール.

Forkwell Jobs（https://jobs.forkwell.com）の求人URLまたは求人IDから、
公式API（/api/v1/jobs/{id}）またはHTML/LD+JSONを活用して求人詳細を取得し、
プロジェクト共通仕様（.agents/rules/job-data-format.md）に準拠した
フロントマター付きMarkdownとして永続化します。
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

# プロジェクトルートパス (scripts/forkwell/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.browser_auth import run_code_snippet
from scripts.common.cli import (
    EntrypointContext,
    create_base_parser,
    entrypoint_guard,
    to_relative_path,
)
from scripts.common.normalizers import (
    detect_remote_type,
    extract_skills_from_text,
    format_salary_display,
    format_salary_text,
    normalize_url,
    parse_salary_range,
)
from scripts.common.storage import JobData, save_job_markdown

SITE_NAME = "Forkwell"
SITE_SOURCE = "forkwell"
SITE_BASE_URL = "https://jobs.forkwell.com"
API_BASE_URL = "https://jobs.forkwell.com/api/v1/jobs"

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / SITE_SOURCE / "jobs"
DEFAULT_SEARCHES_DIR = PROJECT_ROOT / "data" / SITE_SOURCE / "searches"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
HTTP_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


def extract_job_id(target: str) -> str:
    """求人URLまたはID文字列から求人ID（数字文字列）を抽出する."""
    cleaned = target.strip()

    # /jobs/35714 のようなURLパス
    m_url = re.search(r"/jobs/(\d+)", cleaned)
    if m_url:
        return m_url.group(1)

    # クエリパラメータ ?id=35714 や ?j=35714
    m_param = re.search(r"[?&](?:id|job_id|j)=(\d+)", cleaned)
    if m_param:
        return m_param.group(1)

    # 数字のみで構成されたID
    if cleaned.isdigit():
        return cleaned

    # 末尾の数字列
    m_digits = re.search(r"(\d+)", cleaned)
    if m_digits:
        return m_digits.group(1)

    raise ValueError(f"有効なForkwell求人IDまたはURLを抽出できませんでした: {target}")


def resolve_job_url_from_history(job_id: str) -> str | None:
    """過去の検索結果JSONを探索し、求人IDに対応する詳細URLを取得する."""
    if not DEFAULT_SEARCHES_DIR.exists():
        return None

    for json_file in sorted(DEFAULT_SEARCHES_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            for job in data.get("jobs", []):
                if str(job.get("id")) == str(job_id) and job.get("url"):
                    return job["url"]
        except Exception:
            continue
    return None


def fetch_job_detail_api(job_id: str, timeout: int = 15) -> dict[str, Any] | None:
    """Forkwell公式API（/api/v1/jobs/{job_id}）から求人詳細JSONを取得する."""
    api_url = f"{API_BASE_URL}/{job_id}"
    req = urllib.request.Request(api_url, headers=HTTP_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                raw_data = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw_data)
    except urllib.error.HTTPError as e:
        print(f"[DEBUG] API GET failed ({e.code}): {api_url}", file=sys.stderr)
    except Exception as e:
        print(f"[DEBUG] API GET error: {e}", file=sys.stderr)
    return None


def fetch_job_detail_html(
    url: str,
    session: str = "job-hunt",
    timeout: int = 20,
) -> str | None:
    """求人詳細ページのHTMLを取得する (HTTP GET優先、Playwrightフォールバック)."""
    # 1. urllib による HTTP GET
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"[DEBUG] HTML GET failed ({e.code}): {url}", file=sys.stderr)
    except Exception as e:
        print(f"[DEBUG] HTML GET error: {e}", file=sys.stderr)

    # 2. Playwright によるフォールバック
    try:
        js_code = f"""
        await page.goto({json.dumps(url)}, {{ waitUntil: 'domcontentloaded', timeout: {timeout * 1000} }});
        return await page.content();
        """
        html_content = run_code_snippet(session=session, js_code=js_code, timeout=timeout + 10)
        return html_content or None
    except Exception as e:
        print(f"[DEBUG] Playwright fallback failed: {e}", file=sys.stderr)
        return None


def parse_api_response_to_job_data(
    data: dict[str, Any],
    explicit_url: str | None = None,
) -> JobData:
    """APIレスポンスJSONから JobData モデルを構築する."""
    job_id = str(data.get("id"))
    title = data.get("title", "") or "（タイトルなし）"

    # 企業情報
    company_obj = data.get("company") or {}
    company_name = company_obj.get("name") or data.get("company_name") or "（企業名非公開）"
    company_slug = company_obj.get("user_name") or ""
    company_url = f"{SITE_BASE_URL}/{company_slug}" if company_slug else ""

    # 求人URL
    url = explicit_url
    if not url:
        if company_slug:
            url = f"{SITE_BASE_URL}/{company_slug}/jobs/{job_id}"
        else:
            url = f"{SITE_BASE_URL}/jobs/{job_id}"

    # 給与の計算（万円 -> JPY円単位整数）
    base_salaries = data.get("base_salaries") or []
    primary_base_salary = data.get("primary_base_salary") or {}
    min_val: int | float | None = None
    max_val: int | float | None = None

    if isinstance(base_salaries, list) and base_salaries:
        first_sal = base_salaries[0]
        if isinstance(first_sal, dict):
            min_val = first_sal.get("min_value")
            max_val = first_sal.get("max_value")

    if min_val is None and max_val is None and isinstance(primary_base_salary, dict):
        min_val = primary_base_salary.get("min_value")
        max_val = primary_base_salary.get("max_value")

    salary_min = int(min_val * 10000) if min_val is not None else None
    salary_max = int(max_val * 10000) if max_val is not None else None
    salary_text = format_salary_text(salary_min, salary_max)

    # 勤務地
    location = data.get("prefecture_name") or ""

    # 職種
    job_roles: list[str] = []
    profession = data.get("profession")
    if isinstance(profession, dict) and profession.get("name"):
        job_roles.append(profession["name"])

    # 特徴タグ
    job_tags_list = data.get("job_tags") or []
    tags = [t.get("name") for t in job_tags_list if isinstance(t, dict) and t.get("name")]

    # selections からの特徴タグも追加
    selections_list = data.get("selections") or []
    if isinstance(selections_list, list):
        for s in selections_list:
            if isinstance(s, dict) and s.get("name"):
                s_name = s["name"]
                if s_name not in tags:
                    tags.append(s_name)

    # 開発環境・就業環境カテゴリの収集
    job_env_cats = data.get("job_environment_categories") or []
    env_culture_lines: list[str] = []
    statutory_lines: list[str] = []

    if isinstance(job_env_cats, list):
        for cat in job_env_cats:
            if not isinstance(cat, dict):
                continue
            cat_name = cat.get("name") or ""
            envs = cat.get("environments") or []
            env_items = [e.get("name") for e in envs if isinstance(e, dict) and e.get("name")]
            if not env_items:
                continue

            if "職業安定法" in cat_name:
                for it in env_items:
                    statutory_lines.append(f"- {it}")
            else:
                env_culture_lines.append(f"#### {cat_name}")
                for it in env_items:
                    env_culture_lines.append(f"- {it}")
                env_culture_lines.append("")

    # リモート判定
    tag_str = " ".join(tags)
    insurance_text = data.get("insurance") or ""
    working_cond = data.get("working_condition") or ""
    env_text = " ".join(env_culture_lines)
    full_cond_text = f"{title} {tag_str} {insurance_text} {working_cond} {env_text}"
    remote_type = detect_remote_type(location, full_cond_text)
    if any("フルリモート" in t for t in tags) or "フルリモート" in env_text or "フルリモート" in insurance_text:
        remote_type = "フルリモート"
    elif any("一部リモート" in t for t in tags) and remote_type == "出社":
        remote_type = "ハイブリッド"

    # スキルタグ収集
    skills: list[str] = []
    tech = data.get("technology") or {}

    def collect_skilltag_names(skill_dict: dict[str, Any]) -> None:
        for cat_list in skill_dict.values():
            if isinstance(cat_list, list):
                for item in cat_list:
                    if isinstance(item, dict):
                        # real_name を優先、なければ name
                        name = item.get("real_name") or item.get("name")
                        if name and name not in skills:
                            skills.append(name)

    if isinstance(tech.get("practical_skilltags"), dict):
        collect_skilltag_names(tech["practical_skilltags"])
    if isinstance(tech.get("not_practical_skilltags"), dict):
        collect_skilltag_names(tech["not_practical_skilltags"])

    # skilltags も補完
    for st in data.get("skilltags") or []:
        if isinstance(st, dict):
            st_name = st.get("translated_name") or st.get("name")
            if st_name and st_name not in skills:
                skills.append(st_name)

    # 本文テキスト等からのスキル補完
    service_text = data.get("service_and_product") or ""
    must_skills_raw = data.get("required_experience_and_skills") or ""
    desired_skills_raw = data.get("preferred_experience_and_skills") or ""
    full_blob = f"{title} {service_text} {must_skills_raw} {desired_skills_raw}"
    for ext_s in extract_skills_from_text(full_blob):
        if ext_s not in skills:
            skills.append(ext_s)

    # 開発環境セクションの作成
    dev_env_lines: list[str] = []
    if isinstance(tech.get("practical_skilltags"), dict) and tech["practical_skilltags"]:
        dev_env_lines.append("### 実務開発スキル")
        for cat, items in tech["practical_skilltags"].items():
            names = [it.get("real_name") or it.get("name") for it in items if isinstance(it, dict)]
            names = [n for n in names if n]
            if names:
                dev_env_lines.append(f"- **{cat}**: {', '.join(names)}")
        dev_env_lines.append("")

    if isinstance(tech.get("not_practical_skilltags"), dict) and tech["not_practical_skilltags"]:
        dev_env_lines.append("### 利用・歓迎開発スキル")
        for cat, items in tech["not_practical_skilltags"].items():
            names = [it.get("real_name") or it.get("name") for it in items if isinstance(it, dict)]
            names = [n for n in names if n]
            if names:
                dev_env_lines.append(f"- **{cat}**: {', '.join(names)}")
        dev_env_lines.append("")

    if env_culture_lines:
        dev_env_lines.append("### 開発組織・技術文化")
        dev_env_lines.extend(env_culture_lines)

    development_environment = "\n".join(dev_env_lines).strip()

    # 就業条件・福利厚生セクションの作成
    cond_lines: list[str] = []
    emp_types = data.get("employment_types") or []
    if isinstance(emp_types, list) and emp_types:
        cond_lines.append(f"### 雇用形態\n\n{', '.join(emp_types)}\n")
    if working_cond and isinstance(working_cond, str):
        cond_lines.append(f"### 就業時間・休日\n\n{working_cond.strip()}\n")
    if insurance_text and isinstance(insurance_text, str):
        cond_lines.append(f"### 給与・福利厚生・就業場所\n\n{insurance_text.strip()}\n")

    scope_office = data.get("office_change_scope")
    if scope_office and isinstance(scope_office, str):
        cond_lines.append(f"### 就業場所の変更の範囲\n\n{scope_office.strip()}\n")

    scope_prof = data.get("profession_change_scope")
    if scope_prof and isinstance(scope_prof, str):
        cond_lines.append(f"### 従事すべき業務の変更の範囲\n\n{scope_prof.strip()}\n")

    if statutory_lines:
        cond_lines.append("### 労働条件明示事項\n")
        cond_lines.extend(statutory_lines)
        cond_lines.append("")

    conditions = "\n".join(cond_lines).strip()

    return JobData(
        id=job_id,
        source=SITE_SOURCE,
        company=company_name,
        title=title,
        url=url,
        fetched_at=datetime.now().isoformat(timespec="seconds"),
        salary_min=salary_min,
        salary_max=salary_max,
        salary_text=salary_text,
        skills=skills,
        job_roles=job_roles,
        location=location,
        remote_type=remote_type,
        tags=tags,
        company_url=company_url,
        description=service_text.strip(),
        must_skills=must_skills_raw.strip(),
        desired_skills=desired_skills_raw.strip(),
        development_environment=development_environment,
        rewarding=(data.get("message_for_candidates") or "").strip(),
        personality=(data.get("desired_personality") or "").strip(),
        conditions=conditions,
    )


def parse_job_posting_ld_json(
    html_content: str,
    job_id: str,
    url: str,
) -> JobData | None:
    """HTML内の ld+json (JobPosting) スキーマから JobData をパースする."""
    soup = BeautifulSoup(html_content, "html.parser")
    ld_scripts = soup.find_all("script", type="application/ld+json")
    job_posting: dict[str, Any] | None = None

    for s in ld_scripts:
        try:
            val = json.loads(s.string or "")
            if isinstance(val, dict) and val.get("@type") == "JobPosting":
                job_posting = val
                break
        except Exception:
            continue

    if not job_posting:
        return None

    title = job_posting.get("title") or ""
    org = job_posting.get("hiringOrganization") or {}
    company = org.get("name") or "（企業名非公開）"
    company_url = org.get("sameAs") or ""

    # 給与
    base_sal = job_posting.get("baseSalary") or {}
    sal_val = base_sal.get("value") or {}
    sal_min = sal_val.get("minValue")
    sal_max = sal_val.get("maxValue")
    salary_min = int(sal_min) if sal_min is not None else None
    salary_max = int(sal_max) if sal_max is not None else None
    salary_text = format_salary_text(salary_min, salary_max)

    # 勤務地
    loc_place = job_posting.get("jobLocation") or {}
    loc_addr = loc_place.get("address") or {}
    location = loc_addr.get("addressRegion") or ""

    # リモート判定
    job_loc_type = job_posting.get("jobLocationType") or ""
    desc_raw = job_posting.get("description") or ""
    # HTMLタグを除去したテキスト
    desc_soup = BeautifulSoup(desc_raw, "html.parser")
    desc_text = desc_soup.get_text("\n", strip=True)

    remote_type = detect_remote_type(location, f"{title} {desc_text}")
    if job_loc_type == "TELECOMMUTE":
        remote_type = "フルリモート"

    skills = extract_skills_from_text(f"{title} {desc_text}")

    return JobData(
        id=job_id,
        source=SITE_SOURCE,
        company=company,
        title=title,
        url=url,
        fetched_at=datetime.now().isoformat(timespec="seconds"),
        salary_min=salary_min,
        salary_max=salary_max,
        salary_text=salary_text,
        skills=skills,
        location=location,
        remote_type=remote_type,
        company_url=company_url,
        description=desc_text,
    )


def fetch_and_save_forkwell_job(
    target: str | None = None,
    job_id: str | None = None,
    job_url: str | None = None,
    session: str = "job-hunt",
    output_dir: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
    summary: bool = False,
    timeout: int = 20,
) -> tuple[Path, bool]:
    """Forkwellの求人詳細を取得し、Markdownファイルとして保存する.

    Args:
        target: 求人IDまたは求人URL（位置指定）
        job_id: 明示的な求人ID
        job_url: 明示的な求人URL
        session: Playwrightフォールバック時のプロファイル名
        output_dir: 保存先ディレクトリ（デフォルト: data/forkwell/jobs）
        force: 既存ファイルが存在しても強制再取得・上書き保存するか
        dry_run: ファイル保存を実行せず取得のみ行うか
        summary: 進捗メッセージを標準エラー出力に表示するか
        timeout: リクエスト待機タイムアウト秒数

    Returns:
        tuple[Path, bool]: (保存ファイルパス, 新規保存/更新されたか)
    """
    target_dir = output_dir or DEFAULT_OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. target / job_id / job_url の解決
    resolved_id: str | None = job_id
    resolved_url: str | None = job_url

    if target:
        cleaned = target.strip()
        resolved_id = extract_job_id(cleaned)
        if cleaned.startswith("http"):
            resolved_url = cleaned
        elif cleaned.startswith("/"):
            resolved_url = normalize_url(cleaned, base_url=SITE_BASE_URL)

    if not resolved_id:
        if resolved_url:
            resolved_id = extract_job_id(resolved_url)
        else:
            raise ValueError("求人IDまたは求人URLを指定してください。")

    out_path = target_dir / f"{resolved_id}.md"

    # 2. キャッシュチェック
    if out_path.exists() and not force:
        if summary:
            print(f"[スキップ] 既に保存されています: {to_relative_path(out_path)}", file=sys.stderr)
        return out_path, False

    # 3. 過去の検索履歴からのURL補完（未指定時）
    if not resolved_url:
        resolved_url = resolve_job_url_from_history(resolved_id)

    # 4. API による求人詳細取得（主系統）
    job_data: JobData | None = None
    api_response = fetch_job_detail_api(resolved_id, timeout=timeout)
    if api_response and isinstance(api_response, dict) and api_response.get("id"):
        job_data = parse_api_response_to_job_data(api_response, explicit_url=resolved_url)

    # 5. HTML/LD+JSON によるフォールバック（副系統）
    if not job_data:
        html_url = resolved_url or f"{SITE_BASE_URL}/jobs/{resolved_id}"
        html_content = fetch_job_detail_html(html_url, session=session, timeout=timeout)
        if html_content:
            job_data = parse_job_posting_ld_json(html_content, job_id=resolved_id, url=html_url)

    if not job_data:
        raise RuntimeError(f"求人詳細の取得に失敗しました (ID: {resolved_id}, URL: {resolved_url})")

    # 6. 保存処理
    if dry_run:
        if summary:
            print(f"[dry-run] 保存先: {to_relative_path(out_path)}", file=sys.stderr)
        return out_path, True

    saved_path, modified = save_job_markdown(job_data, output_dir=target_dir, force=force)
    if summary:
        print(f"[保存完了] {to_relative_path(saved_path)}", file=sys.stderr)
    return saved_path, modified


def main() -> None:
    """単体求人詳細取得CLIエントリポイント (scripts-entrypoint.md 準拠)."""
    parser = create_base_parser(description="Forkwell 求人詳細取得・Markdown保存スクリプト")
    parser.add_argument("target", help="求人ID（例: 35714）または求人詳細URL")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="保存先ディレクトリ (デフォルト: data/forkwell/jobs)",
    )
    parser.add_argument("--dry-run", action="store_true", help="ファイル保存を行わない")
    parser.add_argument(
        "--session",
        default="job-hunt",
        help="Playwrightセッション名 (デフォルト: job-hunt)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="リクエストタイムアウト秒数 (デフォルト: 20)",
    )

    args = parser.parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        saved_path, is_modified = fetch_and_save_forkwell_job(
            target=args.target,
            session=args.session,
            output_dir=args.output_dir,
            force=args.force,
            dry_run=args.dry_run,
            summary=args.summary,
            timeout=args.timeout,
        )

        ctx.add_result_path(saved_path)

        def print_summary() -> None:
            print(f"\n=== {SITE_NAME} 求人詳細取得 ===")
            print(f"対象: {args.target}")
            print(f"結果: {'更新・作成' if is_modified else '既存スキップ'}")
            print(f"保存パス: {to_relative_path(saved_path)}")

        json_data = {
            "source": SITE_SOURCE,
            "target": args.target,
            "path": str(saved_path),
            "modified": is_modified,
        } if args.json else None

        ctx.flush_outputs(summary_fn=print_summary, json_data=json_data)


if __name__ == "__main__":
    main()
