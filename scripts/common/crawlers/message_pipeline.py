"""メッセージ一覧・スカウト取得共通実行パイプライン (message_pipeline.py).

各求人サイト（Bizreach, Findy, Green, Forkwell 等）のメッセージ取得スクリプトにおける
ボイラープレート（CLI定義、認証待機、Playwright実行、データ検証、Markdown/JSON保存、サマリ表示）
を一元化・共通実行する基盤を提供します。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from scripts.common.auth_engine import SiteAuthConfig, ensure_site_authenticated
from scripts.common.browser_auth import (
    resolve_profile_path,
    run_code_script,
    run_playwright_cmd,
    update_profile_last_used,
)
from scripts.common.cli import (
    EntrypointContext,
    create_base_parser,
    entrypoint_guard,
    to_relative_path,
)
from scripts.common.models.message import MessageBatch, MessageItem


@dataclass
class MessageCrawlerConfig:
    """メッセージスクレイパー設定モデル."""

    site_id: str
    site_name: str
    auth_site: str | SiteAuthConfig
    default_output_dir: Path

    # タブ & URL マッピング
    tab_url_map: dict[str, str] = field(default_factory=dict)
    tab_label_map: dict[str, str] = field(default_factory=dict)
    default_tab: str = "all"
    tab_choices: list[str] | None = None

    # Playwrightスクリプト
    script_path: Path | None = None

    # ファイル保存モード
    # - "hourly": {YYYY-MM-DD-HH}_{tab}.md / .json (Bizreach, OpenWork 等)
    # - "latest_and_history": messages_{tab}.md / .json + history/... (Forkwell, Findy 等)
    # - "timestamp_detailed": {YYYY-MM-DD-HHMMSS}_messages_{tab}.md / .json (Green 等)
    save_mode: Literal["hourly", "latest_and_history", "timestamp_detailed"] = "hourly"

    # フック & カスタマイズ
    custom_fetch_fn: Callable[[MessagePipelineContext], dict[str, Any] | MessageBatch] | None = None
    parse_item_fn: Callable[[dict[str, Any]], MessageItem | dict[str, Any]] | None = None
    parse_batch_fn: Callable[[dict[str, Any]], MessageBatch | dict[str, Any]] | None = None
    summary_item_formatter: Callable[[MessageItem, int], list[str]] | None = None
    custom_summary_fn: Callable[[MessageBatch, MessagePipelineContext], None] | None = None
    markdown_table_columns: list[str] | None = None
    markdown_table_row_fn: Callable[[MessageItem, int], list[str]] | None = None
    markdown_detail_item_fn: Callable[[MessageItem, int], list[str]] | None = None
    custom_save_fn: Callable[[MessageBatch, MessagePipelineContext], list[Path]] | None = None
    setup_args_fn: Callable[[argparse.ArgumentParser], None] | None = None

    # --help の「使用例:」「関連:」（scripts.common.cli.build_epilog）
    examples: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)


@dataclass
class MessagePipelineContext:
    """メッセージパイプライン実行コンテキスト."""

    config: MessageCrawlerConfig
    args: argparse.Namespace
    entrypoint_ctx: EntrypointContext
    tab: str
    tab_label: str
    target_url: str
    session: str
    profile_dir: Path
    now: datetime


def _escape_md_cell(value: Any) -> str:
    """Markdownテーブルセル用文字列エスケープ."""
    if value is None:
        return "-"
    s = str(value).replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()
    return s if s else "-"


def generate_message_markdown(
    batch: MessageBatch,
    config: MessageCrawlerConfig,
    now: datetime,
) -> str:
    """メッセージ一覧バッチから構造化フロントマター付きMarkdownを生成する."""
    tab_label = batch.tab_label or config.tab_label_map.get(batch.tab, batch.tab)
    total_count = batch.total_count if batch.total_count is not None else len(batch.messages)
    fetched_at_str = now.isoformat(timespec="seconds")
    fetched_at_display = now.strftime("%Y-%m-%d %H:%M:%S")
    target_url = batch.url or config.tab_url_map.get(batch.tab, "")

    lines = [
        "---",
        f"source: {batch.source.lower()}",
        "type: messages",
        f"tab: {batch.tab}",
        f"tab_label: '{tab_label}'",
        f"fetched_at: '{fetched_at_str}'",
        f"url: '{target_url}'",
        f"total_count: {total_count}",
        "---",
        "",
        f"# {config.site_name} メッセージ・スカウト一覧 [{tab_label}] ({now.strftime('%Y-%m-%d %H時')})",
        "",
        f"- 取得日時: {fetched_at_display}",
        f"- 対象URL: {target_url}",
        f"- 取得件数: {total_count} 件",
        "",
    ]

    if not batch.messages:
        lines.append("> 現在、受信したメッセージ・スカウトはありません。\n")
        return "\n".join(lines)

    # 1. 概要テーブル
    lines.append("## メッセージ・スカウト一覧")
    lines.append("")

    if config.markdown_table_columns and config.markdown_table_row_fn:
        header_cols = config.markdown_table_columns
        lines.append(f"| {' | '.join(header_cols)} |")
        lines.append(f"|{'---|' * len(header_cols)}")
        for idx, msg in enumerate(batch.messages, start=1):
            row_cells = config.markdown_table_row_fn(msg, idx)
            escaped_cells = [_escape_md_cell(c) for c in row_cells]
            lines.append(f"| {' | '.join(escaped_cells)} |")
    else:
        # デフォルトテーブル
        lines.append("| # | 状態 | 種別 | 企業/送信者 | 件名 | 日時/期限 | 求人URL | スレッドURL |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for idx, msg in enumerate(batch.messages, start=1):
            status = "未読" if msg.is_unread else "既読"
            scout_type = msg.scout_type or "通常"
            sender_comp = msg.company or msg.sender or "送信者不明"
            subject = msg.subject or "（件名なし）"
            date_info = msg.deadline or msg.date or "-"
            job_link = f"[求人詳細]({msg.job_url})" if msg.job_url else "-"
            thread_link = f"[スレッド]({msg.url})" if msg.url else "-"

            lines.append(
                f"| {idx} | {status} | {_escape_md_cell(scout_type)} | {_escape_md_cell(sender_comp)} "
                f"| {_escape_md_cell(subject)} | {_escape_md_cell(date_info)} | {job_link} | {thread_link} |"
            )

    lines.append("")

    # 2. 詳細セクション
    lines.append("## 詳細")
    lines.append("")

    for idx, msg in enumerate(batch.messages, start=1):
        if config.markdown_detail_item_fn:
            detail_lines = config.markdown_detail_item_fn(msg, idx)
            lines.extend(detail_lines)
            lines.append("")
        else:
            comp = msg.company or msg.sender or "企業名不明"
            subj = msg.subject or "（件名なし）"
            lines.append(f"### {idx}. {comp} - {subj}")
            lines.append("")

            status = "未読" if msg.is_unread else "既読"
            lines.append(f"- **状態**: {status}")
            if msg.scout_type:
                lines.append(f"- **スカウト種別**: {msg.scout_type}")
            if msg.sender and msg.sender != comp:
                lines.append(f"- **送信者**: {msg.sender}")
            if msg.date:
                lines.append(f"- **受信日時**: {msg.date}")
            if msg.deadline:
                lines.append(f"- **有効期限**: {msg.deadline}")
            if msg.job_title:
                lines.append(f"- **求人名**: {msg.job_title}")
            if msg.job_url:
                lines.append(f"- **求人URL**: {msg.job_url}")
            if msg.url:
                lines.append(f"- **スレッドURL**: {msg.url}")

            # サイト固有拡張メタデータ (attachedJobs, badges など)
            badges = msg.extra_metadata.get("badges")
            if badges and isinstance(badges, list):
                lines.append(f"- **バッジ**: {', '.join(str(b) for b in badges)}")

            attached_jobs = msg.extra_metadata.get("attachedJobs") or msg.extra_metadata.get("attachedJob")
            if attached_jobs:
                if isinstance(attached_jobs, list):
                    lines.append("- **添付求人一覧**:")
                    for j_idx, job in enumerate(attached_jobs, start=1):
                        j_title = job.get("title", "")
                        j_comp = job.get("company", "")
                        j_sal = job.get("salary", "")
                        j_url = job.get("url", "")
                        sal_part = f" ({j_sal})" if j_sal else ""
                        url_part = f" [リンク]({j_url})" if j_url else ""
                        lines.append(f"  - [{j_idx}] {j_comp} | {j_title}{sal_part}{url_part}")
                elif isinstance(attached_jobs, dict):
                    lines.append(f"- **添付求人**: {attached_jobs.get('url', '')}")

            body_content = msg.body or msg.raw_text or msg.snippet
            if body_content:
                lines.append("")
                lines.append("#### 本文 / 抜粋")
                lines.append("")
                lines.append("```text")
                lines.append(body_content.strip())
                lines.append("```")

            lines.append("")

    return "\n".join(lines).strip() + "\n"


def print_message_summary(batch: MessageBatch, config: MessageCrawlerConfig) -> None:
    """メッセージ一覧バッチのサマリをコンソールに整形出力する."""
    tab_label = batch.tab_label or config.tab_label_map.get(batch.tab, batch.tab)
    total_count = batch.total_count if batch.total_count is not None else len(batch.messages)
    fetched_count = batch.fetched_count if batch.fetched_count is not None else len(batch.messages)

    count_str = f"全 {total_count} 件"
    if fetched_count != total_count:
        count_str += f"（取得: {fetched_count} 件）"

    print("\n========================================================")
    print(f" {config.site_name} メッセージ・スカウト一覧 [{tab_label}]")
    print(f" URL:  {batch.url or config.tab_url_map.get(batch.tab, '')}")
    print(f" 件数: {count_str}")
    print("========================================================\n")

    if not batch.messages:
        print("現在、受信したメッセージ・スカウトはありません。")
        return

    for idx, msg in enumerate(batch.messages, start=1):
        if config.summary_item_formatter:
            lines = config.summary_item_formatter(msg, idx)
            for line in lines:
                print(line)
        else:
            status_prefix = "[未読] " if msg.is_unread else ""
            type_badge = f"[{msg.scout_type}]" if msg.scout_type else ""
            sender_comp = msg.company or msg.sender or "送信者不明"
            if msg.company and msg.sender and msg.company != msg.sender:
                sender_comp = f"{msg.company} ({msg.sender})"

            print(f"[{idx}] {status_prefix}{type_badge} {sender_comp}")
            if msg.subject:
                print(f"    件名:     {msg.subject}")
            if msg.job_title and msg.job_title != msg.subject:
                print(f"    求人名:   {msg.job_title}")
            if msg.date:
                print(f"    日時:     {msg.date}")
            if msg.deadline:
                print(f"    期限:     {msg.deadline}")
            if msg.url:
                print(f"    スレッド: {msg.url}")
            if msg.job_url:
                print(f"    求人URL:  {msg.job_url}")
            if msg.snippet:
                snippet = msg.snippet[:100].replace("\r", " ").replace("\n", " ")
                print(f"    抜粋:     {snippet}...")
            print("-" * 56)


def save_message_batch(
    batch: MessageBatch,
    pipeline_ctx: MessagePipelineContext,
) -> list[Path]:
    """設定された保存モードまたはカスタムフックに従って Markdown / JSON ファイルを保存する."""
    config = pipeline_ctx.config

    if config.custom_save_fn:
        return config.custom_save_fn(batch, pipeline_ctx)

    output_dir = pipeline_ctx.args.output_dir or config.default_output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    now = pipeline_ctx.now
    tab = pipeline_ctx.tab

    md_content = generate_message_markdown(batch, config, now)
    json_str = json.dumps(batch.to_dict(), ensure_ascii=False, indent=2)

    saved_paths: list[Path] = []

    if config.save_mode == "hourly":
        file_stem = f"{now.strftime('%Y-%m-%d-%H')}_{tab}"
        md_path = output_dir / f"{file_stem}.md"
        json_path = output_dir / f"{file_stem}.json"
        md_path.write_text(md_content, encoding="utf-8")
        json_path.write_text(json_str, encoding="utf-8")
        saved_paths.extend([md_path, json_path])

    elif config.save_mode == "latest_and_history":
        history_dir = output_dir / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        time_str = now.strftime("%Y%m%d_%H%M%S")

        latest_md = output_dir / f"messages_{tab}.md"
        latest_json = output_dir / f"messages_{tab}.json"
        history_md = history_dir / f"messages_{tab}_{time_str}.md"
        history_json = history_dir / f"messages_{tab}_{time_str}.json"

        latest_md.write_text(md_content, encoding="utf-8")
        latest_json.write_text(json_str, encoding="utf-8")
        history_md.write_text(md_content, encoding="utf-8")
        history_json.write_text(json_str, encoding="utf-8")

        # 既存規約に合わせて最新ファイル + 履歴ファイルを登録
        saved_paths.extend([latest_md, latest_json, history_md])

    elif config.save_mode == "timestamp_detailed":
        time_str = now.strftime("%Y-%m-%d-%H%M%S")
        file_stem = f"{time_str}_messages_{tab}"
        md_path = output_dir / f"{file_stem}.md"
        json_path = output_dir / f"{file_stem}.json"
        md_path.write_text(md_content, encoding="utf-8")
        json_path.write_text(json_str, encoding="utf-8")
        saved_paths.extend([md_path, json_path])

    return saved_paths


def build_message_parser(config: MessageCrawlerConfig) -> argparse.ArgumentParser:
    """メッセージスクリプト共通のCLIパーサーを生成する."""
    parser = create_base_parser(
        description=f"{config.site_name}のメッセージ・スカウト一覧を取得・表示・ファイル保存します。",
        examples=config.examples,
        related=config.related,
    )

    choices = (
        config.tab_choices
        or list(config.tab_url_map.keys())
        or list(config.tab_label_map.keys())
        or [config.default_tab]
    )

    parser.add_argument(
        "--tab",
        choices=choices,
        default=config.default_tab,
        help=f"取得するタブ (デフォルト: {config.default_tab}, 選択肢: {', '.join(choices)})",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=config.default_output_dir,
        help=f"結果出力先ディレクトリ（デフォルト: {config.default_output_dir}）",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="ファイルへの保存を行わず画面表示のみ行う",
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
        default=120,
        help="手動ログイン待機のタイムアウト秒数（デフォルト: 120秒）",
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

    if config.setup_args_fn:
        config.setup_args_fn(parser)

    return parser


def run_message_pipeline(
    config: MessageCrawlerConfig,
    argv: Sequence[str] | None = None,
) -> int:
    """メッセージ取得パイプラインを実行する."""
    parser = build_message_parser(config)
    args = parser.parse_args(argv)

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        now = datetime.now()
        tab = getattr(args, "tab", config.default_tab)
        tab_label = config.tab_label_map.get(tab, tab)
        target_url = config.tab_url_map.get(tab, "")

        profile_dir = resolve_profile_path(args.session, args.profile_path)
        if not profile_dir.exists():
            profile_dir.mkdir(parents=True, exist_ok=True)

        pipeline_ctx = MessagePipelineContext(
            config=config,
            args=args,
            entrypoint_ctx=ctx,
            tab=tab,
            tab_label=tab_label,
            target_url=target_url,
            session=args.session,
            profile_dir=profile_dir,
            now=now,
        )

        try:
            # 1. 共通認証確認・待機ハンドオフ
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

            # 2. メッセージ一覧データ取得
            raw_data: Any = None
            if config.custom_fetch_fn:
                raw_data = config.custom_fetch_fn(pipeline_ctx)
            else:
                if not config.script_path or not config.script_path.exists():
                    ctx.error(f"必須スクリプトが見つかりません: {config.script_path}")
                    sys.exit(1)

                raw_data = run_code_script(
                    args.session,
                    config.script_path,
                    timeout=args.timeout,
                )

            if not raw_data or (isinstance(raw_data, dict) and raw_data.get("success") is False):
                ctx.error(f"{config.site_name} のメッセージ一覧画面への遷移またはデータ取得に失敗しました。")
                sys.exit(1)

            # 3. MessageBatch モデルへ変換・正規化
            if isinstance(raw_data, MessageBatch):
                batch = raw_data
            else:
                raw_dict = dict(raw_data)
                if "source" not in raw_dict:
                    raw_dict["source"] = config.site_id
                if "tab" not in raw_dict:
                    raw_dict["tab"] = tab
                if "tab_label" not in raw_dict:
                    raw_dict["tab_label"] = tab_label
                if not raw_dict.get("url"):
                    raw_dict["url"] = target_url

                if config.parse_batch_fn:
                    parsed_batch = config.parse_batch_fn(raw_dict)
                    if isinstance(parsed_batch, MessageBatch):
                        batch = parsed_batch
                    else:
                        raw_dict = dict(parsed_batch)
                        batch = MessageBatch.model_validate(raw_dict)
                else:
                    if config.parse_item_fn and "messages" in raw_dict and isinstance(raw_dict["messages"], list):
                        new_msgs: list[Any] = []
                        for m in raw_dict["messages"]:
                            parsed_item = config.parse_item_fn(m)
                            new_msgs.append(parsed_item)
                        raw_dict["messages"] = new_msgs

                    batch = MessageBatch.model_validate(raw_dict)

            # 件数制限（--limit）の適用
            if args.limit and args.limit > 0 and len(batch.messages) > args.limit:
                batch.messages = batch.messages[: args.limit]
                batch.fetched_count = len(batch.messages)

            update_profile_last_used(args.session)

            # 4. ファイル保存
            saved_paths: list[Path] = []
            if not args.no_save:
                saved_paths = save_message_batch(batch, pipeline_ctx)
                if saved_paths:
                    ctx.add_result_paths(saved_paths)

            # 5. 結果出力 (規約準拠)
            def summary_fn() -> None:
                if config.custom_summary_fn:
                    config.custom_summary_fn(batch, pipeline_ctx)
                else:
                    print_message_summary(batch, config)
                if saved_paths:
                    ctx.log("\n[保存完了]")
                    for p in saved_paths:
                        ctx.log(f"  {to_relative_path(p)}")

            return ctx.flush_outputs(summary_fn=summary_fn, json_data=batch.to_dict())

        finally:
            if not args.keep_open:
                run_playwright_cmd([f"-s={args.session}", "close"], timeout=10)
