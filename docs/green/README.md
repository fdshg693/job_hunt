# Green 自動化スクリプト利用ガイド

本ディレクトリでは、Green（[green-japan.com](https://www.green-japan.com/)）におけるプロフィール情報（基本情報、職歴、スキル、希望条件、職務経歴書、自己PR等）の自動取得およびCRUD管理を行うためのスクリプト群の使い方と運用手順をまとめています。

> [!TIP]
> サイト構造、認証仕様、DOMセレクタ、内部REST APIエンドポイントの詳細は [site_structure.md](site_structure.md) を参照してください。

---

## 目次

1. [概要とできること](#1-概要とできること)
2. [スクリプト構成一覧](#2-スクリプト構成一覧)
3. [前提条件と認証基盤](#3-前提条件と認証基盤)
4. [各スクリプトの詳細な使い方](#4-各スクリプトの詳細な使い方)
   - [4.1 プロフィール情報の閲覧・取得: `manage_profile.py --action view`](#41-プロフィール情報の閲覧取得-manage_profilepy---action-view)
   - [4.2 職務経歴書・自己PRの更新: `manage_profile.py --action update_resume`](#42-職務経歴書自己prの更新-manage_profilepy---action-update_resume)
   - [4.3 基本情報・年収・希望条件の更新: `manage_profile.py --action update_basic`](#43-基本情報年収希望条件の更新-manage_profilepy---action-update_basic)
   - [4.4 保有スキルの更新: `manage_profile.py --action update_skills`](#44-保有スキルの更新-manage_profilepy---action-update_skills)
   - [4.5 在籍企業（職歴）の更新: `manage_profile.py --action update_companies`](#45-在籍企業職歴の更新-manage_profilepy---action-update_companies)
   - [4.6 ローカルSSOTプロファイルとの一括同期: `manage_profile.py --action sync_profile`](#46-ローカルssotプロファイルとの一括同期-manage_profilepy---action-sync_profile)
   - [4.7 メッセージ・スカウト一覧および詳細取得: `navigate_messages.py`](#47-メッセージスカウト一覧および詳細取得-navigate_messagespy)
   - [4.8 受信「気になる」一覧取得: `navigate_favorites.py`](#48-受信気になる一覧取得-navigate_favoritespy)
   - [4.9 サーチバー求人検索・一覧取得: `search_jobs.py`](#49-サーチバー求人検索一覧取得-search_jobspy)
   - [4.10 単体求人詳細取得: `fetch_job.py`](#410-単体求人詳細取得-fetch_jobpy)
5. [安全ガード・設計原則](#5-安全ガード設計原則)
6. [データ格納仕様](#6-データ格納仕様)

---

## 1. 概要とできること

Greenにおけるプロフィールの同期・更新運用、スカウト・メッセージ・気になるの探索、およびサーチバーによる求人検索・詳細取得の自動化を目的として、以下の機能を提供します。

- **プロフィール全情報の高精度取得（Read）**: Next.jsの初期データ（`window.__NEXT_DATA__.props.pageProps`）から、基本情報、在籍企業、保有スキル、希望職種、スカウト希望条件、職務経歴書本文、企業に伝えたいこと、ブロック企業を完全な構造化JSON/Markdown（`latest.md` / `latest.json`）として自動保存。
- **職務経歴書（フリーテキスト）の安全な更新**: `--dry-run` プレビュー、Unified Diff 表示、更新前自動バックアップ保存付きで職務経歴書本文を更新。
- **保有スキル・経験職種の一括置換（CRUD）**: ローカルスキル辞書や指定スキルリストに基づき、Greenのスキル・経験年数タグを安全に置換。
- **在籍企業（職歴）の管理**: 社名、雇用形態、入社年月、退社年月、在籍中フラグを含む職歴企業の参照・更新。
- **ローカルSSOTとの同期**: `profile/resume.md`, `profile/preferences.md`, `profile/skills.md` の内容を自動抽出・マッピングし、Greenプロフィールへ一括反映。
- **メッセージ・スカウトの自動取得**: `/messages/v2` から企業／エージェントタブ別に受信スカウト・メッセージ一覧および特定スレッドの本文詳細を自動取得・保存。
- **受信「気になる」の自動取得**: `/favorites/received` から企業から受信した気になる求人・企業情報を自動取得・保存（送信・マッチング・興味なしタブにも対応）。
- **画面上部サーチバー連動の求人検索**: `/search` のサーチバー操作（キーワード入力、勤務地、職種、下限年収）または直接URLクエリ構築により、求人を高速検索し結果を正規化・永続化。
- **個別求人詳細の取得・SSOT保存**: `/job/{id}` から募集要項、仕事内容、必須・歓迎条件、開発環境、勤務条件等を抽出し、共通Markdownフォーマットで保存。
- **CLI規約準拠**: 標準出力（stdout）には変更・作成後ファイルパスのみを出力し、人間向けサマリ表示は `--summary`、進捗・ログは標準エラー出力（stderr）に出力。

---

## 2. スクリプト構成一覧

| スクリプト | 種別 | 主な役割 |
|---|---|---|
| [`scripts/green/manage_profile.py`](file:///c:/C/job_hunt/scripts/green/manage_profile.py) | Python CLI | Greenプロフィール（基本情報・職歴・スキル・希望条件・職務経歴書）CRUD管理エントリポイント |
| [`scripts/green/manage_profile.mjs`](file:///c:/C/job_hunt/scripts/green/manage_profile.mjs) | Playwright JS | Next.js `__NEXT_DATA__` からのデータ抽出および内部REST API呼び出し自動化スクリプト |
| [`scripts/green/navigate_messages.py`](file:///c:/C/job_hunt/scripts/green/navigate_messages.py) | Python CLI | メッセージ・スカウト一覧およびスレッド詳細本文の自動取得・永続化CLI |
| [`scripts/green/navigate_messages.mjs`](file:///c:/C/job_hunt/scripts/green/navigate_messages.mjs) | Playwright JS | `/messages/v2` 画面のタブ操作、スレッド一覧・本文詳細Playwright抽出スクリプト |
| [`scripts/green/navigate_favorites.py`](file:///c:/C/job_hunt/scripts/green/navigate_favorites.py) | Python CLI | 受信「気になる」一覧および各タブ（送信/マッチング/興味なし）の自動取得・永続化CLI |
| [`scripts/green/navigate_favorites.mjs`](file:///c:/C/job_hunt/scripts/green/navigate_favorites.mjs) | Playwright JS | `/favorites/received` 画面の気になる求人・企業リストPlaywright抽出スクリプト |
| [`scripts/green/search_jobs.py`](file:///c:/C/job_hunt/scripts/green/search_jobs.py) | Python CLI | 画面上部サーチバー操作・条件指定による求人検索・一覧取得・保存CLI |
| [`scripts/green/search_jobs.mjs`](file:///c:/C/job_hunt/scripts/green/search_jobs.mjs) | Playwright JS | `/search` 画面のサーチバー（キーワード・年収・勤務地等）操作および一覧DOM抽出スクリプト |
| [`scripts/green/fetch_job.py`](file:///c:/C/job_hunt/scripts/green/fetch_job.py) | Python CLI | 単体求人詳細（`/job/{id}`）の取得および共通求人Markdown永続化CLI |
| [`scripts/green/fetch_job.mjs`](file:///c:/C/job_hunt/scripts/green/fetch_job.mjs) | Playwright JS | 求人詳細ページの `__NEXT_DATA__` / DOM詳細情報Playwright抽出スクリプト |
| [`scripts/green/auth_check.mjs`](file:///c:/C/job_hunt/scripts/green/auth_check.mjs) | Playwright JS | Greenへのアクセス可否・ログイン状態の即時判定 |
| [`scripts/green/auth_guard.mjs`](file:///c:/C/job_hunt/scripts/green/auth_guard.mjs) | Playwright JS | 未ログイン検知時にユーザーの手動ログイン完了を待機 |

---

## 3. 前提条件と認証基盤

- **Python**: 3.13 以上（`uv` 使用）
- **Playwright CLI**: `@playwright/cli` グローバル導入済み
- **セッションプロファイル**: リポジトリ共通プロファイル `job-hunt`（`%LOCALAPPDATA%\claude-browser-profiles\job-hunt`）を使用します。
- **初回ログイン**:
  - セッション未認証時は、`scripts.common.auth_engine` が自動で検知し、OSトースト通知とともに手動ログイン用コマンドを表示して完了を待機します。
  - エージェント環境（Windowsサンドボックス仮想デスクトップ）の制約上、ログイン時はユーザーの外部ターミナル（PowerShell / Windows Terminal）で以下を実行してログインします。
    ```powershell
    playwright-cli -s=job-hunt open "https://www.green-japan.com/login?target_url=%2Fprofiles%2Fedit" --headed --profile="$env:LOCALAPPDATA\claude-browser-profiles\job-hunt"
    ```

---

## 4. 各スクリプトの詳細な使い方

### 4.1 プロフィール情報の閲覧・取得: `manage_profile.py --action view`

現在のGreen登録情報を完全取得し、`data/green/profile/latest.md` および `latest.json` に保存します。

```powershell
# 1. 保存ファイルパスのみ出力（AI・パイプライン向け）
uv run python scripts/green/manage_profile.py --action view

# 2. 人間向けサマリを表示
uv run python scripts/green/manage_profile.py --action view --summary

# 3. JSON形式で標準出力
uv run python scripts/green/manage_profile.py --action view --json
```

### 4.2 職務経歴書・自己PRの更新: `manage_profile.py --action update_resume`

職務経歴書フリーテキスト（`userResume`）を更新します。

```powershell
# 1. 文字列指定で dry-run（差分プレビュー表示、実際の更新は行わない）
uv run python scripts/green/manage_profile.py --action update_resume --resume-text "■職務要約..." --dry-run

# 2. ファイル指定で更新実行（自動バックアップ取得）
uv run python scripts/green/manage_profile.py --action update_resume --resume-file profile/resume.md --summary
```

### 4.3 基本情報・年収・学歴の更新: `manage_profile.py --action update_basic`

現年収、現住所、電話番号、卒業年、学部学科名等を更新します。

```powershell
# 1. 現年収と学歴の更新（dry-run）
uv run python scripts/green/manage_profile.py --action update_basic --salary 408 --graduation-year 2024 --department "文学部西洋古典学専修" --dry-run

# 2. 更新実行
uv run python scripts/green/manage_profile.py --action update_basic --salary 408 --graduation-year 2024 --department "文学部西洋古典学専修" --summary
```

### 4.4 保有スキルの更新: `manage_profile.py --action update_skills`

保有スキルおよび経験年数を一括置換します。スキル名から内部マスターの `skill_id` および経験年数スコア（`skill_score_id`）への自動変換に対応しています。

```powershell
# スキル一覧を指定して更新（dry-run）
uv run python scripts/green/manage_profile.py --action update_skills --skills "Python:1年〜3年,TypeScript:1年〜3年,Go:1年未満,Next.js:1年〜3年" --dry-run
```

### 4.5 在籍企業（職歴）の更新: `manage_profile.py --action update_companies`

職歴企業リストを一括置換します。

```powershell
# JSONファイルから職歴を一括反映
uv run python scripts/green/manage_profile.py --action update_companies --companies-file temp/companies.json --dry-run
```

### 4.6 企業に伝えたいことの更新: `manage_profile.py --action update_career_statement`

転職理由・見てほしい経験・その他アピールを更新します。

```powershell
uv run python scripts/green/manage_profile.py --action update_career_statement --statement-point "自社プロダクト企業でモダンバックエンドにコミットしたい" --statement-highlight "フルスタック開発力とキャッチアップ速度" --summary
```

### 4.7 ローカルSSOTプロファイルとの一括同期: `manage_profile.py --action sync_profile`

本リポジトリの `profile/`（`resume.md`, `preferences.md`, `skills.md`）の情報を自動集約し、職務経歴書フリーテキスト（約5,900文字）、基本情報（現年収 408万円、卒業年 2024年3月、学部学科）、企業に伝えたいこと（3項目）、保有スキル（21件）をGreenプロフィールへ一括安全同期します。

```powershell
# dry-run で全項目の変更差分を確認
uv run python scripts/green/manage_profile.py --action sync_profile --dry-run

# 同期実行
uv run python scripts/green/manage_profile.py --action sync_profile --summary
```

### 4.7 メッセージ・スカウト一覧および詳細取得: `navigate_messages.py`

`/messages/v2` から受信したメッセージ・スカウト一覧（企業／エージェントタブ）および特定スレッドの本文詳細を取得します。

```powershell
# 1. 保存ファイルパスのみ出力（一覧取得、企業＋エージェント全件）
uv run python scripts/green/navigate_messages.py

# 2. 人間向けサマリを表示（企業タブのみ、最大20件）
uv run python scripts/green/navigate_messages.py --tab company --limit 20 --summary

# 3. エージェントタブのメッセージ一覧を取得
uv run python scripts/green/navigate_messages.py --tab agent --summary

# 4. 一覧と同時に各スレッドの本文詳細も取得
uv run python scripts/green/navigate_messages.py --details --limit 10

# 5. 特定スレッドIDの本文詳細のみを取得
uv run python scripts/green/navigate_messages.py --thread-id 12345 --summary
```

### 4.8 受信「気になる」一覧取得: `navigate_favorites.py`

`/favorites/received` から企業から受信した「気になる」求人・企業一覧を取得します。

```powershell
# 1. 保存ファイルパスのみ出力（受信気になる一覧）
uv run python scripts/green/navigate_favorites.py

# 2. 人間向けサマリを表示（最大30件）
uv run python scripts/green/navigate_favorites.py --limit 30 --summary

# 3. あなたから（送信）タブを取得
uv run python scripts/green/navigate_favorites.py --tab sent --summary

# 4. マッチング成立タブを取得
uv run python scripts/green/navigate_favorites.py --tab matched --summary
```

### 4.9 サーチバー求人検索・一覧取得: `search_jobs.py`

`/search` 画面上部のサーチバー操作またはクエリ指定により求人を検索し、結果一覧を保存します。

```powershell
# 1. キーワード指定で検索（ファイルパスのみ出力）
uv run python scripts/green/search_jobs.py --query "Python FastAPI"

# 2. 下限年収とサマリ表示を指定して検索
uv run python scripts/green/search_jobs.py --query "バックエンド" --min-salary 600万 --summary

# 3. 検索結果の上位求人詳細も同時にダウンロード（--fetch-details）
uv run python scripts/green/search_jobs.py --query "機械学習" --limit 10 --fetch-details --download-limit 5 --summary

# 4. 2ページ目を検索
uv run python scripts/green/search_jobs.py --query "フルリモート" --page 2 --summary
```

### 4.10 単体求人詳細取得: `fetch_job.py`

Green求人URLまたは求人IDを指定し、募集要項・仕事内容・応募条件等を抽出してSSOT求人Markdown（`data/green/jobs/{job_id}.md`）に保存します。

```powershell
# 1. 求人IDで取得（ファイルパスのみ出力）
uv run python scripts/green/fetch_job.py 196698

# 2. 求人URL指定で取得し、人間向けサマリを表示
uv run python scripts/green/fetch_job.py "https://www.green-japan.com/job/196698" --summary

# 3. 既存ファイルが存在する場合でも強制再取得（--force）
uv run python scripts/green/fetch_job.py 196698 --force --summary
```

---

## 5. 安全ガード・設計原則

1. **事前自動バックアップ**:
   - 変更（更新）を伴う全アクションで、実行直前の完全なプロフィール状態（JSON）を `data/green/profile/backups/YYYYMMDD_HHMMSS_before_{action}.json` に自動保存します。
2. **`--dry-run` プレビュー**:
   - 変更前の値と変更後の値を Unified Diff 形式でターミナルに出力し、意図しないデータ破壊や誤入力を防止します。
3. **アトミック更新**:
   - Next.js内部REST APIエンドポイントをブラウザセッション内で実行することで、画面の再描画待機によるセレクタ誤認や途中失敗を防止します。
4. **資格情報非保持**:
   - パスワード等の認証情報は一切保持せず、永続プロファイル `job-hunt` のCookieセッションのみを利用します。

---

## 6. データ格納仕様

```text
data/green/
  ├── profile/
  │     ├── latest.md          # 最新プロフィールMarkdown（フロントマター付き）
  │     ├── latest.json        # 最新プロフィール完全JSON
  │     ├── YYYY-MM-DD.md      # 日付スナップショットMarkdown
  │     └── backups/           # 変更操作前の自動バックアップJSON
  │           └── YYYYMMDD_HHMMSS_before_update_resume.json
  ├── messages/
  │     ├── latest_messages_all.md       # 最新メッセージ一覧（全件）
  │     ├── latest_messages_company.md   # 最新メッセージ一覧（企業から）
  │     ├── latest_messages_agent.md     # 最新メッセージ一覧（エージェントから）
  │     ├── YYYY-MM-DD-HHMMSS_messages_all.json # タイムスタンプ付き一覧JSON
  │     └── threads/                     # スレッド別本文詳細
  │           ├── {thread_id}.md
  │           └── {thread_id}.json
  ├── favorites/
  │     ├── latest_favorites_received.md # 最新受信気になる一覧
  │     ├── latest_favorites_sent.md     # 最新送信気になる一覧
  │     ├── latest_favorites_matched.md  # 最新マッチング一覧
  │     └── YYYY-MM-DD-HHMMSS_favorites_received.json # タイムスタンプ付き一覧JSON
  ├── searches/
  │     ├── YYYY-MM-DD_HHMMSS_search_{keyword}.md  # 検索結果Markdown
  │     └── YYYY-MM-DD_HHMMSS_search_{keyword}.json
  └── jobs/
        └── {job_id}.md        # 求人詳細Markdown（共通フォーマット準拠）
```

