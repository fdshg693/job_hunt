# vault/recruiters/{recruiter-key}/index.md テンプレート

```markdown
---
# キー・型・許容値の正は scripts/vault/schema/（一覧は docs/vault/schema.md）
name: "山田 太郎"
recruiter_key: "bizreach_yamada-taro"
agency: "株式会社〇〇エージェンシー"
platform: "bizreach"
platform_user_id: "https://www.bizreach.jp/..."
status: "active" # active | trusted | declined | blacklisted
tracks:
  - "domestic"
rating: "B" # S | A | B | C | D
matching_accuracy: "medium" # high | medium | low | spam
communication_quality: "丁寧・迅速"
dealbreaker_adherence: true
tags:
  - "Go"
  - "バックエンド"
  - "フルリモート強み"
  - "メガベンチャー"
introduced_companies:
  # 企業ログがある場合: company_key で企業ログと結合する（status / fit_score は企業ログ側を見るので書かない）
  - company: "株式会社〇〇"
    company_key: "example-corp"
    date: "2026-10-13"
  # 企業ログが無い場合: 想定年収・所感などを note に残す
  - company: "△△業界の企業（社名非公開）"
    job_title: "AI Engineer"
    date: "2026-10-13"
    note: "想定年収800〜1,200万円。雇用形態・出社頻度は要確認"
date: "2026-10-13"
updated_at: "2026-10-13"
links:
  - category: "corporate"
    title: "エージェント企業サイト"
    url: "https://agent-example.com"
  - category: "sns"
    title: "担当者 LinkedIn"
    url: "https://www.linkedin.com/in/example-recruiter"
    summary: "エンジニア採用担当歴5年、クラウド・SaaS領域特化"
---

# 山田 太郎（株式会社〇〇エージェンシー）評価ログ

## 1. 基本情報・接点経緯

- **氏名**: 山田 太郎
- **所属エージェント / 企業**: 株式会社〇〇エージェンシー
- **接触プラットフォーム**: ビズリーチ（プラチナスカウト）
- **初コンタクト日**: 2026-10-13
- **初回メッセージ・スカウト文の特徴**:
  - （例: 職務経歴書のGoやクラウド基盤経験を読んだ上で、ピンポイントに刺さる求人を打診してきた。テンプレート一括送信ではない印象）

---

## 2. 評価サマリ・見極め分析

### 総合評価: B（検証中）

- **マッチング精度**: 
  - 希望条件（年収800万〜、フルリモート、モダンスタック）を概ね把握している。
  - Dealbreakers（出社強制、SES・受託、深夜残業）を回避した提案ができているか検証中。
- **提案案件の質**:
  - 提案された求人票のレベル感、自社プロダクト比率、成長フェーズ。
- **コミュニケーション・スタンス**:
  - レスポンス速度、こちらの希望に対する傾聴度、応募を急かす強引さがないか。

---

## 3. 紹介・提案求人一覧

| 日付 | 企業名 | 職種 | fit_score | ステータス | ログリンク | メモ・評価 |
|---|---|---|---|---|---|---|
| 2026-10-13 | 株式会社〇〇 | バックエンドエンジニア | 65〜85/100 | considering | [企業ログ](../../tracks/domestic/companies/example-corp/index.md) | 技術スタック合致、リモート可 |

---

## 4. やり取り履歴・面談ログ

### 2026-10-13: 初回スカウト受信・求人打診
- **内容**: 〇〇社の求人提案を受信。
- **所感**: 文面が丁寧で、希望条件に沿った提案。

---

## 5. 今後の対応方針・ネクストアクション

- **方針**: 提案求人の精査を進め、適合度が高ければカジュアル面談調整を依頼。
- **注意点**: 複数求人を並行提案された場合は、足切り条件への抵触がないか必ず一件ずつ精査する。
```
