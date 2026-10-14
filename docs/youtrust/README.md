# YOUTRUST 自動化スクリプト利用ガイド

本ディレクトリでは、YOUTRUST（[youtrust.jp](https://youtrust.jp/)）におけるプロフィール情報（基本情報、ビジネスネーム、居住地、公開範囲、自己紹介、意欲・経歴・スキル等の関連情報）の自動取得およびCRUD管理を行うためのスクリプト群の使い方と運用手順をまとめています。

> [!TIP]
> サイト構造、認証仕様、DOMセレクタ、内部REST APIエンドポイントの詳細は [site_structure.md](site_structure.md) を参照してください。

---

## 目次

1. [概要とできること](#1-概要とできること)
2. [スクリプト構成一覧](#2-スクリプト構成一覧)
3. [前提条件と認証基盤](#3-前提条件と認証基盤)
4. [各スクリプトの詳細な使い方](#4-各スクリプトの詳細な使い方)
   - [4.1 プロフィール情報の閲覧・最新保存: `manage_profile.py --action show`](#41-プロフィール情報の閲覧最新保存-manage_profilepy---action-show)
   - [4.2 最新バックアップの即時退避: `manage_profile.py --action backup`](#42-最新バックアップの即時退避-manage_profilepy---action-backup)
   - [4.3 プロフィール各項目の安全な更新: `manage_profile.py --action update`](#43-プロフィール各項目の安全な更新-manage_profilepy---action-update)
   - [4.4 ローカルSSOTプロファイルとの同期: `manage_profile.py --action sync`](#44-ローカルssotプロファイルとの同期-manage_profilepy---action-sync)
   - [4.5 職歴・学歴のCRUD管理・同期: `manage_background.py`](#45-職歴学歴のcrud管理同期-manage_backgroundpy)
5. [安全ガード・設計原則](#5-安全ガード設計原則)
6. [データ格納仕様](#6-データ格納仕様)

---

## 1. 概要とできること

YOUTRUSTにおけるプロフィールの同期・更新運用、経歴・スキルのバックアップ、およびCLIからの安全な情報管理を目的として、以下の機能を提供します。

- **プロフィール全情報の高精度取得（Read）**: 内部REST API（`/api/users/@me`, `/api/users/{id}/user_birthday`, `/api/v2/users/@me/careers`, `/api/users/@me/career_motivation` 等）およびDOMから、氏名、居住地、公開範囲、自己紹介、経歴企業、転職意欲、資格、リンクを完全な構造化Markdown（`latest.md`）として自動保存。
- **職歴・学歴の完全CRUD管理**: `/settings/background` の職歴（企業・部署）および学歴（学校・専攻・期間等）を内部REST API（v3）経由で閲覧・追加・更新・削除。
- **変更前の完全自動バックアップ**: 変更操作（`update`, `sync`, `add`, `delete`）の実行前には必ず最新データの完全バックアップを `backups/{timestamp}.md` に退避。
- **差分プレビューと安全ガード（`--dry-run`）**: 実画面やAPIを変更する前に、変更前後テキストの Unified Diff または送信予定 Payload をコンソールに表示して意図せぬ変更を防止。
- **ローカルSSOTとの同期（`sync`）**: `profile/resume.md` や `profile/preferences.md` の内容を抽出し、YOUTRUSTの登録情報と照合・同期。
- **CLI規約準拠**: 標準出力（stdout）には変更・作成後ファイルパスのみを出力し、人間向けサマリ表示は `--summary`、進捗・ログは標準エラー出力（stderr）に出力。

---

## 2. スクリプト構成一覧

| スクリプト | 種別 | 主な役割 |
|---|---|---|
| [`scripts/youtrust/manage_profile.py`](file:///c:/C/job_hunt/scripts/youtrust/manage_profile.py) | Python CLI | YOUTRUST プロフィールCRUD管理・同期CLIエントリポイント |
| [`scripts/youtrust/manage_profile.mjs`](file:///c:/C/job_hunt/scripts/youtrust/manage_profile.mjs) | Playwright JS | `/settings/profile` 画面のPlaywright操作・API呼び出しスクリプト |
| [`scripts/youtrust/manage_background.py`](file:///c:/C/job_hunt/scripts/youtrust/manage_background.py) | Python CLI | YOUTRUST 職歴・学歴CRUD管理・同期CLIエントリポイント |
| [`scripts/youtrust/manage_background.mjs`](file:///c:/C/job_hunt/scripts/youtrust/manage_background.mjs) | Playwright JS | `/settings/background` 画面のPlaywright操作・v3 API呼び出しスクリプト |
| [`scripts/youtrust/auth_check.mjs`](file:///c:/C/job_hunt/scripts/youtrust/auth_check.mjs) | Playwright JS | YOUTRUSTへのログイン状態の即時判定 |
| [`scripts/youtrust/auth_guard.mjs`](file:///c:/C/job_hunt/scripts/youtrust/auth_guard.mjs) | Playwright JS | 未ログイン検知時にユーザーの手動ログイン完了を待機 |

---

## 3. 前提条件と認証基盤

- **Python**: 3.13 以上（`uv` 使用）
- **Playwright CLI**: `@playwright/cli` グローバル導入済み
- **セッションプロファイル**: リポジトリ共通プロファイル `job-hunt`（`%LOCALAPPDATA%\claude-browser-profiles\job-hunt`）を使用します。
- **初回ログイン**:
  - セッション未認証時は、`scripts.common.auth_engine` が自動で検知し、OSトースト通知とともに手動ログイン用コマンドを表示して完了を待機します。
  - エージェント環境（Windowsサンドボックス仮想デスクトップ）の制約上、ログイン時はユーザーの外部ターミナル（PowerShell / Windows Terminal）で以下を実行してログインします。
    ```powershell
    playwright-cli -s=job-hunt open "https://youtrust.jp/sign_in?redirect_path=%2Fsettings%2Fprofile&type=sign_in" --headed --profile="$env:LOCALAPPDATA\claude-browser-profiles\job-hunt"
    ```

---

## 4. 各スクリプトの詳細な使い方

### 4.1 プロフィール情報の閲覧・最新保存: `manage_profile.py --action show`

現在のYOUTRUST登録情報を完全取得し、`data/youtrust/profile/latest.md` に保存します。

```powershell
# 1. 保存ファイルパスのみ出力（AI・パイプライン向け）
uv run python scripts/youtrust/manage_profile.py --action show

# 2. 人間向けサマリを表示
uv run python scripts/youtrust/manage_profile.py --action show --summary

# 3. JSON形式で標準出力
uv run python scripts/youtrust/manage_profile.py --action show --json
```

### 4.2 最新バックアップの即時退避: `manage_profile.py --action backup`

最新の登録情報をタイムスタンプ付きのMarkdownファイル（`data/youtrust/profile/backups/profile_backup_YYYYMMDD_HHMMSS.md`）として退避保存します。

```powershell
uv run python scripts/youtrust/manage_profile.py --action backup --summary
```

### 4.3 プロフィール各項目の安全な更新: `manage_profile.py --action update`

氏名、ビジネスネーム、居住地、居住地補足、公開範囲、自己紹介文を更新します。

```powershell
# 1. 自己紹介文の変更を事前確認（dry-run）
uv run python scripts/youtrust/manage_profile.py --action update --intro-text "Webエンジニアとして活動中..." --dry-run

# 2. 自己紹介文を反映実行
uv run python scripts/youtrust/manage_profile.py --action update --intro-text "Webエンジニアとして活動中..." --summary

# 3. ファイルから自己紹介文を指定して更新
uv run python scripts/youtrust/manage_profile.py --action update --intro-file "profile/resume.md" --dry-run

# 4. 居住地および公開範囲の更新
uv run python scripts/youtrust/manage_profile.py --action update --location "東京都" --location-detail "リモート中心" --location-scope only_friends --birthday-scope private --summary
```

**更新可能オプション一覧**:
- `--name`: 氏名
- `--business-name`: ビジネスネーム（ニックネーム・旧姓等）
- `--location`: 居住地（都道府県・市区町村）
- `--location-detail`: 居住地の補足（最大30文字）
- `--location-scope`: 居住地公開範囲（`all` または `only_friends`）
- `--birthday-scope`: 生年月日公開範囲（`friend` または `private`）
- `--intro-text`: 自己紹介テキスト（直接指定）
- `--intro-file`: 自己紹介テキストファイルパス

### 4.4 ローカルSSOTプロファイルとの同期: `manage_profile.py --action sync`

ローカルの職務経歴書マスター（`profile/resume.md`）から自己紹介・略歴を抽出し、YOUTRUSTプロフィールに反映します。

```powershell
# 1. 同期差分を事前確認
uv run python scripts/youtrust/manage_profile.py --action sync --from-profile --dry-run

# 2. 同期反映を実行
uv run python scripts/youtrust/manage_profile.py --action sync --from-profile --summary
```

### 4.5 職歴・学歴のCRUD管理・同期: `manage_background.py`

職歴（`/api/v3/users/@me/career_company_histories`）および学歴（`/api/users/@me` / `/api/v3/users/@me/educations`）の一覧取得、新規追加、更新、削除、およびSSOT（`profile/resume.md`）との照合を行います。

```powershell
# 1. 現在の職歴・学歴一覧を取得・保存（人間向けサマリ表示）
uv run python scripts/youtrust/manage_background.py --action show --summary

# 2. 保存ファイルパスのみ出力（AI・パイプライン向け）
uv run python scripts/youtrust/manage_background.py --action show

# 3. タイムスタンプ付き手動バックアップ保存
uv run python scripts/youtrust/manage_background.py --action backup --summary

# 4. 学歴の追加（dry-run プレビュー）
uv run python scripts/youtrust/manage_background.py --action add --target education --school "東京大学" --faculty "文学部 西洋古典学専修" --entered "2016-04-01" --graduated "2024-03-31" --dry-run

# 5. 学歴の追加（反映実行）
uv run python scripts/youtrust/manage_background.py --action add --target education --school "東京大学" --faculty "文学部 西洋古典学専修" --entered "2016-04-01" --graduated "2024-03-31" --summary

# 6. 企業職歴の新規追加（dry-run プレビュー）
uv run python scripts/youtrust/manage_background.py --action add --target career --company "株式会社プラスアルファ・コンサルティング" --joined "2024-04-01" --left "2025-07-31" --dept "カスタマーリングス開発" --role "フルスタックエンジニア" --dry-run

# 7. 既存企業への部署・プロジェクト追加
uv run python scripts/youtrust/manage_background.py --action add --target career --history-id "e4c86d6b8f57acd68742435d9107e483" --dept "AIソリューション事業部" --role "AIエンジニア" --desc "ワークフローWebアプリ開発" --category "システムエンジニア" --dry-run

# 8. 職歴・学歴の更新（ID指定）
uv run python scripts/youtrust/manage_background.py --action update --target career --history-id "e4c86d6b8f57acd68742435d9107e483" --company "株式会社ヘッドウォータース" --joined "2025-08-01" --summary

# 9. 職歴・学歴の削除（ID指定、dry-run）
uv run python scripts/youtrust/manage_background.py --action delete --target education --edu-id "xxx" --dry-run

# 10. SSOT（profile/resume.md）との照合
uv run python scripts/youtrust/manage_background.py --action sync --summary
```

---

## 5. 安全ガード・設計原則

1. **事前自動バックアップの徹底**:
   - `update`、`sync`、`add`、`delete` を実行する際、PlaywrightがAPIリクエストを発行する前に、自動的に直前の完全状態を `backups/` ディレクトリに保存します。
2. **Unified Diff / Payload による差分可視化**:
   - `--dry-run` 時、あるいは実際の更新時にも標準エラー出力に変更箇所の差分（Unified Diff または 送信予定Payload）を表示し、予期しない項目変更を事前に検知できます。
3. **生年月日の保護**:
   - YOUTRUSTの仕様上、生年月日は一度設定すると変更できないため、スクリプト側でも編集対象から完全に除外しています。

---

## 6. データ格納仕様

```text
data/youtrust/
├── profile/                              # 基本プロフィール情報
│   ├── latest.json                       # 最新取得プロファイルJSON
│   ├── latest.md                         # 最新取得プロファイルMarkdown
│   └── backups/
│       ├── profile_backup_YYYYMMDD_HHMMSS.md # 変更前自動退避バックアップ
│       └── ...
└── background/                           # 職歴・学歴情報
    ├── latest.json                       # 最新取得職歴・学歴JSON
    ├── latest.md                         # 最新取得職歴・学歴Markdown
    └── backups/
        ├── YYYYMMDD_HHMMSS_pre_add_career.json
        ├── YYYYMMDD_HHMMSS_pre_add_career.md
        └── ...
```
