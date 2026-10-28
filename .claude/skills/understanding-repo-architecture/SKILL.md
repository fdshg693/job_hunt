---
# 前提: なし（読むだけのスキル。スクリプト・環境変数・ブラウザは使わない）
# 依存: 書き方そのものは writing-skill（SKILL.md の規約）/ writing-rules（.agents/rules の規約）に任せる。
#       このスキルは「このリポジトリで何をどこに置くか・変えたら何が波及するか」だけを持つ。
# 正本を書き写さない方針: 規約本文は goal.md / role.md / 各ルール / docs/ が正。ここは地図とチェックリストのみ。
# メンテナ向けの設計意図・更新タイミングは同階層の README.md。
name: understanding-repo-architecture
description: このリポジトリの仕組みそのもの（スクリプト・スキル・ルール・docs・vault スキーマ・テンプレート・Web UI・公開同期）を新規作成・改修・再構成する前に、各レイヤーの役割分担と正本、設計思想、変更時に一緒に直すべき箇所を確認するためのスキル。新規スクリプトや媒体の追加、スキル・ルールの追加や書き換え、vault のフロントマター・パス構成の変更、公開対象パスの追加、ディレクトリ再編の前に使う。既存スクリプトを実行するだけ、vault に企業ログや面談ログを記録するだけのタスクでは使わない。
meta:
  tag: [architecture, maintenance, meta]
  requires_repo_tools: none
  requires_env: none
  dependencies: none
  requires_install: none
  requires_hooks: none
  requires_skills: writing-skill, writing-rules
  status: beta
  version: 1.0.0
---

<!-- 自動生成ファイル: .agents/skills/understanding-repo-architecture/SKILL.md から scripts/dev/sync_agents.py で生成。直接編集せず .agents/skills/understanding-repo-architecture/SKILL.md を編集して再同期すること -->

# リポジトリ設計の理解（仕組みを変える前に読む）

このリポジトリは「AI が CLI で調べて vault に記録し、人間が Web UI で見る」就活支援の仕組みです。改修で壊れやすいのは、**正本と生成物の取り違え**と、**一緒に直すべき一覧・文書の更新漏れ**です。このスキルはその地図を渡すだけで、規約本文は持ちません（正本はリンク先）。

> [!CAUTION]
> 1. **正本を直す**: `.claude/{rules,skills,agents}`・`docs/vault/schema.md`・`docs/scripts/catalog.md`・`pipeline.md` のマーカー内・`data/vault_index.sqlite` は生成物。手で直さず、正本を直して再生成する（[layers.md](layers.md)）。
> 2. **規約を書き写さない**: 新しく書くスキル・ルール・docs でも、既存の規約は正本へリンクする。複製は追随漏れの発生源になる。
> 3. **公開対象に個人情報を入れない**: `scripts/`・`docs/`・`tests/`・`templates/`・`webui/`・`.agents/`・`.claude/` などは公開リポジトリへ同期される。氏名・年収・社名・`visibility: internal` の内容を書かない。個人の値は `vault/` から読む。
> 4. **コミットはユーザーに頼まれたときだけ**。

## 手順

1. 変えようとしているものが、どのレイヤーの何の正本かを [layers.md](layers.md) で確かめる。置き場所に迷ったら、そこの「書いてはいけないこと」で振り分ける。
2. 新しい仕組み（ファイルの置き方・データの流れ・検証）を足す・変える場合は、[principles.md](principles.md) の思想に反していないかを確かめる。
3. [change-impact.md](change-impact.md) の該当する変更種別を開き、一緒に直す箇所を作業の TODO に入れてから着手する。
4. 実装後、[change-impact.md](change-impact.md) 末尾の検証コマンドを流す。

## 書き方は別スキル

| 作るもの | 書き方の正 |
| --- | --- |
| スキル（`.agents/skills/`） | [writing-skill](../writing-skill/SKILL.md) |
| ルール（`.agents/rules/`） | [writing-rules](../writing-rules/SKILL.md)（trigger の選び方は [layers.md](layers.md) のコスト注記も見る） |
| CLI スクリプト | [scripts-entrypoint.md](../../rules/scripts-entrypoint.md)、媒体追加は [new_site_scraper_guide.md](../../../docs/guides/new_site_scraper_guide.md) |
| vault のフロントマター | [vault-schema.md](../../rules/vault-schema.md) |
| Web UI | [webui.md](../../rules/webui.md) |
| 実装プラン（`ai/plans/`） | [ai/plans/README.md](../../../ai/plans/README.md) |
