---
# .agents/rules/*.md ルールファイルの新規作成・修正・(新規/未文書化プロジェクトの)一括初期化をコンテキストに埋め込むためのスキル。
# 元々は writing-rules(作成・修正)と init-rules(全体初期化)の2スキルだったが1つに統合。
# 詳細手順・具体例・サブエージェント委譲戦略は同ディレクトリの init.md / writing.md に分離してあるので、
# 本文の分岐に従って状況に応じて読み込むこと。
# 統合の経緯は同階層のREADME.md参照（人間のメンテナ向け）
name: writing-rules
description: Guides creation and maintenance of Google Antigravity workspace rule files (`.agents/rules/*.md`) and workspace context. Use when adding or updating path-scoped/topic-scoped project guidance, organizing existing rules, or bootstrapping rules for a new or largely undocumented codebase.
meta:
  tag: []
  requires_repo_tools: none
  requires_env: none
  dependencies: none
  requires_install: none
  requires_hooks: none
  requires_skills: agent-tools-meta
  status: stable
  description: no description
  version: 2.0.0
---

<!-- 自動生成ファイル: .agents/skills/writing-rules/SKILL.md から scripts/dev/sync_agents.py で生成。直接編集せず .agents/skills/writing-rules/SKILL.md を編集して再同期すること -->

# `.agents/rules/*.md` の作成・管理

`.agents/rules/*.md` は、特定のパスやトピックで必要になるプロジェクト知識を Google Antigravity に渡すための Markdown ファイルである。ルールを作成・変更するときは、対象パス/トリガー、ワークスペース直下の `GEMINI.md` / `AGENTS.md`、ほかのルールとの責務の重複を確認してから配置を決める。

## 次に読むファイル

- **プロジェクト全体の初期化・再生成を明示的に依頼された場合**、またはルールが未整備の新規プロジェクトの場合 → 同ディレクトリの [init.md](init.md) を読む。全体調査を伴う高コストな一回限りの作業なので、明示的な依頼なしには実行しない。
- **ルールを1件新規作成・更新する通常のケース** → 同ディレクトリの [writing.md](writing.md) を読む。ファイル形式、適用範囲、粒度、スタイルをここで確認する。

どちらの場合も、ファイル形式と粒度の基準は [writing.md](writing.md) を正とする。`init.md` は全体調査と統合の進め方だけを追加する。
このリポジトリでルールとスキル・docs のどこに何を置くかに迷った場合は [understanding-repo-architecture](../understanding-repo-architecture/SKILL.md) を参照すること（Antigravity 上では `antigravity-memory` スキルも使える）。

