# Gmail 読み取り専用連携ガイド

就活関連メール（スカウト、面談日程調整、選考結果、媒体の通知）を Gmail API で**読み取り専用**で検索・取得するための、運用手順をまとめる（GCP の準備・認証は Google カレンダー連携と共通で [`docs/google/README.md`](../google/README.md)）。

- スコープは `https://www.googleapis.com/auth/gmail.readonly` のみ。送信・ラベル変更・既読化・削除はできない（既読化は `UNREAD` ラベルの除去＝modify 権限が必要なため、このスコープでは起こらない）。
- 認証はユーザー OAuth（Installed App フロー）で、Google カレンダー連携と同じ OAuth クライアント・`token.json` を共有する（[`docs/google/README.md`](../google/README.md)）。
- 読むのは **`JOB` ラベルとその下位ラベルが付いたメールだけ**（[§10 ラベル規則](#10-ラベル規則)）。

---

## 目次

- [1〜5. セットアップ・認証（共通）](#15-セットアップ認証共通)
6. [スクリプト一覧](#6-スクリプト一覧)
7. [検索・スレッド取得（`search_messages.py` / `fetch_thread.py`）](#7-検索スレッド取得search_messagespy--fetch_threadpy)
8. [保存形式（`data/gmail/`）](#8-保存形式datagmail)
9. [就活向けの検索クエリ例](#9-就活向けの検索クエリ例)
10. [ラベル規則](#10-ラベル規則)

---

## 1〜5. セットアップ・認証（共通）

GCP の準備、認証情報の置き場所、初回認可、トークン失効時の対処は Google カレンダー連携と共通なので [`docs/google/README.md`](../google/README.md) にまとめてある。

| 旧節 | 移動先 |
| --- | --- |
| 1. セットアップ（GCP の準備） | [docs/google §1](../google/README.md#1-セットアップgcp-の準備) |
| 2. 認証情報の置き場所 | [docs/google §2](../google/README.md#2-認証情報の置き場所)（`%LOCALAPPDATA%\job-hunt\google\`、`JOB_HUNT_GOOGLE_DIR`） |
| 3. トラブルシューティング（セットアップ） | [docs/google §3](../google/README.md#3-トラブルシューティングセットアップ) |
| 4. 初回認可（`auth.py`） | [docs/google §4](../google/README.md#4-初回認可authpy)（`uv run python scripts/google/auth.py` / `--check`） |
| 5. トークン失効時の対処 | [docs/google §5](../google/README.md#5-トークン失効時の対処) |

- Gmail のスコープは `gmail.readonly` のみ。定義は `scripts/google/client.py` の `GMAIL_SCOPES`（[docs/google §6](../google/README.md#6-スコープ)）。
- 終了コードは共通: 0 正常 / 1 エラー / 2 再認可が必要。

---

## 6. スクリプト一覧

| スクリプト | 役割 |
| --- | --- |
| `scripts/gmail/client.py` | Gmail API service の生成（`build_service()`）と再試行付き実行（`execute()`）。認証・再試行の本体は共通層 `scripts/google/client.py`。使えないときは `GoogleAuthError` を投げ、呼び出し側は終了コード 2 にする |
| `scripts/gmail/labels.py` | ラベル規則の正本（`ROOT_LABEL` / `CATEGORIES`）。検索範囲の Gmail 検索語の生成と、スレッドが JOB 配下かの判定 |
| `scripts/gmail/mime.py` | `format=raw` のメールを標準 `email` で解析。ヘッダの RFC 2047 デコード、本文（text/plain 優先、無ければ HTML をテキスト化）、添付のメタデータ |
| `scripts/gmail/search_messages.py` | JOB ラベル配下を Gmail 検索構文で検索し、ヒットしたスレッド一覧を保存。`--label` で分類ラベル配下に絞る。`--download` で本文も保存 |
| `scripts/gmail/fetch_thread.py` | スレッド ID を指定して本文を保存（JOB ラベルの無いスレッドは取得しない） |

`client.py` の `execute()` は共通層の再試行（429・`rateLimitExceeded` / `userRateLimitExceeded`（403）・5xx を指数バックオフ、401 は `GoogleAuthError`＝終了コード 2）をそのまま使う（[docs/google §7](../google/README.md#7-スクリプト一覧)）。

---

## 7. 検索・スレッド取得（`search_messages.py` / `fetch_thread.py`）

どちらもエージェントが実行してよい（読み取り専用。メールを既読にしない）。stdout は保存したファイルのパスだけ、進捗は stderr、終了コードは `scripts/google/auth.py` と同じ（2 = 再認可が必要）。

```powershell
# JOB 配下の直近 14 日を一覧だけ保存（本文は取らない）
uv run python scripts/gmail/search_messages.py --since 14d

# 日程調整（JOB/SCHEDULE）だけ、本文も保存
uv run python scripts/gmail/search_messages.py --label schedule --since 7d --download -n 5

# リクルーターとのやり取り（JOB/RECRUITER）を特定ドメインで絞り、ターミナルで見る
uv run python scripts/gmail/search_messages.py --label recruiter -q "from:example.co.jp" -n 10 --summary

# スレッド ID を指定して本文を保存（複数可）
uv run python scripts/gmail/fetch_thread.py --thread-id 19a0b1c2d3e4f567 19a0b1c2d3e4f568
```

| オプション | 対象 | 意味 |
| --- | --- | --- |
| `-q` / `--query` | search | Gmail の検索ボックスと同じ構文をそのまま渡す。ラベル範囲と AND になる（括弧で包むので、`OR` を書いても範囲外には広がらない） |
| `--since` | search | `newer_than:` の省略形（`7d` / `2m` / `1y`）。`-q` と併用すると AND |
| `-l` / `--label` | search | 分類ラベル配下に絞る（`recruiter` / `schedule`。§10）。省略時は JOB 配下すべて。`-q` / `--since` を省くとそのラベル配下を新しい順に一覧する |
| `-n` / `--limit` | 両方 | search: 一覧に載せるスレッド数の上限（既定 20）。fetch: 処理するスレッド数の上限 |
| `-d` / `--download` | search | ヒットしたスレッドの本文も `threads/` に保存する |
| `--thread-id` | fetch | 取得するスレッド ID（スペース区切りで複数、または複数回指定） |
| `--force` | 両方 | 保存済みスレッドを取り直す |
| `-s` / `--summary` | 両方 | 人間向けの一覧を stdout に出す |
| `--json` | 両方 | 結果を JSON で stdout に出す |

- 最初に `labels.list` でラベル ID と名前の対応を取り、検索範囲の語（例: `{label:job label:job-recruiter label:job-schedule}`）を作ってクエリの先頭に付ける。
- 一覧は `messages.list`（ID のみ）→ ヒットしたスレッドごとに最新ヒットの `messages.get(format=metadata)` で件名・From・日時・snippet を取る。`messages.list` は新しい順なので、一覧も新しい順。
- 本文は `threads.get(format=metadata)` でメッセージ ID を取り、各メッセージを `messages.get(format=raw)` で取る（`threads.get` に `raw` は無い）。
- 保存済みのスレッドは、フロントマターの `message_count` と現在のメッセージ数が同じなら本文を取り直さない（返信が来たスレッドだけ更新される）。`--force` で強制。
- 引用部分（`>` 行や「〜wrote:」以降）は削らずそのまま保存する。読み取り時に AI が判断する。
- クォータの目安（ユーザーあたり 6,000 units/分）: 一覧 1 スレッドあたり約 20 units、本文 1 通あたり 60 units（約 100 通/分）。`--limit` は小さめにし、大量取得は避ける。

## 8. 保存形式（`data/gmail/`）

`data/` は gitignore 済み。生メールはここにだけ置き、vault には要約だけを書く。

### `data/gmail/threads/{thread_id}.md`

ファイル名はスレッド ID のみ（件名は記号・長さ・個人情報の問題があるので使わない）。

| フロントマター | 内容 |
| --- | --- |
| `id` | スレッド ID |
| `source` / `type` | `gmail` / `thread` |
| `subject` | 最初のメッセージの件名 |
| `participants` | From / To / Cc に出てきたアドレス（`表示名 <addr>`、重複なし） |
| `first_date` / `last_date` | 最初・最後のメッセージの日時（`internalDate`、ローカルタイムの ISO 8601） |
| `message_count` | メッセージ数（再取得の判定に使う） |
| `labels` | スレッド内メッセージのラベル名の和集合（`INBOX`、`CATEGORY_*`、`JOB/RECRUITER` 等） |
| `url` | Gmail で開く URL（`https://mail.google.com/mail/u/0/#all/{thread_id}`） |
| `fetched_at` | 取得日時 |

本文は古い順にメッセージごとの `## {n}. {日時} — {From}` 見出し＋To / Cc / 添付（ファイル名・種類・サイズのみ。中身は保存しない）＋本文テキスト。HTML のみのメールはテキスト化した旨を書く。

### `data/gmail/searches/YYYY-MM-DD-HHmmss_{slug}.md` / `.json`

- フロントマター: `source: gmail`, `type: searches`, `query`（`-q` と `--since` から作ったクエリ）, `label`（`--label` のキー、省略時 `all`）, `gmail_query`（ラベル範囲を付けて実際に投げたクエリ）, `result_size_estimate`（Gmail の概算ヒット数）, `thread_count`, `fetched_at`
- 本文: スレッド一覧表（日時・From・件名・ヒット数・保存先）と、各スレッドの thread_id / ラベル名 / snippet / Gmail URL
- `.json` は同じ内容を `threads` 配列で持つ（各行の `labels` はラベル名）。
- `slug` は `label` とクエリをファイル名用に置き換えて 40 文字で切ったもの。

### 文字コード

- 本文・ヘッダは名乗っている charset で読み、失敗したら日本語メール向けにフォールバックする（`mime.py` の `decode_bytes`）。
- ISO-2022-JP は JIS→CP932 に変換してから読む。Outlook 等が送る NEC 特殊文字（①、㈱）や IBM 拡張文字（髙）を正しく読むため（標準の `iso2022_jp` は 89〜92 区を別の漢字に化けさせる）。Shift_JIS は CP932 で読む。
- どれでも読めなければ `errors="replace"`（`�`）で必ず文字列にする。

## 9. 就活向けの検索クエリ例

どのクエリも JOB 配下に限られる（§10）。分類ラベルで足りるものは `--label` を使い、`-q` はその中の絞り込みに使う。

| 用途 | オプション例 |
| --- | --- |
| 最近の就活メール全体 | `--since 14d` |
| 面談・面接の日程調整 | `--label schedule --since 14d` |
| リクルーターとのやり取り | `--label recruiter --since 30d` |
| 媒体からの通知・スカウト | `-q "from:(bizreach.jp OR findy-code.io OR forkwell.com OR green-japan.com OR youtrust.jp)"` |
| 選考結果 | `-q "subject:(選考結果 OR 選考のご連絡 OR 結果のご連絡)"` |
| 特定の会社・担当者 | `-q "from:example.co.jp"` / `-q '"株式会社サンプル"'` |
| カレンダー招待 | `-q "filename:ics" --since 30d` |
| 未読だけ | `-q "is:unread"` ＋上記（取得しても既読にはならない） |

- 媒体のドメインは送信元が変わることがあるので、ヒットしないときは `--summary` で From を確かめて調整する。
- 届いているはずのメールが出てこないときは、Gmail で JOB ラベルが付いているかをユーザーに確かめてもらう。

## 10. ラベル規則

このリポジトリが読むメールの範囲と分類は Gmail のラベルで決める。正本は [`scripts/gmail/labels.py`](../../scripts/gmail/labels.py)（`ROOT_LABEL` / `CATEGORIES`）で、規則を変えるときはそこだけを直し、この節と [`.agents/rules/gmail.md`](../../.agents/rules/gmail.md) の説明を合わせる。

| ラベル | `--label` | 意味 |
| --- | --- | --- |
| `JOB` | （省略時） | 就活に関するメール。**このラベル（と下位ラベル）が付いていないメールは検索・取得しない** |
| `JOB/RECRUITER` | `recruiter` | リクルーター・エージェント・ヘッドハンターとのやり取り |
| `JOB/SCHEDULE` | `schedule` | 面談・面接などの日程調整 |

- ラベルの作成・付与はユーザーが Gmail で行う（スコープは `gmail.readonly` なので、スクリプトからは付けられない）。送信元が決まっているものは Gmail のフィルタで自動付与しておくと漏れが減る。
- 下位ラベルだけが付いたメール（例: `JOB/SCHEDULE` だけ）も JOB 配下として扱う。Gmail の `label:` 検索は下位ラベルを含まないため、スクリプトは配下のラベルを列挙して OR にする（Gmail 検索ではラベル名の `/` と空白をハイフンにした `label:job-schedule` の形で書く）。
- 規則に無い下位ラベル（例: `JOB/OFFER`）を Gmail で作っても JOB 配下として読まれる。`--label` で指定したい分類は `CATEGORIES` に追加する。
- 二重の担保として、`fetch_thread.py`（`search_messages.py --download` も同じ処理）は JOB 配下のラベルが 1 通も付いていないスレッドの本文を取らない（`[エラー] ... JOB ラベルが付いていないため取得しません`、終了コード 1）。
- Gmail に `JOB`（`--label` 指定時はその分類ラベル）が無い場合、`search_messages.py` は検索せず終了コード 1 で止まる。
