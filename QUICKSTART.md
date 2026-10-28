# クイックスタートガイド (QUICKSTART.md)

本ガイドは、公開リポジトリ（パブリック版）を取得（clone または fork）したユーザーが、**「自分専用のAI就活サポート環境」をゼロから立ち上げ、AIエージェントを最大限に活用するための実践ガイド**です。

---

## 💡 はじめに：公開リポジトリの前提とテンプレート

本リポジトリは、GitHub Actions（`.github/workflows/sync-public.yml`）によるホワイトリスト同期を採用しています。
そのため、**プライバシー保護の観点から個人のデータフォルダ（`vault/`, `data/` 等）は公開リポジトリには一切含まれていません**。

その代わりに、本リポジトリには雛形ディレクトリ **[`templates/vault/`](templates/vault/)** が用意されています。
`templates/vault/` を `vault/` としてコピーして数箇所書き換えるだけで、すぐにあなた専用の環境が整います。

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

## 📁 Step 2: テンプレートから vault（SSOT）を初期化

AIエージェントがあなたの経歴・希望条件・足切り基準を正確に理解するための**唯一の正本（SSOT: Single Source of Truth）**を作成します。

リポジトリ内の [`templates/vault/`](templates/vault/) をそのまま作業用ディレクトリ `vault/` としてコピーします。`templates/vault/` は `vault/` と同じ構成（`profile/`, `tracks/domestic/`, `tracks/overseas/`, `recruiters/`）になっているため、プロフィール・選考ログ・リクルーター評価の各フォルダが一括で準備されます。

```powershell
# PowerShell の場合
Copy-Item -Recurse templates/vault vault

# Bash / zsh の場合
cp -r templates/vault vault
```

コピー後、`vault/` 配下の以下のファイルをエディタで開き、ご自身の情報に書き換えてください（`vault/` 全体の地図は `vault/README.md` を参照）。

| ファイルパス | 役割・内容 | 書き換えのポイント |
|---|---|---|
| [`vault/profile/resume.md`](templates/vault/profile/resume.md) | **職務経歴書マスター** | これまでの職歴、担当プロジェクト、使用技術、学歴、資格 |
| [`vault/profile/preferences.md`](templates/vault/profile/preferences.md) | **共通の希望条件・転職の軸** | 希望職種、技術志向、ドメイン、共通の足切り条件（disqualifiers） |
| [`vault/profile/skills.md`](templates/vault/profile/skills.md) | **保有スキル・強み・自己PR** | 得意言語・フレームワーク、自己PRエピソード |
| [`vault/profile/accounts.md`](templates/vault/profile/accounts.md) | **媒体アカウント状況** | 各転職サイトの登録・プロフィール同期状況 |
| [`vault/tracks/domestic/strategy.md`](templates/vault/tracks/domestic/strategy.md) | **track 固有の希望条件** | 希望年収（最低・理想）、出社頻度・勤務地、企業フェーズ、雇用形態 |
| [`vault/tracks/domestic/pipeline.md`](templates/vault/tracks/domestic/pipeline.md) | **選考状況ダッシュボード** | 現在の活動フェーズ、目標時期（選考一覧は `scripts/vault/build_pipeline.py` が自動生成） |
| [`vault/tracks/domestic/criteria.md`](templates/vault/tracks/domestic/criteria.md) | **【非公開】本音クライテリア** | 外部エージェントには言えない本音の足切り・裏基準（AIの判定時のみ参照） |
| [`vault/tracks/domestic/ratings.md`](templates/vault/tracks/domestic/ratings.md) | **【非公開】企業格付け・メモ** | 気になる企業のランク付けや個人的なブラックリスト |
| [`vault/profile/internal/notes.md`](templates/vault/profile/internal/notes.md) | **【非公開】本音の転職理由** | 建前の志望動機を作るためのベースとなる本音メモ |

> [!NOTE]
> **track（トラック）について**: 転職活動は `domestic`（日本法人での就業。外資系の日本法人を含む）と `overseas`（海外法人との雇用・契約。海外企業へのフルリモート就業を含む）に分けて管理します。海外転職も検討する場合は `vault/tracks/overseas/` の各ファイルも同様に記入してください。

> [!IMPORTANT]
> **非公開ファイルの厳格なルール**:
> `vault/tracks/{track}/criteria.md`・`vault/tracks/{track}/ratings.md`・`vault/profile/internal/` に書いた内容は、AIエージェントが求人の足切りスクリーニングや意思決定支援を行う際にのみ参照されます。
> 各転職サイトへのプロフィール反映スクリプトや、応募書類・メッセージ返信・面接用文章を作成する際には**絶対に外部露出・引用されないルール（`.agents/rules/user-profile.md`）**が定義されています。安心して本音を記述してください。

