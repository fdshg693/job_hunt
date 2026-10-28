# Findy 求人探索・自動化スクリプト利用ガイド

本ディレクトリでは、Findy（[findy-code.io](https://findy-code.io/)）を活用した求人情報の検索・収集、おすすめ求人取得、いいね・メッセージ取得、プロフィール取得、および職歴・プロジェクトのCRUD管理を行うためのスクリプト群の使い方と運用手順をまとめています。

> [!TIP]
> サイト構造・主要画面・DOMセレクタ・Next.jsデータ構造の詳細は [site_structure.md](site_structure.md) を参照してください。
> GraphQL API による職歴更新の詳細は [work_history_api.md](work_history_api.md) を参照してください。

---

## 目次

1. [概要とできること](#1-概要とできること)
2. [スクリプト構成一覧](#2-スクリプト構成一覧)
3. [前提条件と環境準備](#3-前提条件と環境準備)
4. [各スクリプトの詳細な使い方](#4-各スクリプトの詳細な使い方)
   - [4.1 おすすめ求人取得・保存: `fetch_recommends.py`](#41-おすすめ求人取得保存-fetch_recommendspy)
   - [4.2 いいね一覧取得・認証ハンドオフ: `navigate_likes.py`](#42-いいね一覧取得認証ハンドオフ-navigate_likespy)
   - [4.3 メッセージ・スカウト一覧取得: `navigate_messages.py`](#43-メッセージスカウト一覧取得-navigate_messagespy)
   - [4.4 プロフィール（キャリア・スキル）取得: `fetch_profile.py`](#44-プロフィールキャリアスキル取得-fetch_profilepy)
   - [4.5 職歴・プロジェクトCRUD管理: `manage_work_history.py`](#45-職歴プロジェクトcrud管理-manage_work_historypy)
   - [4.6 公開求人オンライン検索: `search_online.py`](#46-公開求人オンライン検索-search_onlinepy)
   - [4.7 求人詳細単体取得: `fetch_job.py`](#47-求人詳細単体取得-fetch_jobpy)
5. [実践シナリオ別ワークフロー](#5-実践シナリオ別ワークフロー)
6. [認証・ブラウザ操作の制約とトラブルシューティング](#6-認証ブラウザ操作の制約とトラブルシューティング)
7. [データ格納仕様](#7-データ格納仕様)

---

## 1. 概要とできること

Findyにおける求人探索・プロフィール管理の効率化を目的として、以下の機能を提供します。

- **おすすめ求人の取得・フィルタ**: Findyの推薦アルゴリズム準拠のおすすめ求人（`/recommends?sort=recommend`）を取得し、年収・リモート条件で絞り込み保存（`fetch_recommends.py`）。
- **いいね求人の自動収集**: 企業やエージェントから受け取った「いいね」求人を、ブラウザセッション経由で自動取得・履歴保存（`navigate_likes.py`）。
- **メッセージ・スカウト一覧の収集**: 受信したメッセージやスカウト一覧を自動取得・履歴保存（`navigate_messages.py`）。
- **プロフィール（キャリア・スキル）の自動取得**: 職歴・プロジェクト詳細・保有スキル年数・AI活用・自己PR等をGraphQL APIから網羅的に取得・Markdown保存（`fetch_profile.py`）。
- **職歴・プロジェクトのCRUD管理**: キャリア・スキル画面（`/me/career-skills`）における所属企業（workHistories）やプロジェクト（workHistoryProjects）の作成・更新・削除。事前バックアップ・安全ガード付き（`manage_work_history.py`）。
- **公開求人のオンライン検索**: 企業名や技術スタック（Go, Python, TypeScript等）から公開求人を即座に探索・一括ダウンロード（`search_online.py`）。
- **構造化Markdownでの求人保存**: 求人詳細・年収レンジ・技術要件・リモート区分をフロントマター付きMarkdownでローカル永続化（`fetch_job.py`）。
- **全サイト横断高速フィルタ**: `scripts/common/search_local_jobs.py` と連携し、他サイト求人と横断検索可能。
- **安全な認証ハンドオフ**: 未ログイン時は共通認証エンジン（`scripts/common/auth_engine.py`）によりOSトースト通知を発行し、資格情報をコンテキストに漏洩させることなく外部ターミナルでの手動ログイン完了を待機。

---

## 2. スクリプト構成一覧

| スクリプト | 種別 | 主な役割 |
|---|---|---|
| [`scripts/findy/fetch_recommends.py`](../../scripts/findy/fetch_recommends.py) | Python CLI | おすすめ求人（sort=recommend）の取得・条件フィルタ・保存・詳細ダウンロード |
| [`scripts/findy/navigate_likes.py`](../../scripts/findy/navigate_likes.py) | Python CLI | いいね一覧の自動遷移・認証確認・データ抽出・履歴保存 |
| [`scripts/findy/navigate_messages.py`](../../scripts/findy/navigate_messages.py) | Python CLI | メッセージ・スカウト一覧の自動取得・履歴保存・サマリ表示 |
| [`scripts/findy/fetch_profile.py`](../../scripts/findy/fetch_profile.py) | Python CLI | プロフィール（キャリア・スキル）画面から構造化データを取得・Markdown/JSON保存 |
| [`scripts/findy/manage_work_history.py`](../../scripts/findy/manage_work_history.py) | Python CLI | 職歴（所属企業）およびプロジェクトの作成・参照・更新・削除管理 |
| [`scripts/findy/search_online.py`](../../scripts/findy/search_online.py) | Python CLI | 公開求人検索の実行、条件フィルタ、ヒット求人の一括ダウンロード |
| [`scripts/findy/fetch_job.py`](../../scripts/findy/fetch_job.py) | Python CLI | 指定URLの求人詳細を取得し、`data/findy/jobs/` にMarkdown保存 |
| [`scripts/findy/fetch_recommends.mjs`](../../scripts/findy/fetch_recommends.mjs) | Playwright JS | おすすめ求人ページ（`/recommends?sort=recommend`）からのJSONデータ抽出 |
| [`scripts/findy/fetch_profile.mjs`](../../scripts/findy/fetch_profile.mjs) | Playwright JS | `/me/career-skills` 画面でGraphQL通信をインターセプトし完全なデータを抽出 |
| [`scripts/findy/manage_work_history.mjs`](../../scripts/findy/manage_work_history.mjs) | Playwright JS | GraphQL Mutation による職歴・プロジェクトのCRUD操作 |
| [`scripts/findy/navigate_likes.mjs`](../../scripts/findy/navigate_likes.mjs) | Playwright JS | `/likes` に遷移し、求人カード情報をパースして抽出 |
| [`scripts/findy/navigate_messages.mjs`](../../scripts/findy/navigate_messages.mjs) | Playwright JS | `/matches` に遷移し、メッセージ・スカウト一覧を抽出 |

> [!NOTE]
> 認証状態の判定および未認証時の手動ログイン待機ハンドオフは、共通認証エンジン（[`scripts/common/auth_engine.py`](../../scripts/common/auth_engine.py), [`scripts/common/js/universal_auth.mjs`](../../scripts/common/js/universal_auth.mjs)）により自動制御されます。個別スクリプトは不要です。

---

## 3. 前提条件と環境準備

- **Python**: 3.13 以上（`uv` 使用）
- **ブラウザプロファイル**: 認証が必要な操作（おすすめ、いいね、メッセージ、プロフィール、職歴管理）は共通プロファイル `job-hunt` を利用します。
  - 格納先: `%LOCALAPPDATA%\claude-browser-profiles\job-hunt`

---

## 4. 各スクリプトの詳細な使い方

### 4.1 おすすめ求人取得・保存: `fetch_recommends.py`

Findyの推薦アルゴリズムによるおすすめ求人一覧を取得し、条件での絞り込みや求人詳細の一括ダウンロードを行います。

```powershell
# 1. おすすめ求人を最新15件取得して保存
uv run python scripts/findy/fetch_recommends.py -n 15

# 2. 年収800万以上、フルリモートで絞り込み、サマリ表示
uv run python scripts/findy/fetch_recommends.py --min-salary 800 --remote "フルリモート" --summary

# 3. ヒットしたおすすめ求人の詳細を一括ダウンロード保存
uv run python scripts/findy/fetch_recommends.py -n 5 --download
```

### 4.2 いいね一覧取得・認証ハンドオフ: `navigate_likes.py`

企業やエージェントから受け取った「いいね」一覧を取得・保存します。

```powershell
# 企業からのいいねを取得
uv run python scripts/findy/navigate_likes.py --summary

# エージェントからのいいねを取得
uv run python scripts/findy/navigate_likes.py --tab agent --summary

# マッチ済み（いいかも済み）の求人を除外し、判断待ちだけを表示・保存
uv run python scripts/findy/navigate_likes.py --exclude-matched --summary
```

- 各求人に `match_status`（`pending`: 判断待ち / `matched`: マッチ済み / `unknown`: 判定不明）が付く。Markdown の表には「状態」列、JSON の各 job には `match_status` が入る。過去の保存 JSON には無いので、読む側は欠落を `unknown` として扱う。
- `--exclude-matched` は `matched` だけを落とす（`unknown` は判断待ちを取りこぼさないよう残す）。保存ファイルもフィルタ後の内容になり、フロントマターに `exclude_matched: true` と `excluded_count` を記録する。全件の履歴が必要ならオプション無しで取得する。
- 1 ページ目（`/likes?page=1`）のみ取得する。ページングには未対応。

### 4.3 メッセージ・スカウト一覧取得: `navigate_messages.py`

受信したメッセージ・スカウト一覧を取得・保存します。

```powershell
# すべてのメッセージを取得
uv run python scripts/findy/navigate_messages.py --summary

# 未返信メッセージのみを取得
uv run python scripts/findy/navigate_messages.py --tab unreplied --summary
```

### 4.4 プロフィール（キャリア・スキル）取得: `fetch_profile.py`

現在のFindy登録情報（職歴、プロジェクト、スキル、自己PR等）を完全取得し、`data/findy/profile/` に保存します。

```powershell
uv run python scripts/findy/fetch_profile.py
uv run python scripts/findy/fetch_profile.py --summary
```

### 4.5 職歴・プロジェクトCRUD管理: `manage_work_history.py`

Findy上の職歴（所属企業）やプロジェクトの安全な追加・更新・削除を行います。

```powershell
# 1. 職歴一覧の参照
uv run python scripts/findy/manage_work_history.py --action list --summary

# 2. 所属企業の追加（dry-run）
uv run python scripts/findy/manage_work_history.py --action add_work_history --company-name "サンプル株式会社" --dry-run

# 3. プロジェクトの追加
uv run python scripts/findy/manage_work_history.py --action add_project --work-history-id "123" --project-title "基幹システム刷新"
```

### 4.6 公開求人オンライン検索: `search_online.py`

公開求人検索を実行し、キーワードや年収での絞り込み、詳細一括ダウンロードを行います。

```powershell
uv run python scripts/findy/search_online.py "Go" --min-salary 800 --summary
uv run python scripts/findy/search_online.py "Python" -n 5 --download
```

### 4.7 求人詳細単体取得: `fetch_job.py`

URLまたはIDを指定して求人詳細を取得・保存します。

```powershell
uv run python scripts/findy/fetch_job.py "https://findy-code.io/companies/123/jobs/456"
```

---

## 5. 実践シナリオ別ワークフロー

### シナリオ: 毎朝のおすすめ求人・スカウト巡回

```powershell
# 1. おすすめ求人の新着チェック
uv run python scripts/findy/fetch_recommends.py -n 10 --summary

# 2. 新着スカウト・メッセージの確認
uv run python scripts/findy/navigate_messages.py --summary

# 3. 気になる求人をダウンロードして横断検索で比較
uv run python scripts/common/search_local_jobs.py --source findy --detail
```

---

## 6. 認証・ブラウザ操作の制約とトラブルシューティング

未ログインが検知された場合、スクリプトはトースト通知を発行し待機状態に入ります。外部ターミナルで以下を実行してログインしてください：

```powershell
playwright-cli -s=job-hunt open https://findy-code.io/users/sign_in --headed --profile="$env:LOCALAPPDATA\claude-browser-profiles\job-hunt"
```

---

## 7. データ格納仕様

```text
data/findy/
  ├── jobs/              # 求人詳細Markdown ({job_id}.md)
  ├── likes/             # いいね履歴 (YYYY-MM-DD-HH.md / .json)
  ├── messages/          # メッセージ履歴 (YYYY-MM-DD-HH.md / .json)
  ├── recommends/        # おすすめ求人履歴 (YYYY-MM-DD-HHMMSS.md / .json)
  ├── profile/           # キャリア・スキル (latest.md / latest.json / backups/)
  └── searches/          # 検索結果一覧
```
