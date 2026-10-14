"""Green 求人詳細取得・Markdown保存スクリプト.

Green（https://www.green-japan.com）の求人URLまたは求人IDから、
構造化求人データ（募集要項、仕事内容、必須・歓迎条件、勤務条件等）および企業情報を取得し、
リポジトリ共通仕様（.agents/rules/job-data-format.md）に準拠したフロントマター付きMarkdownとして
data/green/jobs/{job_id}.md に永続化します。

エントリポイントスクリプト規約（.agents/rules/scripts-entrypoint.md）準拠。
デフォルト実行時は生成・該当ファイルパスのみをstdoutに出力し、
人間向けサマリは --summary オプション指定時のみ表示します。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパス (scripts/green/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.auth_engine import ensure_site_authenticated
from scripts.common.browser_auth import (
    resolve_profile_path,
    run_code_script,
    run_playwright_cmd,
    update_profile_last_used,
)
from scripts.common.cli import (
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

GREEN_SCRIPTS_DIR = Path(__file__).resolve().parent
FETCH_JOB_SCRIPT_PATH = GREEN_SCRIPTS_DIR / "fetch_job.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "green" / "jobs"
BASE_URL = "https://www.green-japan.com"


def extract_job_id(target: str) -> str:
    """求人URLまたはID文字列から求人ID（数字文字列）を抽出する."""
    cleaned = target.strip()

    # /job/196698 または /company/7848/job/196698
    m_url = re.search(r"/job/(\d+)", cleaned)
    if m_url:
        return m_url.group(1)

    # クエリパラメータ ?id=196698 や ?job_id=196698
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

    raise ValueError(f"有効なGreen求人IDまたはURLを抽出できませんでした: {target}")


def build_job_url(target: str) -> str:
    """求人IDまたはURLから完全なGreen求人URLを構築する."""
    cleaned = target.strip()
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return cleaned
    job_id = extract_job_id(cleaned)
    return f"{BASE_URL}/job/{job_id}"


def run_fetch_job(
    target_url: str,
    session: str = "job-hunt",
    timeout: int = 45,
) -> dict[str, Any]:
    """Playwrightスクリプトを実行して求人詳細および企業情報を取得する."""
    if not FETCH_JOB_SCRIPT_PATH.exists():
        raise RuntimeError(f"Playwrightスクリプトが見つかりません: {FETCH_JOB_SCRIPT_PATH}")

    profile_path = resolve_profile_path(session)
    # ブラウザセッションオープン
    run_playwright_cmd([f"-s={session}", "open", target_url, f"--profile={profile_path}"])

    template_code = FETCH_JOB_SCRIPT_PATH.read_text(encoding="utf-8")
    run_code = template_code.replace("__JOB_URL__", json.dumps(target_url))

    tmp_script = GREEN_SCRIPTS_DIR / f".tmp_fetch_job_{session}.mjs"
    tmp_script.write_text(run_code, encoding="utf-8")

    try:
        result = run_code_script(session, tmp_script, timeout=timeout)
        if not result:
            raise RuntimeError("Playwrightスクリプトの実行に失敗しました（空のレスポンス）")
        if not result.get("success"):
            errs = result.get("errors") or ["不明なエラー"]
            raise RuntimeError(f"スクリプト実行エラー: {', '.join(errs)}")
        update_profile_last_used(session)
        return result
    finally:
        if tmp_script.exists():
            try:
                tmp_script.unlink()
            except Exception:
                pass


def parse_qualification(qualification_text: str) -> tuple[str, str]:
    """応募要件テキストから必須条件（must）と歓迎条件（desired）を分離する."""
    if not qualification_text:
        return "", ""

    must_lines: list[str] = []
    desired_lines: list[str] = []
    current_section = "must"

    for line in qualification_text.splitlines():
        trimmed = line.strip()
        if "歓迎" in trimmed:
            current_section = "desired"
            continue
        elif "必須" in trimmed or "必要" in trimmed:
            current_section = "must"
            continue

        if current_section == "must":
            must_lines.append(line)
        else:
            desired_lines.append(line)

    must_str = "\n".join(must_lines).strip()
    desired_str = "\n".join(desired_lines).strip()

    # 判定がうまく分かれなかった場合は全体を must に格納
    if not must_str and not desired_str:
        return qualification_text.strip(), ""
    if not must_str and desired_str:
        return desired_str, ""

    return must_str, desired_str


def build_job_data(raw_data: dict[str, Any], job_id: str, job_url: str) -> JobData:
    """抽出した辞書データを共通 JobData モデルに変換する."""
    offer = raw_data.get("jobOffer") or {}
    client = raw_data.get("client") or {}

    company_name = (
        client.get("fullName")
        or client.get("name")
        or offer.get("clientBusiness", {}).get("name")
        or "企業名不明"
    )

    job_title = offer.get("title") or offer.get("name") or "求人タイトル不明"
    role_name = offer.get("name") or ""

    # 年収
    min_sal = offer.get("minSalary")
    max_sal = offer.get("maxSalary")
    salary_min = int(min_sal) if min_sal is not None and str(min_sal).isdigit() else None
    salary_max = int(max_sal) if max_sal is not None and str(max_sal).isdigit() else None

    salary_detail = offer.get("salaryDetail", "").strip()
    if salary_min is not None and salary_max is not None:
        salary_text = f"{salary_min}万円〜{salary_max}万円"
    elif salary_min is not None:
        salary_text = f"{salary_min}万円〜"
    else:
        salary_text = salary_detail

    # タグとスキル
    tags: list[str] = []
    skills: list[str] = []

    # offer.tags
    for tag_obj in offer.get("tags") or []:
        if isinstance(tag_obj, dict) and tag_obj.get("name"):
            tname = tag_obj["name"].strip()
            tags.append(tname)
            skills.append(tname)
        elif isinstance(tag_obj, str):
            tags.append(tag_obj.strip())
            skills.append(tag_obj.strip())

    # client.companyFeatures
    for feat in client.get("companyFeatures") or []:
        if isinstance(feat, dict) and feat.get("name"):
            tags.append(feat["name"].strip())

    # 勤務地
    location_parts: list[str] = []
    for area in offer.get("areas") or []:
        if isinstance(area, dict) and area.get("name"):
            location_parts.append(area["name"])
    if offer.get("address"):
        location_parts.append(offer["address"])
    location = " / ".join(dict.fromkeys(location_parts)) if location_parts else offer.get("access", "")

    # リモート判定
    full_text_for_remote = " ".join([
        job_title,
        offer.get("abstract", ""),
        offer.get("detail", ""),
        offer.get("welfare", ""),
        " ".join(tags),
    ])
    remote_type = detect_remote_type(location, full_text_for_remote)

    # 職種ロール
    job_roles: list[str] = []
    if role_name:
        job_roles.append(role_name)
    for cat in offer.get("jobTypeCategories") or []:
        if isinstance(cat, dict):
            for jt in cat.get("jobTypes") or []:
                if isinstance(jt, dict) and jt.get("name"):
                    job_roles.append(jt["name"])
    job_roles = list(dict.fromkeys(job_roles))

    # 本文セクション
    # 職務内容 / 概要
    desc_parts: list[str] = []
    if offer.get("abstract"):
        desc_parts.append(f"### 事業概要・ビジョン\n{offer['abstract']}")
    if offer.get("detail"):
        desc_parts.append(f"### 業務内容\n{offer['detail']}")
    if offer.get("background"):
        desc_parts.append(f"### 募集背景\n{offer['background']}")
    description = "\n\n".join(desc_parts)

    # 応募要件 (must / desired)
    qual = offer.get("qualification", "")
    must_skills, desired_skills = parse_qualification(qual)

    # 開発環境
    env_parts: list[str] = []
    for fc in offer.get("freeContents") or []:
        if isinstance(fc, dict):
            subj = fc.get("subject", "自由項目")
            body = fc.get("body", "")
            if body:
                env_parts.append(f"#### {subj}\n{body}")
    development_environment = "\n\n".join(env_parts)

    # 得られるやりがい・成長
    rewarding = offer.get("acquisition", "")

    # 勤務条件・福利厚生・休日
    cond_parts: list[str] = []
    if offer.get("employmentStatusName"):
        cond_parts.append(f"- **雇用形態**: {offer['employmentStatusName']}")
    if salary_detail:
        cond_parts.append(f"- **給与詳細**: {salary_detail}")
    if offer.get("welfare"):
        cond_parts.append(f"- **勤務条件・福利厚生**:\n{offer['welfare']}")
    if offer.get("holiday"):
        cond_parts.append(f"- **休日・休暇**:\n{offer['holiday']}")
    if offer.get("access"):
        cond_parts.append(f"- **アクセス・交通**: {offer['access']}")
    if offer.get("process"):
        cond_parts.append(f"- **選考プロセス**:\n{offer['process']}")
    conditions = "\n".join(cond_parts)

    # 拡張メタデータ
    extra: dict[str, Any] = {}
    if client.get("id"):
        extra["green_company_id"] = client["id"]
    if client.get("employees"):
        extra["company_employees"] = client["employees"]
    if client.get("capital"):
        extra["company_capital"] = client["capital"]
    if client.get("businessDetail"):
        extra["company_business"] = client["businessDetail"]
    if client.get("title"):
        extra["company_catchphrase"] = client["title"]
    if client.get("presidentName"):
        extra["company_president"] = client["presidentName"]
    if offer.get("employmentStatusName"):
        extra["employment_type"] = offer["employmentStatusName"]
    if offer.get("updatedAtTimestamp"):
        dt = datetime.fromtimestamp(offer["updatedAtTimestamp"])
        extra["updated_at"] = dt.strftime("%Y-%m-%d")

    # 本文からスキル自動抽出を追加マージ
    full_text_for_skills = f"{job_title}\n{description}\n{qual}\n{development_environment}"
    auto_skills = extract_skills_from_text(full_text_for_skills)
    merged_skills = list(dict.fromkeys(skills + auto_skills))

    return JobData(
        id=str(job_id),
        source="green",
        company=company_name,
        title=job_title,
        url=job_url,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_text=salary_text,
        skills=merged_skills,
        job_roles=job_roles,
        location=location,
        remote_type=remote_type,
        tags=list(dict.fromkeys(tags)),
        company_url=f"{BASE_URL}/company/{client['id']}" if client.get("id") else "",
        description=description,
        must_skills=must_skills,
        desired_skills=desired_skills,
        development_environment=development_environment,
        rewarding=rewarding,
        conditions=conditions,
        extra_metadata=extra,
    )


def print_summary(job: JobData) -> None:
    """求人詳細のサマリをコンソールに表示する."""
    print("\n========================================================")
    print(f" Green 求人詳細: {job.company} / {job.title}")
    print(f" URL:        {job.url}")
    print(f" 想定年収:   {job.salary_text or '未記載'}")
    print(f" 勤務地:     {job.location or '未記載'} (リモート: {job.remote_type})")
    if job.job_roles:
        print(f" 職種:       {', '.join(job.job_roles)}")
    if job.skills:
        print(f" スキル:     {', '.join(job.skills[:10])}")
    print("========================================================\n")


def fetch_job(
    target: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    session: str = "job-hunt",
    force: bool = False,
    timeout: int = 45,
) -> tuple[Path, bool, JobData | None]:
    """求人をWebから取得してMarkdownに保存し、ファイルパスと更新フラグを返す."""
    job_id = extract_job_id(target)
    target_url = build_job_url(target)
    output_path = output_dir / f"{job_id}.md"

    if output_path.exists() and not force:
        sys.stderr.write(f"[Green] 既存の求人ファイルが見つかりました: {to_relative_path(output_path)}\n")
        return output_path, False, None

    sys.stderr.write(f"[Green] 求人詳細を取得中 (ID: {job_id}, URL: {target_url})...\n")
    raw_data = run_fetch_job(target_url, session=session, timeout=timeout)

    job_data = build_job_data(raw_data, job_id, target_url)
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_path, is_saved = save_job_markdown(job_data, output_dir, force=force)
    return saved_path, is_saved, job_data


def main() -> None:
    parser = create_base_parser(
        description="Green 求人詳細取得・Markdown保存スクリプト",
    )
    parser.add_argument(
        "target",
        type=str,
        help="取得対象のGreen求人IDまたは求人URL (例: 196698, https://www.green-japan.com/job/196698)",
    )
    parser.add_argument(
        "--session",
        type=str,
        default="job-hunt",
        help="ブラウザプロファイルセッション名 (デフォルト: job-hunt)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="保存先ディレクトリ (デフォルト: data/green/jobs)",
    )

    args = parser.parse_args()

    # 認証確認
    sys.stderr.write(f"[Green] セッション '{args.session}' の認証状態を確認中...\n")
    if not ensure_site_authenticated("green", session=args.session):
        sys.stderr.write("[Green] 認証が完了しなかったため、処理を中断します。\n")
        sys.exit(2)

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        saved_path, is_modified, job_data = fetch_job(
            target=args.target,
            output_dir=args.output_dir,
            session=args.session,
            force=args.force,
        )
        ctx.add_result_path(saved_path)

        def print_summary_cb() -> None:
            if job_data:
                print_summary(job_data)
            print(f"=== Green 求人詳細取得 ===")
            print(f"対象: {args.target}")
            print(f"結果: {'更新・作成' if is_modified else '既存スキップ'}")
            print(f"保存パス: {to_relative_path(saved_path)}")

        json_data = {
            "source": "green",
            "target": args.target,
            "path": to_relative_path(saved_path),
            "modified": is_modified,
        } if args.json else None

        ctx.flush_outputs(summary_fn=print_summary_cb, json_data=json_data)


if __name__ == "__main__":
    main()
