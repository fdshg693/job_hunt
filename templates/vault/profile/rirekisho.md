---
title: "履歴書マスター（汎用 / SSOT）"
updated_at: "2026-10-27"
# 氏名・生年月日・メール・電話は resume.md のフロントマターから読む（ここには書かない）
name_kana: "やまだ たろう"
gender: ""  # 空にすると性別欄を空欄で出す
postal_code: "000-0000"
address: "東京都〇〇区〇〇 1-2-3"
address_kana: "とうきょうと 〇〇く"
# 学歴・職歴・免許資格は {year, month, text} の行リスト。職歴の末尾「現在に至る」「以上」はテンプレートが付ける
education:
  - {year: 2014, month: 3, text: "〇〇高等学校 卒業"}
  - {year: 2014, month: 4, text: "〇〇大学 〇〇学部 入学"}
  - {year: 2018, month: 3, text: "〇〇大学 〇〇学部 卒業"}
work:
  - {year: 2018, month: 4, text: "株式会社サンプル 入社"}
currently_employed: true  # true なら職歴の末尾に「現在に至る」を付ける
licenses:
  - {year: 2020, month: 10, text: "基本情報技術者試験 合格"}
---

# 履歴書マスター（汎用）

応募先に依らない履歴書の項目。PDF は `scripts/profile/export_rirekisho.py` で生成する。
志望動機は応募先ごとに `vault/tracks/{track}/companies/{company-key}/application.md` の `## 志望動機` に書き、`--company` で差し込む。

## 本人希望記入欄

貴社規定に従います。
