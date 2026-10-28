---
title: "国内転職 track (domestic)"
track: "domestic"
updated_at: "2026-10-15"
period: "2026年秋〜2027年春"
---

# 国内転職 track (domestic)

## track の定義

- **対象**: 日本法人に雇用される就業。**外資系企業の日本法人も domestic に含む**。
- 日本国外の法人に雇用・契約される就業（現地就労・リロケーション・海外企業へのフルリモート勤務を含む）は `overseas` track で扱う。

## 期間・目標

- **期間**: （例: 2026年秋〜2027年春）
- **目標**: （例: 自社プロダクト企業でバックエンド基盤のフルサイクル開発に携わり、年収を650万円以上へ引き上げる）

## ファイル構成

| ファイル | 役割 |
|---|---|
| [`strategy.md`](strategy.md) | 国内固有の希望条件（年収・出社/勤務地・企業フェーズ） |
| [`criteria.md`](criteria.md) | 本音の足切り条件（非公開・外部露出厳禁） |
| [`ratings.md`](ratings.md) | 企業格付け・ベンチマーク・ブラックリスト（非公開・外部露出厳禁） |
| [`pipeline.md`](pipeline.md) | 選考ダッシュボード（一覧は `scripts/vault/build_pipeline.py` で生成） |
| `companies/{company-key}/` | 1社1フォルダ（`index.md` ＋ 面談ログ `{YYYY-MM-DD}_{stage}.md`） |
| `screening/` | スクリーニング早期打ち切りの集約ログ |
