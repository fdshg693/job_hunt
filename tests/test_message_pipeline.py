"""メッセージ取得共通実行パイプライン（message_pipeline.py）の単体テスト."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.crawlers.message_pipeline import (
    MessageCrawlerConfig,
    MessagePipelineContext,
    build_message_parser,
    generate_message_markdown,
    print_message_summary,
    run_message_pipeline,
    save_message_batch,
)
from scripts.common.models.message import MessageBatch, MessageItem


class TestMessagePipelineMarkdownAndSummary(unittest.TestCase):
    def setUp(self):
        self.config = MessageCrawlerConfig(
            site_id="test_site",
            site_name="テストサイト",
            auth_site="bizreach",
            default_output_dir=Path("/tmp/test_messages"),
            tab_url_map={"all": "https://example.com/messages"},
            tab_label_map={"all": "すべて"},
            default_tab="all",
        )

    def test_generate_message_markdown_default(self):
        now = datetime(2026, 10, 24, 12, 30, 0)
        batch = MessageBatch(
            source="test_site",
            tab="all",
            tab_label="すべて",
            url="https://example.com/messages",
            total_count=1,
            messages=[
                MessageItem(
                    id="m-1",
                    company="株式会社ABC",
                    sender="人事部",
                    subject="面談のお願い",
                    body="ぜひお話ししたいです。",
                    url="https://example.com/threads/1",
                    job_url="https://example.com/jobs/1",
                    scout_type="プラチナ",
                    is_unread=True,
                )
            ],
        )

        md = generate_message_markdown(batch, self.config, now)
        self.assertIn("source: test_site", md)
        self.assertIn("tab: all", md)
        self.assertIn("tab_label: 'すべて'", md)
        self.assertIn("total_count: 1", md)
        self.assertIn("# テストサイト メッセージ・スカウト一覧 [すべて] (2026-10-24 12時)", md)
        self.assertIn("| 1 | 未読 | プラチナ | 株式会社ABC | 面談のお願い |", md)
        self.assertIn("### 1. 株式会社ABC - 面談のお願い", md)
        self.assertIn("- **状態**: 未読", md)
        self.assertIn("- **スカウト種別**: プラチナ", md)
        self.assertIn("ぜひお話ししたいです。", md)

    def test_generate_message_markdown_empty(self):
        now = datetime(2026, 10, 24, 12, 0, 0)
        batch = MessageBatch(
            source="test_site",
            tab="all",
            tab_label="すべて",
            url="https://example.com/messages",
            total_count=0,
            messages=[],
        )
        md = generate_message_markdown(batch, self.config, now)
        self.assertIn("現在、受信したメッセージ・スカウトはありません。", md)

    def test_generate_message_markdown_custom_hooks(self):
        now = datetime(2026, 10, 24, 12, 0, 0)
        custom_config = MessageCrawlerConfig(
            site_id="test_site",
            site_name="テストサイト",
            auth_site="bizreach",
            default_output_dir=Path("/tmp/test_messages"),
            markdown_table_columns=["番号", "カスタム会社", "カスタム件名"],
            markdown_table_row_fn=lambda m, idx: [str(idx), f"Custom_{m.company}", m.subject],
            markdown_detail_item_fn=lambda m, idx: [f"### [Custom] {idx}: {m.company}", f"- CustomBody: {m.body}"],
        )
        batch = MessageBatch(
            source="test_site",
            tab="all",
            messages=[
                MessageItem(
                    company="ABC社",
                    subject="オファー",
                    body="本文内容",
                )
            ],
        )
        md = generate_message_markdown(batch, custom_config, now)
        self.assertIn("| 番号 | カスタム会社 | カスタム件名 |", md)
        self.assertIn("| 1 | Custom_ABC社 | オファー |", md)
        self.assertIn("### [Custom] 1: ABC社", md)
        self.assertIn("- CustomBody: 本文内容", md)


class TestMessagePipelineSaving(unittest.TestCase):
    def test_save_hourly_mode(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)
            config = MessageCrawlerConfig(
                site_id="bizreach",
                site_name="ビズリーチ",
                auth_site="bizreach",
                default_output_dir=out_dir,
                save_mode="hourly",
            )
            now = datetime(2026, 10, 24, 15, 0, 0)
            batch = MessageBatch(source="bizreach", tab="all", messages=[])
            args = MagicMock()
            args.output_dir = out_dir
            ctx = MessagePipelineContext(
                config=config,
                args=args,
                entrypoint_ctx=MagicMock(),
                tab="all",
                tab_label="すべて",
                target_url="https://example.com",
                session="job-hunt",
                profile_dir=out_dir,
                now=now,
            )

            saved = save_message_batch(batch, ctx)
            self.assertEqual(len(saved), 2)
            self.assertTrue(saved[0].name.endswith("_all.md"))
            self.assertTrue(saved[1].name.endswith("_all.json"))
            self.assertTrue(saved[0].exists())
            self.assertTrue(saved[1].exists())

    def test_save_latest_and_history_mode(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)
            config = MessageCrawlerConfig(
                site_id="forkwell",
                site_name="Forkwell",
                auth_site="forkwell",
                default_output_dir=out_dir,
                save_mode="latest_and_history",
            )
            now = datetime(2026, 10, 24, 15, 30, 45)
            batch = MessageBatch(source="forkwell", tab="active", messages=[])
            args = MagicMock()
            args.output_dir = out_dir
            ctx = MessagePipelineContext(
                config=config,
                args=args,
                entrypoint_ctx=MagicMock(),
                tab="active",
                tab_label="スカウト",
                target_url="https://example.com",
                session="job-hunt",
                profile_dir=out_dir,
                now=now,
            )

            saved = save_message_batch(batch, ctx)
            self.assertEqual(len(saved), 3)
            latest_md = out_dir / "messages_active.md"
            latest_json = out_dir / "messages_active.json"
            history_dir = out_dir / "history"
            self.assertTrue(latest_md.exists())
            self.assertTrue(latest_json.exists())
            self.assertTrue(history_dir.exists())
            self.assertTrue(any(f.name.startswith("messages_active_") for f in history_dir.glob("*.md")))


class TestMessagePipelineExecution(unittest.TestCase):
    @patch("scripts.common.crawlers.message_pipeline.run_playwright_cmd")
    @patch("scripts.common.crawlers.message_pipeline.update_profile_last_used")
    @patch("scripts.common.crawlers.message_pipeline.ensure_site_authenticated")
    def test_run_message_pipeline_success(
        self,
        mock_auth: MagicMock,
        mock_update: MagicMock,
        mock_pw: MagicMock,
    ):
        mock_auth.return_value = True

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)

            def dummy_fetch(ctx: MessagePipelineContext):
                return {
                    "totalCount": 3,
                    "messages": [
                        {
                            "companyName": "企業A",
                            "subject": "スカウト1",
                            "isUnread": True,
                        },
                        {
                            "companyName": "企業B",
                            "subject": "スカウト2",
                            "isUnread": False,
                        },
                        {
                            "companyName": "企業C",
                            "subject": "スカウト3",
                            "isUnread": False,
                        },
                    ],
                }

            config = MessageCrawlerConfig(
                site_id="test_site",
                site_name="テストサイト",
                auth_site="bizreach",
                default_output_dir=out_dir,
                tab_url_map={"all": "https://example.com"},
                tab_label_map={"all": "すべて"},
                custom_fetch_fn=dummy_fetch,
            )

            # limit 2 で実行
            exit_code = run_message_pipeline(config, argv=["--limit", "2", "-o", str(out_dir)])
            self.assertEqual(exit_code, 0)
            mock_auth.assert_called_once()
            mock_update.assert_called_once()
            mock_pw.assert_called_once_with(["-s=job-hunt", "close"], timeout=10)

            # 保存されたファイルを確認
            saved_mds = list(out_dir.glob("*.md"))
            self.assertEqual(len(saved_mds), 1)
            content = saved_mds[0].read_text(encoding="utf-8")
            self.assertIn("企業A", content)
            self.assertIn("企業B", content)
            self.assertNotIn("企業C", content)  # limit=2 で切り詰められていること

    @patch("scripts.common.crawlers.message_pipeline.run_playwright_cmd")
    @patch("scripts.common.crawlers.message_pipeline.ensure_site_authenticated")
    def test_run_message_pipeline_fetch_fail(
        self,
        mock_auth: MagicMock,
        mock_pw: MagicMock,
    ):
        mock_auth.return_value = True

        def fail_fetch(ctx: MessagePipelineContext):
            return {"success": False, "error": "Fetch failed"}

        config = MessageCrawlerConfig(
            site_id="test_site",
            site_name="テストサイト",
            auth_site="bizreach",
            default_output_dir=Path("/tmp/test"),
            custom_fetch_fn=fail_fetch,
        )

        with self.assertRaises(SystemExit) as cm:
            run_message_pipeline(config, argv=[])
        self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
