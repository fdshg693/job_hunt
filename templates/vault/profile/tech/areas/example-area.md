---
# キー・型・許容値の正は scripts/vault/schema/（一覧は docs/vault/schema.md の TechAreaDoc）
area_key: "example-area" # ファイル名と一致させる
title: "Kubernetes"
depth: "practical" # aware | tried | practical | design | teach（定義は docs/vault/schema.md の TechDepth）
last_used: "2026-10-01"
projects:
  - "example-project" # vault/profile/tech/projects/{key}.md のキー
tags:
  - "インフラ"
  - "コンテナ"
# visibility: "internal" # 弱み・未経験の本音など外部に出さない内容を含むなら付ける
updated_at: "2026-10-15"
---

# Kubernetes

## 理解度の根拠（何をやったか）

- 実務: 既存クラスタへのマニフェスト追加・Helm チャートの修正（構築は他メンバー）
- 個人開発: 家計簿 API で Deployment / HPA / Job を自分で書いて運用中

## 説明できること

- Deployment・Service・Ingress の役割と関係
- HPA でスケールさせる条件と、スケール時にジョブが二重処理される問題への対処

## 説明できないこと・未経験

- クラスタ自体の構築・アップグレード（マネージドサービスしか使ったことがない）
- NetworkPolicy・Service Mesh の実運用

## 関連プロジェクト

- [家計簿 API](../projects/example-project.md)
