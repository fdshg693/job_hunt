---
# フロントマター仕様: scripts/vault/schema/ (一覧: docs/vault/schema.md)
# vaultに保存する際は YYYY-MM-DD_{stage}.md にリネームして配置します
company: "株式会社〇〇"
company_key: "company-name"
track: "domestic" # domestic | overseas
date: "YYYY-MM-DD"
stage: "casual"
interviewer: "EM 〇〇氏、人事 △△氏"
result: "pending" # pending | passed | rejected | declined | not_applicable
tags:
  - "カジュアル面談"
---

# 株式会社〇〇 カジュアル面談メモ (YYYY-MM-DD)

## 1. 面談基本情報
- **日時**: YYYY-MM-DD HH:MM〜HH:MM
- **形式**: Google Meet / Zoom / 対面
- **面談相手**:
  - 〇〇氏（役職 / 所属チーム）
- **面談の目的・位置づけ**: （例: 会社紹介・相互理解、開発環境の確認、選考前の意向すり合わせ）

---

## 2. 事前準備・確認したい論点（聞くべきこと）
> 面談前に `index.md` や `vault/profile/preferences.md`、trackの条件から確認事項をリストアップ

- [ ] 出社頻度・リモート運用の実態（週〇日、コアタイム有無など）
- [ ] 開発組織体制と現在の課題（マイクロサービス移行、技術的負債など）
- [ ] 直近注力しているビジネス課題・プロダクト戦略
- [ ] 期待される役割・裁量

---

## 3. 面談中リアルタイムメモ・質疑応答（一次情報）
> 面談中はここに素早く箇条書きで記録

### 会社紹介・組織・開発体制の説明メモ
- 事業・プロダクトの状況: 
- チーム構成・開発プロセス: 
- 技術スタック・インフラ・ツール: 

### こちらからの質問と回答
- **Q1. **
  - **A**: 
- **Q2. **
  - **A**: 
- **Q3. **
  - **A**: 

### 相手からの質問・逆質問への回答
- **Q: 転職のきっかけ・次の環境に求めるものは？**
  - **A**: 
- **Q: これまでの強み・実績について**
  - **A**: 

---

## 4. 所感・カルチャーフィット（主観メモ）
- **ポジティブな印象・魅力**:
  - 
- **懸念点・違和感・リスク**:
  - 
- **総合的な手応え・現時点の志望度**:
  - 志望度: 高 / 中 / 低 / 保留
  - コメント: 

---

## 5. 次回アクション・選考結果
- **次回ステップ**: （例: 1次面接へ進む / 見送り / 他社状況を見て判断）
- **期日・予定**: 
- **反映チェックリスト**:
  - [ ] 企業ログ `vault/tracks/{track}/companies/{company_key}/index.md` の選考サマリに反映
  - [ ] `uv run python scripts/vault/build_pipeline.py --track {track}` で pipeline.md 再生成
