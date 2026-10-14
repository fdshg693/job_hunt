# ビズリーチ 自動化スクリプト利用ガイド

本ディレクトリでは、ビズリーチ（[bizreach.jp](https://www.bizreach.jp/)）におけるスカウトメッセージ一覧の自動取得、メッセージ添付求人の抽出、求人検索・求人詳細ダウンロード、職務経歴書の自動取得、およびWEB履歴書（フリーフォーマット・職歴）のCRUD管理を行うためのスクリプト群の使い方と運用手順をまとめています。

> [!TIP]
> サイト構造・主要画面・DOMセレクタ・認証フローの詳細は [site_structure.md](site_structure.md) を参照してください。

---

## 目次

1. [概要とできること](#1-概要とできること)
2. [スクリプト構成一覧](#2-スクリプト構成一覧)
3. [前提条件と環境準備](#3-前提条件と環境準備)
4. [各スクリプトの詳細な使い方](#4-各スクリプトの詳細な使い方)
   - [4.1 メッセージ一覧取得・認証ハンドオフ: `navigate_messages.py`](#41-メッセージ一覧取得認証ハンドオフ-navigate_messagespy)
   - [4.2 メッセージ添付求人取得・保存: `fetch_message_jobs.py`](#42-メッセージ添付求人取得保存-fetch_message_jobspy)
   - [4.3 求人検索・詳細一括ダウンロード: `search_jobs.py`](#43-求人検索詳細一括ダウンロード-search_jobspy)
   - [4.4 求人詳細単体取得: `fetch_job.py`](#44-求人詳細単体取得-fetch_jobpy)
   - [4.5 職務経歴書自動取得・永続化: `fetch_resume.py`](#45-職務経歴書自動取得永続化-fetch_resumepy)
   - [4.6 WEB履歴書・職歴CRUD管理: `manage_resume.py`](#46-web履歴書職歴crud管理-manage_resumepy)
   - [4.7 Playwright 補助スクリプト (`scripts/bizreach/*.mjs`)](#47-playwright-補助スクリプト-scriptsbizreachmjs)
5. [実践シナリオ別ワークフロー](#5-実践シナリオ別ワークフロー)
6. [認証・ブラウザ操作の制約とトラブルシューティング](#6-認証ブラウザ操作の制約とトラブルシューティング)
7. [データ格納仕様](#7-データ格納仕様)

---

## 1. 概要とできること

ビズリーチにおけるスカウト確認、求人探索、および自身のレジュメ運用の効率化を目的として、以下の機能を提供します。

- **スカウト・メッセージ一覧の自動収集**: 企業やヘッドハンターから届いたスカウトメッセージを、共通ブラウザセッション経由で自動取得・履歴保存（`navigate_messages.py`）。
- **メッセージ添付求人の自動取得**: スカウトやメッセージ内に添付・紐付けられた求人票を特定・解析し、`data/bizreach/jobs/{id}.md` として自動保存（`fetch_message_jobs.py`）。
- **求人検索 & 詳細ダウンロード**: キーワード、年収、勤務地、リモートワーク可否等の条件でビズリーチ上の求人を検索し、検索結果Markdownの生成や求人詳細Markdownの自動保存（`search_jobs.py`）。
- **単体求人詳細取得**: 特定の求人URLやIDから、募集要項・必須/歓迎要件・就業条件を構造化Markdownとして取得・保存（`fetch_job.py`）。
- **職務経歴書の完全取得 & 永続化**: マイページ上の職務経歴書画面から、基本情報・経験職種/業種・職務経歴・フリーフォーマットを構造化Markdown/JSON（`latest.md` / `latest.json`）として自動保存（`fetch_resume.py`）。
- **WEB履歴書・職歴のCRUD管理**: フリーフォーマット自己PRの更新、職歴（所属企業・プロジェクト詳細）の作成・参照・更新・削除を自動化。変更前の自動バックアップ・`--dry-run`プレビューによる安全保護を完備（`manage_resume.py`）。
- **プロジェクト共通求人フォーマット対応**: 保存された求人は共通仕様（`.agents/rules/job-data-format.md`）に準拠し、`scripts/common/search_jobs.py` で他媒体と横断検索可能。
- **安全な認証ハンドオフ**: 未ログイン時はOSトースト通知を発行し、資格情報をコンテキストに漏洩させることなく外部ターミナルでの手動ログイン完了を待機。

---

## 2. スクリプト構成一覧

| スクリプト | 種別 | 主な役割 |
|---|---|---|
| [`scripts/bizreach/navigate_messages.py`](file:///c:/C/job_hunt/scripts/bizreach/navigate_messages.py) | Python CLI | メッセージ一覧の自動遷移・認証確認・データ抽出・履歴保存 |
| [`scripts/bizreach/fetch_message_jobs.py`](file:///c:/C/job_hunt/scripts/bizreach/fetch_message_jobs.py) | Python CLI | メッセージスレッド内の添付求人を抽出し求人詳細Markdownとして保存 |
| [`scripts/bizreach/search_jobs.py`](file:///c:/C/job_hunt/scripts/bizreach/search_jobs.py) | Python CLI | 求人検索・条件絞り込み・検索結果保存・求人詳細一括ダウンロード |
| [`scripts/bizreach/fetch_job.py`](file:///c:/C/job_hunt/scripts/bizreach/fetch_job.py) | Python CLI | 単体求人詳細（URL/ID）の取得・Markdown構造化保存 |
| [`scripts/bizreach/fetch_resume.py`](file:///c:/C/job_hunt/scripts/bizreach/fetch_resume.py) | Python CLI | 職務経歴書（基本情報、職歴、フリーフォーマット）の自動取得・永続化 |
| [`scripts/bizreach/manage_resume.py`](file:///c:/C/job_hunt/scripts/bizreach/manage_resume.py) | Python CLI | WEB履歴書（フリーフォーマット、職歴企業・プロジェクト）のCRUD管理 |
| [`scripts/bizreach/auth_check.mjs`](file:///c:/C/job_hunt/scripts/bizreach/auth_check.mjs) | Playwright JS | ページの認証壁（`auth.id.bizreach.jp`, `/login`等）状態を即時判定 |
| [`scripts/bizreach/auth_guard.mjs`](file:///c:/C/job_hunt/scripts/bizreach/auth_guard.mjs) | Playwright JS | 未認証時に前面化し、ユーザーの手動ログイン完了を待機 |
| [`scripts/bizreach/navigate_messages.mjs`](file:///c:/C/job_hunt/scripts/bizreach/navigate_messages.mjs) | Playwright JS | `/messages/` に遷移し、スクロール読み込みとメッセージ情報の構造化JSON抽出を実行 |
| [`scripts/bizreach/extract_message_jobs.mjs`](file:///c:/C/job_hunt/scripts/bizreach/extract_message_jobs.mjs) | Playwright JS | メッセージ詳細画面から添付求人リンクやIDを抽出 |
| [`scripts/bizreach/search_jobs.mjs`](file:///c:/C/job_hunt/scripts/bizreach/search_jobs.mjs) | Playwright JS | `/jobs/search/` から求人カード情報を抽出 |
| [`scripts/bizreach/fetch_job.mjs`](file:///c:/C/job_hunt/scripts/bizreach/fetch_job.mjs) | Playwright JS | `/jobs/{id}/` から求人詳細情報を抽出 |
| [`scripts/bizreach/fetch_resume.mjs`](file:///c:/C/job_hunt/scripts/bizreach/fetch_resume.mjs) | Playwright JS | 職務経歴書画面（`/resume/company/`）から構造化レジュメ情報を抽出 |
| [`scripts/bizreach/manage_resume.mjs`](file:///c:/C/job_hunt/scripts/bizreach/manage_resume.mjs) | Playwright JS | 職務経歴書・フリーフォーマット画面での入力・保存・CRUD操作 |

---

## 3. 前提条件と環境準備

- **Python**: 3.13 以上（`uv` 使用）
- **ブラウザプロファイル**: 共通プロファイル `job-hunt` を利用します。
  - 格納先: `%LOCALAPPDATA%\claude-browser-profiles\job-hunt`

---

## 4. 各スクリプトの詳細な使い方

### 4.1 メッセージ一覧取得・認証ハンドオフ: `navigate_messages.py`

共通ブラウザプロファイルでビズリーチを開き、メッセージ一覧からスカウト情報を抽出・保存します。

```powershell
# 基本実行（新着メッセージを保存）
uv run python scripts/bizreach/navigate_messages.py

# 企業からの直接スカウトのみを最新10件取得
uv run python scripts/bizreach/navigate_messages.py --tab direct --limit 10 --summary
```

### 4.2 メッセージ添付求人取得・保存: `fetch_message_jobs.py`

特定のスレッドURLまたはIDを指定し、メッセージ内に添付された求人詳細を取得・保存します。

```powershell
# スレッドURLまたはIDを指定
uv run python scripts/bizreach/fetch_message_jobs.py "https://www.bizreach.jp/messages/abc123xyz/" --summary
uv run python scripts/bizreach/fetch_message_jobs.py "abc123xyz"
```

### 4.3 求人検索・詳細一括ダウンロード: `search_jobs.py`

求人検索画面（`/jobs/search/`）から条件検索を行い、一覧ファイル保存および詳細の一括ダウンロードを行います。

```powershell
# 1. キーワード検索
uv run python scripts/bizreach/search_jobs.py "Python" -n 10 --summary

# 2. 年収800万以上、リモート案件で検索し上位5件の詳細を一括ダウンロード
uv run python scripts/bizreach/search_jobs.py "Go" --min-salary 800 --remote -n 5 --download --download-limit 5
```

### 4.4 求人詳細単体取得: `fetch_job.py`

求人URLまたはIDを指定して詳細Markdownを保存します。

```powershell
uv run python scripts/bizreach/fetch_job.py 7755397
uv run python scripts/bizreach/fetch_job.py "https://www.bizreach.jp/jobs/7755397/" --summary
```

### 4.5 職務経歴書自動取得・永続化: `fetch_resume.py`

ビズリーチ上の登録職務経歴書（基本情報、職歴、フリーフォーマット）を完全取得し、`data/bizreach/resume/` に保存します。

```powershell
uv run python scripts/bizreach/fetch_resume.py
uv run python scripts/bizreach/fetch_resume.py --summary
```

### 4.6 WEB履歴書・職歴CRUD管理: `manage_resume.py`

フリーフォーマット自己PRの更新や、職歴企業・担当プロジェクトのCRUD操作を行います。

```powershell
# 1. 現在のフリーフォーマット自己PRを閲覧
uv run python scripts/bizreach/manage_resume.py --action view_freetext --summary

# 2. フリーフォーマットの更新（dry-run）
uv run python scripts/bizreach/manage_resume.py --action update_freetext --freetext-file "profile/resume.md" --dry-run

# 3. フリーフォーマットの更新実行（事前バックアップ自動取得）
uv run python scripts/bizreach/manage_resume.py --action update_freetext --freetext-file "profile/resume.md"

# 4. 職歴企業の追加
uv run python scripts/bizreach/manage_resume.py --action add_company --company-name "株式会社サンプル" --dry-run
```

---

## 5. 実践シナリオ別ワークフロー

### シナリオ: スカウト確認から添付求人ダウンロード・横断分析

```powershell
# 1. 新着スカウト一覧を確認
uv run python scripts/bizreach/navigate_messages.py --summary

# 2. 気になるスカウトの添付求人を保存
uv run python scripts/bizreach/fetch_message_jobs.py "<thread_id>" --summary

# 3. 横断検索ツールで比較
uv run python scripts/common/search_jobs.py --source bizreach --detail
```

---

## 6. 認証・ブラウザ操作の制約とトラブルシューティング

未ログインが検知された場合、スクリプトはトースト通知を発行し待機状態に入ります。外部ターミナルで以下を実行してログインしてください：

```powershell
playwright-cli -s=job-hunt open https://www.bizreach.jp/login/ --headed --profile="$env:LOCALAPPDATA\claude-browser-profiles\job-hunt"
```

---

## 7. データ格納仕様

```text
data/bizreach/
  ├── jobs/              # 求人詳細Markdown ({job_id}.md)
  ├── messages/          # スカウト履歴 (YYYY-MM-DD-HH.md / .json)
  ├── searches/          # 検索履歴 (YYYY-MM-DD-HHMMSS_{query}.md / .json)
  └── resume/            # 職務経歴書 (latest.md / latest.json / backups/)
```
