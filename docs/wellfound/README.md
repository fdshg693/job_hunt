# Wellfound 自動化スクリプト利用ガイド

本ディレクトリでは、Wellfound（旧AngelList Talent、[wellfound.com](https://wellfound.com/)）におけるプロフィール情報（About/Bio、氏名、ソーシャルリンク、保有スキル、職歴、学歴、希望条件等）の自動取得および編集管理を行うためのスクリプト群の使い方と運用手順をまとめています。

> [!TIP]
> サイト構造、認証仕様、DOMセレクタ、内部Apollo GraphQLキャッシュ仕様の詳細は [site_structure.md](site_structure.md) を参照してください。

---

## 目次

1. [概要とできること](#1-概要とできること)
2. [スクリプト構成一覧](#2-スクリプト構成一覧)
3. [前提条件と認証基盤](#3-前提条件と認証基盤)
4. [各スクリプトの詳細な使い方](#4-各スクリプトの詳細な使い方)
   - [4.1 プロフィール情報の閲覧・取得: `manage_profile.py --action view`](#41-プロフィール情報の閲覧取得-manage_profilepy---action-view)
   - [4.2 Bio / About（自己紹介）の更新: `manage_profile.py --action update_bio`](#42-bio--about自己紹介の更新-manage_profilepy---action-update_bio)
   - [4.3 ソーシャルリンクの更新: `manage_profile.py --action update_socials`](#43-ソーシャルリンクの更新-manage_profilepy---action-update_socials)
5. [安全ガード・設計原則](#5-安全ガード設計原則)
6. [データ格納仕様](#6-データ格納仕様)

---

## 1. 概要とできること

Wellfound におけるプロフィールの自動同期・更新運用を目的として、以下の機能を提供します。

- **プロフィール全情報の高精度取得（Read）**: Next.js ページ内の正規化された Apollo Client キャッシュ（`window.__NEXT_DATA__.props.pageProps.apolloState.data`）から、Candidate 情報、保有スキル（`NewTag`）、職歴（`StartupRoleMetadata`）、学歴（`Education`）、居住地、レジュメURL、希望条件（`TalentViewer.analytics.traits`）を完全な構造化JSON/Markdown（`latest.md` / `latest.json`）として自動保存。
- **Bio / About（自己紹介）の安全な更新**: `--dry-run` プレビュー、Unified Diff 表示、更新前自動バックアップ保存付きで最大160文字の自己紹介文を更新。
- **ソーシャルリンク（LinkedIn / GitHub / Twitter / Website）の更新**: 誤入力を防ぐ安全ガード付きでURLを更新。
- **CLI規約準拠**: 標準出力（stdout）には変更・作成後ファイルパスのみを出力し、人間向けサマリ表示は `--summary`、進捗・ログは標準エラー出力（stderr）に出力。

---

## 2. スクリプト構成一覧

| スクリプト | 種別 | 主な役割 |
|---|---|---|
| [`scripts/wellfound/manage_profile.py`](../../scripts/wellfound/manage_profile.py) | Python CLI | Wellfound プロフィール（閲覧・Bio更新・ソーシャル更新等）管理エントリポイント |
| [`scripts/wellfound/manage_profile.mjs`](../../scripts/wellfound/manage_profile.mjs) | Playwright JS | Apollo キャッシュからのデータ抽出および DOM フォーム操作・Save ボタン自動化スクリプト |

> [!NOTE]
> 認証状態の判定および未認証時の手動ログイン待機ハンドオフは、共通認証エンジン（[`scripts/common/auth_engine.py`](../../scripts/common/auth_engine.py), [`scripts/common/js/universal_auth.mjs`](../../scripts/common/js/universal_auth.mjs)）により自動制御されます。個別スクリプトは不要です。

---

## 3. 前提条件と認証基盤

- **永続プロファイル**: 就活共通プロファイル `job-hunt`（`%LOCALAPPDATA%\claude-browser-profiles\job-hunt`）を使用。
- **未認証時のハンドオフ**: セッション切れ時は `auth_engine.py` により OS トースト通知を送信し、ユーザーの外部ターミナルで `playwright-cli -s=job-hunt open https://wellfound.com/login --headed --profile="..."` の実行を待機。

---

## 4. 各スクリプトの詳細な使い方

### 4.1 プロフィール情報の閲覧・取得: `manage_profile.py --action view`

現在のプロフィール（Candidate 情報、スキル、職歴、学歴、希望条件）を抽出し、`data/wellfound/profile/latest.md` および `latest.json` に保存します。

```powershell
# パスのみ出力（AI・パイプライン向け）
uv run python scripts/wellfound/manage_profile.py --action view

# 人間向けサマリ表示
uv run python scripts/wellfound/manage_profile.py --action view --summary

# JSON出力
uv run python scripts/wellfound/manage_profile.py --action view --json
```

### 4.2 Bio / About（自己紹介）の更新: `manage_profile.py --action update_bio`

```powershell
# 差分プレビュー（変更を適用しない安全確認）
uv run python scripts/wellfound/manage_profile.py --action update_bio --bio "Full-stack engineer..." --dry-run

# 実際に更新（自動バックアップを取得した上で適用）
uv run python scripts/wellfound/manage_profile.py --action update_bio --bio "Full-stack engineer..."
```

### 4.3 ソーシャルリンクの更新: `manage_profile.py --action update_socials`

```powershell
# 差分プレビュー
uv run python scripts/wellfound/manage_profile.py --action update_socials --linkedin "https://www.linkedin.com/in/..." --github "https://github.com/..." --dry-run

# 実際に更新
uv run python scripts/wellfound/manage_profile.py --action update_socials --linkedin "https://www.linkedin.com/in/..."
```

### 4.4 実績・成果 (What I've built) の更新: `manage_profile.py --action update_achievements`

```powershell
# 差分プレビュー
uv run python scripts/wellfound/manage_profile.py --action update_achievements --achievements "Built and deployed an AI agent system..." --dry-run

# 実際に更新
uv run python scripts/wellfound/manage_profile.py --action update_achievements --achievements "Built and deployed an AI agent system..."
```

### 4.5 職歴の更新: `manage_profile.py --action update_experience`

```powershell
# 終了日の追加・在籍解除（Plus Alpha Consulting: 07/2025終了、current: false）
uv run python scripts/wellfound/manage_profile.py --action update_experience --company-name "Plus Alpha Consulting" --ended-at "07/2025" --no-current
```

### 4.6 職歴の新規追加: `manage_profile.py --action add_experience`

```powershell
# 新規職歴の追加（Headwaters Co., Ltd. 在籍中）
uv run python scripts/wellfound/manage_profile.py --action add_experience --company-name "Headwaters Co., Ltd." --role-title "AI Engineer / Full-Stack Engineer" --started-at "08/2025" --current --description "AI Engineer / Full-Stack Engineer..."
```

### 4.7 職歴の削除: `manage_profile.py --action remove_experience`

```powershell
uv run python scripts/wellfound/manage_profile.py --action remove_experience --company-name "Headwaters"
```

### 4.8 保有スキルの追加: `manage_profile.py --action add_skills`

```powershell
uv run python scripts/wellfound/manage_profile.py --action add_skills --skills "Java, Azure, Kubernetes, Docker, FastAPI, Terraform"
```

### 4.9 アイデンティティの更新: `manage_profile.py --action update_identity`

```powershell
uv run python scripts/wellfound/manage_profile.py --action update_identity --east-asian --no-south-asian
```

---

## 5. 安全ガード・設計原則

1. **更新前完全自動バックアップ**:
   いかなる更新操作（`update_*`）でも、変更を反映する直前に現在の完全プロフィール（JSON / Markdown）を `data/wellfound/profile/backups/{timestamp}_*.json` に永続保存します。
2. **`--dry-run` 差分プレビュー**:
   更新前に必ず `--dry-run` オプションで変更差分（Unified Diff）を確認できます。
3. **動的アクションバーと Save / Cancel ボタン制御**:
   フォーム変更時に出現する `Save` ボタンのクリックを検知し、完了まで待機します。異常時は `Cancel` ボタンで復元します。

---

## 6. データ格納仕様

```
data/wellfound/profile/
├── latest.json              # 最新の完全プロフィール構造化JSON
├── latest.md                # フロントマター付き最新プロフィールMarkdown
└── backups/                 # 更新前自動バックアップ
    ├── 20261014_120000_pre_update_bio.json
    └── 20261014_120000_pre_update_bio.md
```
