"""閲覧用 Web UI (webui/) の単体テスト. フィクスチャの vault で全画面とフィルタを確認する."""

import sys
import unittest
import warnings
from pathlib import Path

# プロジェクトルート設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

with warnings.catch_warnings():
    warnings.simplefilter("ignore")  # starlette の TestClient が httpx 利用の非推奨警告を出す
    from fastapi.testclient import TestClient

from tests.test_build_index import COMPANY_FULL, IndexFixture, RECRUITER_WITH_ARCHIVED
from webui import app as webui_app
from webui.app import create_app
from webui.links import ui_url
from webui.markdown import render

COMPANY_BODY = COMPANY_FULL + """
## 選考・面談サマリ

- [カジュアル面談 (2026-10-05)](2026-10-05_casual.md)
- 足切り基準は [criteria](../../criteria.md) を参照
- 求人: [Findy](https://example.com/jobs/job1)

<script>alert(1)</script>
"""

DECLINED = """---
company: "見送り株式会社"
company_key: "declined-co"
track: "domestic"
status: "declined"
decline_reason: "週3出社"
date: "2026-10-01"
updated_at: "2026-10-02"
---
"""


class WebUITest(IndexFixture):
    def setUp(self):
        super().setUp()
        self.write("vault/tracks/domestic/companies/sample/index.md", COMPANY_BODY)
        self.write("vault/tracks/domestic/companies/declined-co/index.md", DECLINED)
        self.client = TestClient(create_app(self.root, self.db))

    def get(self, url: str, **kwargs):
        res = self.client.get(url, **kwargs)
        self.assertEqual(res.status_code, 200, f"{url}: {res.text[:500]}")
        return res.text

    def test_all_pages_ok(self):
        for url in (
            "/",
            "/companies",
            "/companies/domestic/sample",
            "/recruiters",
            "/recruiters/bizreach_yamada-taro",
            "/screening",
            "/archive",
            "/jobs",
            "/jobs/findy/job1",
            "/search?q=サンプル",
            "/search",
        ):
            self.get(url)

    def test_dashboard_lists_scheduled_action(self):
        html = self.get("/")
        self.assertIn("カジュアル面談", html)
        self.assertIn("2026-10-25 10:00", html)

    def test_companies_default_is_active_only(self):
        html = self.get("/companies")
        self.assertIn("株式会社サンプル", html)
        self.assertNotIn("見送り株式会社", html)
        # 条件を付けた場合は指定どおり
        html = self.get("/companies?category=closed")
        self.assertNotIn("株式会社サンプル", html)
        self.assertIn("見送り株式会社", html)
        self.assertIn("見送り株式会社", self.get("/companies?track="))  # ステータス指定なし = 全件

    def test_company_filters(self):
        self.assertIn("株式会社サンプル", self.get("/companies?fit_min=60&salary_min=1000&office_days_max=1"))
        self.assertNotIn("株式会社サンプル", self.get("/companies?fit_min=70"))
        self.assertNotIn("株式会社サンプル", self.get("/companies?office_days_max=0.5"))
        self.assertIn("株式会社サンプル", self.get("/companies?tag=go"))
        self.assertIn("株式会社サンプル", self.get("/companies?remote_type=hybrid&action_type=scheduled"))
        self.assertNotIn("株式会社サンプル", self.get("/companies?remote_type=full_remote"))
        self.assertIn("株式会社サンプル", self.get("/companies?q=Sample"))
        self.assertNotIn("株式会社サンプル", self.get("/companies?q=存在しない語"))
        # 不正な値は無視する
        self.get("/companies?fit_min=abc&status=bogus&sort=drop&dir=x")

    def test_companies_sort(self):
        html = self.get("/companies?track=&sort=company&dir=desc")
        self.assertLess(html.index("見送り株式会社"), html.index("株式会社サンプル"))
        html = self.get("/companies?track=&sort=company&dir=asc")
        self.assertLess(html.index("株式会社サンプル"), html.index("見送り株式会社"))

    def test_htmx_returns_partial(self):
        html = self.get("/companies?fit_min=60", headers={"HX-Request": "true"})
        self.assertNotIn("<html", html)
        self.assertIn("株式会社サンプル", html)

    def test_company_detail(self):
        html = self.get("/companies/domestic/sample")
        self.assertIn("700〜1000万円", html)
        self.assertIn("ハイブリッド（週1出社）", html)
        self.assertIn('href="/recruiters/bizreach_yamada-taro"', html)
        self.assertIn('id="iv-2026-10-05_casual"', html)  # 面談ログのタブ
        self.assertIn('href="/companies/domestic/sample#iv-2026-10-05_casual"', html)  # 本文の相対リンクを書き換える
        self.assertIn('class="dead-link"', html)  # criteria.md へのリンクは無効化
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn('href="/jobs/findy/job1"', html)  # 社名が一致する取得済み求人

    def test_not_found(self):
        self.assertEqual(self.client.get("/companies/domestic/nope").status_code, 404)
        self.assertEqual(self.client.get("/companies/overseas/sample").status_code, 404)
        self.assertEqual(self.client.get("/recruiters/nobody_x").status_code, 404)
        self.assertEqual(self.client.get("/jobs/findy/nope").status_code, 404)

    def test_recruiter_detail_joins_company_log(self):
        html = self.get("/recruiters/bizreach_yamada-taro")
        self.assertIn('href="/companies/domestic/sample"', html)
        self.assertIn("カジュアル面談", html)  # 企業ログ側の status

    def test_screening_and_jobs(self):
        self.assertIn("打ち切り株式会社", self.get("/screening?q=打ち切り"))
        self.assertNotIn("打ち切り株式会社", self.get("/screening?track=overseas"))
        html = self.get("/jobs?has_log=1&salary_min=900&remote_type=full_remote&skill=go&source=findy")
        self.assertIn("バックエンドエンジニア（Go）", html)
        self.assertIn('href="/companies/domestic/sample"', html)  # 企業ログありのバッジ
        self.assertNotIn("バックエンドエンジニア（Go）", self.get("/jobs?salary_min=1000"))

    def test_archive(self):
        html = self.get("/archive?track=domestic")
        self.assertIn("圧縮済み株式会社", html)
        self.assertIn("出社が週1以下になったら", html)
        self.assertIn("畳み込み株式会社", html)
        self.assertNotIn("圧縮済み株式会社", self.get("/archive?track=overseas"))
        keyed = self.get("/archive?track=domestic&key=archived-co")
        self.assertIn("圧縮済み株式会社", keyed)
        self.assertNotIn("畳み込み株式会社", keyed)
        self.assertNotIn("圧縮済み株式会社", self.get("/archive?status=discarded"))
        self.assertIn("圧縮済み株式会社", self.get("/archive?q=出社が週1"))
        self.assertIn('href="/archive?track=domestic"', self.get("/search?q=畳み込み"))

    def test_recruiter_detail_links_archived_company(self):
        html = self.get("/recruiters/bizreach_yamada-taro")
        self.assertIn('href="/archive?track=domestic&amp;key=archived-co"', html)
        self.assertIn("見送り・辞退", html)

    def test_company_detail_links_and_materials(self):
        company_with_links = COMPANY_BODY.replace(
            'date: "2026-10-01"',
            'date: "2026-10-01"\nlinks:\n  - category: "deck"\n    title: "会社説明資料"\n    url: "https://example.com/deck"\n    summary: "スライド概要"\n    material: "materials/deck.md"\n  - category: "blog"\n    title: "技術ブログ"\n    url: "https://example.com/blog"',
        )
        self.write("vault/tracks/domestic/companies/sample/index.md", company_with_links)
        self.write(
            "vault/tracks/domestic/companies/sample/materials/deck.md",
            '---\ntitle: "サンプル会社説明資料"\nsource_url: "https://example.com/deck"\nfetched_at: "2026-10-05"\n'
            'raw_data:\n  - "data/speakerdeck/sample/deck/"\nraw_fetched_at: "2026-10-04"\n---\n\n# 見出し\n\nスライド要約の本文です。\n',
        )
        html = self.get("/companies/domestic/sample")
        # リンクカードの検証
        self.assertIn("参考リソース・資料リンク", html)
        self.assertIn("会社説明資料", html)
        self.assertIn("https://example.com/deck", html)
        self.assertIn("スライド概要", html)
        self.assertIn("会社説明資料・ピッチデック", html)
        self.assertIn("技術ブログ", html)
        self.assertIn("📄 資料を開く", html)
        # 資料タブの検証
        self.assertIn("📄 サンプル会社説明資料", html)
        self.assertIn("スライド要約の本文です。", html)
        self.assertIn('id="mat-deck"', html)
        # 日付は資料側のフロントマターから表示し、フロントマター自体は本文に出さない
        self.assertIn("要約 2026-10-05", html)
        self.assertIn("生データ取得 2026-10-04", html)
        self.assertNotIn("raw_fetched_at", html)

    def test_recruiter_detail_links_and_materials(self):
        recruiter_with_links = RECRUITER_WITH_ARCHIVED.replace(
            'updated_at: "2026-10-01"',
            'updated_at: "2026-10-01"\nlinks:\n  - category: "corporate"\n    title: "エージェント会社情報"\n    url: "https://example.com/agency"\n    summary: "会社概要"\n    material: "materials/profile.md"',
        )
        self.write("vault/recruiters/bizreach_yamada-taro/index.md", recruiter_with_links)
        self.write(
            "vault/recruiters/bizreach_yamada-taro/materials/profile.md",
            "# エージェント概要資料\n\n担当者の詳細情報です。\n",
        )
        html = self.get("/recruiters/bizreach_yamada-taro")
        self.assertIn("参考リソース・資料リンク", html)
        self.assertIn("エージェント会社情報", html)
        self.assertIn("https://example.com/agency", html)
        self.assertIn("📄 資料を開く", html)
        self.assertIn("📄 エージェント概要資料", html)
        self.assertIn("担当者の詳細情報です。", html)
        self.assertIn('id="mat-profile"', html)

    def test_search_groups_by_kind(self):
        html = self.get("/search?q=サンプル")
        self.assertIn('href="/companies/domestic/sample"', html)
        self.assertIn('href="/jobs/findy/job1"', html)

    def test_search_excludes_tech_notes(self):
        # 技術ノートは索引には入るが、プロフィールを表示しない Web UI の検索には出さない
        self.assertNotIn("vault/profile/tech/", self.get("/search?q=全文検索"))

    def test_vault_change_is_reflected_without_restart(self):
        self.get("/companies")
        self.write("vault/tracks/domestic/companies/newco/index.md", DECLINED.replace("declined-co", "newco")
                   .replace("見送り株式会社", "新規株式会社").replace('"declined"', '"considering"'))
        self.assertIn("新規株式会社", self.get("/companies"))

    def test_reindex_redirects_back(self):
        res = self.client.post("/reindex", headers={"referer": "http://127.0.0.1:8765/jobs?q=Go"}, follow_redirects=False)
        self.assertEqual(res.status_code, 303)
        self.assertEqual(res.headers["location"], "/jobs?q=Go")
        res = self.client.post("/reindex", headers={"referer": "https://evil.example/"}, follow_redirects=False)
        self.assertEqual(res.headers["location"], "/")

    def test_binds_localhost_only(self):
        self.assertEqual(webui_app.HOST, "127.0.0.1")


