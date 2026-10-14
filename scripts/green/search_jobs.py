"""Green 求人検索・取得CLIスクリプト.

Green（https://www.green-japan.com/search）において、
画面上部サーチバー操作またはクエリパラメータ指定により、
キーワード、年収下限等の条件で求人を検索し、
結果一覧および求人詳細をローカルMarkdown/JSONとして永続化します。

エントリポイントスクリプト規約（.agents/rules/scripts-entrypoint.md）準拠。
デフォルト実行時は生成・該当ファイルパスのみをstdoutに出力し、
人間向けサマリは --summary オプション指定時のみ表示します。
"""

from __future__ import annotations

import argparse
import json
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
    create_search_parser,
    entrypoint_guard,
    to_relative_path,
)
from scripts.common.normalizers import (
    detect_remote_type,
    format_salary_display,
    format_salary_text,
    parse_salary_arg,
    parse_salary_range,
)
from scripts.common.storage import save_search_result
from scripts.green.fetch_job import fetch_job

GREEN_SCRIPTS_DIR = Path(__file__).resolve().parent
SEARCH_JOBS_SCRIPT_PATH = GREEN_SCRIPTS_DIR / "search_jobs.mjs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "green" / "searches"
DEFAULT_JOBS_DIR = PROJECT_ROOT / "data" / "green" / "jobs"
SEARCH_PAGE_URL = "https://www.green-japan.com/search"


def run_search_jobs(
    keyword: str = "",
    min_salary_man: int | None = None,
    page: int = 1,
    limit: int = 20,
    session: str = "job-hunt",
    timeout: int = 60,
) -> dict[str, Any]:
    """Playwrightスクリプトを実行して求人検索を実行・結果を抽出する."""
    if not SEARCH_JOBS_SCRIPT_PATH.exists():
        raise RuntimeError(f"Playwrightスクリプトが見つかりません: {SEARCH_JOBS_SCRIPT_PATH}")

    profile_path = resolve_profile_path(session)
    # ブラウザセッションオープン
    run_playwright_cmd([f"-s={session}", "open", SEARCH_PAGE_URL, f"--profile={profile_path}"])

    template_code = SEARCH_JOBS_SCRIPT_PATH.read_text(encoding="utf-8")
    min_salary_val = str(min_salary_man) if min_salary_man is not None else ""

    run_code = (
        template_code.replace("__KEYWORD__", json.dumps(keyword).strip('"'))
        .replace("__MIN_SALARY__", min_salary_val)
        .replace("__PAGE__", str(page))
        .replace("__LIMIT__", str(limit))
    )

    tmp_script = GREEN_SCRIPTS_DIR / f".tmp_search_{session}.mjs"
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


def normalize_job_item(raw_item: dict[str, Any]) -> dict[str, Any]:
    """生求人アイテムを共通フォーマットに正規化する."""
    sal_min, sal_max = parse_salary_range(raw_item.get("salary", ""))
    # 万円単位への変換（もし円単位で返っていたら調整）
    sal_min_man = sal_min // 10000 if sal_min is not None else None
    sal_max_man = sal_max // 10000 if sal_max is not None else None

    location = raw_item.get("location", "")
    full_text = f"{raw_item.get('title', '')} {raw_item.get('roleName', '')} {' '.join(raw_item.get('tags', []))}"
    remote_type = detect_remote_type(location, full_text)

    return {
        "id": str(raw_item.get("id", "")),
        "company": raw_item.get("company", "企業名不明"),
        "company_id": raw_item.get("companyId", ""),
        "company_title": raw_item.get("companyTitle", ""),
        "title": raw_item.get("title", "求人タイトル不明"),
        "role_name": raw_item.get("roleName", ""),
        "salary_min": sal_min_man,
        "salary_max": sal_max_man,
        "salary_text": raw_item.get("salary", "") or format_salary_display(sal_min_man, sal_max_man),
        "location": location,
        "remote_type": remote_type,
        "url": raw_item.get("url", ""),
        "tags": raw_item.get("tags", []),
        "employees_number": raw_item.get("employeesNumber"),
        "updated_at_timestamp": raw_item.get("updatedAtTimestamp"),
    }


