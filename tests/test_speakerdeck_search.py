"""Speaker Deck スライド検索機能の単体テスト."""

import unittest
from unittest.mock import patch

from scripts.speakerdeck.search_decks import (
    DeckSearchItem,
    SpeakerDeckSearchResult,
    build_search_markdown,
    build_search_url,
    parse_search_page_html,
    sanitize_filename,
    search_decks,
)


SAMPLE_SEARCH_HTML = """
<!DOCTYPE html>
<html>
<body>
  <div class="card deck-preview" data-id="uuid-12345" data-slide-count="25" data-cover-image="https://example.com/cover1.jpg">
    <a class="deck-preview-link" href="/testuser/first-deck" title="テストスライド 1">
      <div class="deck-preview-image">
        <div class="deck-preview-slide"></div>
      </div>
      <div class="deck-title px-3 pt-3 text-truncate">
        テストスライド 1
      </div>
    </a>
    <div class="deck-preview-meta d-flex px-2">
      <div class="text-truncate py-3 pe-2 me-auto">
        <a aria-label="山田 太郎 profile" href="/testuser">
          <img alt="Avatar for 山田 太郎" class="avatar" src="https://example.com/avatar.jpg" />
          山田 太郎
        </a>
      </div>
      <div class="px-2 py-3">
        <svg class="icon icon-star"></svg> 15
      </div>
      <div class="px-1 py-3">
        <span title="1,234 views"><svg class="icon icon-eye"></svg> 1.2k</span>
      </div>
    </div>
  </div>

  <div class="card deck-preview" data-id="uuid-67890" data-slide-count="10" data-cover-image="https://example.com/cover2.jpg">
    <a class="deck-preview-link" href="/corp/second-deck">
      <div class="deck-title px-3 pt-3 text-truncate">
        企業説明資料 2026
      </div>
    </a>
    <div class="deck-preview-meta d-flex px-2">
      <div class="text-truncate py-3 pe-2 me-auto">
        <a href="/corp">
          corp
        </a>
      </div>
      <div class="px-2 py-3">
        <svg class="icon icon-star"></svg> 0
      </div>
      <div class="px-1 py-3">
        <span title="50 views"><svg class="icon icon-eye"></svg> 50</span>
      </div>
    </div>
  </div>

  <!-- ページネーション -->
  <nav class="pagy-bootstrap-nav">
    <ul class="pagination">
      <li class="page-item active"><a class="page-link" href="/search?page=1">1</a></li>
      <li class="page-item next"><a class="page-link" href="/search?page=2">Next</a></li>
    </ul>
  </nav>
</body>
</html>
"""

SAMPLE_SEARCH_HTML_LAST_PAGE = """
<!DOCTYPE html>
<html>
<body>
  <div class="card deck-preview" data-id="uuid-last" data-slide-count="5">
    <a class="deck-preview-link" href="/solo/last-deck" title="最終スライド"></a>
  </div>
  <nav class="pagy-bootstrap-nav">
    <ul class="pagination">
      <li class="page-item next disabled"><span class="page-link">Next</span></li>
    </ul>
  </nav>
</body>
</html>
"""

SAMPLE_SEARCH_HTML_EMPTY = """
<!DOCTYPE html>
<html>
<body>
  <div class="empty-state">
    No results found
  </div>
</body>
</html>
"""


