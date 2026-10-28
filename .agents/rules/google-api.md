---
trigger: glob
globs: scripts/google/**/*.py, scripts/gmail/**/*.py, scripts/gcal/**/*.py, docs/google/**/*.md
---

# Google API 共通認証ルール

Gmail・Google カレンダー連携が共有する OAuth 認証（`scripts/google/`）の運用ルール。GCP の準備・認可・失効対応の正本は [`docs/google/README.md`](../../docs/google/README.md)。

## スコープ

- スコープはサービス別（`GMAIL_SCOPES` / `CALENDAR_SCOPES`）に `scripts/google/client.py` にだけ定義し、`SCOPES` はその和集合にする。他のファイルにスコープ URL を書かない。
- token.json のスコープは和集合と**完全一致**だけを受け付ける（不足も過剰も拒否）。この検証を緩めるオプション・コード（部分一致、`OAUTHLIB_RELAX_TOKEN_SCOPE`、`include_granted_scopes`）を追加しない。
- スコープの追加・変更（全権 `calendar`、`gmail.modify` 等を含む）はコードを書く前にユーザーに相談する。Gmail 側の制約は [gmail.md](gmail.md)。

## 認証情報

- `client_secret.json` / `token.json` はリポジトリ外（既定 `%LOCALAPPDATA%\job-hunt\google\`、`JOB_HUNT_GOOGLE_DIR` で上書き）に置く。中身を読む・出力する・コミットすることはしない。エージェントは存在確認と `uv run python scripts/google/auth.py --check` だけを行う。
- 旧 `%LOCALAPPDATA%\job-hunt\gmail\` / `JOB_HUNT_GMAIL_DIR` へのフォールバックは作らない。
- 初回認可・再認可（`uv run python scripts/google/auth.py`）はブラウザでの同意が要るので、ユーザーが外部ターミナルで実行する（[playwright-action.md](playwright-action.md) と同じ方針）。終了コード 2 は再認可が必要という意味なので、そのコマンドをユーザーに案内して止まる。
- GCP 側の変更（API 有効化、同意画面・OAuth クライアントの操作）はユーザーが行う。エージェントは `gcloud services list --enabled` 等の読み取りで確かめるだけ。

## 実装

- service は `scripts.google.client.build_service(api, version)`、API 呼び出しは `execute()`（再試行・401→`GoogleAuthError`）を通す。サービス側（`scripts/gmail/client.py` 等）は薄いラッパーにとどめ、認証・再試行を重複実装しない。
- `GoogleAuthError` を捕まえたら `handoff_message()` を stderr に出して終了コード 2 にする。