---

## 📂 Step 3: ログ管理の構成（企業・面談・リクルーター）

求人相談ログ、リクルーター評価、面談メモを蓄積するフォルダは、Step 2 のコピーで `vault/` 配下に準備済みです。

### 各ファイルの役割（三層管理アーキテクチャ）
- **第1層: 全体ダッシュボード (`vault/tracks/{track}/pipeline.md`)**:
  - 全社の選考フェーズ、次回アクション、優先度を一覧する薄い表（各企業ログのフロントマターから自動生成）。
- **第2層: 企業メインファイル (`vault/tracks/{track}/companies/{company-name}/index.md`)**:
  - 企業ごとの求人調査、プロファイル適合分析（fit_score）、最新の選考ステータスを集約。
  - 選考ステータス（検討中・企業側お見送り・自分から辞退など）はフロントマターの `status` で管理し、フォルダ移動は行いません。
  - 早期スクリーニングで打ち切った企業は `vault/tracks/{track}/screening/` に調査バッチ単位で集約。
  - 前職・現職企業は `vault/profile/employers/{company-name}.md` に配置。
- **第3層: 面談・選考議事録 (`vault/tracks/{track}/companies/{company-name}/{YYYY-MM-DD}_{stage}.md`)**:
  - カジュアル面談や各次面接の質疑応答生ログ、逆質問、一次情報を企業メインファイルと同じフォルダに独立記録。
- **人単位の評価カルテ (`vault/recruiters/{recruiter-key}/index.md`)**:
  - 企業とは独立して、エージェント担当者・ヘッドハンター単位の提案品質や信頼度を蓄積。
  - 担当者との事前面談ログも同じフォルダ（`vault/recruiters/{recruiter-key}/`）に記録。

### フロントマターのスキーマと検証

各ログのフロントマター（キー・型・許容値）は `scripts/vault/schema/` で定義されています。一覧は [`docs/vault/schema.md`](docs/vault/schema.md)（自動生成）を見てください。年収は万円の整数（`salary_min` / `salary_max`）、勤務形態は `remote_type` ＋週あたり出社日数、fit_score は `fit_score_min` / `fit_score_max` のように、絞り込みに使う値は構造化されています。

ログを手で書き換えたら、検証してから選考ダッシュボードを再生成します（AIエージェントは記録のたびにこれを実行します）。

```powershell
uv run python scripts/vault/validate.py --summary        # スキーマ違反・フォルダ名との不一致などを検出
uv run python scripts/vault/build_pipeline.py --track domestic
```

---

## 🤖 Step 4: AIエージェントに「いつ」「どんなスキルで」「どう頼むか」

