---
trigger: model_decision
description: カジュアル面談や各次面接の詳細メモ・議事録・感想を記録・参照する際、または interviews/ 配下のファイルを操作・連携する際に適用
---

# 面談・選考詳細ログ (`interviews/`) 運用ルール

カジュアル面談、技術面談、各次面接、オファー面談などの詳細なメモ、質疑応答の生ログ、一次情報、および主観的な感想・カルチャーフィットの所感は、プロジェクトルートの [`interviews/{company-name}/`](../../interviews/) 配下に会社別サブフォルダを切って記録・蓄積します。

## 三層構造と役割分担

選考・企業情報は以下の三層構造で疎結合かつ検索性高く管理します。

1. **全体サマリ（ダッシュボード）: [`profile/status.md`](../../profile/status.md)**
   - 全社の選考フェーズ、次回予定、優先度を俯瞰する。
   - ここは**薄い大雑把な一覧表**に留め、各社の詳細ログへのリンク（`chat/{company-name}.md`）を保持する。
2. **企業メインファイル（要約・最新状況）: [`chat/{company-name}.md`](../../chat/)**
   - 企業の求人調査、条件、適合度、最新の選考ステータス、および面談結果のサマリを簡潔に集約する。
3. **面談・選考詳細ログ（一次情報・生メモ）: [`interviews/{company-name}/`](../../interviews/)**
   - 各回の面談・面接における質疑応答の詳細メモ、面談相手の印象、現場のリアルな開発体制、主観的感想、一時情報を独立ファイルとして蓄積する。

---

## ディレクトリとファイル命名規則

- **ディレクトリパス**: `interviews/{company-name}/`
  - 企業キー（`company-name`）は kebab-case（英数字小文字ハイフン区切り）とし、[`chat/{company-name}.md`](../../chat/) と完全に一致させる。
- **ファイルパス**: `interviews/{company-name}/{YYYY-MM-DD}_{stage}.md`
  - 例:
    - `interviews/on-call/2026-10-15_casual.md` （カジュアル面談）
    - `interviews/on-call/2026-10-22_1st-interview.md` （1次面接）
    - `interviews/on-call/2026-11-05_final.md` （最終面接）
    - `interviews/on-call/2026-11-12_offer.md` （オファー面談・条件提示）
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
  - ヘッドハンターやエージェント担当者との事前面談・求人紹介面談の詳細ログは `interviews/recruiters/{recruiter-key}/{YYYY-MM-DD}_{stage}.md` に配置する（例: `interviews/recruiters/bizreach_yamada-taro/2026-10-15_career-consultation.md`）。
  - リクルーターログ（[`recruiters/{folder}/{recruiter-key}.md`](../../recruiters/)）と相互リンクする。

---

## フロントマター仕様

各面談ログファイルの先頭に以下のYAMLフロントマターを必ず付与する。

```yaml
---
company: "株式会社〇〇"
company_key: "company-name"
date: "YYYY-MM-DD"
stage: "casual" # casual | 1st-interview | 2nd-interview | final | offer | other
stage_name: "カジュアル面談"
interviewer: "EM ○○氏、Tech Lead △△氏"
result: "pending" # passed | rejected | declined | pending | not_applicable
tags:
  - "カジュアル面談"
  - "開発体制"
  - "出社頻度確認"
chat_log: "chat/company-name.md"
---
```

---

## 本文セクション標準構成

詳細は [テンプレート](../../interviews/TEMPLATE.md) に準拠する。

1. `# {company} {stage_name}詳細メモ ({date})`
2. `## 1. 面談基本情報`: 実施日時、形式（Google Meet等）、面談相手の役職、面談の目的・ポジション
3. `## 2. 事前準備・確認したかった論点（聞くべきこと）`:
   - `chat/{company}.md` や `profile/` から抽出した確認事項・Dealbreaker
   - 各論点ごとに「背景」と「角を立てずに実態を引き出す質問の投げ方」を具体的に記載
4. `## 3. アピールポイント・訴求ストーリー（話すべきこと）`:
   - 相手企業の課題・ニーズとユーザーの実績・強みのマッピング（ASCII図または表形式）
   - 面談で刺さる具体的な訴求エピソード・技術実績
5. `## 4. 面談メモ・質疑応答（一次情報）`:
   - 企業・事業・開発体制の説明要点
   - こちらからの質問と回答
   - 相手からの質問・逆質問への回答
6. `## 5. 所感・カルチャーマッチ・感想（主観メモ）`:
   - ポジティブな魅力・印象
   - 懸念点・違和感・リスク
   - 総合的な手応え・現時点の志望度
7. `## 6. 次回アクション・選考結果`:
   - 次回ステップ、次回日程
   - `chat/{company}.md` および `profile/status.md` への反映確認

---

## 運用フローと三層同期の原則

面談の実施前後は以下のフローで情報を同期・集約する。

1. **面談前（準備）**:
   - `chat/{company-name}.md` の調査内容・適合分析を再確認し、面談で確認すべき疑問点を抽出。
   - `interviews/{company-name}/{date}_{stage}.md` を作成し、事前確認論点を整理する。
2. **面談後（一次情報の記録）**:
   - 面談内容のメモ、質疑応答、リアルな感想を `interviews/{company-name}/{date}_{stage}.md` に記録する。
3. **`chat/{company-name}.md` へのサマリ反映（メインファイル更新）**:
   - 面談全体の要点・確認結果（例: 出社頻度の実態、技術スタック詳細）を `chat/{company-name}.md` の選考進捗セクションに要約し、`interviews/...` へのリンクを記載する。
   - Frontmatter の `status` や `updated_at` を更新する。
4. **`profile/status.md` の更新（全体俯瞰）**:
   - 選考企業一覧テーブルのステータス（次回予定、薄いメモ）を最新化する。
5. **`profile/` へのフィードバック（能動的更新）**:
   - 面談を通じて新たに判明した自身の希望条件（出社許容度や組織カルチャーの好み）や自己PRの感触を、`profile/preferences.md`, `profile/skills.md`, `profile/internal/` に反映する。
