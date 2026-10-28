---
paths:
- scripts/gmail/**/*.py
- docs/gmail/**/*.md
- data/gmail/**/*.md
---

<!-- 自動生成ファイル: .agents/rules/gmail.md から scripts/dev/sync_agents.py で生成。直接編集せず .agents/rules/gmail.md を編集して再同期すること -->

# Gmail 読み取り連携ルール

就活関連メールを Gmail API で読み取り専用で検索・取得する連携（`scripts/gmail/`）の運用ルール。仕様・手順の正本は [`docs/gmail/README.md`](../../docs/gmail/README.md)、メールを読んで既存フローへ振り分ける手順はスキル [`read-job-mail`](../skills/read-job-mail/SKILL.md)。

## 読み取り専用の担保

- Gmail のスコープは `https://www.googleapis.com/auth/gmail.readonly` のみ。定義は `scripts/google/client.py` の `GMAIL_SCOPES` の 1 か所だけに置く（Calendar と共有する token.json の扱いは [google-api.md](google-api.md)）。
- 送信・下書き作成・ラベル変更・既読化・削除を行うコード（`messages.modify` / `send` / `trash` 等の呼び出し）やスコープを追加しない。必要になったらコードを書く前にユーザーに相談する。
- 返信文の下書きはチャット上で作ってよいが、送信は常にユーザーが Gmail で手で行う。

## 読む範囲（ラベル規則）

- 読むのは Gmail の `JOB` ラベルとその下位ラベルが付いたメールだけ。`JOB/RECRUITER` はリクルーターとのやり取り、`JOB/SCHEDULE` は面談等の日程調整。
- 規則の正本は `scripts/gmail/labels.py`（`ROOT_LABEL` / `CATEGORIES`）。ラベル名・分類はここ以外（スクリプト・スキル・ドキュメントのクエリ例）にハードコードしない。変えるときはここを直し、[`docs/gmail/README.md`](../../docs/gmail/README.md) §10 を合わせる。
- 範囲の制限はスクリプト側で必ずかける（検索は JOB 配下に限定、スレッド取得は JOB ラベルの無いものを拒否）。この制限を外すオプションやコードを追加しない。
- ラベルの付与はユーザーが Gmail で行う。期待したメールが見つからないときは、範囲外を探しに行かず、ラベルが付いているかをユーザーに確かめる。

## 認証情報

- 認証は Google カレンダー連携と共通（`scripts/google/`）。認証情報の置き場所・確認（`uv run python scripts/google/auth.py --check`）・再認可の案内は [google-api.md](google-api.md) に従う。

## メール本文の扱い

- メール本文は `data/gmail/`（gitignore 済・パブリック同期対象外）にだけ保存する。
- vault（企業ログ・リクルーターログ・面談ログ）には本文を写さず、要約と `data/gmail/threads/{thread_id}.md` への参照だけを書く。
- 外部向けの文章（返信下書き等）に `visibility: internal` の情報を混ぜない（[user-profile.md](user-profile.md)）。リクルーターへの返信は [recruiter-log.md](recruiter-log.md) の「リクルーターへの返信下書き」にも従う（独自調査の内容を持ち込まない、相手の発言の文脈を確かめる）。

## 公開同期への配慮

- `scripts/` `docs/` `.agents/` はパブリック同期される。クエリ例・テスト・ドキュメントに実在の個人アドレス・選考中の社名・スレッド ID を書かない（`from:example.co.jp` のような汎用例にする）。