class TestSpeakerDeckSearch(unittest.TestCase):
    """Speaker Deck 検索機能のテスト."""

    def test_build_search_url(self):
        # 1. 基本（言語指定あり、page 1）
        u1 = build_search_url("ログラス", lang="ja", page=1)
        self.assertEqual(u1, "https://speakerdeck.com/search?q=%E3%83%AD%E3%82%B0%E3%83%A9%E3%82%B9&lang=ja")

        # 2. 全言語指定（all や空文字）
        u2 = build_search_url("Loglass", lang="all", page=1)
        self.assertEqual(u2, "https://speakerdeck.com/search?q=Loglass")

        u3 = build_search_url("Loglass", lang="", page=1)
        self.assertEqual(u3, "https://speakerdeck.com/search?q=Loglass")

        # 3. ページネーション（page 2）
        u4 = build_search_url("Python", lang="ja", page=2)
        self.assertIn("page=2", u4)
        self.assertIn("lang=ja", u4)
        self.assertIn("q=Python", u4)

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("株式会社 ログラス"), "株式会社_ログラス")
        self.assertEqual(sanitize_filename("foo/bar:baz?*"), "foo_bar_baz")
        self.assertEqual(sanitize_filename("   "), "search")

    def test_parse_search_page_html(self):
        decks, has_next = parse_search_page_html(SAMPLE_SEARCH_HTML)
        self.assertTrue(has_next)
        self.assertEqual(len(decks), 2)

        # 1枚目
        d1 = decks[0]
        self.assertEqual(d1.id, "uuid-12345")
        self.assertEqual(d1.title, "テストスライド 1")
        self.assertEqual(d1.url, "https://speakerdeck.com/testuser/first-deck")
        self.assertEqual(d1.username, "testuser")
        self.assertEqual(d1.author_name, "山田 太郎")
        self.assertEqual(d1.slide_count, 25)
        self.assertEqual(d1.cover_image, "https://example.com/cover1.jpg")
        self.assertEqual(d1.stars, 15)
        self.assertEqual(d1.views, 1234)
        self.assertEqual(d1.views_text, "1.2k")

        # 2枚目
        d2 = decks[1]
        self.assertEqual(d2.id, "uuid-67890")
        self.assertEqual(d2.title, "企業説明資料 2026")
        self.assertEqual(d2.url, "https://speakerdeck.com/corp/second-deck")
        self.assertEqual(d2.username, "corp")
        self.assertEqual(d2.author_name, "corp")
        self.assertEqual(d2.slide_count, 10)
        self.assertEqual(d2.stars, 0)
        self.assertEqual(d2.views, 50)

    def test_parse_search_page_html_last_page(self):
        decks, has_next = parse_search_page_html(SAMPLE_SEARCH_HTML_LAST_PAGE)
        self.assertFalse(has_next)
        self.assertEqual(len(decks), 1)
        self.assertEqual(decks[0].id, "uuid-last")

    def test_parse_search_page_html_empty(self):
        decks, has_next = parse_search_page_html(SAMPLE_SEARCH_HTML_EMPTY)
        self.assertFalse(has_next)
        self.assertEqual(len(decks), 0)

    def test_build_search_markdown(self):
        item = DeckSearchItem(
            id="uuid-1",
            title="会社案内 | 2026",
            url="https://speakerdeck.com/acme/company",
            username="acme",
            author_name="アクメ株式会社",
            slide_count=30,
            views=5000,
            views_text="5k",
            stars=8,
        )
        result = SpeakerDeckSearchResult(
            query="Acme",
            lang="ja",
            total_pages_fetched=1,
            returned_count=1,
            searched_at="2026-10-24T00:00:00",
            decks=[item],
        )

        md = build_search_markdown(result)
        self.assertIn("query: Acme", md)
        self.assertIn("lang: ja", md)
        self.assertIn("# Speaker Deck 検索結果: Acme", md)
        self.assertIn("会社案内 \\| 2026", md)  # パイプのエスケープ
        self.assertIn("アクメ株式会社 (@acme)", md)
        self.assertIn("| 1 |", md)
        self.assertIn("5k", md)

    def test_build_search_markdown_empty(self):
        result = SpeakerDeckSearchResult(
            query="存在しないキーワード12345",
            lang="ja",
            total_pages_fetched=1,
            returned_count=0,
            searched_at="2026-10-24T00:00:00",
            decks=[],
        )
        md = build_search_markdown(result)
        self.assertIn("*（該当するスライドは見つかりませんでした）*", md)

    @patch("scripts.speakerdeck.search_decks.fetch_url_content")
    def test_search_decks_pagination_and_limit(self, mock_fetch):
        # 1ページ目で2件返却、has_next=True
        # limit=1 なので1件取得時点で打ち切られることを検証
        mock_fetch.return_value = (SAMPLE_SEARCH_HTML, 200)

        result, paths = search_decks(
            query="テスト",
            lang="ja",
            limit=1,
            dry_run=True,
            save_files=False,
        )

        self.assertEqual(result.returned_count, 1)
        self.assertEqual(result.total_pages_fetched, 1)
        self.assertEqual(result.decks[0].id, "uuid-12345")
        mock_fetch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
