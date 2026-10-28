<!-- 自動生成ファイル: .agents/rules/user-profile.md から scripts/dev/sync_agents.py で生成。直接編集せず .agents/rules/user-profile.md を編集して再同期すること -->

> **適用条件**: ユーザーの経歴、職務経歴書、希望条件、転職ステータス、スキル情報の参照・更新、または求人との適合度を評価する際に適用

# ユーザープロフィール・経歴 SSOT ガイドライン

ユーザー自身の経歴・希望条件・転職状況に関する情報は、[`vault/profile/`](../../vault/profile/)（人の共通情報）と [`vault/tracks/{track}/`](../../vault/tracks/)（転職活動 track 固有の条件・選考状況）を唯一の正本（SSOT）として扱います。track の定義は [tracks.md](tracks.md) を参照。

## SSOTファイル構成

### 人の共通情報（track 非依存）: `vault/profile/`

- [`vault/profile/resume.md`](../../vault/profile/resume.md): 職務経歴書マスター（職歴、学歴、担当プロジェクト、資格、語学、フロントマター `links` の外部公開リンク）
- [`vault/profile/rirekisho.md`](../../vault/profile/rirekisho.md): 履歴書の汎用項目（ふりがな・住所・学歴/職歴・免許資格・本人希望の既定文）。氏名・生年月日・連絡先は `resume.md` から読む
- [`vault/profile/skills.md`](../../vault/profile/skills.md): スキルスタック詳細・強み・自己PR・実績エピソード素材集
- [`vault/profile/preferences.md`](../../vault/profile/preferences.md): 共通の志向軸（職種・技術志向・ドメイン観・track 共通の業務内容/カルチャーNG）
- [`vault/profile/accounts.md`](../../vault/profile/accounts.md): 求人媒体の登録・連携状況（`accounts_sync_status`）
- [`vault/profile/sites/`](../../vault/profile/sites/): 媒体別プロフィール完成文（スクリプトは読むだけで、外部送信用完成文の正本はここ）
- [`vault/profile/tech/`](../../vault/profile/tech/): 技術詳細ノート（一次情報）。`projects/{key}.md` にプロジェクトの細部・現在地、`areas/{key}.md` に技術領域ごとの理解度（[tech-notes.md](tech-notes.md)）
- [`vault/profile/employers/`](../../vault/profile/employers/): 前職・現職の企業ログ（`status: employer`。`check_company.py` で全 track 除外）
- [`vault/profile/internal/notes.md`](../../vault/profile/internal/notes.md): **非公開**。track に依存しない転職理由・キャリア観の本音メモ
- [`vault/profile/en/`](../../vault/profile/en/): 派生英語版プロフィール（後述）

### track 固有情報: `vault/tracks/{track}/`（国内: [`vault/tracks/domestic/`](../../vault/tracks/domestic/)）

- `strategy.md`: track 固有の希望条件（年収 `current/target_annual_income_*`、出社・勤務地 `work_style`、雇用形態、企業フェーズ `company_stage`、英語環境の位置づけ、track 固有NG `disqualifiers`）
- `criteria.md`: **非公開**。track の本音の足切り・必須条件（Dealbreakers）
- `ratings.md`: **非公開**。企業格付け・ベンチマーク・ブラックリスト
- `pipeline.md`: 選考状況ダッシュボード（フェーズ、目標時期、次回アクション、選考企業一覧）

### 共通 / track 固有の振り分け方針

| 情報 | 置き場所 |
|---|---|
| 職種・技術志向・ドメイン観・track 共通の業務内容/カルチャーNG | `vault/profile/preferences.md` |
| 技術の一次情報（プロジェクト詳細・現在地・領域ごとの理解度） | `vault/profile/tech/`（要約は `resume.md` / `skills.md`） |
| 年収・出社/勤務地・雇用形態・企業フェーズ・英語環境の位置づけ・track 固有NG | `vault/tracks/{track}/strategy.md` |
| track の足切りルール（数値・出社条件・カルチャー/業務内容のNG） | `vault/tracks/{track}/criteria.md` |
| 足切りの背景にある本音・キャリア観 | `vault/profile/internal/notes.md` |
| 媒体登録・連携状況 | `vault/profile/accounts.md` |
| 選考状況・次回アクション | `vault/tracks/{track}/pipeline.md` |

- **迷う記述は track 側に置く**。共通部に誤って入れると、別 track の判断を国内条件で縛ることになるため。後から共通化する方が安全。

## 非公開情報（`visibility: "internal"`）

- 対象: `vault/profile/internal/` 配下、および各 track の `criteria.md`・`ratings.md`。これらのファイルにはフロントマター `visibility: "internal"` を付ける。
- ユーザーの本音・足切り基準であり、外部求人媒体へのプロフィール更新スクリプトや応募書類・メッセージ返信・面接用文章の生成時には**絶対に露出・引用してはなりません**。
- 求人の自動スクリーニング・足切り判定、優先度スコアリング、およびユーザーとの対話・意思決定支援時のみ参照します。
- `strategy.md` は外部提出用文章の素材にしてよい（ただし表現は応募先に合わせて調整する）。

