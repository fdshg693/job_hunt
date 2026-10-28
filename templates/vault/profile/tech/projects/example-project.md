---
# キー・型・許容値の正は scripts/vault/schema/（一覧は docs/vault/schema.md の TechProjectDoc）
project_key: "example-project" # ファイル名と一致させる
title: "家計簿 API（個人開発）"
project_type: "personal" # personal | work | oss
status: "active" # active | paused | done
started_at: "2026-08-01"
tech_stack:
  - "Go"
  - "PostgreSQL"
  - "Kubernetes"
role: "設計・実装・運用を 1 人で担当"
areas:
  - "example-area" # vault/profile/tech/areas/{key}.md のキー
tags:
  - "個人開発"
  - "バックエンド"
updated_at: "2026-10-15"
---

# 家計簿 API（個人開発）

## 概要

- 何を作っているか: 銀行明細 CSV を取り込んで集計する REST API
- 動機: Go の並行処理と Kubernetes 運用を実際に手を動かして身につけるため

## 現在地（今やっていること）

- 2026-10: CSV 取り込みをジョブキュー化し、Pod の水平スケールを検証中

## 構成・設計判断

- DB は PostgreSQL。集計クエリが中心でトランザクション整合性が欲しいため、NoSQL は採らなかった
- 取り込み処理は API と分離したワーカーにした（大きな CSV で API のレイテンシが悪化したため）

## 詰まった点と解決

- ワーカーを増やすと同じジョブを二重処理した → `SELECT ... FOR UPDATE SKIP LOCKED` でジョブを確保する方式に変えて解消

## 未解決・次にやること

- 監視（メトリクス・トレース）が未整備。OpenTelemetry を入れる予定

## 面接で話せるポイント

- 二重処理の原因調査から、ロック方式を選んだ理由（他案との比較）まで説明できる
