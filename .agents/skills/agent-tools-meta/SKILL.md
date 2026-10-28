---
name: agent-tools-meta
description: Use when answering questions about the AI agent tools themselves — Claude Code or Google Antigravity — rather than this repository's job-hunting work. Covers the `claude` / `agy` CLI options and subcommands (`claude --help`, `agy help`, -p/--print, --model, --dangerously-skip-permissions, mcp, plugin, agents, doctor), Claude Code features and settings from code.claude.com (hooks, skills, settings.json, slash commands, subagents, MCP, memory, CLAUDE.md), Antigravity features from antigravity.google (Antigravity 2.0, IDE, CLI, SDK, skills, rules, workflows, plugins, hooks, sandbox, permissions, artifacts, pricing), Antigravity persistent context (GEMINI.md, AGENTS.md, .agents/rules, ~/.gemini/GEMINI.md, workflows), Antigravity subagents (invoke_subagent, custom .md subagents, /agents panel, /boost, /teamwork-preview), and delegating a one-shot task to the Claude Code CLI with `claude -p` (only when the user explicitly asks). Grounds answers in the CLI's own help output and the latest official docs instead of training-data memory. Not for writing SKILL.md or .agents/rules files (use writing-skill / writing-rules).
---

# AI エージェントツール（Claude Code / Antigravity）のメタ情報

Claude Code と Google Antigravity というツールそのものの使い方を、CLI の実際のヘルプ出力と最新の公式ドキュメントを根拠に答えるためのエントリポイント。各ツールの本文は同じフォルダの参照ファイルにある。

> [!CAUTION]
> 1. **下の表で該当する参照ファイルだけを読む**。全ファイルを読まない。ツールが分からない質問は、どちらのツールの話かを先に確かめる。
> 2. **[claude/cli-use.md](claude/cli-use.md) はユーザーが「claude CLI に任せて」「`claude -p` で実行して」と明示的に頼んだときだけ使う**。委譲先はコード変更・シェル実行の副作用と API 課金を伴う。CLI の使い方の質問なら [claude/cli-docs.md](claude/cli-docs.md) で答える。
> 3. **パスはこのスキルのフォルダ（この `SKILL.md` のあるフォルダ。参照ファイル内では `<skill-dir>`）基準**。同じ中身が `.agents/skills/` と `.claude/skills/` の両方にあるので、いま読んでいる側のフォルダを使う。スクリプトの出力（`output/`）は自動生成物でコミットしない。

## 質問の種類 → 読む参照ファイル

| ツール | 質問の種類 | 読むファイル |
| --- | --- | --- |
| Claude Code | `claude` コマンドのオプション・フラグ・サブコマンド | [claude/cli-docs.md](claude/cli-docs.md) |
| Claude Code | 機能・設定の仕様（hooks、skills、settings.json、スラッシュコマンド、サブエージェント、MCP、メモリ・CLAUDE.md 等） | [claude/code-docs.md](claude/code-docs.md) |
| Claude Code | タスクを `claude -p` に単発で委譲して実行する（**明示依頼時のみ**） | [claude/cli-use.md](claude/cli-use.md) |
| Antigravity | `agy` コマンドのオプション・フラグ・サブコマンド | [antigravity/cli-docs.md](antigravity/cli-docs.md) |
| Antigravity | 機能・設定の仕様（IDE、CLI、SDK、skills、plugins、hooks、MCP、sandbox、permissions、pricing 等） | [antigravity/docs.md](antigravity/docs.md) |
| Antigravity | 記憶の置き場所（GEMINI.md / AGENTS.md / `.agents/rules` / グローバル Rules / Workflows）、ルールが効かない原因 | [antigravity/memory.md](antigravity/memory.md) |
| Antigravity | サブエージェント（組み込み・カスタム定義・ワークスペース分離・`/agents` パネル・`/boost`・`/teamwork-preview`・SDK） | [antigravity/subagents.md](antigravity/subagents.md) |

- `memory.md` / `subagents.md` は公式ドキュメントのスナップショット。細部が怪しいときは [antigravity/docs.md](antigravity/docs.md) の手順で元ページを取り直して確かめる。
- SKILL.md やルールファイルの書き方そのものは [writing-skill](../writing-skill/SKILL.md) / [writing-rules](../writing-rules/SKILL.md)。
