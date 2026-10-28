# Forkwell 自動化スクリプト利用ガイド

本ディレクトリでは、Forkwell Jobs（[jobs.forkwell.com](https://jobs.forkwell.com/)）における求人検索、求人詳細ダウンロード、プロフィール取得、およびプロフィール（自己紹介・やりたいこと・スカウト等）・職歴のCRUD管理を行うためのスクリプト群の使い方と運用手順をまとめています。

> [!TIP]
> サイト構造・主要画面・DOMセレクタ・API仕様の詳細は [site_structure.md](site_structure.md) を参照してください。

---

## 目次

1. [概要とできること](#1-概要とできること)
2. [スクリプト構成一覧](#2-スクリプト構成一覧)
3. [前提条件と環境準備](#3-前提条件と環境準備)
4. [各スクリプトの詳細な使い方](#4-各スクリプトの詳細な使い方)
   - [4.1 求人検索・詳細一括ダウンロード: `search_jobs.py`](#41-求人検索詳細一括ダウンロード-search_jobspy)
   - [4.2 求人詳細単体取得: `fetch_job.py`](#42-求人詳細単体取得-fetch_jobpy)
   - [4.3 プロフィール情報取得・永続化: `fetch_profile.py`](#43-プロフィール情報取得永続化-fetch_profilepy)
   - [4.4 プロフィール（自己紹介・やりたいこと）管理: `manage_profile.py`](#44-プロフィール自己紹介やりたいこと管理-manage_profilepy)
   - [4.5 職歴・プロジェクトCRUD管理: `manage_work_history.py`](#45-職歴プロジェクトcrud管理-manage_work_historypy)
   - [4.6 メッセージ・スカウト一覧取得: `navigate_messages.py`](#46-メッセージスカウト一覧取得-navigate_messagespy)
5. [実践シナリオ別ワークフロー](#5-実践シナリオ別ワークフロー)
6. [データ格納仕様](#6-データ格納仕様)

---

## 1. 概要とできること

Forkwellにおける求人探索・情報収集および自身のプロフィール運用の効率化を目的として、以下の機能を提供します。

- **公開求人の検索 & 一覧永続化**: キーワード、年収、勤務地、リモート形態等の条件でForkwell上の求人を検索し、検索結果一覧Markdown/JSONを自動生成（`search_jobs.py`）。
- **求人詳細の一括ダウンロード**: 検索結果でヒットした求人詳細を一括取得し、公式API（`/api/v1/jobs/{id}`）またはHTMLパースにより `data/forkwell/jobs/{id}.md` として自動保存。
- **求人詳細単体取得**: 特定の求人URLまたはIDから、募集要項・仕事内容・必須/歓迎要件・就業条件・技術スタックを構造化Markdownとして取得・保存（`fetch_job.py`）。
- **プロフィール・設定情報の自動取得**: ダッシュボード（`/dashboard`, `/dashboard/preferences`, `/dashboard/skills`）から登録情報を完全取得し、構造化Markdown/JSON（`latest.md` / `latest.json`）として永続化（`fetch_profile.py`）。
- **プロフィール（自己紹介・やりたいこと）更新管理**: 自己紹介（Bio）、やりたい・目指したいこと（Career Vision）、スカウト設定の閲覧・安全な更新（事前バックアップ・dry-run付き、`manage_profile.py`）。
- **職歴・プロジェクトCRUD管理**: 所属企業・担当プロジェクトの参照・追加・更新・削除を自動化（事前バックアップ・dry-run・安全ガード付き、`manage_work_history.py`）。
- **メッセージ・スカウトの自動取得 & 永続化**: インボックス（`/inbox`）から「スカウト・やりとり」および「アーカイブ」のメッセージ一覧・詳細本文・提示条件・添付求人を構造化Markdown/JSONとして自動取得（`navigate_messages.py`）。
- **プロジェクト共通求人フォーマット対応**: 保存された求人は共通仕様（`.agents/rules/job-data-format.md`）に準拠し、`scripts/common/search_local_jobs.py` で他媒体と横断検索可能。
- **安全な認証ハンドオフ**: 未ログイン時は共通認証エンジン（`scripts/common/auth_engine.py`）によりOSトースト通知を発行し、資格情報をコンテキストに漏洩させることなく外部ターミナルでの手動ログイン完了を待機。

---

## 2. スクリプト構成一覧

| スクリプト | 種別 | 主な役割 |
|---|---|---|
| [`scripts/forkwell/search_jobs.py`](../../scripts/forkwell/search_jobs.py) | Python CLI | 求人検索・条件絞り込み・検索結果保存・求人詳細一括ダウンロード |
| [`scripts/forkwell/fetch_job.py`](../../scripts/forkwell/fetch_job.py) | Python CLI | 単体求人詳細（URL/ID）の取得・Markdown構造化保存（API/HTML） |
| [`scripts/forkwell/fetch_profile.py`](../../scripts/forkwell/fetch_profile.py) | Python CLI | プロフィール（ダッシュボード・希望条件・スキル）の自動取得・永続化 |
| [`scripts/forkwell/manage_profile.py`](../../scripts/forkwell/manage_profile.py) | Python CLI | 自己紹介・やりたいこと・スカウト受取設定の閲覧・更新管理 |
| [`scripts/forkwell/manage_work_history.py`](../../scripts/forkwell/manage_work_history.py) | Python CLI | 職歴（企業）およびプロジェクトの作成・参照・更新・削除管理 |
| [`scripts/forkwell/navigate_messages.py`](../../scripts/forkwell/navigate_messages.py) | Python CLI | メッセージ・スカウト一覧・詳細の自動取得・タブ切り替え・ファイル保存 |
| [`scripts/forkwell/fetch_profile.mjs`](../../scripts/forkwell/fetch_profile.mjs) | Playwright JS | ダッシュボードDOMから構造化プロフィールデータを抽出 |
| [`scripts/forkwell/manage_profile.mjs`](../../scripts/forkwell/manage_profile.mjs) | Playwright JS | プロフィール設定画面におけるフォーム入力・送信・API操作 |
| [`scripts/forkwell/manage_work_history.mjs`](../../scripts/forkwell/manage_work_history.mjs) | Playwright JS | 職歴・プロジェクト設定画面におけるフォーム入力・CRUD操作 |
| [`scripts/forkwell/navigate_messages.mjs`](../../scripts/forkwell/navigate_messages.mjs) | Playwright JS | インボックスDOMからタブ切り替え・カード・詳細本文を抽出 |

> [!NOTE]
> 認証状態の判定および未認証時の手動ログイン待機ハンドオフは、共通認証エンジン（[`scripts/common/auth_engine.py`](../../scripts/common/auth_engine.py), [`scripts/common/js/universal_auth.mjs`](../../scripts/common/js/universal_auth.mjs)）により自動制御されます。個別スクリプトは不要です。

---

## 3. 前提条件と環境準備

- **Python**: 3.13 以上（`uv` 使用）
- **ブラウザプロファイル**: 認証が必要な操作（プロフィール取得・更新、職歴管理）は共通プロファイル `job-hunt` を利用します。
  - 格納先: `%LOCALAPPDATA%\claude-browser-profiles\job-hunt`

---

## 4. 各スクリプトの詳細な使い方

### 4.1 求人検索・詳細一括ダウンロード: `search_jobs.py`

Forkwell Jobs の検索画面からキーワードや年収、リモート条件で求人を検索し、検索結果一覧ファイルと求人詳細を一括保存します。

```powershell
# 1. キーワード検索（ヒット求人の一覧Markdown/JSON保存）
uv run python scripts/forkwell/search_jobs.py "Go" -n 10

# 2. 年収・フルリモートで絞り込み、サマリを表示
uv run python scripts/forkwell/search_jobs.py "Python" --min-salary 800 --remote "フルリモート" --summary

# 3. 検索ヒット求人の詳細Markdownを一括ダウンロード保存
uv run python scripts/forkwell/search_jobs.py "TypeScript" -n 5 --download
```

### 4.2 求人詳細単体取得: `fetch_job.py`

URLまたはIDを指定して求人詳細をローカルMarkdownとして保存します。

```powershell
# URLまたはIDを指定して取得
uv run python scripts/forkwell/fetch_job.py "https://jobs.forkwell.com/jobs/12345"
uv run python scripts/forkwell/fetch_job.py "12345" --summary
```

### 4.3 プロフィール情報取得・永続化: `fetch_profile.py`

現在のForkwell登録情報（ユーザー情報、希望条件、スキル）を完全取得し、`data/forkwell/profile/` に保存します。

```powershell
uv run python scripts/forkwell/fetch_profile.py
uv run python scripts/forkwell/fetch_profile.py --summary
```

### 4.4 プロフィール（自己紹介・やりたいこと）管理: `manage_profile.py`

自己紹介（Bio）、やりたいこと（Career Vision）、スカウト設定の閲覧・更新を行います。

```powershell
# 1. 現在の設定内容を閲覧
uv run python scripts/forkwell/manage_profile.py --action view --summary

# 2. 自己紹介の更新（dry-run で差分プレビュー）
uv run python scripts/forkwell/manage_profile.py --action update_bio --bio "Go/Pythonを活用したバックエンド開発..." --dry-run

# 3. 自己紹介の更新実行（事前バックアップが自動取得されます）
uv run python scripts/forkwell/manage_profile.py --action update_bio --bio "Go/Pythonを活用したバックエンド開発..."

# 4. やりたいことの更新
uv run python scripts/forkwell/manage_profile.py --action update_vision --vision "LLMやクラウドネイティブ技術の活用..."
```

### 4.5 職歴・プロジェクトCRUD管理: `manage_work_history.py`

職歴（所属企業）やプロジェクトの安全な追加・更新・削除を行います。

```powershell
# 1. 現在の職歴一覧を表示
uv run python scripts/forkwell/manage_work_history.py --action list --summary

# 2. 企業の追加（dry-run）
uv run python scripts/forkwell/manage_work_history.py --action add_company --company-name "サンプル株式会社" --dry-run

# 3. 企業の追加実行
uv run python scripts/forkwell/manage_work_history.py --action add_company --company-name "サンプル株式会社"

# 4. プロジェクトの追加
uv run python scripts/forkwell/manage_work_history.py --action add_project --company-id "123" --project-title "マイクロサービス刷新" --summary
```

### 4.6 メッセージ・スカウト一覧取得: `navigate_messages.py`

Forkwell Jobs のインボックス（`/inbox`）からメッセージおよびスカウト一覧・詳細を取得・永続化します。

```powershell
# 1. アクティブなスカウト・やりとり一覧を取得・サマリ表示（デフォルト）
uv run python scripts/forkwell/navigate_messages.py --summary

# 2. アーカイブされたメッセージを取得
uv run python scripts/forkwell/navigate_messages.py --tab archive --summary

# 3. すべて（やりとり＋アーカイブ）を取得
uv run python scripts/forkwell/navigate_messages.py --tab all --summary

# 4. 件数を制限して取得（例: 5件）
uv run python scripts/forkwell/navigate_messages.py --limit 5 --summary

# 5. 高速一覧取得（詳細本文のクリック取得をスキップ）
uv run python scripts/forkwell/navigate_messages.py --no-details --summary
```

### 4.7 Playwright 補助スクリプト (`scripts/forkwell/*.mjs`)

各Python CLIから呼び出されるブラウザ自動化補助スクリプト群です。共通プロファイル `job-hunt` の下で実行されます。

---

## 5. 実践シナリオ別ワークフロー

### シナリオ: 高年収リモート求人の収集とプロフィール同期

```powershell
# 1. Forkwell から希望求人を収集
uv run python scripts/forkwell/search_jobs.py "Go" --min-salary 850 --remote "フルリモート" --download --summary

# 2. 横断検索で他サイトの求人と比較
uv run python scripts/common/search_local_jobs.py -s Go --min-salary 850 --remote "フルリモート"

# 3. 現在の Forkwell プロフィールをバックアップ取得
uv run python scripts/forkwell/fetch_profile.py --summary
```

---

## 6. データ格納仕様

```text
data/forkwell/
  ├── jobs/
  │   └── {job_id}.md        # 求人詳細Markdown（job-data-format準拠）
  ├── searches/
  │   ├── YYYY-MM-DD-HHMMSS_{query}.md   # 検索結果一覧
  │   └── YYYY-MM-DD-HHMMSS_{query}.json # 検索結果JSON
  ├── profile/
  │   ├── latest.md          # 最新プロフィールMarkdown
  │   ├── latest.json        # 最新プロフィールJSON
  │   ├── YYYY-MM-DD.md      # 日付スナップショット
  │   └── backups/           # 変更操作前の自動バックアップJSON
  └── messages/
      ├── messages_active.md   # アクティブなスカウト・やりとり最新
      ├── messages_active.json
      ├── messages_archive.md  # アーカイブ最新
      ├── messages_archive.json
      ├── messages_all.md      # 全件最新
      ├── messages_all.json
      └── history/             # タイムスタンプ付き取得履歴
```