def filter_jobs(
    jobs: list[dict[str, Any]],
    min_salary_man: int | None = None,
    max_salary_man: int | None = None,
    remote_only: bool = False,
) -> list[dict[str, Any]]:
    """取得求人リストに対して年収やリモート条件でフィルタリングを行う."""
    filtered: list[dict[str, Any]] = []

    for job in jobs:
        # 年収下限フィルタ
        if min_salary_man is not None:
            max_s = job.get("salary_max")
            # 上限年収が設定されているのに下限に届かない場合は除外
            if max_s is not None and max_s < min_salary_man:
                continue

        # 年収上限フィルタ
        if max_salary_man is not None:
            min_s = job.get("salary_min")
            # 下限年収が指定上限を超えている場合は除外
            if min_s is not None and min_s > max_salary_man:
                continue

        # リモートフィルタ
        if remote_only:
            rtype = job.get("remote_type", "")
            if rtype == "出社":
                continue

        filtered.append(job)

    return filtered


def print_search_summary(
    keyword: str,
    total_count: int,
    jobs: list[dict[str, Any]],
    md_path: Path,
    json_path: Path,
    downloaded_paths: list[Path] | None = None,
) -> None:
    """人間向けの検索サマリをコンソールに出力する."""
    print("\n========================================================")
    print(f" Green 求人検索結果: {keyword or '（全件）'}")
    print(f" 全体件数:   {total_count} 件")
    print(f" 取得件数:   {len(jobs)} 件")
    print(f" Markdown:   {to_relative_path(md_path)}")
    print(f" JSON:       {to_relative_path(json_path)}")
    print("========================================================\n")

    if not jobs:
        print("該当する求人はありませんでした。")
        return

    for idx, job in enumerate(jobs[:20], start=1):
        print(f"[{idx}] {job['company']} / {job['title']}")
        if job.get("salary_text"):
            print(f"    想定年収: {job['salary_text']}")
        if job.get("location"):
            print(f"    勤務地:   {job['location']} ({job['remote_type']})")
        if job.get("tags"):
            print(f"    タグ:     {', '.join(job['tags'][:5])}")
        if job.get("url"):
            print(f"    URL:      {job['url']}")
        print("-" * 56)

    if downloaded_paths:
        print(f"\n[ダウンロード] {len(downloaded_paths)} 件の求人詳細を保存しました:")
        for p in downloaded_paths:
            print(f"  - {to_relative_path(p)}")


