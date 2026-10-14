---
trigger: model_decision
description: エージェント担当者・ヘッドハンター・リクルーターについて相談を受け調査・回答する際、または recruiters/ 配下のリクルーター評価ログを作成・参照・更新する際に適用
---

# リクルーター・ヘッドハンター評価ログ (`recruiters/`) 運用ルール

転職活動におけるエージェント担当者、ヘッドハンター、企業リクルーター（採用担当者）からの求人紹介・スカウトについて相談・回答する際、および人単位での評価・見極めを行う際は、プロジェクトルートの [`recruiters/`](../../recruiters/) ディレクトリ配下に担当者別ログを作成・蓄積します。

## 目的と位置づけ

- **人単位（エージェント／ヘッドハンター）での評価の蓄積**:
  - 求人や企業そのもののスペック（`chat/`）とは独立して、「誰がどの媒体でどんな提案をしてきたか」「ユーザーの希望や本音の足切り条件を理解しているか」「強引さや定型文スパムではないか」を客観的に評価する。
- **紹介案件の品質・マッチング精度の追跡**:
  - 同一のリクルーターから複数の求人が紹介された場合に、紹介案件一覧（`chat/` へのリンク）を一元管理し、リクルーターのマッチング精度・目利き力を定量・定性的に把握する。
- **悪質・地雷エージェントの重複対応防止**:
  - 希望条件無視やSES/常駐案件・ブラック企業の押し付けを行う担当者を `blacklisted/` や `declined/` に記録し、無駄な面談や連絡の消耗を防ぐ。
- **関連スキル**: [`consult-company-job`](../skills/consult-company-job/SKILL.md)
- **関連ルール**: [求人相談・調査ログルール](chat-log.md), [面談詳細ログルール](interview-log.md), [ユーザープロフィールルール](user-profile.md)

## 状態別サブフォルダ構成（必須）

`recruiters/` 直下には [`README.md`](../../recruiters/README.md) と [`TEMPLATE.md`](../../recruiters/TEMPLATE.md) のみを置き、個別担当者ログは状態に応じて以下のサブフォルダに格納する。

| フォルダ | 意味 | 配置基準 |
|---|---|---|
| `recruiters/active/` | やり取り中・検討中 | 現在メッセージやり取り中、求人紹介を受けている、または面談調整中のリクルーター |
| `recruiters/trusted/` | 信頼できるパートナー（高評価） | ユーザーの志向・Dealbreakerを深く理解し、高品質・高マッチ度な案件を継続提案してくれる優秀なリクルーター（評価 S/A） |
| `recruiters/declined/` | 見送り・連絡終了 | 提案内容が合わなかった、やり取りを終了した、またはユーザー主導で連絡をフェードアウト・辞退したリクルーター |
| `recruiters/blacklisted/` | 要注意・NG・ブラックリスト | 希望条件（年収・リモート等）の完全無視、定型文コピペの乱れ撃ち、強引な応募催促など、二度と関わりたくない悪質リクルーター（評価 D） |

- **新規作成は `recruiters/active/` が既定**。初回からあからさまな定型文スパムやDealbreaker無視と判明した場合は直接 `blacklisted/` に配置可能。
- **移動ルール**: やり取りの進展や評価の変化に応じて、`git mv recruiters/active/{key}.md recruiters/{trusted|declined|blacklisted}/` で移動し、フロントマターの `status` / `rating` / `updated_at` を更新する。
- **検索**: 既存のリクルーターログ存在確認は `recruiters/*/{key}.md`（全サブフォルダ横断）で行う。

## ファイル命名規則

- **パス形式**: `recruiters/{status}/{agency-or-platform}_{recruiter-name}.md`
- **命名規則**:
  - 半角英数字小文字ハイフン/アンダースコア区切り（例: `bizreach_yamada-taro.md`, `recruit_suzuki-ichiro.md`, `jac_john-smith.md`, `direct_mercari_tanaka-hanako.md`）。
  - 所属エージェント組織またはプラットフォーム名をプレフィックスとし、アンダースコア（`_`）で担当者名をつなぐ。
  - 氏名が不明・イニシャル表記のみの場合はプラットフォーム＋公開IDや識別子（例: `bizreach_hh-12345.md`, `linkedin_recruiter-abc.md`）。

## フロントマター仕様

```yaml
---
name: "担当者 氏名"
recruiter_key: "agency_recruiter-name"
agency: "株式会社〇〇エージェンシー" # 所属企業/エージェント名
platform: "bizreach" # bizreach | linkedin | findy | levtech_direct | forkwell | direct | email | other
platform_user_id: "https://..." # プラットフォーム上のプロフィールURLやID
status: "active" # active | trusted | declined | blacklisted
rating: "B" # S (最優良・パートナー) | A (優良) | B (通常・検証中) | C (微妙・ズレあり) | D (悪質・NG)
matching_accuracy: "medium" # high | medium | low | spam (希望条件・志向への理解度)
communication_quality: "丁寧・迅速" # 丁寧・迅速 | 事務的 | 遅い | 強引・定型文
dealbreaker_adherence: true # 足切り条件（年収下限・リモート等）を尊重しているか
tags:
  - "Go"
  - "メガベンチャー"
  - "フルリモート強み"
introduced_companies:
  - company: "株式会社グラファー"
    company_key: "graffer"
    chat_log: "chat/active/graffer.md"
    fit_score: "70〜85/100"
    status: "considering"
    date: "YYYY-MM-DD"
date: "YYYY-MM-DD" # 初回接触日
updated_at: "YYYY-MM-DD" # 最終更新日
interview_dir: "interviews/recruiters/agency_recruiter-name/" # 事前面談ログがある場合
---
```

## 本文セクション構成

1. `# {name}（{agency}）評価ログ`
2. `## 1. 基本情報・接点経緯`: 接触媒体、スカウト種別（プラチナ/通常）、初回メッセージの文面分析（個別カスタマイズか定型コピペか）
3. `## 2. 評価サマリ・見極め分析`:
   - マッチング精度（希望条件・Dealbreakerの理解度）
   - 提案案件の質（地雷案件・SES・レガシー負債の有無、独自案件の有無）
   - コミュニケーション品質（レスポンス、強引さの有無、パートナーシップ志向かノルマ志向か）
4. `## 3. 紹介・提案求人一覧`: 紹介企業テーブル（日付、企業名、fit_score、ステータス、`chat/` リンク、所感）
5. `## 4. やり取り履歴・面談ログ`: 日付ごとのメッセージ要約、事前面談メモ
6. `## 5. 今後の対応方針・ネクストアクション`: 返信方針、付き合いの継続有無、注意点

## 企業ログ (`chat/`) との双方向連携

リクルーター経由で求人相談が行われた場合、**企業ログとリクルーターログの双方向リンク**を必ず形成する。

1. **企業ログ (`chat/{folder}/{company-name}.md`) 側の記述**:
   - フロントマターに以下を追加:
     ```yaml
     recruiter: "agency_recruiter-name"
     recruiter_link: "recruiters/active/agency_recruiter-name.md"
     ```
   - 本文の「1. 相談・リクエスト内容」に紹介元リクルーターを明記。
2. **リクルーターログ (`recruiters/{folder}/{recruiter-key}.md`) 側の記述**:
   - `introduced_companies` リストに対象企業と `chat_log` パスを追加。
   - 紹介案件の適合度を踏まえ、リクルーター自身の `matching_accuracy` や `rating` を更新。
