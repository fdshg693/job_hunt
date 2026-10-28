"""職務経歴書 PDF 出力 (scripts/profile/export_pdf.py) の単体テスト（ブラウザは起動しない）."""

import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest import mock

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.profile import export_pdf
from scripts.profile.export_pdf import check_leaks, render_html, select_sections, split_sections

FM = {
    "name": "山田 太郎",
    "name_en": "Taro Yamada",
    "birth_date": "1995-04-01",
    "current_annual_income": 5000000,
    "email": "taro@example.com",
    "phone": "090-1234-5678",
    "links": {"github": "https://github.com/taro"},
    "primary_skills": ["Python", "Go"],
    "certifications": ["基本情報技術者"],
    "english_skill": "TOEIC 900",
}

BODY = """
# 職務経歴書 (SSOT)

## 基本情報

- 生年月日: 1995年4月1日
- 現在の年収: 500万円
- Email: taro@example.com

---

## 職務要約

バックエンド開発に従事。
---

## 職務経歴

### 1. 株式会社サンプル（2020年4月〜在職中）

#### プロジェクト: API 基盤
- **期間**: 2021年
<script>alert(1)</script>

## 新しく足した節

ここは載らない。
"""

TODAY = dt.date(2026, 10, 19)


def _render(contact: bool = False) -> str:
    sections, _ = select_sections(split_sections(BODY), "ja")
    return render_html(FM, sections, "ja", contact=contact, today=TODAY)


class SectionTest(unittest.TestCase):
    def test_allowlist_keeps_only_known_sections(self) -> None:
        sections, unknown = select_sections(split_sections(BODY), "ja")
        self.assertEqual([s.heading for s in sections], ["職務要約", "職務経歴"])
        # 基本情報は意図的に落とすので警告しない。未知の節だけ警告対象
        self.assertEqual(unknown, ["新しく足した節"])

    def test_rendered_html_excludes_basic_info_and_raw_html(self) -> None:
        markup = _render()
        self.assertNotIn("現在の年収", markup)
        self.assertNotIn("ここは載らない", markup)
        self.assertNotIn("<script>", markup)
        self.assertNotIn("---", markup)  # 段落直後の区切り線が見出しや本文にならない
        self.assertIn("2026年10月19日現在", markup)
        self.assertIn("Python", markup)

    def test_contact_only_when_requested(self) -> None:
        self.assertNotIn("taro@example.com", _render(contact=False))
        self.assertIn("taro@example.com", _render(contact=True))


class LeakGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(export_pdf, "_internal_fragments", return_value=["本音では出社は週1までにしたい"])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_clean_output_passes(self) -> None:
        self.assertEqual(check_leaks(_render(), FM, FM, contact=False), [])

    def test_contact_allowed_with_flag(self) -> None:
        self.assertEqual(check_leaks(_render(contact=True), FM, FM, contact=True), [])

    def test_detects_forbidden_values(self) -> None:
        leaked = _render().replace("</body>", "<p>500万 1995年4月1日 taro@example.com 本音では出社は週1までにしたい</p></body>")
        found = " ".join(check_leaks(leaked, FM, FM, contact=False))
        for label in ("現在年収", "生年月日", "連絡先", "非公開ファイル"):
            self.assertIn(label, found)


if __name__ == "__main__":
    unittest.main()
