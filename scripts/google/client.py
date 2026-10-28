"""Google API クライアント共通層.

トークン（token.json）の読込・自動 refresh、API service の生成、再試行付きのリクエスト実行を行います。
スコープはサービスごとに定義し、トークンのスコープはその和集合と完全一致するものだけを受け付けます
（Gmail は gmail.readonly のみ。余計なスコープが付いたトークンは拒否します）。

認証情報はリポジトリ外（既定: %LOCALAPPDATA%\\job-hunt\\google\\）に置き、
環境変数 JOB_HUNT_GOOGLE_DIR で上書きできます。仕様は docs/google/README.md を参照。
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# スコープはサービス別にこの 1 か所でだけ定義する（追加・変更はコードを書く前にユーザーに相談する）
# Gmail は読み取り専用の担保。変更・送信系スコープは書かない
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
# Calendar: 自分所有のカレンダーの予定 CRUD・空き状況・カレンダー一覧の閲覧（全権 calendar は使わない）
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events.owned",
    "https://www.googleapis.com/auth/calendar.events.freebusy",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
]
# 同意画面での表示名（分割同意で外されたスコープの案内に使う）
SCOPE_LABELS = {
    GMAIL_SCOPES[0]: "Gmail のメールの閲覧",
    CALENDAR_SCOPES[0]: "自分のカレンダーの予定の閲覧・編集",
    CALENDAR_SCOPES[1]: "カレンダーの空き状況の閲覧",
    CALENDAR_SCOPES[2]: "カレンダー一覧の閲覧",
}
# token.json が持つべきスコープ（和集合）
SCOPES = GMAIL_SCOPES + CALENDAR_SCOPES

# 認証情報ディレクトリの上書き用環境変数
GOOGLE_DIR_ENV = "JOB_HUNT_GOOGLE_DIR"
CLIENT_SECRET_FILENAME = "client_secret.json"
TOKEN_FILENAME = "token.json"

# token.json に追記する独自キー（初回認可の日時。refresh では更新しない）
AUTHORIZED_AT_KEY = "job_hunt_authorized_at"

# 同意画面が Testing の間、refresh token は認可から 7 日で失効する
TESTING_REFRESH_TOKEN_DAYS = 7

# ユーザーが自分の外部ターミナルで実行する再認可コマンド
REAUTH_COMMAND = "uv run python scripts/google/auth.py"


class GoogleAuthError(Exception):
    """認証が使えない状態（未認可・失効・スコープ不一致）。ユーザーの再認可が必要."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

    def handoff_message(self) -> str:
        """stderr に出す再認可の案内."""
        return (
            f"{self.reason}\n"
            f"ユーザーが自分の外部ターミナルで次を実行し、ブラウザで同意してください:\n"
            f"  {REAUTH_COMMAND}\n"
            f"詳細: docs/google/README.md"
        )


def credentials_dir() -> Path:
    """認証情報ディレクトリを解決する（環境変数 → %LOCALAPPDATA%\\job-hunt\\google）."""
    override = os.environ.get(GOOGLE_DIR_ENV)
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get(
        "LOCALAPPDATA",
        str(Path.home() / "AppData" / "Local") if sys.platform == "win32" else str(Path.home() / ".local" / "share"),
    )
    return (Path(local_app_data) / "job-hunt" / "google").resolve()


def client_secret_path() -> Path:
    return credentials_dir() / CLIENT_SECRET_FILENAME


def token_path() -> Path:
    return credentials_dir() / TOKEN_FILENAME


def _scope_list(scopes: Any) -> list[str]:
    if isinstance(scopes, str):
        return scopes.split()
    return list(scopes or [])


def describe_scopes(scopes: Any) -> str:
    """スコープを同意画面の表示名つきで並べる（案内文用）."""
    return "、".join(f"{SCOPE_LABELS.get(s, s)}（{s}）" for s in sorted(_scope_list(scopes)))


def check_scopes(scopes: Any) -> None:
    """トークンのスコープが SCOPES（全サービスの和集合）と完全一致することを確かめる."""
    granted = set(_scope_list(scopes))
    missing = set(SCOPES) - granted
    extra = granted - set(SCOPES)
    if not missing and not extra:
        return
    parts = []
    if missing:
        parts.append(f"不足: {describe_scopes(missing)}")
    if extra:
        parts.append(f"想定外: {', '.join(sorted(extra))}")
    raise GoogleAuthError(
        f"トークンのスコープが想定と異なります（{' / '.join(parts)}）。token.json を使わず再認可が必要です。"
    )


