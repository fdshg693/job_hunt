"""全サイト メッセージ共通パイプライン移行検証テスト (test_messages_pipeline_rollout.py).

Step 4 で横展開した6サイト（Bizreach, Findy, Levtech Direct, OpenWork, LinkedIn, YOUTRUST）
のメッセージスクレイパーが、共通パイプライン・Pydanticモデル・フォーマット生成・ファイル永続化と正常に連携することを検証します。
"""

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

from scripts.bizreach.navigate_messages import (
    CONFIG as BIZREACH_CONFIG,
    generate_markdown as bizreach_generate_markdown,
    print_formatted_summary as bizreach_print_summary,
    save_messages_result as bizreach_save_messages,
)
from scripts.common.crawlers.message_pipeline import run_message_pipeline
from scripts.common.models.message import MessageBatch, MessageItem
from scripts.findy.navigate_messages import (
    CONFIG as FINDY_CONFIG,
    generate_markdown as findy_generate_markdown,
    print_formatted_summary as findy_print_summary,
    save_messages_result as findy_save_messages,
)
from scripts.levtech_direct.navigate_messages import (
    CONFIG as LEVTECH_CONFIG,
    generate_markdown as levtech_generate_markdown,
    print_formatted_summary as levtech_print_summary,
    save_messages_result as levtech_save_messages,
)
from scripts.linkedin.navigate_messages import (
    CONFIG as LINKEDIN_CONFIG,
    generate_markdown as linkedin_generate_markdown,
    print_formatted_summary as linkedin_print_summary,
    save_messages_result as linkedin_save_messages,
)
from scripts.openwork.navigate_messages import (
    CONFIG as OPENWORK_CONFIG,
    generate_markdown as openwork_generate_markdown,
    print_formatted_summary as openwork_print_summary,
    save_messages_result as openwork_save_messages,
)
from scripts.youtrust.navigate_messages import (
    CONFIG as YOUTRUST_CONFIG,
    generate_markdown as youtrust_generate_markdown,
    print_formatted_summary as youtrust_print_summary,
    save_messages_result as youtrust_save_messages,
)


