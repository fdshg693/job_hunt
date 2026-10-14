"""ビズリーチ メッセージ添付求人取得・Markdown保存モジュール.

ビズリーチのスカウト/メッセージ画面から添付求人を特定・抽出し、
プロジェクト共通仕様（.agents/rules/job-data-format.md）に準拠したフロントマター付きMarkdownとして保存します。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

# プロジェクトルートパス
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.bizreach.fetch_job import (
    DEFAULT_OUTPUT_DIR,
    fetch_and_save_bizreach_job,
)
from scripts.common.auth_engine import ensure_site_authenticated
from scripts.common.browser_auth import (
    resolve_profile_path,
    run_code_script,
    run_playwright_cmd,
    update_profile_last_used,
)
from scripts.common.cli import EntrypointContext, create_base_parser, to_relative_path

BIZREACH_SCRIPTS_DIR = Path(__file__).resolve().parent


def extract_thread_id(url_or_id: str) -> str:
    """メッセージURLまたはスレッドIDからスレッドIDを抽出・正規化する."""
    cleaned = url_or_id.strip()
    m = re.search(r"/messages/([a-zA-Z0-9_-]+)", cleaned)
    if m:
        return m.group(1)
    if re.match(r"^[a-zA-Z0-9_-]+$", cleaned):
        return cleaned
    raise ValueError(f"無効なビズリーチメッセージURLまたはスレッドIDです: {url_or_id}")


def normalize_message_url(url_or_id: str) -> tuple[str, str]:
    """(thread_id, full_url) のタプルを返す."""
    thread_id = extract_thread_id(url_or_id)
    return thread_id, f"https://www.bizreach.jp/messages/{thread_id}/"


def print_summary(
    thread_id: str,
    message_url: str,
    sender_name: str,
    job_results: list[dict[str, Any]],
) -> None:
    """メッセージ添付求人の取得サマリをコンソールに整形出力する."""
    print("\n========================================================")
    print(" ビズリーチ メッセージ添付求人 取得結果")
    print(f" スレッドID: {thread_id}")
    print(f" URL:        {message_url}")
    print(f" 送信者:     {sender_name or '送信者名不明'}")
    print(f" 添付求人数: {len(job_results)} 件")
    print("========================================================\n")

    if not job_results:
        print("添付求人はありませんでした。")
        return

    for idx, r in enumerate(job_results, start=1):
        status_disp = "[既存]" if r.get("status") == "skipped" else "[新規保存]"
        print(f"[{idx}] {status_disp} {r.get('company', '')} | {r.get('title', '')}")
        print(f"    想定年収: {r.get('salary', '未記載')}")
        if r.get("path"):
            print(f"    保存先:   {to_relative_path(r['path'])}")
        print("-" * 56)


def fetch_message_jobs(
    target: str,
    session: str = "job-hunt",
    profile_path: str | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    force: bool = False,
    dry_run: bool = False,
    summary: bool = False,
    timeout: int = 120,
    headed: bool = False,
    no_notify: bool = False,
) -> tuple[list[Path], list[dict[str, Any]]]:
    """メッセージスレッドから添付求人を抽出して詳細保存する."""
    thread_id, message_url = normalize_message_url(target)
    extract_jobs_script = BIZREACH_SCRIPTS_DIR / "extract_message_jobs.mjs"
    if not extract_jobs_script.exists():
        raise FileNotFoundError(f"必須スクリプトが見つかりません: {extract_jobs_script}")

    profile_dir = resolve_profile_path(session, profile_path)
    if not profile_dir.exists():
        profile_dir.mkdir(parents=True, exist_ok=True)

    # 1. 共通認証エンジンによるブラウザセッション起動・認証確認・手動待機ハンドオフ
    ensure_site_authenticated(
        site="bizreach",
        session=session,
        target_url=message_url,
        headed=headed,
        timeout=timeout,
        no_notify=no_notify,
        profile_dir=profile_dir,
        exit_on_fail=True,
    )

    # 2. 添付求人抽出スクリプトを実行
    res = run_code_script(session, extract_jobs_script, timeout=40)
    if not res or not res.get("success"):
        err_msg = res.get("error") if res else "抽出結果が空でした"
        raise RuntimeError(f"添付求人の抽出に失敗しました ({message_url}): {err_msg}")

    update_profile_last_used(session)

    sender_name = res.get("senderName", "")
    attached_jobs = res.get("jobs", [])

    if not attached_jobs:
        print(f"[{thread_id}] 添付求人はありませんでした。", file=sys.stderr)
        if summary:
            print_summary(thread_id, message_url, sender_name, [])
        return [], []

    # 3. 各添付求人の詳細を取得・保存
    saved_paths: list[Path] = []
    job_results: list[dict[str, Any]] = []
    extra_frontmatter = {
        "source_message_url": message_url,
        "source_thread_id": thread_id,
    }

    for job in attached_jobs:
        job_id = job.get("jobId")
        job_url = job.get("jobUrl") or f"https://www.bizreach.jp/jobs/{job_id}/"
        initial_location = job.get("location")

        try:
            path, detail_data = fetch_and_save_bizreach_job(
                job_url,
                session=session,
                output_dir=output_dir,
                force=force,
                dry_run=dry_run,
                summary=False,
                initial_location=initial_location,
                extra_frontmatter=extra_frontmatter,
            )
            if path:
                saved_paths.append(path)
                job_results.append({
                    "id": job_id,
                    "title": detail_data.get("title") or job.get("title"),
                    "company": detail_data.get("company") or job.get("company"),
                    "salary": detail_data.get("salaryText") or job.get("salary"),
                    "path": path,
                    "status": detail_data.get("status", "saved"),
                })
        except Exception as e:
            print(f"エラー: 求人 {job_id} の取得に失敗しました: {e}", file=sys.stderr)

    if summary:
        print_summary(thread_id, message_url, sender_name, job_results)

    return saved_paths, job_results


def main() -> None:
    """CLIエントリポイント."""
    parser = create_base_parser(
        description="ビズリーチのスカウト/メッセージ画面から添付求人を自動抽出し、詳細Markdownとして保存します。"
    )
    parser.add_argument("target", help="ビズリーチメッセージURLまたはスレッドID（例: 444484943）")
    parser.add_argument("--session", default="job-hunt", help="Playwright CLIセッション名（デフォルト: job-hunt）")
    parser.add_argument("--profile-path", help="ブラウザプロファイルディレクトリのパス")
    parser.add_argument("-o", "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="保存先ディレクトリ")
    parser.add_argument("--dry-run", action="store_true", help="ファイル書き込みを行わない")
    parser.add_argument("--headed", action="store_true", help="ブラウザを可視ウィンドウで起動する")
    parser.add_argument("--keep-open", action="store_true", help="ブラウザセッションを維持")
    parser.add_argument("--timeout", type=int, default=120, help="手動ログイン待機のタイムアウト秒数")
    parser.add_argument("--no-notify", action="store_true", help="認証壁検知時のOSトースト通知を送信しない")

    args = parser.parse_args()
    ctx = EntrypointContext(summary=args.summary, json_mode=args.json)

    try:
        saved_paths, results = fetch_message_jobs(
            args.target,
            session=args.session,
            profile_path=args.profile_path,
            output_dir=args.output_dir,
            force=args.force,
            dry_run=args.dry_run,
            summary=args.summary,
            timeout=args.timeout,
            headed=args.headed,
            no_notify=args.no_notify,
        )

        ctx.add_result_paths(saved_paths)

        def summary_fn() -> None:
            # fetch_message_jobs already prints summary when summary=True
            pass

        sys.exit(ctx.flush_outputs(summary_fn=summary_fn, json_data=results))

    finally:
        if not args.keep_open:
            run_playwright_cmd([f"-s={args.session}", "close"], timeout=10)


if __name__ == "__main__":
    main()
