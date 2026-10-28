"""Gmail API クライアント.

認証（token.json の読込・refresh・スコープ検証）と再試行は Google 共通層 scripts/google/client.py が担い、
ここは Gmail API service の生成だけを持ちます。Gmail のスコープは gmail.readonly のみ（定義は共通層の GMAIL_SCOPES）。
仕様は docs/gmail/README.md、認証は docs/google/README.md を参照。
"""

from __future__ import annotations

from typing import Any

from scripts.google.client import GoogleAuthError
from scripts.google.client import build_service as _build_service
from scripts.google.client import execute as _execute

__all__ = ["GoogleAuthError", "build_service", "execute"]


def build_service(creds: Any | None = None) -> Any:
    """Gmail API v1 の service を生成する."""
    return _build_service("gmail", "v1", creds)


def execute(request: Any) -> Any:
    """Gmail API リクエストを再試行付きで実行する（429・rateLimitExceeded・5xx は指数バックオフ）."""
    return _execute(request, api_name="Gmail API")
