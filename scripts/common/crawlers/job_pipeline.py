"""求人詳細取得共通実行パイプライン (job_pipeline.py).

各求人サイト（Bizreach, Findy, Green, Forkwell, LinkedIn, OpenWork 等）の求人詳細取得スクリプトにおける
ボイラープレート（CLI定義、認証待機、キャッシュ確認、データ検証、Markdown保存、サマリ表示）
を一元化・共通実行する基盤を提供します。
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.common.auth_engine import SiteAuthConfig, ensure_site_authenticated
from scripts.common.browser_auth import (
    resolve_profile_path,
    run_code_script,
    run_code_snippet,
    run_playwright_cmd,
    update_profile_last_used,
)
from scripts.common.cli import (
    EntrypointContext,
    create_base_parser,
    entrypoint_guard,
    to_relative_path,
)
from scripts.common.models.job import JobPosting
from scripts.common.storage import JobData, save_job_markdown


@dataclass
class JobCrawlerConfig:
    """求人詳細スクレイパー設定モデル."""

    site_id: str
    site_name: str
    default_output_dir: Path

    # サイト認証（不要な場合は None）
    auth_site: str | SiteAuthConfig | None = None

    # ID/URL解決
    extract_job_id_fn: Callable[[str], str] | None = None
    normalize_url_fn: Callable[[str], str] | None = None

    # 取得処理
    custom_fetch_fn: Callable[[JobPipelineContext], dict[str, Any] | JobPosting | JobData] | None = None
    script_path: Path | None = None
    script_template_generator: Callable[[str], str] | None = None

    # データ変換・保存
    parse_job_fn: Callable[[dict[str, Any], JobPipelineContext], JobPosting | JobData] | None = None
    custom_save_fn: Callable[[JobPosting | JobData, JobPipelineContext], tuple[Path, bool]] | None = None

    # サマリ表示・CLI拡張
    custom_summary_fn: Callable[[JobPosting | JobData, JobPipelineContext], None] | None = None
    setup_args_fn: Callable[[argparse.ArgumentParser], None] | None = None

    # --help の「使用例:」「関連:」（scripts.common.cli.build_epilog）
    examples: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    default_timeout: int = 45


@dataclass
class JobPipelineContext:
    """求人パイプライン実行コンテキスト."""

    config: JobCrawlerConfig
    args: argparse.Namespace
    entrypoint_ctx: EntrypointContext
    target: str
    job_id: str
    target_url: str
    output_dir: Path
    output_path: Path
    session: str
    profile_dir: Path
    now: datetime


def print_job_summary(job: JobPosting | JobData, config: JobCrawlerConfig) -> None:
    """求人詳細モデルのサマリをコンソールに整形出力する."""
    skills_display = ", ".join(job.skills[:10]) if job.skills else "未記載"
    roles_display = ", ".join(job.job_roles) if job.job_roles else "未記載"

    print("\n========================================================")
    print(f" {config.site_name} 求人詳細: {job.company or '企業名非公開'} / {job.title or 'タイトルなし'}")
    print(f" URL:        {job.url}")
    print(f" 想定年収:   {job.salary_text or '未記載'}")
    print(f" 勤務地:     {job.location or '未記載'} (リモート: {job.remote_type or '不明'})")
    if job.job_roles:
        print(f" 職種:       {roles_display}")
    if job.skills:
        print(f" スキル:     {skills_display}")
    print("========================================================\n")


def build_job_parser(config: JobCrawlerConfig) -> argparse.ArgumentParser:
    """求人スクリプト共通のCLIパーサーを生成する."""
    parser = create_base_parser(
        description=f"{config.site_name}の求人詳細を取得し、Markdownファイルとして保存します。",
        examples=config.examples,
        related=config.related,
    )

    parser.add_argument(
        "target",
        help=f"{config.site_name}の求人IDまたは求人詳細URL",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=config.default_output_dir,
        help=f"求人Markdownの保存先ディレクトリ（デフォルト: {config.default_output_dir}）",
    )
    parser.add_argument(
        "--session",
        default="job-hunt",
        help="Playwright CLIセッション名（デフォルト: job-hunt）",
    )
    parser.add_argument(
        "--profile-path",
        help="ブラウザプロファイルディレクトリのパス（省略時は自動解決）",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="可視ブラウザで起動する（手動操作用）",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=config.default_timeout,
        help=f"タイムアウト秒数（デフォルト: {config.default_timeout}秒）",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="認証壁検知時のOSトースト通知を送信しない",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="処理完了後にブラウザセッションを閉じずに保持する",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="ファイル書き込みを行わない",
    )

    if config.setup_args_fn:
        config.setup_args_fn(parser)

    return parser


def run_job_pipeline(
    config: JobCrawlerConfig,
    argv: Sequence[str] | None = None,
) -> int:
    """求人詳細取得パイプラインを実行する."""
    parser = build_job_parser(config)
    args = parser.parse_args(argv)

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        now = datetime.now()
        target = args.target.strip()

        # 1. ID / URL の解決
        if config.extract_job_id_fn:
            job_id = config.extract_job_id_fn(target)
        else:
            job_id = target

        if config.normalize_url_fn:
            target_url = config.normalize_url_fn(target)
        else:
            target_url = target

        output_dir: Path = args.output_dir or config.default_output_dir
        output_path = output_dir / f"{job_id}.md"

        profile_dir = resolve_profile_path(args.session, args.profile_path)
        if not profile_dir.exists():
            profile_dir.mkdir(parents=True, exist_ok=True)

        pipeline_ctx = JobPipelineContext(
            config=config,
            args=args,
            entrypoint_ctx=ctx,
            target=target,
            job_id=job_id,
            target_url=target_url,
            output_dir=output_dir,
            output_path=output_path,
            session=args.session,
            profile_dir=profile_dir,
            now=now,
        )

        # 2. キャッシュ確認（既存ファイルが存在し force でない場合はスキップ）
        if output_path.exists() and not args.force:
            ctx.add_result_path(output_path)

            def cached_summary() -> None:
                ctx.log(f"[{config.site_name}] 既存の求人ファイルが見つかりました（スキップ）: {to_relative_path(output_path)}")

            json_data = {
                "source": config.site_id,
                "id": job_id,
                "target": target,
                "path": to_relative_path(output_path),
                "modified": False,
                "status": "skipped",
            } if args.json else None

            return ctx.flush_outputs(summary_fn=cached_summary, json_data=json_data)

        # 3. 認証確認・ハンドオフ（設定されている場合）
        if config.auth_site:
            ensure_site_authenticated(
                site=config.auth_site,
                session=args.session,
                target_url=target_url or None,
                headed=args.headed,
                timeout=args.timeout,
                no_notify=args.no_notify,
                profile_dir=profile_dir,
                exit_on_fail=True,
            )

        used_playwright = False
        try:
            # 4. データ取得
            raw_data: Any = None
            if config.custom_fetch_fn:
                raw_data = config.custom_fetch_fn(pipeline_ctx)
            elif config.script_template_generator:
                used_playwright = True
                script_code = config.script_template_generator(target_url)
                raw_data = run_code_snippet(args.session, script_code, timeout=args.timeout)
            elif config.script_path:
                used_playwright = True
                if not config.script_path.exists():
                    ctx.error(f"必須スクリプトが見つかりません: {config.script_path}")
                    sys.exit(1)
                raw_data = run_code_script(args.session, config.script_path, timeout=args.timeout)
            else:
                ctx.error(f"{config.site_name} のフェッチ設定（custom_fetch_fn 等）が指定されていません。")
                sys.exit(1)

            if not raw_data or (isinstance(raw_data, dict) and raw_data.get("success") is False):
                err_msg = (raw_data.get("error") or raw_data.get("errors")) if isinstance(raw_data, dict) else "取得結果が空でした"
                ctx.error(f"{config.site_name} 求人詳細の取得に失敗しました ({target_url}): {err_msg}")
                sys.exit(1)

            # 5. JobPosting / JobData モデルへの変換・検証
            if isinstance(raw_data, (JobPosting, JobData)):
                job = raw_data
            elif config.parse_job_fn:
                job = config.parse_job_fn(raw_data, pipeline_ctx)
            else:
                # デフォルト変換
                raw_dict = dict(raw_data)
                if "id" not in raw_dict:
                    raw_dict["id"] = job_id
                if "source" not in raw_dict:
                    raw_dict["source"] = config.site_id
                if "url" not in raw_dict:
                    raw_dict["url"] = target_url
                job = JobPosting.model_validate(raw_dict)

            update_profile_last_used(args.session)

            # 6. 保存処理
            saved_path = output_path
            is_modified = True
            if not args.dry_run:
                if config.custom_save_fn:
                    saved_path, is_modified = config.custom_save_fn(job, pipeline_ctx)
                else:
                    saved_path, is_modified = save_job_markdown(job, output_dir=output_dir, force=args.force)
                ctx.add_result_path(saved_path)

            # 7. 出力 (規約準拠)
            def summary_fn() -> None:
                if config.custom_summary_fn:
                    config.custom_summary_fn(job, pipeline_ctx)
                else:
                    print_job_summary(job, config)
                ctx.log(f"=== {config.site_name} 求人詳細取得 ===")
                ctx.log(f"対象: {target}")
                ctx.log(f"結果: {'更新・作成' if is_modified else '既存スキップ'}")
                ctx.log(f"保存パス: {to_relative_path(saved_path)}")

            json_data = {
                "source": config.site_id,
                "id": job_id,
                "target": target,
                "path": to_relative_path(saved_path),
                "modified": is_modified,
            }
            if hasattr(job, "to_dict"):
                json_data["job"] = job.to_dict()

            return ctx.flush_outputs(summary_fn=summary_fn, json_data=json_data if args.json else None)

        finally:
            if used_playwright and not args.keep_open:
                run_playwright_cmd([f"-s={args.session}", "close"], timeout=10)