def main() -> None:
    parser = create_search_parser(
        description="Green 求人検索CLI（画面上部サーチバー操作・条件指定・結果保存・ダウンロード連携）",
        default_limit=20,
        default_download_limit=5,
        default_session="job-hunt",
    )
    parser.add_argument(
        "--page",
        type=int,
        default=1,
        help="検索ページ番号 (デフォルト: 1)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="検索結果保存先ディレクトリ (デフォルト: data/green/searches)",
    )
    parser.add_argument(
        "--jobs-dir",
        type=Path,
        default=DEFAULT_JOBS_DIR,
        help="求人詳細保存先ディレクトリ (デフォルト: data/green/jobs)",
    )

    args = parser.parse_args()

    # クエリキーワード組み立て
    query_parts: list[str] = []
    if getattr(args, "query", None):
        query_parts.extend(args.query)
    if getattr(args, "keywords", None):
        query_parts.extend(args.keywords)
    if getattr(args, "skills", None):
        query_parts.extend(args.skills)
    if getattr(args, "company", None):
        query_parts.append(args.company)
    if getattr(args, "title", None):
        query_parts.append(args.title)
    if getattr(args, "role", None):
        query_parts.append(args.role)

    kw = " ".join(query_parts).strip()

    # 年収引数のパース (円単位から万円単位へ変換)
    min_sal_man: int | None = None
    if args.min_salary:
        min_sal_yen = parse_salary_arg(args.min_salary)
        if min_sal_yen:
            min_sal_man = min_sal_yen // 10000

    max_sal_man: int | None = None
    if args.max_salary:
        max_sal_yen = parse_salary_arg(args.max_salary)
        if max_sal_yen:
            max_sal_man = max_sal_yen // 10000

    # 認証確認
    sys.stderr.write(f"[Green] セッション '{args.session}' の認証状態を確認中...\n")
    if not ensure_site_authenticated("green", session=args.session):
        sys.stderr.write("[Green] 認証が完了しなかったため、処理を中断します。\n")
        sys.exit(2)

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        sys.stderr.write(f"[Green] 求人検索を実行中 (キーワード: '{kw}', 下限年収: {min_sal_man or '指定なし'}万円, ページ: {args.page})...\n")

        raw_result = run_search_jobs(
            keyword=kw,
            min_salary_man=min_sal_man,
            page=args.page,
            limit=args.limit or 20,
            session=args.session,
        )

        total_count = raw_result.get("totalCount", 0)
        raw_jobs = raw_result.get("jobs", [])

        # 正規化
        normalized_jobs = [normalize_job_item(j) for j in raw_jobs]

        # フィルタリング
        filtered_jobs = filter_jobs(
            normalized_jobs,
            min_salary_man=min_sal_man,
            max_salary_man=max_sal_man,
            remote_only=args.remote,
        )

        # 件数制限
        if args.limit and len(filtered_jobs) > args.limit:
            filtered_jobs = filtered_jobs[: args.limit]

        # 検索結果の永続化
        args.output_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "page": args.page,
            "min_salary_man": min_sal_man,
            "max_salary_man": max_sal_man,
            "remote": args.remote,
            "search_url": raw_result.get("url", SEARCH_PAGE_URL),
        }
        md_path, json_path = save_search_result(
            source="green",
            keyword=kw,
            jobs=filtered_jobs,
            total_count=total_count,
            returned_count=len(filtered_jobs),
            output_dir=args.output_dir,
            metadata=meta,
        )
        ctx.add_result_path(md_path)
        ctx.add_result_path(json_path)

        # --download 連携
        downloaded_paths: list[Path] = []
        if args.download and filtered_jobs:
            download_limit = args.download_limit or 5
            target_download_jobs = filtered_jobs[:download_limit]
            sys.stderr.write(f"[Green] ヒットした求人から {len(target_download_jobs)} 件を自動保存中...\n")

            for j in target_download_jobs:
                jid = j.get("id")
                if not jid:
                    continue
                try:
                    dl_path, is_mod, _ = fetch_job(
                        target=jid,
                        output_dir=args.jobs_dir,
                        session=args.session,
                        force=args.force,
                    )
                    downloaded_paths.append(dl_path)
                    ctx.add_result_path(dl_path)
                except Exception as dl_err:
                    sys.stderr.write(f"[警告] 求人 {jid} のダウンロードに失敗しました: {dl_err}\n")

        def print_summary_cb() -> None:
            print_search_summary(
                keyword=kw,
                total_count=total_count,
                jobs=filtered_jobs,
                md_path=md_path,
                json_path=json_path,
                downloaded_paths=downloaded_paths,
            )

        json_payload = {
            "source": "green",
            "keyword": kw,
            "total_count": total_count,
            "returned_count": len(filtered_jobs),
            "md_path": to_relative_path(md_path),
            "json_path": to_relative_path(json_path),
            "downloaded": [to_relative_path(p) for p in downloaded_paths],
            "jobs": filtered_jobs,
        } if args.json else None

        ctx.flush_outputs(summary_fn=print_summary_cb, json_data=json_payload)


if __name__ == "__main__":
    main()
