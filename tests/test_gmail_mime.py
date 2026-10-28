"""Gmail の MIME 解析（scripts/gmail/mime.py）の単体テスト."""

import base64
import unittest
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from scripts.gmail.mime import decode_bytes, parse_message_bytes, parse_raw


def _to_raw(data: bytes) -> str:
    """Gmail API と同じくパディングなしの base64url にする."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


class TestDecodeBytes(unittest.TestCase):
    def test_iso2022jp_with_nec_special_chars(self):
        # CP932 の NEC 特殊文字（①、㈱）を JIS X 0208 の 13 区に入れた ISO-2022-JP（Outlook 等）
        data = b"\x1b$B\x2d\x21\x2d\x6a\x1b(B ok"
        self.assertEqual(decode_bytes(data, "ISO-2022-JP"), "①㈱ ok")

    def test_iso2022jp_with_ibm_extension(self):
        # 髙（CP932 0xEEE0, NEC 選定 IBM 拡張）を JIS に戻したバイト列
        data = b"\x1b$B\x7c\x62\x1b(B"
        self.assertEqual(decode_bytes(data, "iso-2022-jp"), "髙")

    def test_shift_jis_label_with_cp932_chars(self):
        self.assertEqual(decode_bytes("①髙橋".encode("cp932"), "Shift_JIS"), "①髙橋")

    def test_wrong_label_falls_back(self):
        self.assertEqual(decode_bytes("日本語".encode("utf-8"), "iso-2022-jp"), "日本語")

    def test_undecodable_is_replaced(self):
        result = decode_bytes(b"\x1b$B\xff\xff\x1b(B", "iso-2022-jp")
        self.assertIsInstance(result, str)


class TestParseMessage(unittest.TestCase):
    def test_iso2022jp_plain(self):
        msg = MIMEText("面談日程のご連絡です。\n10/25 14:00 はいかがでしょうか。", "plain", "iso-2022-jp")
        msg["Subject"] = Header("【面談調整】カジュアル面談", "iso-2022-jp").encode()
        msg["From"] = f'{Header("山田 太郎", "iso-2022-jp").encode()} <yamada@example.com>'
        msg["To"] = "me@example.com"
        msg["Date"] = "Wed, 21 Oct 2026 10:00:00 +0900"

        parsed = parse_raw(_to_raw(msg.as_bytes()))
        self.assertEqual(parsed.subject, "【面談調整】カジュアル面談")
        self.assertEqual(parsed.from_, "山田 太郎 <yamada@example.com>")
        self.assertEqual(parsed.to, ["me@example.com"])
        self.assertIn("10/25 14:00", parsed.body)
        self.assertEqual(parsed.body_type, "text/plain")

    def test_multipart_alternative_prefers_plain(self):
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Scout"
        msg.attach(MIMEText("プレーン本文", "plain", "utf-8"))
        msg.attach(MIMEText("<p>HTML本文</p>", "html", "utf-8"))

        parsed = parse_message_bytes(msg.as_bytes())
        self.assertEqual(parsed.body, "プレーン本文")
        self.assertEqual(parsed.body_type, "text/plain")

    def test_html_only(self):
        html = (
            "<html><head><style>p{color:red}</style></head>"
            "<body><p>選考結果のご連絡</p><p>次回は<br>二次面接です</p><script>x()</script></body></html>"
        )
        msg = MIMEText(html, "html", "utf-8")
        parsed = parse_message_bytes(msg.as_bytes())
        self.assertEqual(parsed.body_type, "text/html")
        self.assertIn("選考結果のご連絡", parsed.body)
        self.assertIn("二次面接です", parsed.body)
        self.assertNotIn("color:red", parsed.body)
        self.assertNotIn("x()", parsed.body)

    def test_attachment_metadata_only(self):
        msg = MIMEMultipart()
        msg["Subject"] = "求人票送付"
        msg.attach(MIMEText("求人票を添付します。", "plain", "utf-8"))
        pdf = MIMEApplication(b"%PDF-1.4 dummy", _subtype="pdf")
        pdf.add_header("Content-Disposition", "attachment", filename=("utf-8", "", "求人票.pdf"))
        msg.attach(pdf)

        parsed = parse_message_bytes(msg.as_bytes())
        self.assertEqual(parsed.body, "求人票を添付します。")
        self.assertEqual(len(parsed.attachments), 1)
        att = parsed.attachments[0]
        self.assertEqual(att.filename, "求人票.pdf")
        self.assertEqual(att.content_type, "application/pdf")
        self.assertEqual(att.size, len(b"%PDF-1.4 dummy"))

    def test_iso2022jp_body_with_nec_chars(self):
        raw = (
            b"Subject: test\r\n"
            b"MIME-Version: 1.0\r\n"
            b"Content-Type: text/plain; charset=ISO-2022-JP\r\n"
            b"Content-Transfer-Encoding: 7bit\r\n\r\n"
            b"\x1b$B\x2d\x21\x1b(B step\r\n"
        )
        parsed = parse_message_bytes(raw)
        self.assertEqual(parsed.body, "① step")

    def test_no_body(self):
        parsed = parse_message_bytes(b"Subject: empty\r\n\r\n")
        self.assertEqual(parsed.subject, "empty")
        self.assertEqual(parsed.body, "")


if __name__ == "__main__":
    unittest.main()
