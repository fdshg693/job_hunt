<!-- 自動生成ファイル: .agents/rules/interview-log.md から scripts/dev/sync_agents.py で生成。直接編集せず .agents/rules/interview-log.md を編集して再同期すること -->

> **適用条件**: カジュアル面談や各次面接・リクルーター面談の詳細メモ・議事録・感想を記録・参照する際、または vault/tracks/*/companies/*/ や vault/recruiters/*/ 配下の面談ログを操作・連携する際に適用

# 面談・選考詳細ログ運用ルール

カジュアル面談、技術面談、各次面接、オファー面談などの詳細なメモ、質疑応答の生ログ、一次情報、および主観的な感想・カルチャーフィットの所感は、企業ログ `index.md` と同じ企業フォルダ [`vault/tracks/{track}/companies/{company-key}/`](../../vault/tracks/) に面談1回1ファイルで記録・蓄積します。

## 三層構造と役割分担

選考・企業情報は以下の三層構造で疎結合かつ検索性高く管理します。

1. **全体サマリ（ダッシュボード）: `vault/tracks/{track}/pipeline.md`**（国内: [`vault/tracks/domestic/pipeline.md`](../../vault/tracks/domestic/pipeline.md)）
   - track 内の選考フェーズ、次回予定、優先度を俯瞰する。
   - 選考企業一覧はマーカー間を `scripts/vault/build_pipeline.py` が企業ログのフロントマターから自動生成する。手書きするのはマーカー外の活動フェーズ・次回アクションのみ（[tracks.md](tracks.md)）。
2. **企業メインファイル（要約・最新状況）: `vault/tracks/{track}/companies/{company-key}/index.md`**
   - 企業の求人調査、条件、適合度、最新の選考ステータス、および面談結果のサマリを簡潔に集約する（[company-log.md](company-log.md)）。
3. **面談・選考詳細ログ（一次情報・生メモ）: `vault/tracks/{track}/companies/{company-key}/{YYYY-MM-DD}_{stage}.md`**
   - 各回の面談・面接における質疑応答の詳細メモ、面談相手の印象、現場のリアルな開発体制、主観的感想、一次情報を独立ファイルとして蓄積する。

---

## ディレクトリとファイル命名規則

- **ファイルパス**: `vault/tracks/{track}/companies/{company-key}/{YYYY-MM-DD}_{stage}.md`
  - 企業フォルダは企業ログと共有する。面談ログのために別フォルダは作らない。
  - 例:
    - `vault/tracks/domestic/companies/on-call/2026-10-15_casual.md` （カジュアル面談）
    - `vault/tracks/domestic/companies/on-call/2026-10-22_1st-interview.md` （1次面接）
    - `vault/tracks/domestic/companies/on-call/2026-11-05_final.md` （最終面接）
    - `vault/tracks/domestic/companies/on-call/2026-11-12_offer.md` （オファー面談・条件提示）
- **標準ステージ識別子 (`stage`)**:
  - `casual`: カジュアル面談
  - `1st-interview`: 1次面接（技術面接など）
  - `2nd-interview`: 2次面接
  - `final`: 最終面接・役員面接
  - `offer`: オファー面談・条件面談
  - `retro`: 振り返り・選考辞退/見送りメモ
  - `career-consultation`: エージェント・ヘッドハンターとのキャリア相談・事前面談
  - `job-introduction`: エージェント・ヘッドハンターとの求人紹介・打合せ

- **リクルーター・エージェントとの面談ログ**:
  - ヘッドハンターやエージェント担当者との事前面談・求人紹介面談の詳細ログは、リクルーターフォルダ `vault/recruiters/{recruiter-key}/{YYYY-MM-DD}_{stage}.md` に配置する（例: `vault/recruiters/bizreach_yamada-taro/2026-10-15_career-consultation.md`）。
  - 同フォルダの `index.md`（リクルーターログ、[recruiter-log.md](recruiter-log.md)）に要点とリンクを反映する。

---

## フロントマター仕様

- キー・型・許容値の正は [`scripts/vault/schema/`](../../scripts/vault/schema/)。一覧は生成物 [`docs/vault/schema.md`](../../docs/vault/schema.md) の `InterviewDoc` を見る（このルールにフィールド表は書かない）。
- テンプレートは [`templates/interview/casual.md`](../../templates/interview/casual.md)（本選考は [`templates/interview/interview.md`](../../templates/interview/interview.md)、エージェント面談は [`templates/interview/recruiter.md`](../../templates/interview/recruiter.md)）。作成・更新したら `uv run python scripts/vault/validate.py` を実行してエラー0にする。
- `date` / `stage` はファイル名（`{YYYY-MM-DD}_{stage}.md`）と、`company_key` / `track` は配置フォルダと一致させる（不一致は検証エラー）。企業ログへのパスは書かない（同じフォルダにあるため）。
- `stage_name` は標準ラベルから表示名を変えたい場合だけ書く。
- `result` はその回の結果。面談後に `pending` のまま放置せず、結果が出たら更新する（合否の無い面談は `not_applicable`）。

---

## 本文セクション標準構成

見出し構成は stage 別のテンプレート（[`templates/interview/`](../../templates/interview/)）に従う。どのテンプレートでも次の内容を押さえる。

- **基本情報**: 実施日時、形式（Google Meet等）、面談相手の役職、面談の目的・ポジション
- **事前準備（聞くこと・話すこと）**:
  - 同フォルダの `index.md`、`vault/profile/`、track の `strategy.md` / `criteria.md` から抽出した確認事項・Dealbreaker。論点ごとに「背景」と「角を立てずに実態を引き出す質問の投げ方」を書く
  - 本選考では、相手企業の課題・ニーズとユーザーの実績・強みの対応（表形式）と、刺さる訴求エピソード
- **面談メモ・質疑応答（一次情報）**: 企業・事業・開発体制の説明要点、こちらからの質問と回答、相手からの質問・逆質問への回答
- **所感（主観メモ）**: ポジティブな魅力・印象、懸念点・違和感・リスク、総合的な手応え・現時点の志望度
- **次回アクション・選考結果**: 次回ステップ・日程、`index.md` と `pipeline.md` への反映確認

---

## 運用フローと三層同期の原則

面談の実施前後は以下のフローで情報を同期・集約する。

1. **面談前（準備）**:
   - 企業フォルダの `index.md` の調査内容・適合分析を再確認し、面談で確認すべき疑問点を抽出。
   - 同フォルダに `{date}_{stage}.md` を作成し、事前確認論点を整理する。
2. **面談後（一次情報の記録）**:
   - 面談内容のメモ、質疑応答、リアルな感想を `{date}_{stage}.md` に記録する。
3. **`index.md` へのサマリ反映（メインファイル更新）**:
   - 面談全体の要点・確認結果（例: 出社頻度の実態、技術スタック詳細）を `index.md` の「5. 選考・面談サマリ」に要約し、面談ログへの相対リンク（例: `[カジュアル面談 (2026-10-15)](2026-10-15_casual.md)`）を記載する。
   - フロントマターの `status` / `status_note` / `updated_at` を更新する。
4. **`pipeline.md` の更新（全体俯瞰）**:
   - `uv run python scripts/vault/build_pipeline.py --track {track}` で選考企業一覧を再生成し、マーカー外の次回アクションを手で更新する。
5. **プロフィールへのフィードバック（能動的更新）**:
   - 面談を通じて新たに判明した志向・自己PRの感触は `vault/profile/`（`preferences.md`, `skills.md`, `internal/notes.md`）へ、track 固有の条件（出社許容度・年収感・足切り）は track の `strategy.md` / `criteria.md` へ反映する（振り分けは [user-profile.md](user-profile.md)）。