本リポジトリには、AIエージェントのための専門スキル（`.agents/skills/`）と行動規範（`.agents/rules/`）が組み込まれています。Antigravity は `.agents/` を、Claude Code は同じ内容を変換した `.claude/` を自動で読み込むため、リポジトリのルートでエージェントを起動するだけで使えます。Cursor・Codex CLI など他のエージェントを使う場合の設定は、[README の「AIコーディングエージェントで使う場合」](README.md#aiコーディングエージェントで使う場合)を参照してください。

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

私の希望条件（vault/profile/preferences.md, vault/tracks/domestic/strategy.md）や経歴と照らし合わせて、受ける価値があるか分析してください。
OpenWorkの口コミや退職理由、開発環境なども多角的に調べた上で、fit_score をレンジ（例: 60〜85/100）で提示し、
調査結果を vault/tracks/domestic/companies/{company-name}/index.md に保存してください。
また、私の希望に不明点があれば積極的に質問してください。
```

- **エージェントが自動で行うこと**:
  1. `vault/profile/preferences.md`・`vault/tracks/{track}/strategy.md` の希望条件や足切り条件（Dealbreakers）、技術志向と照合
  2. 求人票詳細本文および OpenWork の口コミ（`scripts/openwork/fetch_reviews.py`）を調査
  3. 建前の求人票情報だけでなく、未検証のリスクを含めて fit_score をレンジ（幅）で提示
  4. プロファイルに不足している情報を引き出すため、ユーザーへ能動的に追加質問を投げかけ
  5. 構造化ログ（YAML Frontmatter付き）を `vault/tracks/{track}/companies/{company-name}/index.md` に新規作成・更新

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
結果を vault/recruiters/bizreach_yamada-taro/index.md に記録してください。
```

- **エージェントが自動で行うこと**:
  1. 提案内容があなたの足切り条件（SES、出社必須、年収下限等）に抵触していないか検証
  2. 担当者の評価ランク（S〜D）、マッチング精度を判定
  3. `vault/recruiters/` 配下に担当者ごとのカルテを作成し、悪質・要注意担当者（`status: blacklisted`）をフィルタリング

---

### 場面 3: 面談の事前準備（想定質問・逆質問）をしたいとき

- **タイミング**:
  - カジュアル面談や各次面接の日程が決まり、準備をしたいとき
- **AIへの指示プロンプト例**:

```text
明日、〇〇社（vault/tracks/domestic/companies/xxx/index.md）とカジュアル面談があります。
私の職歴（vault/profile/resume.md）と相手の求人内容を踏まえて、
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
vault/tracks/domestic/companies/xxx/2026-10-15_casual.md に構造化された面談ログとしてまとめてください。
また、面談を通じて分かった最新状況を vault/tracks/domestic/companies/xxx/index.md に反映し、
選考ダッシュボード（vault/tracks/domestic/pipeline.md）も更新してください。

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
python scripts/common/search_local_jobs.py --query "Go Kubernetes" --min-salary 700
```

> [!TIP]
> **ブラウザでログインが必要な場合**:
> ログインセッションが切れている場合は、お使いの外部ターミナルで以下のコマンドを実行して通常ブラウザを開き、手動ログインを完了させてください。
> ```powershell
> playwright-cli -s=job-hunt open https://bizreach.jp/login/ --headed --profile="$env:LOCALAPPDATA\claude-browser-profiles\job-hunt"
> ```
> ログイン後はブラウザを閉じるだけで、セッションが自動保存されます。

---

### 場面 6: 選考状況や企業ログを自分で眺めたいとき（Web UI）

記録は AIエージェント（CLI）が行い、人間はローカルの閲覧専用 Web UI で絞り込み・閲覧します。

```powershell
uv run python -m webui
# → http://127.0.0.1:8765 をブラウザで開く
```

- **ダッシュボード**: 要対応・確定済予定・結果待ちと、track ごとの選考中企業
- **企業一覧/詳細**: 会社名検索、「進行中だけ」、fit_score 下限、年収、勤務形態、タグ等で絞り込み。詳細では本文と面談ログを閲覧
- **リクルーター / スクリーニング / 求人 / 全文検索**: 取得済み求人（`data/*/jobs`）も含めて横断検索
- 表示は vault から作る SQLite 索引（`data/vault_index.sqlite`）を使い、vault が変わると自動で作り直されます。127.0.0.1 でのみ待ち受け、vault への書き込みは行いません。非公開ファイル（`criteria.md`・`ratings.md`・`vault/profile/internal/`）は表示しません。
- 編集したい場合は、AIエージェントに依頼するかエディタで Markdown を直接書き換えてください。

---

## 🔒 Step 5: （任意）プライベート／パブリック運用の方法

もしあなたも「自分用のプライベートリポジトリ」で転職活動を行いながら、コード基盤のみを「パブリックリポジトリ」としてGitHubで公開したい場合は、標準で用意されている GitHub Actions ワークフロー（`.github/workflows/sync-public.yml`）をご利用いただけます。

1. **SSH Deploy Key の生成**:
   ```powershell
   ssh-keygen -t ed25519 -C "job_hunt_public_sync" -f .\sync_deploy_key --% -N ""
   ```
2. **公開リポジトリ（同期先）**: `Settings > Deploy keys` に `sync_deploy_key.pub` を登録（**Allow write access にチェック**）。
3. **プライベートリポジトリ（本番）**: `Settings > Secrets and variables > Actions` に Secret `SYNC_DEPLOY_KEY` として `sync_deploy_key`（秘密鍵）を登録。
4. `main` ブランチに push すると、自動的に機密ディレクトリ（`vault/`, `data/`, `ai/plans/`, `internal/`, `.scratch/`）を除外したクリーンな単一コミットが公開リポジトリへ force push されます。

---

## 📖 次に読むべきドキュメント

- **[`README.md`](./README.md)**: プロジェクト全体のコンセプト・全体像
- **[`docs/vault/schema.md`](./docs/vault/schema.md)**: vault フロントマタースキーマ（自動生成）
- **[`docs/README.md`](./docs/README.md)**: 各サイト別（Findy, ビズリーチ, OpenWork等）のスクリプト仕様・サイト構造ドキュメント一覧
- **[`docs/guides/new_site_scraper_guide.md`](./docs/guides/new_site_scraper_guide.md)**: 新たな転職サイトを自動化対象に追加したい場合の実装ガイド
