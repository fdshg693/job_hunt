"""Forkwell & Green メッセージ共通パイプライン移行単体テスト (test_pilot_messages_migration.py)."""

from __future__ import annotations

import io
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

from scripts.forkwell.navigate_messages import (
    CONFIG as FORKWELL_CONFIG,
    generate_markdown as forkwell_generate_markdown,
    print_formatted_summary as forkwell_print_summary,
)
from scripts.green.navigate_messages import (
    CONFIG as GREEN_CONFIG,
    generate_markdown as green_generate_markdown,
    generate_thread_markdown as green_generate_thread_markdown,
    print_formatted_summary as green_print_summary,
    print_thread_detail_summary as green_print_thread_summary,
)
from scripts.common.crawlers.message_pipeline import run_message_pipeline
from scripts.common.models.message import MessageBatch, MessageItem


class TestForkwellMessageMigration(unittest.TestCase):
    """Forkwellメッセージパイプライン移行のテスト."""

    def setUp(self):
        self.sample_forkwell_data = {
            "success": True,
            "url": "https://jobs.forkwell.com/inbox",
            "totalCount": 2,
            "messages": [
                {
                    "company": "株式会社サンプル",
                    "subject": "エンジニア採用のご案内",
                    "statusText": "返信待ち",
                    "deadline": "2026/11/01",
                    "jobTitle": "Pythonテックリード",
                    "jobSalary": "800万円〜1200万円",
                    "jobRole": "バックエンドエンジニア",
                    "jobUrl": "https://jobs.forkwell.com/sample/jobs/101",
                    "threadUrl": "https://jobs.forkwell.com/inbox/101",
                    "scoutType": "プラチナスカウト",
                    "badges": ["急募", "フルリモート"],
                    "body": "貴殿のプロフィールを拝見し、ぜひお話ししたくご連絡いたしました。",
                },
                {
                    "company": "テスト合同会社",
                    "subject": "カジュアル面談のお誘い",
                    "statusText": "辞退済",
                    "jobTitle": "フルスタックエンジニア",
                    "threadUrl": "https://jobs.forkwell.com/inbox/102",
                    "snippet": "弊社の新規事業チームにおいて...",
                },
            ],
        }

    def test_forkwell_markdown_generation(self):
        now = datetime(2026, 10, 24, 15, 0, 0)
        batch = MessageBatch.model_validate({
            "source": "forkwell",
            "tab": "active",
            "tab_label": "スカウト・やりとり",
            "url": "https://jobs.forkwell.com/inbox",
            **self.sample_forkwell_data,
        })
        md = forkwell_generate_markdown(batch, "active", now)

        self.assertIn("source: forkwell", md)
        self.assertIn("tab: active", md)
        self.assertIn("tab_label: 'スカウト・やりとり'", md)
        self.assertIn("total_count: 2", md)
        self.assertIn("# Forkwell メッセージ・スカウト一覧 [スカウト・やりとり] (2026-10-24 15時)", md)
        self.assertIn("| # | 種別/バッジ | 企業名 | 件名 | ステータス/期限 | 求人URL | スレッドURL |", md)
        self.assertIn("急募 / フルリモート", md)
        self.assertIn("株式会社サンプル", md)
        self.assertIn("Pythonテックリード", md)
        self.assertIn("貴殿のプロフィールを拝見し", md)

    def test_forkwell_summary_output(self):
        batch = MessageBatch.model_validate({
            "source": "forkwell",
            "tab": "active",
            **self.sample_forkwell_data,
        })
        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            forkwell_print_summary(batch, tab="active")

        output = stdout_buf.getvalue()
        self.assertIn("Forkwell メッセージ・スカウト一覧 [スカウト・やりとり]", output)
        self.assertIn("[急募] [フルリモート] 株式会社サンプル | 返信待ち", output)
        self.assertIn("件名:     エンジニア採用のご案内", output)
        self.assertIn("提示年収: 800万円〜1200万円", output)

    @patch("scripts.forkwell.navigate_messages.execute_navigate_messages")
    @patch("scripts.common.crawlers.message_pipeline.ensure_site_authenticated")
    @patch("scripts.common.crawlers.message_pipeline.run_playwright_cmd")
    @patch("scripts.common.crawlers.message_pipeline.update_profile_last_used")
    def test_forkwell_pipeline_run_and_save(
        self,
        mock_update: MagicMock,
        mock_pw: MagicMock,
        mock_auth: MagicMock,
        mock_exec: MagicMock,
    ):
        mock_auth.return_value = True
        mock_exec.return_value = self.sample_forkwell_data

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)

            # --tab archived (archiveに正規化されること)
            exit_code = run_message_pipeline(
                FORKWELL_CONFIG,
                argv=["--tab", "archived", "-o", str(out_dir)],
            )
            self.assertEqual(exit_code, 0)
            mock_auth.assert_called_once()
            mock_exec.assert_called_once_with(
                session="job-hunt",
                tab="archive",
                limit=0,
                no_details=False,
                timeout=120,
            )

            # latest_and_history のファイル存在確認
            latest_md = out_dir / "messages_archive.md"
            latest_json = out_dir / "messages_archive.json"
            history_dir = out_dir / "history"

            self.assertTrue(latest_md.exists(), "latest messages_archive.md が生成されていること")
            self.assertTrue(latest_json.exists(), "latest messages_archive.json が生成されていること")
            self.assertTrue(history_dir.exists(), "history ディレクトリが生成されていること")
            history_files = list(history_dir.glob("messages_archive_*.md"))
            self.assertGreater(len(history_files), 0, "history mdファイルが保存されていること")

            # 内容確認
            md_text = latest_md.read_text(encoding="utf-8")
            self.assertIn("株式会社サンプル", md_text)
            self.assertIn("tab: archive", md_text)


