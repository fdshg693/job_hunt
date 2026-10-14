---
# Sources (fetched 2026-08-30 via the antigravity-docs skill, raw Markdown twins
# at https://antigravity.google/docs/<path>.md — see that skill's docs_url_map.md
# for the current fetch rule):
#   https://antigravity.google/docs/rules-workflows
#   https://antigravity.google/docs/ide/rules
#   https://antigravity.google/docs/cli/gcli-migration
#   https://antigravity.google/docs/agent-settings (checked, no memory-related content)
#   https://antigravity.google/docs/faq (checked, no memory-related content)
# Depends on: antigravity-docs skill — re-fetch the sources above to refresh this
# reference when the docs change.
name: antigravity-memory
description: Guides placement and authoring of persistent Agent context in Google Antigravity — GEMINI.md, AGENTS.md, workspace Rules (.agents/rules), global Rules (~/.gemini/GEMINI.md), and Workflows. Use when deciding what belongs in each mechanism, explaining how/when Antigravity reads these files (including what is and isn't officially documented about nested directories and reload timing), or troubleshooting why a rule isn't applied. Not for Agent Skills (use antigravity-skills) or general Antigravity features (use antigravity-docs).
meta:
  tag: []
  requires_repo_tools: none
  requires_env: none
  dependencies: none
  requires_install: none
  requires_hooks: none
  requires_skills: antigravity-docs, antigravity-skills
  status: stable
  description: no description
  version: 1.0.1
---

# Antigravityのメモリ設計（GEMINI.md / AGENTS.md / Rules）

Google Antigravity がプロジェクト知識を「記憶」する仕組みは、公式ドキュメント上では
**Rules**（`.agents/rules/` ワークスペース単位、`~/.gemini/GEMINI.md` グローバル）と
**Workflows**（`/workflow-name` で呼ぶ手順書）の2つに整理されている。加えて、CLI
移行ガイドには「ワークスペース直下の `GEMINI.md` と `AGENTS.md` を Agent が読む」という
記載がある。このスキルは、どこに何を書くべきかの判断と、公式に確認できる範囲／
できない範囲（ネスト対応・再読込タイミングなど）の切り分けを行う。

## 最重要: 仕組みの全体像

| 機能                   | 場所                                                        | スコープ                 | 向いている内容                       |
| ---------------------- | ----------------------------------------------------------- | ------------------------ | ------------------------------------ |
| グローバル Rules       | `~/.gemini/GEMINI.md`                                       | 全ワークスペース共通     | 個人の全プロジェクト共通の指示       |
| ワークスペース Rules   | `.agents/rules/*.md`（旧 `.agent/rules/` も後方互換で対応） | ワークスペース/gitルート | コーディング規約・条件付き指示       |
| ワークスペース context | ワークスペース直下の `GEMINI.md` / `AGENTS.md`              | ワークスペース           | クロスツール共通の永続指示           |
| Workflows              | `/workflow-name`（プラグイン等で定義）                      | 呼び出し時のみ           | 反復作業の手順（トラジェクトリ単位） |
| Skills                 | `.agents/skills/` 等                                        | 関連依頼時だけ           | 手順・専門ワークフロー（詳細は下記） |

- Skills との切り分けは **antigravity-skills** スキルを使う（本スキルは Rules/context/Workflows専用）。
- 「毎回守るべき規約」は Rules か GEMINI.md/AGENTS.md、「特定作業の手順」は Skill か Workflow、
  という切り分けが最初の判断。

## GEMINI.md / AGENTS.md の扱い

- 公式の CLI 移行ガイド（gcli → Antigravity CLI）に次の記載がある:
  > "The agent continues to parse and enforce rule constraints defined inside your
  > active directory's GEMINI.md and AGENTS.md files."
  - つまり **ワークスペース（アクティブディレクトリ）直下の `GEMINI.md` と `AGENTS.md`
    の両方が対応**しており、Gemini CLI と Antigravity CLI で挙動は変わらない。
  - グローバル層は `~/.gemini/GEMINI.md` のみ（`~/.gemini/AGENTS.md` のような
    グローバル `AGENTS.md` は公式記載なし）。
- **ネスト（サブディレクトリ配置）の扱いは公式ドキュメントに記載がない。** Rules ページ・
  IDE Rules ページ・移行ガイドのいずれも「アクティブディレクトリ」としか言っておらず、
  サブディレクトリごとの `GEMINI.md`/`AGENTS.md` を自動で拾うか、拾うとして
  いつ（セッション開始時のみか、ファイル編集のたびに再走査するか）読むかは未文書。
  - Codex の AGENTS.md discovery（ルート→CWD経路を起動時に1回だけ歩く）や Claude Code の
    ネスト CLAUDE.md（ディレクトリツリー全体を都度注入）の挙動をそのまま類推して
    説明しないこと。確証が必要なら下記フォールバックで最新ドキュメントを確認する。
- **CLAUDE.md 自体への直接対応は公式記載が無い。** 移行ガイドが明示するのは
  `GEMINI.md` と `AGENTS.md` の2つだけで、`CLAUDE.md`というファイル名は
  Antigravity 側のドキュメントに一度も登場しない。Cursor/Cline 等が `CLAUDE.md` を
  `AGENTS.md` 相当のエイリアスとして扱うのとは異なる点に注意する。

## Claude Codeの`.claude/rules`に相当する仕組み

- Antigravity の **ワークスペース Rules**（`.agents/rules/*.md`）が最も近い機能。
  各ルールファイルは次の4種類の発火方式のいずれかを持つ（公式ドキュメント記載）:
  - **Manual** — エージェント入力欄での `@` メンションで手動適用
  - **Always On** — 常時適用
  - **Model Decision** — 自然言語の説明文を見てAIが関連性を判断
  - **Glob** — `*.js` や `src/**/*.ts` のようなパターンにマッチするファイルに適用
  - YAML frontmatter では `trigger` キー（`glob`, `always_on`, `model_decision`, `manual`）を指定する。Glob 方式の場合は `trigger: glob` を指定し、`globs:` にカンマ区切りで対象パスを1行で記述する。
    ```yaml
    ---
    trigger: glob
    globs: src/**/*.ts, tests/**/*.ts
    ---
    ```
- ルール内では `@filename` で他ファイルを参照できる（相対パスはルールファイル基準、
  絶対パス`/`始まりはまず真の絶対パス、フォールバックでワークスペース相対パスとして解決）。
- **文字数上限は Rules・Workflows ファイルともに1ファイル12,000文字。** 超える場合は
  トピックごとにファイルを分割する。
- プラグインが同梱する `rules/` サブディレクトリ（`<rule-name>.md`）は、上記の
  ワークスペース Rules とは別枠でプラグイン配布時にバンドルされるもの
  （詳細は **antigravity-skills** スキルのプラグイン構造の節を参照）。

## Workflows（Rulesとの違い）

- `/workflow-name` のスラッシュコマンドで呼び出す「反復タスクの手順書」。
- Rulesが**プロンプトレベル**で常時/条件付きに文脈を注入するのに対し、
  Workflowsは**トラジェクトリレベル**でステップ列を進行させる。
- Workflow同士のネスト呼び出し（あるWorkflowの指示から別のWorkflowを呼ぶ）が可能。
- 文字数上限はRulesと同じく1ファイル12,000文字。

## 自動生成メモリ機能について（無い）

- Claude Codeの auto memory や Codex の `memories`機能（過去チャットからの自動生成・
  `~/.codex/memories/`への永続化）に相当する**「会話から自動でメモリを生成する」機能は、
  公式ドキュメント（Features / Agent Settings / FAQ を確認済み）に記載が無い**。
- Antigravityの永続コンテキストは GEMINI.md/AGENTS.md/Rules という**人間が書く静的テキスト**
  のみで、生成的な自動メモリ機構があるとは断定しないこと。今後の機能追加で状況が
  変わっている可能性はあるため、疑わしい場合は下記フォールバックで確認する。
- Agent Settingsで言及される `~/.gemini/antigravity/` は Artifacts と Knowledge Items
  の格納場所であり、本スキルが扱う「Rules/context」の仕組みとは別物（混同しない）。

## 依頼別の対応

1. **「GEMINI.md/AGENTS.mdを作って/読み方を教えて」** — ワークスペース直下に1ファイル、
   具体的でスキャンしやすい箇条書きで作成する。両方存在する場合の優先順位は
   公式記載が無いため断定せず、どちらか一方に統一するか、フォールバックで確認する。
2. **「特定のファイル種別・ディレクトリだけに適用したい」** — `.agents/rules/` に
   Globまたはモデル判断方式のルールを作る。
3. **「チーム/自分だけの使い分けをしたい」** — チーム共有はワークスペース側
   （`.agents/rules/` またはワークスペース直下の`GEMINI.md`/`AGENTS.md`、Gitコミット）、
   自分の全プロジェクト共通は `~/.gemini/GEMINI.md`。
4. **「メモリ仕様について質問」** — 上記の各節で回答できない場合、下記フォールバックで
   最新の公式ドキュメントを確認する。

## チェックリスト

- [ ] ネスト（サブディレクトリ）対応やファイル編集ごとの再読込タイミングを、
      確認済みの仕様であるかのように断定していないか（未文書）
- [ ] `CLAUDE.md` というファイル名がAntigravityで直接読まれると案内していないか
      （公式に確認できるのは `GEMINI.md`/`AGENTS.md` のみ）
- [ ] Claude Codeの`.claude/rules`のfrontmatterキー名（`paths`等）やCursorの
      `alwaysApply`/`globs`をAntigravityの`.agents/rules/`にそのまま流用していないか
      （発火方式の種類は同じ発想だが、キー名は別ツールの仕様）
- [ ] 「会話から自動でメモリが生成される」機能がある、と断定していないか（未確認・おそらく無し）
- [ ] Rules/Workflowsファイルが1ファイル12,000文字を超えていないか
- [ ] 秘密情報・APIキーをGEMINI.md/AGENTS.md/Rulesファイルに書き込んでいないか

## 困ったときは

1. 仕様が変わっている可能性がある、または未文書の詳細（frontmatterキー名、優先順位、
   ネスト対応の有無）を確認したい場合は **antigravity-docs** スキルで次のページを
   再取得する（このスキルはスナップショットであり陳腐化しうる）。
   - `docs/rules-workflows`（Rules & Workflows の概念全般）
   - `docs/ide/rules`（IDEでのRules設定）
   - `docs/cli/gcli-migration`（GEMINI.md/AGENTS.mdの扱いの根拠）
   - 各ページのMarkdown原文は `https://antigravity.google/docs/<path>.md`
     （パスに`.md`を付けるだけ）で取得できる。詳細は antigravity-docs スキルの
     `docs_url_map.md` を参照（旧`/assets/docs/...`方式は2026-08-30時点で
     廃止済み・全滅していることを確認済み）。
2. Skillsとの切り分け、SKILL.mdフォーマット、プラグイン同梱の`rules/`構造は
   **antigravity-skills** スキルを使う。
3. 他ツール（Claude Code / Cursor / Cline / Codex）のメモリ仕様と混同しない —
   それぞれ claude-code-memory / cursor-memory / cline-memory / codex-memory スキルを使う。
