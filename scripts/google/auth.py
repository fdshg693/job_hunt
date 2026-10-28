"""Google API（Gmail・Calendar 共通）の初回認可・トークン確認 CLI.

- 引数なし: ブラウザで同意して token.json を作り直す（ユーザーが自分の外部ターミナルで実行する）
- --check: 既存トークンが使えるかを Gmail・Calendar の両方で確かめ、失効の目安までの残り日数を stderr に出す（エージェントが使う）

終了コード: 0 正常 / 1 エラー / 2 未認可・失効・スコープ不一致（ユーザーの再認可が必要）
"""

from __future__ import annotations

import contextlib
import sys
from datetime import UTC, datetime
from pathlib import Path

# プロジェクトルートパス (scripts/google/ の2階層上)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.cli import EntrypointContext, create_base_parser, entrypoint_guard
from scripts.google.client import (
    SCOPES,
    GoogleAuthError,
    build_service,
    check_scopes,
    client_secret_path,
    describe_scopes,
    estimated_expiry,
    load_credentials,
    read_authorized_at,
    save_token,
)


def authorize(ctx: EntrypointContext) -> Path:
    """Installed App フローで同意を取り、token.json を保存する."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    secret = client_secret_path()
    if not secret.exists():
        raise GoogleAuthError(
            f"{secret} がありません。docs/google/README.md の「1.5 OAuth クライアント」に従って配置してください。"
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    ctx.info("ブラウザで Google アカウントを選び、表示されたアクセス権限（Gmail の閲覧・カレンダー）にすべてチェックを入れてください。")
    ctx.info("「Google はこのアプリを確認していません」と出たら「続行」を選びます（Testing 状態のため）。")
    try:
        # 認可 URL の案内は stdout に出るので stderr へ逃がす（stdout はパス専用）
        with contextlib.redirect_stdout(sys.stderr):
            creds = flow.run_local_server(
                port=0,
                open_browser=True,
                success_message="認可が完了しました。このタブを閉じてターミナルに戻ってください。",
            )
    except Warning as e:
        # 分割同意でスコープのチェックを外すと oauthlib が "Scope has changed" を投げる（old_scope / new_scope 付き）
        missing = set(getattr(e, "old_scope", None) or []) - set(getattr(e, "new_scope", None) or [])
        detail = f"外されたもの: {describe_scopes(missing)}" if missing else str(e)
        raise GoogleAuthError(
            f"要求したアクセス権限の一部が許可されませんでした（{detail}）。すべてにチェックを入れて再実行してください。"
        ) from e

    check_scopes(creds.granted_scopes or creds.scopes)
    authorized_at = datetime.now(UTC)
    path = save_token(creds, authorized_at=authorized_at)
    ctx.info(f"token.json を保存しました。失効の目安: {estimated_expiry(authorized_at).astimezone():%Y-%m-%d %H:%M}（Testing 状態は 7 日）")
    return path


def _probe(name: str, request: object) -> None:
    """軽い API 呼び出しを 1 回だけ行う。結果（メールアドレス・カレンダー名）は出力しない."""
    from googleapiclient.errors import HttpError

    try:
        request.execute()  # type: ignore[attr-defined]
    except HttpError as e:
        if e.resp.status == 401:
            raise GoogleAuthError(f"トークンが {name} API に拒否されました（401）。") from e
        raise RuntimeError(
            f"{name} API の呼び出しに失敗しました（HTTP {e.resp.status}）。API の有効化を確認してください（docs/google/README.md §1.3）。"
        ) from e


def check(ctx: EntrypointContext) -> None:
    """トークンを読み込み（必要なら refresh）、Gmail・Calendar を 1 回ずつ呼んで使えることを確かめる."""
    creds = load_credentials()
    _probe("Gmail", build_service("gmail", "v1", creds).users().getProfile(userId="me"))
    _probe("Calendar", build_service("calendar", "v3", creds).calendarList().list(maxResults=1))

    ctx.info("トークンは有効です（Gmail: gmail.readonly / Calendar: events.owned・events.freebusy・calendarlist.readonly）。")
    authorized_at = read_authorized_at()
    if authorized_at is None:
        ctx.warn("認可日時が記録されていないため、失効の目安が分かりません。")
        return
    expiry = estimated_expiry(authorized_at)
    remaining = expiry - datetime.now(UTC)
    days = remaining.total_seconds() / 86400
    message = f"失効の目安: {expiry.astimezone():%Y-%m-%d %H:%M}（残り約 {days:.1f} 日）"
    if days < 1:
        ctx.warn(f"{message}。大事な予定の前に再認可しておくと安全です。")
    else:
        ctx.info(message)


def main() -> int:
    parser = create_base_parser(
        description="Google API（Gmail・Calendar）の初回認可（ブラウザ同意）とトークン確認",
        examples=[
            "uv run python scripts/google/auth.py  # ユーザーが自分のターミナルで実行（ブラウザで同意）",
            "uv run python scripts/google/auth.py --check  # トークンが使えるか確かめる（エージェント用）",
        ],
        related=[
            "scripts/gmail/search_messages.py: 次に使う（認可後に Gmail を検索する）",
            "scripts/gcal/find_slots.py: 次に使う（認可後にカレンダーの空きを出す）",
        ],
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="既存トークンが使えるかだけを確かめる（ブラウザは開かない）",
    )
    args = parser.parse_args()

    with entrypoint_guard(summary=args.summary, json_mode=args.json) as ctx:
        try:
            if args.check:
                check(ctx)
            else:
                ctx.add_result_path(authorize(ctx))
        except GoogleAuthError as e:
            ctx.error(e.handoff_message())
            ctx.set_exit_code(2)
        return ctx.flush_outputs()


if __name__ == "__main__":
    sys.exit(main())