class TestGreenMessageMigration(unittest.TestCase):
    """Greenメッセージパイプライン移行のテスト."""

    def setUp(self):
        self.sample_green_data = {
            "success": True,
            "url": "https://www.green-japan.com/messages/v2",
            "totalCount": 2,
            "messages": [
                {
                    "threadId": "green-1001",
                    "type": "company",
                    "scoutType": "気になる",
                    "company": "GreenIT株式会社",
                    "senderName": "採用担当 佐藤",
                    "subject": "サーバーサイド開発の募集",
                    "jobTitle": "Go/Pythonエンジニア",
                    "salary": "700〜1000万円",
                    "threadUrl": "https://www.green-japan.com/messages/v2/threads/green-1001",
                    "attachedJob": {
                        "url": "https://www.green-japan.com/job/1001",
                        "rawText": "Go言語を用いたマイクロサービス開発",
                    },
                    "messages": [
                        {
                            "sentAt": "2026/10/24 10:00",
                            "body": "あなたの経歴に興味を持ちました。ぜひ一度お話ししませんか？",
                        }
                    ],
                },
                {
                    "threadId": "green-1002",
                    "type": "agent",
                    "scoutType": "スカウト",
                    "company": "キャリアエージェント",
                    "senderName": "コンサルタント 鈴木",
                    "subject": "大手SaaS企業のご紹介",
                    "threadUrl": "https://www.green-japan.com/messages/v2/threads/green-1002",
                },
            ],
        }

    def test_green_markdown_generation(self):
        now = datetime(2026, 10, 24, 15, 30, 0)
        batch = MessageBatch.model_validate({
            "source": "green",
            "tab": "all",
            "tab_label": "すべて（企業＋エージェント）",
            "url": "https://www.green-japan.com/messages/v2",
            **self.sample_green_data,
        })
        md = green_generate_markdown(batch, "all", now)

        self.assertIn("source: green", md)
        self.assertIn("tab: all", md)
        self.assertIn("tab_label: 'すべて（企業＋エージェント）'", md)
        self.assertIn("total_count: 2", md)
        self.assertIn("# Green メッセージ・スカウト一覧 (すべて（企業＋エージェント）)", md)
        self.assertIn("### 1. [企業] `気になる` GreenIT株式会社 (採用担当 佐藤)", md)
        self.assertIn("- **スレッドID**: `green-1001`", md)
        self.assertIn("- **想定年収**: 700〜1000万円", md)
        self.assertIn("あなたの経歴に興味を持ちました", md)

    def test_green_thread_detail_markdown(self):
        now = datetime(2026, 10, 24, 15, 30, 0)
        thread = self.sample_green_data["messages"][0]
        md = green_generate_thread_markdown(thread, now)

        self.assertIn("source: green", md)
        self.assertIn("type: message_thread", md)
        self.assertIn("thread_id: 'green-1001'", md)
        self.assertIn("message_count: 1", md)
        self.assertIn("# Green スレッド詳細 (ID: green-1001)", md)
        self.assertIn("Go言語を用いたマイクロサービス開発", md)
        self.assertIn("### メッセージ #1 (2026/10/24 10:00)", md)

    @patch("scripts.green.navigate_messages.run_navigate")
    @patch("scripts.common.crawlers.message_pipeline.ensure_site_authenticated")
    @patch("scripts.common.crawlers.message_pipeline.run_playwright_cmd")
    @patch("scripts.common.crawlers.message_pipeline.update_profile_last_used")
    def test_green_pipeline_list_with_details(
        self,
        mock_update: MagicMock,
        mock_pw: MagicMock,
        mock_auth: MagicMock,
        mock_nav: MagicMock,
    ):
        mock_auth.return_value = True
        mock_nav.return_value = self.sample_green_data

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)

            # --details を付けて実行
            exit_code = run_message_pipeline(
                GREEN_CONFIG,
                argv=["--tab", "all", "--details", "-o", str(out_dir)],
            )
            self.assertEqual(exit_code, 0)
            mock_nav.assert_called_once_with(
                session="job-hunt",
                tab="all",
                limit=0,
                fetch_details=True,
                thread_id=None,
                timeout=120,
            )

            # 保存されたファイルを確認
            list_mds = list(out_dir.glob("*_messages_all.md"))
            list_jsons = list(out_dir.glob("*_messages_all.json"))
            self.assertEqual(len(list_mds), 1)
            self.assertEqual(len(list_jsons), 1)

            # threads 配下のファイルを確認
            threads_dir = out_dir / "threads"
            self.assertTrue(threads_dir.exists())
            thread_md = threads_dir / "green-1001.md"
            thread_json = threads_dir / "green-1001.json"
            self.assertTrue(thread_md.exists())
            self.assertTrue(thread_json.exists())

    @patch("scripts.green.navigate_messages.run_navigate")
    @patch("scripts.common.crawlers.message_pipeline.ensure_site_authenticated")
    @patch("scripts.common.crawlers.message_pipeline.run_playwright_cmd")
    @patch("scripts.common.crawlers.message_pipeline.update_profile_last_used")
    def test_green_pipeline_single_thread(
        self,
        mock_update: MagicMock,
        mock_pw: MagicMock,
        mock_auth: MagicMock,
        mock_nav: MagicMock,
    ):
        mock_auth.return_value = True
        thread_data = {
            "success": True,
            "threadDetail": self.sample_green_data["messages"][0],
        }
        mock_nav.return_value = thread_data

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)

            exit_code = run_message_pipeline(
                GREEN_CONFIG,
                argv=["--thread-id", "green-1001", "-o", str(out_dir)],
            )
            self.assertEqual(exit_code, 0)
            mock_nav.assert_called_once_with(
                session="job-hunt",
                tab="all",
                limit=0,
                fetch_details=False,
                thread_id="green-1001",
                timeout=120,
            )

            threads_dir = out_dir / "threads"
            thread_md = threads_dir / "green-1001.md"
            thread_json = threads_dir / "green-1001.json"
            self.assertTrue(thread_md.exists())
            self.assertTrue(thread_json.exists())


if __name__ == "__main__":
    unittest.main()
