# LinkedIn 自動化スクリプト利用ガイド

本ディレクトリでは、LinkedIn（[linkedin.com](https://www.linkedin.com/)）における求人検索、求人詳細ダウンロード、プロフィール取得、Headline/About更新、職歴（Experience）CRUD管理、およびスキル（Skills）CRUD管理を行うためのスクリプト群の使い方と運用手順をまとめています。

> [!TIP]
> サイト構造・主要画面・DOMセレクタ・保護IDの詳細は [site_structure.md](site_structure.md) を参照してください。

---

## 目次

1. [概要とできること](#1-概要とできること)
2. [スクリプト構成一覧](#2-スクリプト構成一覧)
3. [前提条件と環境準備](#3-前提条件と環境準備)
4. [各スクリプトの詳細な使い方](#4-各スクリプトの詳細な使い方)
   - [4.1 求人検索・詳細一括ダウンロード: `search_jobs.py`](#41-求人検索詳細一括ダウンロード-search_jobspy)
   - [4.2 求人詳細単体取得: `fetch_job.py`](#42-求人詳細単体取得-fetch_jobpy)
   - [4.3 プロフィール情報取得: `fetch_profile.py`](#43-プロフィール情報取得-fetch_profilepy)
   - [4.4 プロフィール（Headline, About）更新: `manage_profile.py`](#44-プロフィールheadline-about更新-manage_profilepy)
   - [4.5 職歴（Experience）CRUD管理: `manage_experience.py`](#45-職歴experiencecrud管理-manage_experiencepy)
   - [4.6 保有スキル（Skills）CRUD管理: `manage_skills.py`](#46-保有スキルskillscrud管理-manage_skillspy)
   - [4.7 メッセージ一覧・スレッド取得: `navigate_messages.py`](#47-メッセージ一覧スレッド取得-navigate_messagespy)
   - [4.8 受信招待（つながり申請）取得 & 価値検討: `fetch_invitations.py`](#48-受信招待つながり申請取得--価値検討-fetch_invitationspy)
5. [実践シナリオ別ワークフロー](#5-実践シナリオ別ワークフロー)
6. [データ格納仕様](#6-データ格納仕様)

---

## 1. 概要とできること

外資系・グローバル企業へのアプローチおよび英語プロフィール連携を効率化するため、以下の機能を提供します。

- **求人検索 & 一覧永続化**: キーワード、勤務地、リモート形態等で求人を検索し、検索結果一覧Markdown/JSONを自動生成（`search_jobs.py`）。
- **求人詳細の一括ダウンロード**: 検索結果でヒットした求人詳細を一括取得し、`data/linkedin/jobs/{id}.md` として自動保存。
- **求人詳細単体取得**: 特定の求人URLまたはIDから、募集要項・仕事内容・必須/歓迎要件・就業条件・技術スタックを構造化Markdownとして取得・保存（`fetch_job.py`）。
- **プロフィール情報の完全取得**: プロフィールトップ、自己紹介（About）、スキル一覧画面（`/details/skills/`）から登録情報を取得し、構造化Markdown/JSON（`latest.md` / `latest.json`）として永続化（`fetch_profile.py`）。
- **Headline / About 更新管理**: 肩書き（Headline）および自己紹介（About）を安全に更新。事前バックアップおよび完了後の自動再同期に対応（`manage_profile.py`）。
- **職歴（Experience）CRUD管理**: 職歴詳細画面（`/details/experience/`）における職歴の作成・参照・更新・削除。重要職歴（ヘッドウォータース、プラスアルファ等）への変更を遮断する安全ガードを搭載（`manage_experience.py`）。
- **スキル（Skills）CRUD管理**: 保有スキル一覧画面（`/details/skills/`）におけるスキルの参照・追加・削除。事前バックアップと再同期に対応（`manage_skills.py`）。
- **メッセージ一覧取得**: 会話一覧やスレッド本文を取得・永続化（`navigate_messages.py`）。
- **受信招待取得 & つながり価値検討**: 保留中の受信つながり申請を取得し、ユーザープロファイル（希望条件・スキル・内部基準）と照合して属性分類・推奨度・評価コメントを自動判定（`fetch_invitations.py`）。
- **派生英語版プロフィール（`vault/profile/en/`）連携**: 更新データのソースとして `vault/profile/en/` の英訳データを活用可能。
- **安全な認証ハンドオフ**: 未ログインやチェックポイント（CAPTCHA等）検知時は共通認証エンジン（`scripts/common/auth_engine.py`）によりOSトースト通知を発行し、資格情報をコンテキストに漏洩させることなく外部ターミナルでの手動解除・ログイン完了を待機。

---

## 2. スクリプト構成一覧

| スクリプト | 種別 | 主な役割 |
|---|---|---|
| [`scripts/linkedin/search_jobs.py`](../../scripts/linkedin/search_jobs.py) | Python CLI | 求人検索・条件絞り込み・検索結果保存・求人詳細一括ダウンロード |
| [`scripts/linkedin/fetch_job.py`](../../scripts/linkedin/fetch_job.py) | Python CLI | 単体求人詳細（URL/ID）の取得・Markdown構造化保存 |
| [`scripts/linkedin/fetch_profile.py`](../../scripts/linkedin/fetch_profile.py) | Python CLI | プロフィール（Headline, About, Skills等）の自動取得・永続化 |
| [`scripts/linkedin/manage_profile.py`](../../scripts/linkedin/manage_profile.py) | Python CLI | Headline（肩書き）および About（自己紹介）の更新管理 |
| [`scripts/linkedin/manage_experience.py`](../../scripts/linkedin/manage_experience.py) | Python CLI | 職歴（Experience）の参照・追加・更新・削除（安全ガード付き） |
| [`scripts/linkedin/manage_skills.py`](../../scripts/linkedin/manage_skills.py) | Python CLI | 保有スキル（Skills）の参照・追加・削除（事前バックアップ付き） |
| [`scripts/linkedin/navigate_messages.py`](../../scripts/linkedin/navigate_messages.py) | Python CLI | メッセージ会話一覧・スレッド本文の取得・永続化（読み取り専用） |
| [`scripts/linkedin/fetch_invitations.py`](../../scripts/linkedin/fetch_invitations.py) | Python CLI | 受信招待一覧取得・プロフィール連携・つながり価値評価（読み取り・検討専用） |
| [`scripts/linkedin/invitation_evaluator.py`](../../scripts/linkedin/invitation_evaluator.py) | Python モジュール | 申請者の属性分類・マッチングスコア・推奨ランク・コメント判定エンジン |
| [`scripts/linkedin/fetch_invitations.mjs`](../../scripts/linkedin/fetch_invitations.mjs) | Playwright JS | `/mynetwork/invitation-manager/received/` からDOM走査・招待一覧抽出 |
| [`scripts/linkedin/fetch_applicant_profile.mjs`](../../scripts/linkedin/fetch_applicant_profile.mjs) | Playwright JS | 申請者の公開プロフィールページから現職・自己紹介・スキルを抽出 |
| [`scripts/linkedin/navigate_messages.mjs`](../../scripts/linkedin/navigate_messages.mjs) | Playwright JS | `/messaging/` の会話リスト（内部スクロール）・スレッドDOMから抽出 |
| [`scripts/linkedin/fetch_profile.mjs`](../../scripts/linkedin/fetch_profile.mjs) | Playwright JS | プロフィールおよびスキル画面DOMから構造化データを抽出 |
| [`scripts/linkedin/manage_profile.mjs`](../../scripts/linkedin/manage_profile.mjs) | Playwright JS | プロフィール編集モーダルでのフォーム操作・保存 |
| [`scripts/linkedin/manage_experience.mjs`](../../scripts/linkedin/manage_experience.mjs) | Playwright JS | 職歴詳細画面でのCRUDモーダル操作・保存 |
| [`scripts/linkedin/manage_skills.mjs`](../../scripts/linkedin/manage_skills.mjs) | Playwright JS | スキル詳細画面での追加・削除モーダル操作 |

> [!NOTE]
> 認証状態（ログイン壁やセキュリティ確認・CAPTCHA）の判定および手動解除待機ハンドオフは、共通認証エンジン（[`scripts/common/auth_engine.py`](../../scripts/common/auth_engine.py), [`scripts/common/js/universal_auth.mjs`](../../scripts/common/js/universal_auth.mjs)）により自動制御されます。個別スクリプトは不要です。

---

## 3. 前提条件と環境準備

- **Python**: 3.13 以上（`uv` 使用）
- **ブラウザプロファイル**: 共通プロファイル `job-hunt` を利用します。
  - 格納先: `%LOCALAPPDATA%\claude-browser-profiles\job-hunt`
  - セキュリティチェックポイント等が発生した場合は、外部ターミナルで手動解除を行います。

---

## 4. 各スクリプトの詳細な使い方

### 4.1 求人検索・詳細一括ダウンロード: `search_jobs.py`

LinkedInの求人検索画面から求人を検索し、結果一覧ファイルおよび詳細Markdownを保存します。

```powershell
# 1. キーワード検索（日本国内）
uv run python scripts/linkedin/search_jobs.py "Python Engineer" -n 10

# 2. リモート形態で絞り込み、サマリを表示
uv run python scripts/linkedin/search_jobs.py "Backend" --remote "フルリモート" --summary

# 3. 検索ヒット求人の詳細Markdownを一括ダウンロード保存
uv run python scripts/linkedin/search_jobs.py "AI Engineer" -n 5 --download
```

### 4.2 求人詳細単体取得: `fetch_job.py`

URLまたはIDを指定して求人詳細を取得・保存します。

```powershell
uv run python scripts/linkedin/fetch_job.py "https://www.linkedin.com/jobs/view/4454473941/"
uv run python scripts/linkedin/fetch_job.py "4454473941" --summary
```

### 4.3 プロフィール情報取得: `fetch_profile.py`

現在のLinkedIn登録プロフィール（Headline, About, Skills等）を取得し、`data/linkedin/profile/` に保存します。

```powershell
uv run python scripts/linkedin/fetch_profile.py
```

### 4.4 プロフィール（Headline, About）更新: `manage_profile.py`

肩書きや自己紹介文を更新します（事前バックアップ自動取得）。

```powershell
# Headline の更新
uv run python scripts/linkedin/manage_profile.py --headline "Software Engineer | Python, Go, Cloud"

# About の更新
uv run python scripts/linkedin/manage_profile.py --about "Experienced backend engineer specialized in scalable architectures..."
```

### 4.5 職歴（Experience）CRUD管理: `manage_experience.py`

職歴の参照・追加・更新・削除を行います。

```powershell
# 1. 職歴一覧の参照
uv run python scripts/linkedin/manage_experience.py --action list

# 2. 新規職歴の追加
uv run python scripts/linkedin/manage_experience.py --action add --company "Example Inc." --title "Lead Engineer" --start-month "2024-04"

# 3. 職歴の更新（安全保護対象IDへの変更は拒絶されます）
uv run python scripts/linkedin/manage_experience.py --action update --id "12345678" --title "Senior Engineer"

# 4. 職歴の削除
uv run python scripts/linkedin/manage_experience.py --action delete --id "12345678"
```

### 4.6 保有スキル（Skills）CRUD管理: `manage_skills.py`

スキルの参照・追加・削除を行います。

```powershell
# 1. スキル一覧の参照
uv run python scripts/linkedin/manage_skills.py --action list

# 2. スキルの追加
uv run python scripts/linkedin/manage_skills.py --action add --skill "FastAPI"

# 3. スキルの削除
uv run python scripts/linkedin/manage_skills.py --action delete --skill "OldSkill"
```

### 4.7 メッセージ一覧・スレッド取得: `navigate_messages.py`

`/messaging/` の会話一覧（InMail・Sponsored・未読・スター付きの判別含む）を取得し、`data/linkedin/messages/` に保存します。ステータス（Focused / Other / Archived / Spam）および Focused / Other 時のサブフィルタ（Jobs / Unread / Connections / InMail / Starred）による絞り込みに対応しています。読み取り専用で、メッセージ送信は行いません。

```powershell
# 1. 会話一覧のみ（Focused・先頭5件、サマリ表示）
uv run python scripts/linkedin/navigate_messages.py -n 5 --summary

# 2. ステータスで絞り込み（Focused / Other / Archived / Spam）
uv run python scripts/linkedin/navigate_messages.py --status Other --summary
uv run python scripts/linkedin/navigate_messages.py --status Archived --summary
uv run python scripts/linkedin/navigate_messages.py --status Spam --summary

# 3. Focused または Other のサブフィルタで絞り込み（Jobs / Unread / Connections / InMail / Starred）
uv run python scripts/linkedin/navigate_messages.py --status Focused --filter Starred --summary
uv run python scripts/linkedin/navigate_messages.py --status Other --filter Jobs --summary
uv run python scripts/linkedin/navigate_messages.py --filter Unread --summary  # 省略時は Focused

# 4. スレッド本文も取得（各会話を開くため既読になる・低速。件数を絞ること）
uv run python scripts/linkedin/navigate_messages.py -n 3 --threads
```

> [!WARNING]
> `--threads` は各会話を開くため、相手に既読が通知されます。また `/messaging/` を開くと LinkedIn の仕様で先頭スレッドが自動で開かれます（一覧のみの取得でも先頭1件は既読になり得ます）。

### 4.8 受信招待（つながり申請）取得 & 価値検討: `fetch_invitations.py`

`/mynetwork/invitation-manager/received/` から受信したつながり申請の一覧を取得し、ユーザープロファイル（`vault/profile/`）と照合して属性分類・推奨度・評価コメントを自動判定します。

> [!IMPORTANT]
> 安全運用の原則に基づき、本スクリプトは**情報の読み取り・抽出・評価専用**です。承諾（Accept）や拒否（Ignore）の自動操作は行いません。

```powershell
# 1. 受信招待一覧を取得してサマリ表示（つながり価値評価を含む）
uv run python scripts/linkedin/fetch_invitations.py --summary

# 2. 申請者のプロフィール詳細ページも巡回して追加取得（経歴・スキル等を補完）
uv run python scripts/linkedin/fetch_invitations.py --fetch-profiles --summary

# 3. 件数を制限して取得（例: 先頭5件）
uv run python scripts/linkedin/fetch_invitations.py -n 5 --summary

# 4. 保存済みJSONファイルを再評価（ブラウザ起動なし・オフライン実行）
uv run python scripts/linkedin/fetch_invitations.py --input data/linkedin/invitations/latest.json --summary

# 5. JSON形式で標準出力（他ツール連携用）
uv run python scripts/linkedin/fetch_invitations.py --json
```

#### つながり価値評価の分類・推奨基準

| 項目 | 内容 |
|---|---|
| **属性カテゴリ** | `企業人事 / 採用担当`, `転職エージェント / ヘッドハンター`, `エンジニア / 技術者`, `営業 / ビジネス / 勧誘`, `その他` |
| **推奨ランク** | **S (高推奨)**: 志向領域（AI/Cloud/Go/WFH等）に合致する具体的打診<br>**A (推奨)**: ITエンジニア・IT採用担当・専門エージェント等、有益なネットワーク<br>**B (ニュートラル)**: 一般的な同業・ネットワーク拡大<br>**C (低優先/注意)**: 営業勧誘・SES懸念・条件不一致 |
| **評価対象** | 申請者の肩書き（Headline）、会社名、添付メッセージ、プロフィール詳細（現職・自己紹介・スキル）、共通コネクション |

### 4.10 メッセージ評価・仕分け支援: `evaluate_messages.py`

LinkedIn「Other」等のメッセージ群を整理する際、キーワードに基づく属性分類や初期参考スコアを出力します。

```powershell
# 特定ブロック（例: Block 1）の事前フィルタ結果を表示
uv run python scripts/linkedin/evaluate_messages.py --block 1

# 全ブロックの参考集計を出力
uv run python scripts/linkedin/evaluate_messages.py --all
```

#### 【重要】メッセージ・スカウト評価運用の絶対原則

1. **機械的フィルタは参考情報に留め、総合判断を徹底する**:
   - スクリプトによる自動スコアリングやキーワード抽出は、初期の粗削りな「事前フィルタ」に過ぎません。
   - スコアのみで最終決定（返信・保存・削除/アーカイブ）を下すことは厳禁です。必ずユーザーのプロファイル（`vault/profile/preferences.md`, `criteria.md` 等）と照らし合わせ、送信者・企業・職種・文脈を総合的に吟味して判断してください。
2. **調査スキップ時の理由明記義務**:
   - 事前フィルタ（古い日付、明らかな営業アンケート等）を理由に、それ以上の詳細調査（スレッド本文開封や企業・リクルーター調査）を行わない場合は、**「〜を理由に詳細調査はスキップ」と必ずその旨と理由を明記・記録**してください。
3. **数十件規模での思考停止・完全機械化の禁止**:
   - 30〜40件程度の人間が目を通せる規模のメッセージに対して、安易な完全自動化や機械的スコアへの依存で楽をしようとしてはなりません。1件1件の価値を丁寧に評価してください。

---

## 5. 実践シナリオ別ワークフロー

### シナリオ A: 受信したつながり申請（招待）のチェックと価値検討

```powershell
# 1. 受信招待を取得し、プロファイル照合結果・推奨判断を確認
uv run python scripts/linkedin/fetch_invitations.py --summary

# 2. 評価結果（data/linkedin/invitations/latest.md）を確認
#    - Sランク / Aランクの申請者を優先してブラウザから手動承認またはメッセージ返信
#    - Cランク（営業・商材勧誘）は手動でスキップまたは保留
```

### シナリオ B: 英語版プロフィール（`vault/profile/en/`）の同期とLinkedInへの反映

```powershell
# 1. 日本語SSOTと英語版プロフィールの鮮度を確認
uv run python scripts/profile/sync_en.py --summary

# 2. 最新のLinkedInプロフィールをバックアップ取得
uv run python scripts/linkedin/fetch_profile.py

# 3. vault/profile/en/ の記述に合わせて Headline / About を更新
uv run python scripts/linkedin/manage_profile.py --headline "Senior Software Engineer" --about "..."
```

---

## 6. データ格納仕様

```text
data/linkedin/
  ├── jobs/
  │   └── {job_id}.md        # 求人詳細Markdown（job-data-format準拠）
  ├── searches/
  │   ├── YYYY-MM-DD-HHMMSS_{query}.md   # 検索結果一覧
  │   └── YYYY-MM-DD-HHMMSS_{query}.json # 検索結果JSON
  ├── profile/
  │   ├── latest.md          # 最新プロフィールMarkdown
  │   ├── latest.json        # 最新プロフィールJSON
  │   └── backups/           # 更新前の自動バックアップJSON
  ├── experience/
  │   ├── latest.json        # 最新職歴JSON
  │   └── backups/           # 更新前の自動バックアップJSON
  ├── messages/
  │   ├── messages_{filter}.md / .json       # 最新（フィルタ別、例: messages_all.md）
  │   └── history/messages_{filter}_YYYYMMDD_HHMMSS.md / .json  # タイムスタンプ履歴
  └── invitations/
      ├── latest.md          # 最新受信招待・価値評価Markdown
      ├── latest.json        # 最新受信招待・価値評価JSON
      ├── {YYYYMMDD_HHMMSS}.json # タイムスタンプ別スナップショット
      └── history/
          ├── invitations_{YYYYMMDD_HHMMSS}.md
          └── invitations_{YYYYMMDD_HHMMSS}.json
```
