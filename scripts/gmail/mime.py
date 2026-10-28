"""Gmail の raw（RFC 2822）メールを解析し、ヘッダ・本文テキスト・添付メタデータを取り出す.

- `messages.get(format=raw)` の base64url 文字列を標準 `email` パッケージで解析する
- 本文は text/plain を優先し、無ければ text/html をテキスト化する（beautifulsoup4）
- 添付はファイル名・種類・サイズだけを返し、中身は保存しない
- ISO-2022-JP / Shift_JIS を名乗りつつ Windows 拡張文字（①、髙 等）を含むメールに備え、
  CP932 系へのフォールバックを行い、最後は errors="replace" で必ず文字列にする
"""

from __future__ import annotations

import base64
import email
import email.policy
from dataclasses import dataclass, field
from email.header import decode_header
from email.message import Message
from email.utils import getaddresses
from typing import Any

# 名乗っている charset ごとの追加候補（先頭から順に strict で試す）
_ISO2022JP_NAMES = {"iso-2022-jp", "iso2022_jp", "csiso2022jp", "iso-2022-jp-1", "iso-2022-jp-2"}
_SJIS_NAMES = {"shift_jis", "shift-jis", "sjis", "x-sjis", "ms_kanji", "csshiftjis", "windows-31j", "cp932"}
_EUCJP_NAMES = {"euc-jp", "euc_jp", "x-euc-jp", "eucjp"}


@dataclass
class Attachment:
    filename: str
    content_type: str
    size: int


@dataclass
class ParsedMessage:
    subject: str = ""
    from_: str = ""
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    date: str = ""
    body: str = ""
    body_type: str = ""  # "text/plain" / "text/html" / ""（本文なし）
    attachments: list[Attachment] = field(default_factory=list)


def decode_base64url(data: str) -> bytes:
    """Gmail API の base64url（パディング省略あり）をデコードする."""
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _iso2022jp_to_cp932(data: bytes, errors: str = "strict") -> str:
    """ISO-2022-JP のバイト列を JIS→Shift_JIS 変換して CP932 で読む.

    Outlook 等が送る ISO-2022-JP には CP932 の NEC 特殊文字（①、㈱ 等）や
    NEC 選定 IBM 拡張文字（髙 等）が JIS X 0208 の空き領域に入っていることがあり、
    標準の iso2022_jp 系コーデックでは読めない。
    """
    out = bytearray()
    mode = "ascii"
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if b == 0x1B:  # ESC
            seq = data[i + 1 : i + 3]
            if seq in (b"$B", b"$@"):
                mode = "jis"
            elif seq in (b"(B", b"(J"):
                mode = "ascii"
            elif seq == b"(I":
                mode = "kana"
            else:
                raise UnicodeDecodeError("iso2022_jp_cp932", data, i, i + 3, "unknown escape sequence")
            i += 3
            continue
        if b in (0x0A, 0x0D):
            out.append(b)
            i += 1
            continue
        if mode == "jis":
            if i + 1 >= n:
                raise UnicodeDecodeError("iso2022_jp_cp932", data, i, n, "truncated multibyte sequence")
            j1, j2 = b, data[i + 1]
            s1 = ((j1 + 1) >> 1) + (0x70 if j1 <= 0x5E else 0xB0)
            if j1 % 2:
                s2 = j2 + 0x1F + (1 if j2 >= 0x60 else 0)
            else:
                s2 = j2 + 0x7E
            out += bytes((s1 & 0xFF, s2 & 0xFF))
            i += 2
        elif mode == "kana":
            out.append(b | 0x80)
            i += 1
        else:
            out.append(b)
            i += 1
    return bytes(out).decode("cp932", errors=errors)


