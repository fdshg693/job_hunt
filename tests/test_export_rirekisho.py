"""履歴書 PDF 出力 (scripts/profile/export_rirekisho.py) の単体テスト（ブラウザは起動しない）."""

import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest import mock

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.profile import export_rirekisho
from scripts.profile.export_rirekisho import age_on, check_leaks, history_rows, render_html, section_text

RESUME_FM = {
    "name": "山田 太郎",
    "birth_date": "1995-04-01",
    "current_annual_income": 5000000,
    "email": "taro@example.com",
    "phone": "090-1234-5678",
}

FM = {
    "name_kana": "やまだ たろう",
    "gender": "",
    "postal_code": "100-0001",
    "address": "東京都千代田区千代田1-1",
    "education": [{"year": 2014, "month": 3, "text": "サンプル高等学校 卒業"}],
    "work": [{"year": 2018, "month": 4, "text": "株式会社サンプル 入社"}],
    "currently_employed": True,
    "licenses": [{"year": 2020, "month": 10, "text": "基本情報技術者試験 合格"}],
}

APPLICATION_BODY = """
# 応募先メモ

## 志望動機

一行目の文です。
二行目の文です。

三行目の文です。

## 本人希望記入欄

職種：バックエンドエンジニアを希望します。
"""


class TestRirekisho(unittest.TestCase):
    def test_age_counts_birthday(self):
        self.assertEqual(age_on(dt.date(1995, 4, 1), dt.date(2026, 3, 31)), 30)
        self.assertEqual(age_on(dt.date(1995, 4, 1), dt.date(2026, 4, 1)), 31)

    def test_history_rows_add_headings_and_end_marks(self):
        texts = [r["text"] for r in history_rows(FM)]
        self.assertEqual(texts[0], "学歴")
        self.assertIn("職歴", texts)
        self.assertLess(texts.index("現在に至る"), texts.index("以上"))
        self.assertEqual(len(texts), export_rirekisho.HISTORY_ROWS)

    def test_history_rows_without_current_job(self):
        texts = [r["text"] for r in history_rows({**FM, "currently_employed": False})]
        self.assertNotIn("現在に至る", texts)

    def test_section_text_keeps_lines(self):
        self.assertEqual(
            section_text(APPLICATION_BODY, "志望動機"), "一行目の文です。\n二行目の文です。\n三行目の文です。"
        )
        self.assertIsNone(section_text(APPLICATION_BODY, "存在しない節"))

    def test_render_includes_personal_fields(self):
        markup = render_html(
            RESUME_FM, FM, motivation="動機<script>", wishes="規定に従います", as_of_day=dt.date(2026, 10, 28)
        )
        self.assertIn("1995年4月1日生（満31歳）", markup)
        self.assertIn("taro@example.com", markup)
        self.assertIn("2026年10月28日現在", markup)
        self.assertNotIn("<script>", markup)

    def test_leak_guard(self):
        with mock.patch.object(
            export_rirekisho, "_internal_fragments", return_value=["これは非公開ファイルにある長い本音の文章です"]
        ):
            clean = render_html(RESUME_FM, FM, motivation="", wishes="", as_of_day=dt.date(2026, 10, 28))
            self.assertEqual(check_leaks(clean, RESUME_FM), [])
            leaked = render_html(
                RESUME_FM,
                FM,
                motivation="年収500万からの転職。これは非公開ファイルにある長い本音の文章です",
                wishes="",
                as_of_day=dt.date(2026, 10, 28),
            )
            found = check_leaks(leaked, RESUME_FM)
        self.assertTrue(any("現在年収" in f for f in found))
        self.assertTrue(any("非公開" in f for f in found))


if __name__ == "__main__":
    unittest.main()
