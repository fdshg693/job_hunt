# OpenWork 自動化スクリプト利用ガイド

本ディレクトリでは、OpenWork（[openwork.jp](https://www.openwork.jp/)）における求人検索、求人詳細ダウンロード、WEB履歴書取得、メッセージ・スカウト取得、会社名解決、および会社クチコミ（8項目評価スコア・社員クチコミ）の自動取得・永続化を行うためのスクリプト群の使い方と運用手順をまとめています。

> [!TIP]
> サイト構造・主要画面・DOMセレクタ・URLクエリパラメータの詳細は [site_structure.md](site_structure.md) を参照してください。

---

## 目次

1. [概要とできること](#1-概要とできること)
2. [スクリプト構成一覧](#2-スクリプト構成一覧)
3. [前提条件と環境準備](#3-前提条件と環境準備)
4. [各スクリプトの詳細な使い方](#4-各スクリプトの詳細な使い方)
   - [4.1 求人検索・詳細一括ダウンロード: `search_jobs.py`](#41-求人検索詳細一括ダウンロード-search_jobspy)
   - [4.2 求人詳細単体取得: `fetch_job.py`](#42-求人詳細単体取得-fetch_jobpy)
   - [4.3 会社名解決・企業ID特定: `resolve_company.py`](#43-会社名解決企業id特定-resolve_companypy)
   - [4.4 会社クチコミ・8項目スコア取得: `fetch_reviews.py`](#44-会社クチコミ8項目スコア取得-fetch_reviewspy)
   - [4.5 WEB履歴書取得・永続化: `fetch_resume.py`](#45-web履歴書取得永続化-fetch_resumepy)
   - [4.6 メッセージ・スカウト自動取得: `navigate_messages.py`](#46-メッセージスカウト自動取得-navigate_messagespy)
5. [実践シナリオ別ワークフロー](#5-実践シナリオ別ワークフロー)
6. [認証・CAPTCHAハンドオフとトラブルシューティング](#6-認証captchaハンドオフとトラブルシューティング)
7. [データ格納仕様](#7-データ格納仕様)

---

## 1. 概要とできること

OpenWorkにおける求人探索、企業クチコミ・カルチャー分析、および登録済みのWEB履歴書管理を目的として、以下の機能を提供します。

- **高速な求人検索 & 一覧永続化**: キーワード、年収、勤務地、リモートワーク可否等の条件で求人を検索し、検索結果一覧Markdown/JSONを自動生成（`search_jobs.py`）。
- **求人詳細の一括ダウンロード**: 検索結果でヒットした求人詳細を一括取得し、`data/openwork/jobs/{id}.md` として自動保存。
- **求人詳細単体取得**: 特定の求人URLまたはIDから、募集要項・仕事内容・就業条件・会社概要を構造化Markdownとして取得・保存（`fetch_job.py`）。
- **会社名解決（企業ID特定）**: 会社名（例: 「SmartHR」「メルカリ」）からOpenWork上の企業ID（`m_id`）、会社ページURL、クチコミURL、総合評価スコアを自動解決（`resolve_company.py`）。
- **社員クチコミ・8項目スコアの自動収集**: 企業IDまたは会社名から、8項目レーティング（待遇満足度、士気、風通し、20代成長環境、法令順守等）および社員の生クチコミを取得し、`data/openwork/reviews/{m_id}.md` に保存（`fetch_reviews.py`）。
- **WEB履歴書の自動取得 & 永続化**: マイページ上のWEB履歴書（`/mypage/resume`）から、基本情報・学歴・職歴・スキル・希望条件を完全取得しローカル保存（`fetch_resume.py`）。
- **スカウト・メッセージ一覧の取得**: 受信スカウト・メッセージを自動取得し、Markdown/JSONで履歴保存（`navigate_messages.py`）。
- **プロジェクト共通求人フォーマット対応**: 保存された求人は他媒体と横断して `scripts/common/search_local_jobs.py` で検索可能。
- **安全な認証・CAPTCHAハンドオフ**: 画像認証（CAPTCHA）や403 WAF、未ログイン検知時は共通認証エンジン（`scripts/common/auth_engine.py`）によりOSトースト通知を発行し、資格情報をコンテキストに漏洩させることなく外部ターミナルでの手動解除・ログイン完了を待機。

---

## 2. スクリプト構成一覧

| スクリプト | 種別 | 主な役割 |
|---|---|---|
| [`scripts/openwork/search_jobs.py`](../../scripts/openwork/search_jobs.py) | Python CLI | 求人検索・条件絞り込み・検索結果保存・求人詳細一括ダウンロード |
| [`scripts/openwork/fetch_job.py`](../../scripts/openwork/fetch_job.py) | Python CLI | 単体求人詳細（URL/ID）の取得・Markdown構造化保存 |
| [`scripts/openwork/resolve_company.py`](../../scripts/openwork/resolve_company.py) | Python CLI | 会社名からの企業ID（`m_id`）解決・会社メタデータ探索 |
| [`scripts/openwork/fetch_reviews.py`](../../scripts/openwork/fetch_reviews.py) | Python CLI | 企業ID/会社名からのクチコミ・8項目評価スコア取得・Markdown保存 |
| [`scripts/openwork/fetch_resume.py`](../../scripts/openwork/fetch_resume.py) | Python CLI | WEB履歴書（職歴・学歴・スキル・希望条件）の自動取得・構造化保存 |
| [`scripts/openwork/navigate_messages.py`](../../scripts/openwork/navigate_messages.py) | Python CLI | メッセージ・スカウト一覧の自動取得・構造化保存・サマリ表示 |
| [`scripts/openwork/fetch_resume.mjs`](../../scripts/openwork/fetch_resume.mjs) | Playwright JS | WEB履歴書画面DOMからの構造化データ抽出 |
| [`scripts/openwork/navigate_messages.mjs`](../../scripts/openwork/navigate_messages.mjs) | Playwright JS | メッセージ画面DOMからのスカウト一覧抽出 |

> [!NOTE]
> 認証状態や画像認証（CAPTCHA）・403 WAFの判定および手動解除待機ハンドオフは、共通認証エンジン（[`scripts/common/auth_engine.py`](../../scripts/common/auth_engine.py), [`scripts/common/js/universal_auth.mjs`](../../scripts/common/js/universal_auth.mjs)）により自動制御されます。個別スクリプトは不要です。

---

## 3. 前提条件と環境準備

- **Python**: 3.13 以上（`uv` 使用）
- **ブラウザプロファイル**: 画像認証解除やログインが必要な操作は共通プロファイル `job-hunt` を利用します。
  - 格納先: `%LOCALAPPDATA%\claude-browser-profiles\job-hunt`

---

## 4. 各スクリプトの詳細な使い方

### 4.1 求人検索・詳細一括ダウンロード: `search_jobs.py`

キーワードや年収・リモート条件で求人を検索し、結果一覧ファイルおよび詳細Markdownを保存します。

```powershell
# 1. キーワード検索
uv run python scripts/openwork/search_jobs.py "Python" -n 10 --summary

# 2. 年収800万以上、フルリモートで上位5件の詳細をダウンロード
uv run python scripts/openwork/search_jobs.py "Go" --min-salary 800 --remote -n 5 --download
```

### 4.2 求人詳細単体取得: `fetch_job.py`

URLまたはIDを指定して求人詳細を保存します。

```powershell
uv run python scripts/openwork/fetch_job.py "https://www.openwork.jp/a0C30000003Llud/recruit?j=da38a7e426dbb3c1"
```

### 4.3 会社名解決・企業ID特定: `resolve_company.py`

会社名からOpenWorkの企業ID（`m_id`）やメタデータを検索・解決します。

```powershell
# 会社名で検索（標準出力はパス/m_id）
uv run python scripts/openwork/resolve_company.py "SmartHR"

# 詳細サマリを表示（スコア、社員数、業界等）
uv run python scripts/openwork/resolve_company.py "メルカリ" --summary
```

### 4.4 会社クチコミ・8項目スコア取得: `fetch_reviews.py`

企業ID（`m_id`）または会社名を指定して、OpenWorkの社員クチコミと8項目スコアを取得・保存します。

```powershell
# 会社名を指定してクチコミ取得（内部で resolve_company 連携）
uv run python scripts/openwork/fetch_reviews.py "SmartHR" --summary

# 企業ID（m_id）を直接指定して取得
uv run python scripts/openwork/fetch_reviews.py "a0C1000000sZg9J"
```

### 4.5 WEB履歴書取得・永続化: `fetch_resume.py`

現在のOpenWork登録WEB履歴書を完全取得し、`data/openwork/resume/` に保存します。

```powershell
uv run python scripts/openwork/fetch_resume.py --summary
```

### 4.6 メッセージ・スカウト自動取得: `navigate_messages.py`

受信したスカウト・メッセージ一覧を取得・保存します。

```powershell
uv run python scripts/openwork/navigate_messages.py --summary
```

---

## 5. 実践シナリオ別ワークフロー

### シナリオ: 気になる企業のクチコミ調査と求人探索

```powershell
# 1. 企業名からクチコミと8項目スコアを取得
uv run python scripts/openwork/fetch_reviews.py "メルカリ" --summary

# 2. その企業のオープン求人を検索
uv run python scripts/openwork/search_jobs.py "メルカリ" --download --summary
```

---

## 6. 認証・CAPTCHAハンドオフとトラブルシューティング

画像認証（CAPTCHA）や未ログインが検知された場合、スクリプトはトースト通知を発行し待機状態に入ります。外部ターミナルで以下を実行して解除・ログインしてください：

```powershell
playwright-cli -s=job-hunt open https://www.openwork.jp/login.php --headed --profile="$env:LOCALAPPDATA\claude-browser-profiles\job-hunt"
```

---

## 7. データ格納仕様

```text
data/openwork/
  ├── jobs/              # 求人詳細Markdown ({job_id}.md)
  ├── messages/          # スカウト履歴 (YYYY-MM-DD-HH.md / .json)
  ├── resume/            # WEB履歴書 (latest.md / latest.json)
  ├── reviews/           # 会社クチコミ・8項目スコア ({m_id}.md)
  └── searches/          # 検索結果一覧 (YYYY-MM-DD-HHMMSS_{query}.md / .json)
```
