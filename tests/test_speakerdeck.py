"""Speaker Deck スライド文字起こし機能の単体テスト."""

import unittest
from datetime import datetime

from scripts.speakerdeck.fetch_deck import (
    DeckData,
    SlideData,
    build_markdown,
    normalize_slide_text,
    parse_deck_page_html,
    parse_player_html,
    parse_speakerdeck_url,
)


class TestSpeakerdeck(unittest.TestCase):
    """Speaker Deck パース・整形ロジックのテスト."""

    def test_normalize_slide_text(self):
        raw = "Line 1\n\n\n\nLine 2  \n\x0c"
        cleaned = normalize_slide_text(raw)
        self.assertEqual(cleaned, "Line 1\n\nLine 2")

        # 空文字や制御文字のみの場合
        self.assertEqual(normalize_slide_text(""), "")
        self.assertEqual(normalize_slide_text("\x0c\f \n "), "")

    def test_parse_speakerdeck_url(self):
        u1 = "https://speakerdeck.com/loglass2019/whats-loglass"
        self.assertEqual(parse_speakerdeck_url(u1), ("loglass2019", "whats-loglass"))

        u2 = "https://speakerdeck.com/loglass2019/whats-loglass/?slide=5"
        self.assertEqual(parse_speakerdeck_url(u2), ("loglass2019", "whats-loglass"))

        u3 = "https://speakerdeck.com/player/abc123uuid"
        self.assertEqual(parse_speakerdeck_url(u3), ("player", "abc123uuid"))

    def test_parse_deck_page_html(self):
        sample_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="ログラス 会社紹介資料" />
            <meta property="og:description" content="ログラスの概要・プロダクト・カルチャーを紹介するスライドです。" />
        </head>
        <body>
            <h1>ログラス 会社紹介資料</h1>
            <a class="speakerdeck-author" href="/loglass2019">ログラス公式</a>
            <div class="speakerdeck-embed" data-id="12345678-abcd-ef01-2345-6789abcdef01"></div>
            <a title="Download PDF" href="https://files.speakerdeck.com/presentations/12345/presentation.pdf">Download PDF</a>
            <time datetime="2024-05-01">2024年5月1日</time>
        </body>
        </html>
        """
        meta = parse_deck_page_html(sample_html, "https://speakerdeck.com/loglass2019/whats-loglass")
        self.assertEqual(meta["username"], "loglass2019")
        self.assertEqual(meta["deck_slug"], "whats-loglass")
        self.assertEqual(meta["title"], "ログラス 会社紹介資料")
        self.assertEqual(meta["presentation_id"], "12345678-abcd-ef01-2345-6789abcdef01")
        self.assertEqual(meta["author_name"], "ログラス公式")
        self.assertEqual(meta["description"], "ログラスの概要・プロダクト・カルチャーを紹介するスライドです。")
        self.assertEqual(meta["published_at"], "2024-05-01")
        self.assertEqual(meta["pdf_url"], "https://files.speakerdeck.com/presentations/12345/presentation.pdf")

    def test_parse_player_html(self):
        sample_player_html = """
        <!DOCTYPE html>
        <html>
        <body>
            <!-- プレゼンター枠（除外されるべき要素） -->
            <div class="sd-player-slide sd-player-presenter-previous js-sd-player-previous-slide"></div>
            <div class="sd-player-slide sd-player-presenter-current js-sd-player-current-slide"></div>
            <div class="sd-player-slide sd-player-presenter-next js-sd-player-next-slide"></div>

            <!-- 実スライド要素 -->
            <div class="sd-player-slide js-sd-slide"
                 data-url="https://files.speakerdeck.com/presentations/123/slide_0.jpg"
                 data-preview-url="https://files.speakerdeck.com/presentations/123/preview_slide_0.jpg"
                 data-slide-note="スライド1の発表者ノート">
                <h2 class="sd-player-slides--heading">Slide 1</h2>
                <div class="sd-player-slides--text">
                    ログラス会社紹介
                    良い景気を作ろう。
                    \x0c
                </div>
            </div>
            <div class="sd-player-slide js-sd-slide"
                 data-url="https://files.speakerdeck.com/presentations/123/slide_1.jpg"
                 data-preview-url="https://files.speakerdeck.com/presentations/123/preview_slide_1.jpg">
                <h2 class="sd-player-slides--heading">Slide 2</h2>
                <div class="sd-player-slides--text">
                    ミッション・ビジョン
                </div>
            </div>
            <div class="sd-player-slide js-sd-slide"
                 data-url="https://files.speakerdeck.com/presentations/123/slide_2.jpg">
                <h2 class="sd-player-slides--heading">Slide 3</h2>
            </div>
        </body>
        </html>
        """
        slides = parse_player_html(sample_player_html)
        self.assertEqual(len(slides), 3)

        s1 = slides[0]
        self.assertEqual(s1.index, 1)
        self.assertEqual(s1.image_url, "https://files.speakerdeck.com/presentations/123/slide_0.jpg")
        self.assertEqual(s1.note, "スライド1の発表者ノート")
        self.assertIn("良い景気を作ろう。", s1.text)
        self.assertNotIn("\x0c", s1.text)

        s2 = slides[1]
        self.assertEqual(s2.index, 2)
        self.assertEqual(s2.note, "")
        self.assertIn("ミッション・ビジョン", s2.text)

        s3 = slides[2]
        self.assertEqual(s3.index, 3)
        self.assertEqual(s3.text, "")

    def test_build_markdown(self):
        slides = [
            SlideData(
                index=1,
                image_url="https://example.com/s1.jpg",
                text="タイトルスライド本文",
                note="ノート1",
            ),
            SlideData(
                index=2,
                image_url="https://example.com/s2.jpg",
                text="",
            ),
        ]
        deck = DeckData(
            url="https://speakerdeck.com/testuser/test-deck",
            username="testuser",
            deck_slug="test-deck",
            title="テストスライド",
            presentation_id="mock-uuid",
            author_name="テストユーザー",
            description="スライド説明文",
            published_at="2026-10-23",
            pdf_url="https://example.com/test.pdf",
            slide_count=2,
            slides=slides,
            fetched_at="2026-10-23T23:00:00",
        )

        md = build_markdown(deck)
        self.assertIn("title: テストスライド", md)
        self.assertIn("presentation_id: mock-uuid", md)
        self.assertIn("# テストスライド", md)
        self.assertIn("- **発表者**: テストユーザー (@testuser)", md)
        self.assertIn("- **スライド枚数**: 2 枚", md)
        self.assertIn("### Slide 1", md)
        self.assertIn("![Slide 1](https://example.com/s1.jpg)", md)
        self.assertIn("タイトルスライド本文", md)
        self.assertIn("> **登壇者ノート**: ノート1", md)
        self.assertIn("### Slide 2", md)
        self.assertIn("*（スライドテキストなし）*", md)


if __name__ == "__main__":
    unittest.main()
