---
trigger: model_decision
description: ユーザーの経歴、職務経歴書、希望条件、転職ステータス、スキル情報の参照・更新、または求人との適合度を評価する際に適用
---

# ユーザープロフィール・経歴 SSOT ガイドライン

ユーザー自身の経歴・希望条件・転職状況に関する情報は、プロジェクトルートの [`profile/`](../../profile/) ディレクトリを唯一の正本（SSOT）として扱います。

## SSOTファイル構成

- [`profile/resume.md`](../../profile/resume.md): 職務経歴書マスター（職歴、学歴、担当プロジェクト、資格、語学）
- [`profile/preferences.md`](../../profile/preferences.md): 希望条件・転職の軸（希望年収、働き方、企業規模、技術志向、NG条件）
- [`profile/status.md`](../../profile/status.md): 現在の選考・転職活動状況（応募先、選考ステータス、次回アクション）
- [`profile/skills.md`](../../profile/skills.md): スキルスタック詳細・強み・自己PR・実績エピソード素材集
- [`profile/internal/`](../../profile/internal/): **非公開・内部判定用（外部露出厳禁）**
  - [`profile/internal/criteria.md`](../../profile/internal/criteria.md): 本音の足切り・必須条件（Dealbreakers）
  - [`profile/internal/companies.md`](../../profile/internal/companies.md): 企業格付け・ベンチマーク・ブラックリスト
  - [`profile/internal/notes.md`](../../profile/internal/notes.md): 転職理由・キャリアの本音メモ

## 派生英語版プロフィール (`profile_en/`) 構成

英語媒体（LinkedIn等）向けの連携・同期データとして、プロジェクトルートの [`profile_en/`](../../profile_en/) ディレクトリに派生英語版プロフィールを配置します。

- [`profile_en/resume.md`](../../profile_en/resume.md): 英語版職務経歴書マスター
- [`profile_en/skills.md`](../../profile_en/skills.md): 英語版保有スキル・強み・STAR実績集
- [`profile_en/preferences.md`](../../profile_en/preferences.md): 英語版希望条件・キャリア軸

### 英語版同期・メタデータ規約
1. **SSOTからの派生関係**:
   - `profile/`（日本語）が唯一の正本（SSOT）であり、`profile_en/` はそこから派生・英訳されたデータです。
2. **フロントマター必須メタデータ**:
   - `source_file`: 同期元日本語ファイルパス（例: `profile/resume.md`）
   - `source_updated_at`: 同期元ファイルの更新日（YYYY-MM-DD）
   - `synced_at`: 翻訳・同期を実行した日付（YYYY-MM-DD）
   - `language`: `en`
3. **同期検証と更新管理**:
   - `source_updated_at` が `profile/` 側の `updated_at` より古い場合は差分未同期（STALE）と判定されます。
   - 同期状態の確認・管理は CLI ツール [`scripts/profile/sync_en.py`](../../scripts/profile/sync_en.py)（`-s`, `--strict`, `update-meta`）を使用します。
4. **外部英語媒体への連携**:
   - LinkedInなど英語表記を前提とする求人媒体・スカウトプラットフォームへのプロフィール反映・更新を行う際は、`profile_en/` の記述を正本として参照します。
5. **非公開情報の完全除外**:
   - `profile/internal/` は機密・本音メモのため、`profile_en/` への翻訳・同期対象外（外部露出厳禁）です。

## 参照・更新の原則

1. **SSOTの厳守**:
   - `data/` 配下（例: `data/bizreach/resume/` や `data/findy/profile/`）は外部媒体から取得したスナップショット（キャッシュ）に過ぎません。
   - ユーザーの経歴や志向を評価・参照する際は、常に `profile/` 配下を優先してください。
2. **外部サイト更新スクリプトとの連携**:
   - 各求人サービスへの反映（例: `scripts/findy/manage_work_history.py`, `scripts/bizreach/manage_resume.py` 等）を行う際は、`profile/resume.md` の記述をソースデータとして利用します。
   - 英語プロフィール媒体（LinkedIn等）の更新時は、`profile_en/` の記述をソースデータとして利用します。
3. **内部専用情報（`profile/internal/`）の厳格な非公開制約**:
   - `profile/internal/` 配下の内容はユーザーの本音・足切り基準であり、外部求人媒体へのプロフィール更新スクリプトや応募書類・メッセージ返信・面接用文章の生成時には**絶対に露出・引用してはなりません**。
   - 求人の自動スクリーニング・足切り判定、優先度スコアリング、およびユーザーとの対話・意思決定支援時のみ参照します。
4. **データ更新時のルール**:
   - 情報を追記・修正した際は、Frontmatter 内の `updated_at` を当日の日付（YYYY-MM-DD）に更新してください。
   - 選考状況の全体サマリ（応募先一覧、現在のステータス、次回日程・薄いメモ）は必ず [`profile/status.md`](../../profile/status.md) に集約してください。各企業の最新状況サマリは [`chat/{company-name}.md`](../../chat/)、面談ごとの詳細メモ・一次情報は [`interviews/{company-name}/`](../../interviews/) で管理し、`status.md` からリンクします（三層管理アーキテクチャ）。
5. **相談対話（`chat/`）および面談後（`interviews/`）を通じた能動的アップデート**:
   - ユーザーから個別の企業や求人について相談を受けた際（スキル `consult-company-job`、ルール `.agents/rules/chat-log.md` 参照）や、カジュアル面談・面接を終えた際（ルール `.agents/rules/interview-log.md` 参照）は、単に確認するだけでなく、求人要件や面談でのリアルな気づきをきっかけに積極的に追加質問を行い、新たな志向・実績・NG条件を `profile/` へ能動的に追記してください。