## 派生英語版プロフィール (`vault/profile/en/`) 構成

英語媒体（LinkedIn等）向けの連携・同期データとして、[`vault/profile/en/`](../../vault/profile/en/) に派生英語版プロフィールを配置します。

- [`vault/profile/en/resume.md`](../../vault/profile/en/resume.md): 英語版職務経歴書マスター
- [`vault/profile/en/skills.md`](../../vault/profile/en/skills.md): 英語版保有スキル・強み・STAR実績集
- [`vault/profile/en/preferences.md`](../../vault/profile/en/preferences.md): 英語版の共通志向軸（track 固有の年収・出社条件は含めない）

### 英語版同期・メタデータ規約
1. **SSOTからの派生関係**:
   - `vault/profile/`（日本語）が唯一の正本（SSOT）であり、`vault/profile/en/` はそこから派生・英訳されたデータです。
2. **フロントマター必須メタデータ**:
   - `source_file`: 同期元日本語ファイルパス（例: `vault/profile/resume.md`）
   - `source_updated_at`: 同期元ファイルの更新日（YYYY-MM-DD）
   - `synced_at`: 翻訳・同期を実行した日付（YYYY-MM-DD）
   - `language`: `en`
3. **同期検証と更新管理**:
   - `source_updated_at` が同期元の `updated_at` より古い場合は差分未同期（STALE）と判定されます。
   - 同期状態の確認・管理は CLI ツール [`scripts/profile/sync_en.py`](../../scripts/profile/sync_en.py)（`-s`, `--strict`, `update-meta`）を使用します。
4. **外部英語媒体への連携**:
   - LinkedInなど英語表記を前提とする求人媒体・スカウトプラットフォームへのプロフィール反映・更新を行う際は、`vault/profile/en/` の記述を正本として参照します。
5. **非公開情報の完全除外**:
   - `visibility: "internal"` のファイルは翻訳・同期対象外（外部露出厳禁）です。

## 参照・更新の原則

1. **SSOTの厳守**:
   - `data/` 配下（例: `data/bizreach/resume/` や `data/findy/profile/`）は外部媒体から取得したスナップショット（キャッシュ）に過ぎません。
   - ユーザーの経歴や志向を評価・参照する際は、常に `vault/profile/` と該当 track のファイルを優先してください。
2. **外部サイト更新スクリプトとの連携**:
   - 各求人サービスへの反映（例: `scripts/findy/manage_work_history.py`, `scripts/bizreach/manage_resume.py` 等）を行う際は、`vault/profile/resume.md` の記述をソースデータとして利用します。希望条件の同期（例: `scripts/levtech_direct/manage_profile_condition.py`）は該当 track の `strategy.md` を読みます。
   - 英語プロフィール媒体（LinkedIn等）の更新時は、`vault/profile/en/` の記述をソースデータとして利用します。
   - 職務経歴書・英文レジュメの PDF は [`scripts/profile/export_pdf.py`](../../scripts/profile/export_pdf.py) で `resume.md` から生成します（手作業で PDF 用の別原稿を作らない。仕様は [`docs/profile/README.md`](../../docs/profile/README.md)）。連絡先を PDF に載せるのは `--contact` 指定時のみで、その値は `resume.md` のフロントマター `email` / `phone` に置きます。
   - 履歴書の PDF は [`scripts/profile/export_rirekisho.py`](../../scripts/profile/export_rirekisho.py) で `rirekisho.md` から生成します。志望動機など応募先ごとの記入事項は企業フォルダの `application.md`（`## 志望動機` / `## 本人希望記入欄`）に書き、`--company` で差し込みます。
   - パスはスクリプトにハードコードせず `scripts/common/paths.py` の定数・ヘルパーを使います。
3. **データ更新時のルール**:
   - 情報を追記・修正した際は、フロントマター内の `updated_at` を当日の日付（YYYY-MM-DD）に更新してください。
   - 選考状況の全体サマリは track の `pipeline.md` に集約してください（選考企業一覧は `scripts/vault/build_pipeline.py` で生成）。各企業の最新状況サマリは企業フォルダの `index.md`、面談ごとの詳細メモ・一次情報は同フォルダの面談ログで管理します（三層管理、[interview-log.md](interview-log.md)）。
4. **相談対話および面談後を通じた能動的アップデート**:
   - ユーザーから個別の企業や求人について相談を受けた際（スキル `consult-company-job`、ルール [company-log.md](company-log.md) 参照）や、カジュアル面談・面接を終えた際（ルール [interview-log.md](interview-log.md) 参照）は、単に確認するだけでなく、求人要件や面談でのリアルな気づきをきっかけに積極的に追加質問を行い、新たな志向・実績・NG条件を上記の振り分け方針に従って能動的に追記してください。