class TestMessagesPipelineRollout(unittest.TestCase):
    """6サイトの共通パイプライン移行テスト."""

    def setUp(self):
        self.now = datetime(2026, 10, 24, 15, 30, 0)

    def test_bizreach_pipeline(self):
        sample_data = {
            "url": "https://www.bizreach.jp/messages/",
            "totalCount": 1,
            "messages": [
                {
                    "sender": "エージェント田中",
                    "subject": "外資系テックリード求人のご案内",
                    "date": "2026/10/24 10:00",
                    "url": "https://www.bizreach.jp/messages/12345",
                    "scoutType": "プラチナスカウト",
                    "isUnread": True,
                    "snippet": "ご経歴を拝見し...",
                    "attachedJobs": [
                        {
                            "title": "Principal Engineer",
                            "company": "グローバルテック株式会社",
                            "salary": "1,500万円〜2,000万円",
                            "url": "https://www.bizreach.jp/jobs/9999",
                        }
                    ],
                }
            ],
        }

        # 1. Markdown生成検証
        md = bizreach_generate_markdown(sample_data, "direct", self.now)
        self.assertIn("source: bizreach", md)
        self.assertIn("tab: direct", md)
        self.assertIn("エージェント田中", md)
        self.assertIn("外資系テックリード求人のご案内", md)
        self.assertIn("Principal Engineer", md)
        self.assertIn("1,500万円〜2,000万円", md)

        # 2. サマリ出力検証
        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            bizreach_print_summary(sample_data, tab="direct")
        output = stdout_buf.getvalue()
        self.assertIn("ビズリーチ メッセージ・スカウト一覧", output)
        self.assertIn("エージェント田中", output)
        self.assertIn("Principal Engineer", output)

        # 3. 保存処理検証
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            md_path, json_path = bizreach_save_messages(sample_data, tab="direct", output_dir=tmp_path, now=self.now)
            self.assertTrue(md_path.exists())
            self.assertTrue(json_path.exists())
            self.assertEqual(md_path.name, "2026-10-24-15_direct.md")
            self.assertEqual(json_path.name, "2026-10-24-15_direct.json")

    def test_findy_pipeline(self):
        sample_data = {
            "url": "https://findy-code.io/matches",
            "totalCount": 1,
            "messages": [
                {
                    "company": "Findyテスト企業",
                    "subject": "開発マネージャーのポジション",
                    "date": "2026-10-24",
                    "url": "https://findy-code.io/matches/555",
                    "jobUrl": "https://findy-code.io/jobs/777",
                    "scoutType": "プレミアム",
                    "isUnread": True,
                    "isReplied": False,
                    "snippet": "弊社のCTOより直接スカウトです",
                    "latestMessage": "弊社のCTOより直接スカウトです。ぜひカジュアル面談を...",
                }
            ],
        }

        # 1. Markdown生成検証
        md = findy_generate_markdown(sample_data, "all", self.now)
        self.assertIn("source: findy", md)
        self.assertIn("Findyテスト企業", md)
        self.assertIn("開発マネージャーのポジション", md)
        self.assertIn("弊社のCTOより直接スカウトです", md)

        # 2. サマリ出力検証
        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            findy_print_summary(sample_data, tab="all")
        output = stdout_buf.getvalue()
        self.assertIn("Findy メッセージ・スカウト一覧", output)
        self.assertIn("Findyテスト企業", output)

        # 3. 保存処理検証
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            paths = findy_save_messages(sample_data, tab="all", output_dir=tmp_path, now=self.now)
            self.assertEqual(len(paths), 3)
            self.assertTrue((tmp_path / "messages_all.md").exists())
            self.assertTrue((tmp_path / "messages_all.json").exists())

    def test_levtech_direct_pipeline(self):
        sample_data = {
            "url": "https://levtech-direct.jp/mypage/message",
            "totalCount": 1,
            "messages": [
                {
                    "company": "レバテック提携企業",
                    "subject": "フルスタックエンジニア募集",
                    "date": "2026/10/24",
                    "threadUrl": "https://levtech-direct.jp/mypage/message/888",
                    "jobUrl": "https://levtech-direct.jp/jobs/999",
                    "jobTitle": "シニアエンジニア",
                    "jobSalary": "900万〜1300万",
                    "badges": ["急募", "フルリモート"],
                    "body": "ぜひ一度お話ししませんか？",
                }
            ],
        }

        # 1. Markdown生成検証
        md = levtech_generate_markdown(sample_data, "active", self.now)
        self.assertIn("source: levtech_direct", md)
        self.assertIn("レバテック提携企業", md)
        self.assertIn("シニアエンジニア", md)
        self.assertIn("急募 / フルリモート", md)

        # 2. サマリ出力検証
        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            levtech_print_summary(sample_data, tab="active")
        output = stdout_buf.getvalue()
        self.assertIn("レバテックダイレクト メッセージ・スカウト一覧", output)
        self.assertIn("レバテック提携企業", output)
        self.assertIn("シニアエンジニア", output)

        # 3. 保存処理検証
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            paths = levtech_save_messages(sample_data, tab="active", output_dir=tmp_path, now=self.now)
            self.assertEqual(len(paths), 3)
            self.assertTrue((tmp_path / "messages_active.md").exists())
            self.assertTrue((tmp_path / "messages_active.json").exists())

    def test_openwork_pipeline(self):
        sample_data = {
            "url": "https://www.openwork.jp/job_apply_list",
            "totalCount": 1,
            "messages": [
                {
                    "company": "オープンワーク評価企業",
                    "subject": "WEB面談のご案内",
                    "date": "2026-10-24 12:00",
                    "deadline": "2026-10-31",
                    "url": "https://www.openwork.jp/job_apply_list/111",
                    "scoutType": "特別スカウト",
                    "isUnread": False,
                    "snippet": "評価スコアの高い企業です",
                }
            ],
        }

        # 1. Markdown生成検証
        md = openwork_generate_markdown(sample_data, "company", self.now)
        self.assertIn("source: openwork", md)
        self.assertIn("オープンワーク評価企業", md)
        self.assertIn("WEB面談のご案内", md)
        self.assertIn("2026-10-31", md)

        # 2. サマリ出力検証
        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            openwork_print_summary(sample_data, tab="company")
        output = stdout_buf.getvalue()
        self.assertIn("OpenWork メッセージ・スカウト一覧", output)
        self.assertIn("オープンワーク評価企業", output)

        # 3. 保存処理検証
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            md_path, json_path = openwork_save_messages(sample_data, tab="company", output_dir=tmp_path, now=self.now)
            self.assertTrue(md_path.exists())
            self.assertTrue(json_path.exists())
            self.assertEqual(md_path.name, "2026-10-24-15_company.md")

    def test_linkedin_pipeline(self):
        sample_data = {
            "url": "https://www.linkedin.com/messaging/?filter=job",
            "totalCount": 1,
            "messages": [
                {
                    "name": "Recruiter Alice",
                    "date": "Oct 24",
                    "label": "Jobs",
                    "unread": True,
                    "starred": True,
                    "snippet": "We have an exciting opportunity for Staff Engineer.",
                    "threadUrl": "https://www.linkedin.com/messaging/thread/333",
                    "thread": [
                        {
                            "sender": "Recruiter Alice",
                            "day": "Today",
                            "time": "14:00",
                            "text": "Hi, I found your profile impressive!",
                        }
                    ],
                }
            ],
        }

        # 1. Markdown生成検証
        md = linkedin_generate_markdown(sample_data, status="Focused", filter_name="Jobs", now=self.now)
        self.assertIn("source: linkedin", md)
        self.assertIn("Recruiter Alice", md)
        self.assertIn("Jobs", md)
        self.assertIn("Hi, I found your profile impressive!", md)

        # 2. サマリ出力検証
        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            linkedin_print_summary(sample_data, status="Focused", filter_name="Jobs")
        output = stdout_buf.getvalue()
        self.assertIn("LinkedIn メッセージ", output)
        self.assertIn("Recruiter Alice", output)

        # 3. 保存処理検証
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            paths = linkedin_save_messages(sample_data, status="Focused", filter_name="Jobs", output_dir=tmp_path, now=self.now)
            self.assertEqual(len(paths), 3)
            self.assertTrue((tmp_path / "messages_focused_jobs.md").exists())
            self.assertTrue((tmp_path / "messages_focused_jobs.json").exists())

    def test_youtrust_pipeline(self):
        sample_data = {
            "url": "https://youtrust.jp/chat_rooms",
            "totalCount": 1,
            "rooms": [
                {
                    "id": "room_xyz",
                    "displayName": "山田 太郎（株式会社ユートラ）",
                    "chatRoomType": "scout",
                    "unreadCount": 2,
                    "isBookmarked": True,
                    "isArchived": False,
                    "lastCommentedAt": 1761280000,
                    "lastCommentContent": "スカウトを送らせていただきました。",
                    "otherUser": {
                        "name": "山田 太郎",
                        "companyName": "株式会社ユートラ",
                        "jobCategories": ["人事", "採用担当"],
                        "skills": ["スカウト", "採用広報"],
                        "introduction": "ユートラ採用責任者です。",
                    },
                    "thread": [
                        {
                            "sender": {"name": "山田 太郎"},
                            "createdAt": 1761280000,
                            "comment": "ぜひお話しさせてください！",
                        }
                    ],
                }
            ],
        }

        # 1. Markdown生成検証
        md = youtrust_generate_markdown(sample_data, box_type="scout", now=self.now)
        self.assertIn("source: youtrust", md)
        self.assertIn("山田 太郎", md)
        self.assertIn("株式会社ユートラ", md)
        self.assertIn("ぜひお話しさせてください！", md)

        # 2. サマリ出力検証
        stdout_buf = io.StringIO()
        with patch("sys.stdout", stdout_buf):
            youtrust_print_summary(sample_data, box_type="scout")
        output = stdout_buf.getvalue()
        self.assertIn("YOUTRUST チャットルーム・メッセージ一覧", output)
        self.assertIn("山田 太郎", output)

        # 3. 保存処理検証
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            paths = youtrust_save_messages(sample_data, box_type="scout", output_dir=tmp_path, now=self.now)
            self.assertTrue((tmp_path / "messages_scout.md").exists())
            self.assertTrue((tmp_path / "messages_scout.json").exists())
            self.assertTrue((tmp_path / "rooms" / "room_xyz.md").exists())
            self.assertTrue((tmp_path / "rooms" / "room_xyz.json").exists())


if __name__ == "__main__":
    unittest.main()
