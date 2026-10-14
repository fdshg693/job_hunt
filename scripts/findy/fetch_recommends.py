"""Findyおすすめ求人（sort=recommend）取得・フィルタ・保存スクリプト.

リポジトリ共通プロファイル（デフォルト: job-hunt）を使用し、
Findyのログイン後のおすすめ求人（https://findy-code.io/recommends?sort=recommend）を取得して、
希望条件での絞り込み、ファイル保存、詳細サマリ出力を行います。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# プロジェクトルートパスを sys.path に追加して直接実行に対応
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.auth_engine import ensure_site_authenticated
from scripts.common.browser_auth import (
    resolve_profile_path,
    run_code_script,
    run_playwright_cmd,
)
from scripts.common.cli import EntrypointContext, create_search_parser, to_relative_path
from scripts.common.normalizers import (
    detect_remote_type,
    format_salary_display,
    format_salary_text,
    parse_salary_arg,
)
from scripts.findy.fetch_job import (
    DEFAULT_OUTPUT_DIR as DEFAULT_JOBS_DIR,
    fetch_and_save_job,
)

FINDY_SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "findy" / "recommends"


@dataclass
class RecommendJobItem:
    """おすすめ求人アイテム."""

    id: str
    hash: str
    company_id: int | None
    company: str
    title: str
    url: str
    salary_min: int | None = None
    salary_max: int | None = None
    salary_text: str | None = None
    skills: list[str] = field(default_factory=list)
    job_roles: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    remote_type: str = "不明"
    work_hours: str = ""
    description: str = ""
    created_at: str = ""
    published_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def filter_jobs(
    jobs: list[RecommendJobItem],
    min_salary: int | None = None,
    max_salary: int | None = None,
    company: str | None = None,
    title: str | None = None,
    skills: list[str] | None = None,
    remote_type: str | None = None,
    role: str | None = None,
    query_words: list[str] | None = None,
) -> list[RecommendJobItem]:
    """取得したおすすめ求人を条件で絞り込む."""
    matched: list[RecommendJobItem] = []

    for job in jobs:
        if min_salary is not None:
            effective_max = job.salary_max if job.salary_max is not None else job.salary_min
            if effective_max is not None and effective_max < min_salary:
                continue

        if max_salary is not None:
            effective_min = job.salary_min if job.salary_min is not None else job.salary_max
            if effective_min is not None and effective_min > max_salary:
                continue

        if company and company.lower() not in job.company.lower():
            continue

        if title and title.lower() not in job.title.lower():
            continue

        if role:
            role_lower = role.lower()
            if not any(role_lower in r.lower() for r in job.job_roles):
                continue

        if skills:
            job_skills_lower = [s.lower() for s in job.skills]
            has_all_skills = True
            for req_skill in skills:
                req_lower = req_skill.lower()
                if not any(req_lower in js for js in job_skills_lower):
                    has_all_skills = False
                    break
            if not has_all_skills:
                continue

        if remote_type:
            if remote_type.lower() not in job.remote_type.lower():
                continue

        if query_words:
            all_text = f"{job.company} {job.title} {' '.join(job.skills)} {' '.join(job.tags)} {job.description}".lower()
            if not all(w.lower() in all_text for w in query_words):
                continue

        matched.append(job)

    return matched


def generate_markdown(
    jobs: list[RecommendJobItem],
    total_count: int,
    now: datetime,
) -> str:
    """おすすめ求人一覧のMarkdownドキュメントを生成する."""
    lines = [
        "---",
        "source: findy",
        "type: recommends",
        f"fetched_at: '{now.isoformat(timespec='seconds')}'",
        f"total_count: {total_count}",
        f"item_count: {len(jobs)}",
        "---",
        "",
        f"# Findy おすすめ求人一覧 ({now.strftime('%Y-%m-%d %H:%M')})",
        "",
        f"- **取得日時**: {now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **おすすめ全件数**: {total_count} 件",
        f"- **取得件数**: {len(jobs)} 件",
        "",
        "## おすすめ求人テーブル",
        "",
        "| # | 企業名 | 求人タイトル | 想定年収 | リモート | スキル | URL |",
        "|---|---|---|---|---|---|---|",
    ]

    for idx, job in enumerate(jobs, start=1):
        comp = job.company.replace("|", "\\|")
        title = job.title.replace("|", "\\|")
        sal = format_salary_display(job.salary_min, job.salary_max, job.salary_text)
        rem = job.remote_type
        sk = ", ".join(job.skills[:4]) if job.skills else "-"
        link = f"[詳細]({job.url})"
        lines.append(f"| {idx} | {comp} | {title} | {sal} | {rem} | {sk} | {link} |")

    lines.append("")
    lines.append("## 詳細リスト")
    lines.append("")

    for idx, job in enumerate(jobs, start=1):
        lines.append(f"### {idx}. {job.company} - {job.title}")
        lines.append(f"- **URL**: {job.url}")
        sal_disp = format_salary_display(job.salary_min, job.salary_max, job.salary_text)
        lines.append(f"- **想定年収**: {sal_disp}")
        lines.append(f"- **リモート**: {job.remote_type}")
        if job.job_roles:
            lines.append(f"- **職種**: {', '.join(job.job_roles)}")
        if job.skills:
            lines.append(f"- **スキル**: {', '.join(job.skills)}")
        if job.tags:
            lines.append(f"- **タグ**: {', '.join(job.tags[:8])}")
        if job.work_hours:
            lines.append(f"- **勤務時間**: {job.work_hours.splitlines()[0]}")
        if job.description:
            desc_snippet = job.description[:200].replace("\n", " ").strip()
            lines.append(f"- **概要**: {desc_snippet}...")
        lines.append("")

    return "\n".join(lines)


def save_recommends_result(
    jobs: list[RecommendJobItem],
    total_count: int,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    now: datetime | None = None,
) -> tuple[Path, Path]:
    """おすすめ求人データをMarkdownとJSONでファイル保存する."""
    if now is None:
        now = datetime.now()

    output_dir.mkdir(parents=True, exist_ok=True)
    file_stem = now.strftime("%Y-%m-%d-%H")
    md_path = output_dir / f"{file_stem}.md"
    json_path = output_dir / f"{file_stem}.json"

    md_content = generate_markdown(jobs, total_count, now)
    md_path.write_text(md_content, encoding="utf-8")

    json_payload = {
        "source": "findy",
        "type": "recommends",
        "fetched_at": now.isoformat(timespec="seconds"),
        "total_count": total_count,
        "item_count": len(jobs),
        "jobs": [j.to_dict() for j in jobs],
    }
    json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return md_path, json_path


def print_search_results(
    jobs: list[RecommendJobItem],
    total_count: int,
    detail: bool = False,
    limit: int | None = None,
) -> None:
    """検索結果をコンソールに出力する."""
    print("\n========================================================")
    print(" Findy おすすめ求人一覧 (sort=recommend)")
    print(f" 全体件数: {total_count} 件 / 取得・表示: {len(jobs)} 件")
    print("========================================================\n")

    display_jobs = jobs[:limit] if limit else jobs
    if not display_jobs:
        print("条件に一致する求人は見つかりませんでした。")
        return

    for idx, job in enumerate(display_jobs, start=1):
        salary_disp = format_salary_display(job.salary_min, job.salary_max, job.salary_text)
        skills_disp = ", ".join(job.skills[:8]) if job.skills else "未指定"
        if len(job.skills) > 8:
            skills_disp += f" 他{len(job.skills) - 8}件"

        print(f"[{idx}] {job.company} | {job.title}")
        print(f"    - URL:      {job.url}")
        print(f"    - 想定年収: {salary_disp} | リモート: {job.remote_type}")
        print(f"    - スキル:   {skills_disp}")
        if job.tags:
            print(f"    - タグ:     {', '.join(job.tags[:6])}")
        if detail and job.description:
            snippet = job.description[:140].replace("\n", " ").strip()
            print(f"    - 概要:     {snippet}...")
        print("-" * 56)


def main() -> None:
    parser = create_search_parser(
        description="Findyのログイン後おすすめ求人（sort=recommend）を取得・フィルタ・保存します。",
        default_limit=20,
        default_download_limit=5,
    )
    parser.add_argument(
        "--page",
        type=int,
        default=1,
        help="取得開始ページ番号 (デフォルト: 1)",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=1,
        help="取得対象の総ページ数 (デフォルト: 1)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"おすすめ求人ファイル保存先ディレクトリ (デフォルト: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--jobs-dir",
        type=Path,
        default=DEFAULT_JOBS_DIR,
        help=f"求人詳細Markdown保存先ディレクトリ (デフォルト: {DEFAULT_JOBS_DIR})",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="終了時にブラウザセッションを閉じずに保持する",
    )

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    fetch_script = FINDY_SCRIPTS_DIR / "fetch_recommends.mjs"
    if not fetch_script.exists():
        ctx.error(f"必須スクリプトが見つかりません: {fetch_script}")
        sys.exit(1)

    profile_dir = resolve_profile_path(args.session, getattr(args, "profile_path", None))
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    all_jobs: list[RecommendJobItem] = []
    total_count = 0

    try:
        # 1. 認証の確認
        ensure_site_authenticated(
            site="findy",
            session=args.session,
            target_url="https://findy-code.io/home",
            headed=args.headed,
            timeout=args.timeout,
        )

        # 2. 指定されたページ分取得
        for p in range(args.page, args.page + args.pages):
            env_vars = {"FINDY_RECOMMENDS_PAGE": str(p)}
            data = run_code_script(
                session=args.session,
                script_path=fetch_script,
                env_vars=env_vars,
            )

            if not data or not isinstance(data, dict):
                continue

            if "totalCount" in data:
                total_count = data["totalCount"]

            raw_jobs = data.get("jobs", [])
            for item in raw_jobs:
                sal_min = item.get("salaryMin")
                sal_max = item.get("salaryMax")
                sal_text = format_salary_text(sal_min, sal_max, None)
                title = item.get("title", "")
                desc = item.get("description", "")
                tags_str = " ".join(item.get("tags", []))
                remote = detect_remote_type(None, f"{title} {desc} {tags_str}")

                all_jobs.append(
                    RecommendJobItem(
                        id=str(item.get("id", "")),
                        hash=str(item.get("hash", "")),
                        company_id=item.get("companyId"),
                        company=item.get("company", "企業名非公開"),
                        title=title,
                        url=item.get("url", ""),
                        salary_min=sal_min,
                        salary_max=sal_max,
                        salary_text=sal_text,
                        skills=item.get("skills", []),
                        job_roles=item.get("jobRoles", []),
                        tags=item.get("tags", []),
                        remote_type=remote,
                        work_hours=item.get("workHours", ""),
                        description=desc,
                        created_at=item.get("createdAt", ""),
                        published_at=item.get("publishedAt", ""),
                    )
                )

    except KeyboardInterrupt:
        ctx.error("中断されました。")
        sys.exit(130)
    except Exception as e:
        ctx.error(f"取得エラー: {e}")
        sys.exit(1)
    finally:
        if not args.keep_open:
            run_playwright_cmd([f"-s={args.session}", "close"])

    # 3. フィルタリング
    min_sal = parse_salary_arg(args.min_salary) if args.min_salary else None
    max_sal = parse_salary_arg(args.max_salary) if args.max_salary else None

    filtered_jobs = filter_jobs(
        jobs=all_jobs,
        min_salary=min_sal,
        max_salary=max_sal,
        company=args.company,
        title=args.title,
        skills=args.skills,
        remote_type=args.remote,
        role=args.role,
        query_words=args.query,
    )

    # 4. ダウンロード（--download 指定時）
    downloaded_files: list[Path] = []
    if args.download:
        dl_targets = filtered_jobs[: args.download_limit]
        for job in dl_targets:
            if not job.company_id or not job.hash:
                continue
            if args.dry_run:
                ctx.info(f"[dry-run] ダウンロード対象: {job.company} - {job.title}")
                continue
            try:
                md_path = fetch_and_save_job(
                    company_id=job.company_id,
                    job_hash=job.hash,
                    output_dir=args.jobs_dir,
                    force=args.force,
                )
                if md_path:
                    downloaded_files.append(md_path)
            except Exception as e:
                ctx.warn(f"求人詳細取得失敗 ({job.url}): {e}")

    # 5. 結果保存
    saved_md_path: Path | None = None
    saved_json_path: Path | None = None
    if not args.no_save and all_jobs:
        saved_md_path, saved_json_path = save_recommends_result(
            jobs=filtered_jobs if (min_sal or max_sal or args.company or args.title or args.skills or args.remote or args.role or args.query) else all_jobs,
            total_count=total_count,
            output_dir=args.output_dir,
        )

    # 6. 出力
    if ctx.json_mode:
        payload = {
            "source": "findy",
            "type": "recommends",
            "total_count": total_count,
            "returned_count": len(all_jobs),
            "matched_count": len(filtered_jobs),
            "jobs": [j.to_dict() for j in filtered_jobs[: args.limit]],
            "saved_md": to_relative_path(saved_md_path) if saved_md_path else None,
            "saved_json": to_relative_path(saved_json_path) if saved_json_path else None,
            "downloaded": [to_relative_path(p) for p in downloaded_files],
        }
        ctx.output_json(payload)
        return

    if ctx.summary:
        if saved_md_path:
            print(f"\n[おすすめ求人一覧保存] {to_relative_path(saved_md_path)}")
        if downloaded_files:
            print(f"[求人詳細ダウンロード] {len(downloaded_files)} 件保存完了")
        print_search_results(
            jobs=filtered_jobs,
            total_count=total_count,
            detail=args.detail,
            limit=args.limit,
        )
    else:
        # CLI規約: ファイルパスのみ出力
        if saved_md_path:
            ctx.output_path(saved_md_path)
        for p in downloaded_files:
            ctx.output_path(p)


if __name__ == "__main__":
    main()
