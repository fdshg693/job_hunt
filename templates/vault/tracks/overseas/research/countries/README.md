# 国別調査 (research/countries/)

対象国ごとに 1 ファイル `{iso2}.md`（ISO 3166-1 alpha-2 の小文字。例: `ca.md`, `au.md`, `se.md`）を作り、海外就業の判断材料をまとめる。候補国は [`../../strategy.md`](../../strategy.md) の `target_regions`。

- 調査は対象国の候補が固まってから着手する（骨格段階では個別ファイルを作らない）。
- ビザ・税などの制度情報は変わりやすいため、**一次情報（政府・公的機関サイト）の URL と確認日**を必ず残す。

## ファイル書式

```markdown
---
country: "カナダ"
iso2: "ca"
updated_at: "YYYY-MM-DD"
priority: "high"          # high | medium | low | excluded
answers: ["Q-01"]         # questions.md の問い ID
visa_routes:              # 自分が使えそうな経路
  - name: "ワーキングホリデー（IEC）"
    age_limit: "18〜30歳（要確認）"
    sponsor_required: false
    notes: ""
english_sufficient: true  # 英語のみで就業・生活が成り立つか
sources:
  - url: "https://..."
    checked_at: "YYYY-MM-DD"
---

# {国名} 調査メモ

## 1. ビザ・在留資格
- 経路ごとの要件（年齢・学歴・職歴・語学スコア・資金）、期間、家族帯同、永住への接続

## 2. 税・社会保障
- 所得税・社会保障の概算、日本との租税条約・社会保障協定、日本在住リモート時の扱い

## 3. 生活費
- 主要都市の家賃・生活費の目安、「普通に暮らせる」年収水準の目安

## 4. エンジニア市場
- 需要（職種・技術スタック）、給与相場（現地通貨・円換算）、主要な求人媒体、外国人採用の傾向

## 5. 所感・判定
- strategy.md / criteria.md との照合結果、優先度の理由、未検証事項
```