class LinksAndMarkdownTest(unittest.TestCase):
    def test_ui_url(self):
        self.assertEqual(ui_url("vault/tracks/domestic/companies/a-b/index.md"), "/companies/domestic/a-b")
        self.assertEqual(ui_url("vault/recruiters/x_y/2026-10-02_career-consultation.md"),
                         "/recruiters/x_y#iv-2026-10-02_career-consultation")
        self.assertEqual(ui_url("data/green/jobs/123.md"), "/jobs/green/123")
        self.assertIsNone(ui_url("vault/tracks/domestic/criteria.md"))
        self.assertIsNone(ui_url("vault/profile/internal/notes.md"))
        self.assertTrue(ui_url("vault/tracks/domestic/screening/2026-10-08_x.md").startswith("/screening?"))
        self.assertEqual(ui_url("vault/tracks/overseas/archive.md"), "/archive?track=overseas")

    def test_render_blocks_unsafe_links(self):
        html = render("[x](javascript:alert(1)) [y](../../../../profile/internal/notes.md)",
                      "vault/tracks/domestic/companies/a/index.md")
        self.assertNotIn('href="javascript', html)
        self.assertNotIn("notes.md", html.replace("[x]", ""))
        self.assertIn("dead-link", html)


if __name__ == "__main__":
    unittest.main()