def decode_bytes(data: bytes, charset: str | None) -> str:
    """名乗っている charset で読み、失敗したら日本語メール向けの候補にフォールバックする."""
    name = (charset or "").strip().lower()
    candidates: list[Any] = []
    if name in _ISO2022JP_NAMES:
        # 標準の iso2022_jp は 89〜92 区（IBM 拡張）を別の漢字として読んでしまい失敗しないので、CP932 経由を先に試す
        candidates = [_iso2022jp_to_cp932, "iso2022_jp_2", "iso2022_jp_ext"]
    elif name in _SJIS_NAMES:
        candidates = ["cp932", "shift_jis"]
    elif name in _EUCJP_NAMES:
        candidates = ["euc_jp", "euc_jis_2004"]
    elif name and name not in ("unknown-8bit", "us-ascii", "ascii"):
        candidates = [name]
    candidates += ["utf-8", "cp932"]

    for cand in candidates:
        try:
            return cand(data) if callable(cand) else data.decode(cand)
        except (UnicodeDecodeError, LookupError):
            continue

    if name in _ISO2022JP_NAMES:
        return _iso2022jp_to_cp932(data, errors="replace")
    try:
        return data.decode(name or "utf-8", errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def decode_header_value(value: Any) -> str:
    """RFC 2047 のエンコード語を含むヘッダ値を文字列にする."""
    if value is None:
        return ""
    parts = []
    for chunk, charset in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(decode_bytes(chunk, charset))
        else:
            parts.append(chunk)
    return "".join(parts).strip()


def _format_addresses(raw_values: list[Any]) -> list[str]:
    """アドレスヘッダを「表示名 <addr>」の配列にする（表示名はエンコード語をデコード）."""
    result = []
    for name, addr in getaddresses([str(v) for v in raw_values if v is not None]):
        if not addr and not name:
            continue
        display = decode_header_value(name) if name else ""
        result.append(f"{display} <{addr}>" if display else addr)
    return result


def html_to_text(html: str) -> str:
    """HTML メールを読めるテキストにする（script/style は捨てる）."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    text = soup.get_text("\n")
    lines = [line.strip() for line in text.splitlines()]
    # 空行の連続を 1 行にまとめる
    compact: list[str] = []
    for line in lines:
        if line or (compact and compact[-1]):
            compact.append(line)
    return "\n".join(compact).strip()


def _part_text(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    return decode_bytes(payload, part.get_content_charset())


def _is_attachment(part: Message) -> bool:
    if part.get_content_disposition() == "attachment":
        return True
    # inline でもファイル名付きの非テキストは添付扱い（画像など）
    return bool(part.get_filename()) and part.get_content_maintype() != "text"


def parse_message_bytes(data: bytes) -> ParsedMessage:
    """RFC 2822 のバイト列を解析する."""
    # compat32 でヘッダを生のまま受け取り、charset のフォールバックを自前で行う
    msg = email.message_from_bytes(data, policy=email.policy.compat32)

    parsed = ParsedMessage(
        subject=decode_header_value(msg.get("Subject")),
        from_=", ".join(_format_addresses(msg.get_all("From", []))),
        to=_format_addresses(msg.get_all("To", [])),
        cc=_format_addresses(msg.get_all("Cc", [])),
        date=decode_header_value(msg.get("Date")),
    )

    plain: list[str] = []
    html: list[str] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        if _is_attachment(part):
            payload = part.get_payload(decode=True) or b""
            parsed.attachments.append(
                Attachment(
                    filename=decode_header_value(part.get_filename()) or "(名前なし)",
                    content_type=part.get_content_type(),
                    size=len(payload),
                )
            )
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain":
            plain.append(_part_text(part))
        elif ctype == "text/html":
            html.append(_part_text(part))

    if any(t.strip() for t in plain):
        parsed.body = "\n\n".join(t.strip() for t in plain if t.strip())
        parsed.body_type = "text/plain"
    elif html:
        parsed.body = "\n\n".join(html_to_text(h) for h in html).strip()
        parsed.body_type = "text/html"
    return parsed


def parse_raw(raw: str) -> ParsedMessage:
    """`messages.get(format=raw)` の `raw` フィールドを解析する."""
    return parse_message_bytes(decode_base64url(raw))
