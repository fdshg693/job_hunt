# クイックスタートガイド (QUICKSTART.md)

本ガイドは、公開リポジトリ（パブリック版）を取得（clone または fork）したユーザーが、**「自分専用のAI就活サポート環境」をゼロから立ち上げ、AIエージェントを最大限に活用するための実践ガイド**です。

---

## 💡 はじめに：公開リポジトリの前提とテンプレート

本リポジトリは、GitHub Actions（`.github/workflows/sync-public.yml`）によるホワイトリスト同期を採用しています。
そのため、**プライバシー保護の観点から個人のデータフォルダ（`profile/`, `interviews/`, `chat/`, `recruiters/`, `data/` 等）は公開リポジトリには一切含まれていません**。

その代わりに、本リポジトリには雛形ディレクトリ **[`templates/`](templates/)** が用意されています。
`templates/` をコピーして数箇所書き換えるだけで、すぐにあなた専用の環境が整います。

---

## 🛠️ Step 1: 開発環境のセットアップ

### 1. Python環境の準備
本プロジェクトはパッケージマネージャとして [`uv`](https://github.com/astral-sh/uv) を推奨しています（標準の `pip` / `venv` でも動作します）。

```powershell
# uv がインストールされている場合
uv sync

# または標準の pip / venv を使う場合
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

### 2. Playwright（ブラウザ自動化）のインストール
求人票の取得やサイト操作に必要な Playwright ブラウザおよび `playwright-cli` をインストールします。

```powershell
npm install -g @playwright/cli@latest
npx playwright install chromium
```

### 3. ブラウザログインセッションの共有プロファイル
スクリプトやAIエージェントによる自動化では、就活共通のブラウザプロファイル（Cookie・ログイン状態）を参照します。
- Windows: `%LOCALAPPDATA%\claude-browser-profiles\job-hunt`
- Mac/Linux: `~/.config/claude-browser-profiles/job-hunt`

各転職サイト（Findy, ビズリーチ, OpenWork等）にログインする際は、普段お使いの外部ターミナルから一度プロファイルを指定して開いて手動ログインしておくと、次回以降エージェントがログイン済みセッションを自動利用できます。

---

## 📁 Step 2: テンプレートからプロファイル（SSOT）を初期化

AIエージェントがあなたの経歴・希望条件・足切り基準を正確に理解するための**唯一の正本（SSOT: Single Source of Truth）**を作成します。

リポジトリ内の [`templates/profile/`](templates/profile/) をそのまま作業用ディレクトリ `profile/` としてコピーします。

```powershell
# PowerShell の場合
Copy-Item -Recurse templates/profile profile

# Bash / zsh の場合
cp -r templates/profile profile
```

コピー後、`profile/` 配下に生成された以下のファイルをエディタで開き、ご自身の情報に書き換えてください。

| ファイルパス | 役割・内容 | 書き換えのポイント |
|---|---|---|
| [`profile/resume.md`](templates/profile/resume.md) | **職務経歴書マスター** | これまでの職歴、担当プロジェクト、使用技術、学歴、資格 |
| [`profile/preferences.md`](templates/profile/preferences.md) | **希望条件・転職の軸** | 希望職種、希望年収（最低・理想）、リモート比率、技術スタック、**足切り条件（disqualifiers）** |
| [`profile/skills.md`](templates/profile/skills.md) | **保有スキル・強み・自己PR** | 得意言語・フレームワーク、自己PRエピソード |
| [`profile/status.md`](templates/profile/status.md) | **選考状況ダッシュボード** | 現在の活動フェーズ、目標時期、応募先一覧（薄い進捗表） |
| [`profile/internal/criteria.md`](templates/profile/internal/criteria.md) | **【非公開】本音クライテリア** | 外部エージェントには言えない本音の足切り・裏基準（AIの判定時のみ参照） |
| [`profile/internal/companies.md`](templates/profile/internal/companies.md) | **【非公開】企業格付け・メモ** | 気になる企業のランク付けや個人的なブラックリスト |
| [`profile/internal/notes.md`](templates/profile/internal/notes.md) | **【非公開】本音の転職理由** | 建前の志望動機を作るためのベースとなる本音メモ |

> [!IMPORTANT]
> **`profile/internal/` の厳格な非公開ルール**:
> `profile/internal/` 配下に書いた内容は、AIエージェントが求人の足切りスクリーニングや意思決定支援を行う際にのみ参照されます。
> 各転職サイトへのプロフィール反映スクリプトや、応募書類・メッセージ返信・面接用文章を作成する際には**絶対に外部露出・引用されないルール（`.agents/rules/user-profile.md`）**が定義されています。安心して本音を記述してください。

---

## 📂 Step 3: ログ管理フォルダ（`chat/`, `recruiters/`, `interviews/`）の初期化

求人相談ログ、リクルーター評価、面談メモを蓄積する各フォルダも、テンプレートから一括コピーして準備できます。

```powershell
# PowerShell の場合
Copy-Item -Recurse templates/chat chat
Copy-Item -Recurse templates/recruiters recruiters
Copy-Item -Recurse templates/interviews interviews

# Bash / zsh の場合
cp -r templates/chat chat
cp -r templates/recruiters recruiters
cp -r templates/interviews interviews
```

### 各ディレクトリの役割（三層管理アーキテクチャ）
- **第1層: 全体ダッシュボード (`profile/status.md`)**:
  - 全社の選考フェーズ、次回アクション、優先度を一覧する薄い表。
- **第2層: 企業メインファイル (`chat/{folder}/{company-name}.md`)**:
  - 企業ごとの求人調査、プロファイル適合分析（fit_score）、最新の選考ステータスを集約。
  - 状態別フォルダ: `active/`（検討中）、`rejected/`（企業側お見送り）、`declined/`（自分から辞退）、`discarded/`（早期スクリーニング打ち切り集約）。
- **第3層: 面談・選考議事録 (`interviews/{company-name}/{YYYY-MM-DD}_{stage}.md`)**:
  - カジュアル面談や各次面接の質疑応答生ログ、逆質問、一次情報を独立記録。
- **人単位の評価カルテ (`recruiters/{folder}/{recruiter-key}.md`)**:
  - 企業とは独立して、エージェント担当者・ヘッドハンター単位の提案品質や信頼度を蓄積。
  - 状態別フォルダ: `active/`（やり取り中）、`trusted/`（優良パートナー）、`declined/`（見送り）、`blacklisted/`（要注意・NG）。

---

## 🤖 Step 4: AIエージェントに「いつ」「どんなスキルで」「どう頼むか」

本リポジトリには、AIエージェント（Antigravity, Cursor, Claude Code, Windsurf等）のための専門スキル（`.agents/skills/`）と行動規範（`.agents/rules/`）が組み込まれています。

日常の就職・転職活動において、以下のような場面でチャットからAIエージェントに指示を出してください。

---

### 場面 1: 気になる求人や企業を相談・調査したいとき

- **使用スキル**: `consult-company-job`
- **タイミング**:
  - 転職サイト（Findy, ビズリーチ, Forkwell等）で気になる求人を見つけたとき
  - スカウトメールに記載された求人URLを検討したいとき
  - 企業名を聞いて「この会社はどうだろう？」と思ったとき
- **AIへの指示プロンプト例**:

```text
この求人について相談したいです。
URL: https://findy-code.io/companies/... （または求人票のテキストを貼り付け）

私の希望条件（profile/preferences.md）や経歴と照らし合わせて、受ける価値があるか分析してください。
OpenWorkの口コミや退職理由、開発環境なども多角的に調べた上で、fit_score をレンジ（例: 60〜85/100）で提示し、
調査結果を chat/active/{company-name}.md に保存してください。
また、私の希望に不明点があれば積極的に質問してください。
```

- **エージェントが自動で行うこと**:
  1. `profile/preferences.md` の足切り条件（Dealbreakers）や技術志向と照合
  2. 求人票詳細本文および OpenWork の口コミ（`scripts/openwork/fetch_reviews.py`）を調査
  3. 建前の求人票情報だけでなく、未検証のリスクを含めて fit_score をレンジ（幅）で提示
  4. プロファイルに不足している情報を引き出すため、ユーザーへ能動的に追加質問を投げかけ
  5. 構造化ログ（YAML Frontmatter付き）を `chat/active/{company-name}.md` に新規作成・更新

---

### 場面 2: エージェント担当者やヘッドハンターを見極めたいとき

- **使用スキル**: `consult-company-job`
- **タイミング**:
  - ビズリーチ、LinkedIn、メール等でエージェント担当者・ヘッドハンターからスカウトが届いたとき
- **AIへの指示プロンプト例**:

```text
ビズリーチで、〇〇エージェンシーの山田さんというヘッドハンターから以下のスカウトが届きました。
（スカウト文面と紹介求人を貼り付け）

このリクルーターの提案品質（定型文コピペのバラ撒きではないか、私の希望条件や足切り条件を理解しているか）を評価し、
事前面談を受ける価値があるか判断してください。
結果を recruiters/active/bizreach_yamada-taro.md に記録してください。
```

- **エージェントが自動で行うこと**:
  1. 提案内容があなたの足切り条件（SES、出社必須、年収下限等）に抵触していないか検証
  2. 担当者の評価ランク（S〜D）、マッチング精度を判定
  3. `recruiters/` 配下に担当者ごとのカルテを作成し、悪質・要注意担当者（`blacklisted/`）をフィルタリング

---

### 場面 3: 面談の事前準備（想定質問・逆質問）をしたいとき

- **タイミング**:
  - カジュアル面談や各次面接の日程が決まり、準備をしたいとき
- **AIへの指示プロンプト例**:

```text
明日、〇〇社（chat/active/xxx.md）とカジュアル面談があります。
私の職歴（profile/resume.md）と相手の求人内容を踏まえて、
- 私がアピールすべき経験・実績のポイント
- 現場のエンジニアや人事に対して確認すべき「逆質問」のリスト（リモート実態、開発体制、技術的負債など）
を整理してください。
```

---

### 場面 4: 面談が終わって、議事録・感想を記録したいとき

- **タイミング**:
  - カジュアル面談や面接を終えた直後
- **AIへの指示プロンプト例**:

```text
〇〇社のカジュアル面談が終わりました。以下の雑多なメモを渡すので、
interviews/xxx/2026-10-15_casual.md に構造化された面談ログとしてまとめてください。
また、面談を通じて分かった最新状況を chat/active/xxx.md に反映し、
選考ダッシュボード（profile/status.md）のステータスも更新してください。

【面談メモ】
- 開発チームは10名、GoとTypeScriptを使用
- リモートは現在週1出社が原則で、制度変更の予定はないとのこと
- ...
```

---

### 場面 5: 各種求人サイトの情報を取得・同期したいとき

- **使用スクリプト**: `scripts/{site}/`
- **主な実行コマンド例**:

```powershell
# OpenWork で特定の会社の口コミ・8項目スコアを取得
python scripts/openwork/fetch_reviews.py --company "株式会社メルカリ" --summary

# Findy でおすすめ求人（推薦アルゴリズム準拠）を取得
python scripts/findy/fetch_recommends.py --summary

# ビズリーチ で最新のメッセージ・スカウト一覧を取得
python scripts/bizreach/navigate_messages.py --summary

# ローカルに保存された求人Markdownを条件で横断検索
python scripts/common/search_jobs.py --query "Go Kubernetes" --min-salary 700
```

> [!TIP]
> **ブラウザでログインが必要な場合**:
> ログインセッションが切れている場合は、お使いの外部ターミナルで以下のコマンドを実行して通常ブラウザを開き、手動ログインを完了させてください。
> ```powershell
> playwright-cli -s=job-hunt open https://bizreach.jp/login/ --headed --profile="$env:LOCALAPPDATA\claude-browser-profiles\job-hunt"
> ```
> ログイン後はブラウザを閉じるだけで、セッションが自動保存されます。

---

## 🔒 Step 5: （任意）プライベート／パブリック運用の方法

もしあなたも「自分用のプライベートリポジトリ」で転職活動を行いながら、コード基盤のみを「パブリックリポジトリ」としてGitHubで公開したい場合は、標準で用意されている GitHub Actions ワークフロー（`.github/workflows/sync-public.yml`）をご利用いただけます。

1. **SSH Deploy Key の生成**:
   ```powershell
   ssh-keygen -t ed25519 -C "job_hunt_public_sync" -f .\sync_deploy_key --% -N ""
   ```
2. **公開リポジトリ（同期先）**: `Settings > Deploy keys` に `sync_deploy_key.pub` を登録（**Allow write access にチェック**）。
3. **プライベートリポジトリ（本番）**: `Settings > Secrets and variables > Actions` に Secret `SYNC_DEPLOY_KEY` として `sync_deploy_key`（秘密鍵）を登録。
4. `main` ブランチに push すると、自動的に機密ディレクトリ（`profile/`, `chat/`, `interviews/`, `recruiters/`, `data/`）を除外したクリーンな単一コミットが公開リポジトリへ force push されます。

---

## 📖 次に読むべきドキュメント

- **[`README.md`](./README.md)**: プロジェクト全体のコンセプト・全体像
- **[`docs/README.md`](./docs/README.md)**: 各サイト別（Findy, ビズリーチ, OpenWork等）のスクリプト仕様・サイト構造ドキュメント一覧
- **[`docs/guides/new_site_scraper_guide.md`](./docs/guides/new_site_scraper_guide.md)**: 新たな転職サイトを自動化対象に追加したい場合の実装ガイド