def read_authorized_at(path: Path | None = None) -> datetime | None:
    """token.json に記録した初回認可の日時（UTC）を返す。無ければ None."""
    path = path or token_path()
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        return datetime.fromisoformat(info[AUTHORIZED_AT_KEY])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def estimated_expiry(authorized_at: datetime) -> datetime:
    """Testing 状態での refresh token 失効の目安."""
    return authorized_at + timedelta(days=TESTING_REFRESH_TOKEN_DAYS)


def save_token(creds: Any, authorized_at: datetime | None = None) -> Path:
    """Credentials を token.json に保存する。authorized_at 省略時は既存の値を引き継ぐ."""
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if authorized_at is None:
        authorized_at = read_authorized_at(path)
    info = json.loads(creds.to_json())
    if authorized_at is not None:
        info[AUTHORIZED_AT_KEY] = authorized_at.astimezone(UTC).isoformat()
    path.write_text(json.dumps(info, indent=2), encoding="utf-8")
    return path


def load_credentials() -> Any:
    """token.json を読み、必要なら refresh した Credentials を返す.

    使えない場合は GoogleAuthError を投げる（呼び出し側は終了コード 2 でハンドオフする）。
    """
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    path = token_path()
    if not path.exists():
        raise GoogleAuthError(f"未認可です（{path} がありません）。")

    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        check_scopes(info.get("scopes"))
        creds = Credentials.from_authorized_user_info(info)
    except (ValueError, json.JSONDecodeError) as e:
        raise GoogleAuthError(f"token.json を読み込めません（形式不正）: {type(e).__name__}") from e

    if creds.valid:
        return creds
    if not creds.refresh_token:
        raise GoogleAuthError("token.json に refresh token がありません。")

    try:
        creds.refresh(Request())
    except RefreshError as e:
        # Testing の 7 日失効・パスワード変更・権限取り消しは invalid_grant になる
        if "invalid_grant" in str(e):
            raise GoogleAuthError(
                "トークン失効（invalid_grant）。refresh token が期限切れか取り消されています"
                "（Testing の 7 日失効・パスワード変更・6 か月未使用・アクセス取り消し）。"
            ) from e
        raise GoogleAuthError(f"トークンの更新に失敗しました: {type(e).__name__}") from e

    save_token(creds)
    return creds


def build_service(api: str, version: str, creds: Any | None = None) -> Any:
    """Google API の service を生成する（例: build_service("gmail", "v1")）."""
    from googleapiclient.discovery import build

    return build(api, version, credentials=creds or load_credentials(), cache_discovery=False)


# レート制限と一時的なサーバーエラーの再試行（Gmail・Calendar とも同じ判定でよい）
RETRY_MAX_ATTEMPTS = 5
RETRY_BASE_SECONDS = 2.0
_RATE_LIMIT_REASONS = {"rateLimitExceeded", "userRateLimitExceeded"}

# テストで差し替えるため、モジュール変数経由で呼ぶ
_sleep = time.sleep


def _is_retryable(error: Any) -> bool:
    status = error.resp.status
    if status == 429 or status >= 500:
        return True
    if status == 403:
        try:
            details = json.loads(error.content.decode("utf-8"))["error"]["errors"]
            return any(d.get("reason") in _RATE_LIMIT_REASONS for d in details)
        except (ValueError, KeyError, TypeError, AttributeError):
            return False
    return False


def execute(request: Any, api_name: str = "Google API") -> Any:
    """API リクエストを実行する。429・rateLimitExceeded・5xx は指数バックオフで再試行する."""
    from googleapiclient.errors import HttpError

    for attempt in range(RETRY_MAX_ATTEMPTS):
        try:
            return request.execute()
        except HttpError as e:
            if e.resp.status == 401:
                raise GoogleAuthError("トークンが API に拒否されました（401）。") from e
            if not _is_retryable(e) or attempt == RETRY_MAX_ATTEMPTS - 1:
                raise
            wait = RETRY_BASE_SECONDS * (2**attempt) + random.uniform(0, 1)
            print(f"[INFO] {api_name} のレート制限/一時エラー（HTTP {e.resp.status}）。{wait:.1f} 秒待って再試行します。", file=sys.stderr)
            _sleep(wait)
    raise AssertionError("unreachable")
