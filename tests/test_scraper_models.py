"""スクレイパー共通データモデル（MessageItem, MessageBatch, JobPosting）の単体テスト."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.models import JobPosting, MessageBatch, MessageItem
from scripts.common.storage import JobData


class TestMessageModels(unittest.TestCase):
    def test_message_item_snake_case(self):
        item = MessageItem(
            id="msg-123",
            sender="山田太郎",
            company="テスト株式会社",
            subject="カジュアル面談のご案内",
            body="本文です",
            snippet="本文抜粋",
            url="https://example.com/messages/123",
            date="2026-10-24T10:00:00+09:00",
            is_unread=True,
            scout_type="プラチナスカウト",
            deadline="2026-11-01",
            job_url="https://example.com/jobs/456",
            job_title="バックエンドエンジニア",
        )
        self.assertEqual(item.id, "msg-123")
        self.assertEqual(item.sender, "山田太郎")
        self.assertEqual(item.company, "テスト株式会社")
        self.assertTrue(item.is_unread)
        self.assertEqual(item.scout_type, "プラチナスカウト")

        d = item.to_dict()
        self.assertEqual(d["isUnread"], True)
        self.assertEqual(d["is_unread"], True)
        self.assertEqual(d["scoutType"], "プラチナスカウト")
        self.assertEqual(d["jobUrl"], "https://example.com/jobs/456")

    def test_message_item_camel_case_normalization(self):
        raw_dict = {
            "id": 473161,
            "senderName": "採用担当",
            "companyName": "株式会社テスト",
            "subject": "スカウトです",
            "snippet": "抜粋文...",
            "latestMessage": "最新メッセージ本文",
            "threadUrl": "https://example.com/threads/473161",
            "isUnread": True,
            "scoutType": "面談確約",
            "jobUrl": "https://example.com/jobs/999",
            "jobTitle": "Tech Lead",
            "sentAt": "2026-10-20",
            "attachedJobs": [{"title": "求人1"}],
            "badges": ["急募", "リモート"],
        }
        item = MessageItem.model_validate(raw_dict)
        self.assertEqual(item.id, 473161)
        self.assertEqual(item.sender, "採用担当")
        self.assertEqual(item.company, "株式会社テスト")
        self.assertEqual(item.body, "最新メッセージ本文")
        self.assertEqual(item.url, "https://example.com/threads/473161")
        self.assertTrue(item.is_unread)
        self.assertEqual(item.scout_type, "面談確約")
        self.assertEqual(item.job_url, "https://example.com/jobs/999")
        self.assertEqual(item.job_title, "Tech Lead")
        self.assertEqual(item.date, "2026-10-20")

        # 未知のフィールドが extra_metadata に退避されていること
        self.assertIn("attachedJobs", item.extra_metadata)
        self.assertIn("badges", item.extra_metadata)
        self.assertEqual(len(item.extra_metadata["attachedJobs"]), 1)

        # to_dict で extra_metadata も出力に含まれること
        d = item.to_dict()
        self.assertIn("attachedJobs", d)
        self.assertIn("badges", d)
        self.assertEqual(d["isUnread"], True)
        self.assertEqual(d["latestMessage"], "最新メッセージ本文")

    def test_message_batch(self):
        raw_batch = {
            "source": "bizreach",
            "tab": "scout",
            "tab_label": "スカウト",
            "url": "https://example.com/bizreach/messages",
            "totalCount": 10,
            "fetchedCount": 1,
            "messages": [
                {
                    "subject": "ビズリーチ案件",
                    "company": "大手IT",
                    "isUnread": False,
                }
            ],
            "customHeader": "テスト値",
        }
        batch = MessageBatch.model_validate(raw_batch)
        self.assertEqual(batch.source, "bizreach")
        self.assertEqual(batch.total_count, 10)
        self.assertEqual(batch.fetched_count, 1)
        self.assertEqual(len(batch.messages), 1)
        self.assertEqual(batch.messages[0].subject, "ビズリーチ案件")
        self.assertEqual(batch.extra_metadata.get("customHeader"), "テスト値")

        d = batch.to_dict()
        self.assertEqual(d["source"], "bizreach")
        self.assertEqual(d["totalCount"], 10)
        self.assertEqual(d["fetchedCount"], 1)
        self.assertEqual(len(d["messages"]), 1)
        self.assertEqual(d.get("customHeader"), "テスト値")


class TestJobPostingModel(unittest.TestCase):
    def test_job_posting_and_job_data_roundtrip(self):
        job_data = JobData(
            id="job-abc",
            source="findy",
            company="サンプル株式会社",
            title="シニアエンジニア",
            url="https://findy-code.io/jobs/job-abc",
            salary_min=8000000,
            salary_max=12000000,
            salary_text="800万〜1200万円",
            skills=["Python", "Go", "Kubernetes"],
            job_roles=["バックエンドエンジニア"],
            location="東京都渋谷区",
            remote_type="フルリモート",
            tags=["急募", "自社プロダクト"],
            company_url="https://sample.example.com",
            description="サービスのバックエンド開発を担当していただきます。",
            must_skills="Python実務経験3年以上",
            desired_skills="Kubernetes運用経験",
            development_environment="AWS, GitHub Actions, Docker",
            rewarding="裁量権が大きい環境です",
            personality="自走できる方",
            conditions="フレックスタイム制",
            extra_metadata={"custom_flag": True, "score": 95},
        )

        # JobData -> JobPosting
        posting = JobPosting.from_job_data(job_data)
        self.assertEqual(posting.id, "job-abc")
        self.assertEqual(posting.source, "findy")
        self.assertEqual(posting.skills, ["Python", "Go", "Kubernetes"])
        self.assertEqual(posting.salary_min, 8000000)
        self.assertEqual(posting.extra_metadata["custom_flag"], True)

        # Markdown / Frontmatter の一致確認
        self.assertEqual(posting.to_frontmatter_dict(), job_data.to_frontmatter_dict())
        self.assertEqual(posting.to_markdown(), job_data.to_markdown())
        self.assertEqual(posting.to_dict(), job_data.to_dict())

        # JobPosting -> JobData
        restored_job_data = posting.to_job_data()
        self.assertEqual(restored_job_data.id, job_data.id)
        self.assertEqual(restored_job_data.salary_max, job_data.salary_max)
        self.assertEqual(restored_job_data.skills, job_data.skills)
        self.assertEqual(restored_job_data.extra_metadata, job_data.extra_metadata)
        self.assertEqual(restored_job_data.to_markdown(), job_data.to_markdown())


if __name__ == "__main__":
    unittest.main()
