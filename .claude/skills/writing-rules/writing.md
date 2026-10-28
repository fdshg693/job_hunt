# Creating and Editing a Single Rule File

## General guidelines for writing documentation in this codebase

Focus on discovering the essential knowledge that would help an AI agent be immediately productive in this codebase.
Consider aspects like:

- The "big picture" architecture that requires reading multiple files to understand - major components, service boundaries, data flows, and the "why" behind structural decisions
- Critical developer workflows (builds, tests, debugging) especially commands that aren't obvious from file inspection alone
- Project-specific conventions and patterns that differ from common practices
- Integration points, external dependencies, and cross-component communication patterns

- Write concise, actionable instructions (~20-50 lines) using markdown structure
- Include specific examples from the codebase when describing patterns (keep it short and focused)
- Avoid generic advice ("write tests", "handle errors") - focus on THIS project's specific approaches
- Document only discoverable patterns, not aspirational practices
- Reference key files/directories that exemplify important patterns (use `@path/to/file` where helpful)

## How to write `.agents/rules/*.md` files

All persisted topic/path rules in this codebase are stored as **rule files** under `.agents/rules/` (e.g. `.agents/rules/<topic>.md`).
A rule file is a single Markdown file that can define trigger conditions (such as globs, model decision, or always-on) and provides the necessary context whenever relevant files or topics are addressed.

For persistent, workspace-wide cross-cutting instructions, use workspace-root `GEMINI.md` / `AGENTS.md` or an always-on rule file (such as `.agents/rules/goal.md`).

## File format

Each rule file lives at `.agents/rules/<topic>.md` and has this shape:

```markdown
---
trigger: glob
globs: vault/**/*.md, templates/vault/**/*.md, scripts/vault/**/*.py
---

# vault フロントマタースキーマ規約

<short body — point to authoritative sources (e.g. `scripts/vault/schema/`, generated `docs/vault/schema.md`) or reference files via `@path/to/file`
and summarize what they cover. Keep it focused; do not duplicate the source docs.>
```

- **Trigger types in Antigravity**:
  - **Glob** (`trigger: glob` + `globs:`): マッチするファイルを開いた・編集した際に適用。**`globs:` はカンマ区切りの単一行で記述する**（例: `globs: src/**/*.ts, tests/**/*.ts`）。
  - **Always On** (`trigger: always_on`): ワークスペース全体で常時適用。
  - **Model Decision** (`trigger: model_decision` + `description:`): プロンプトに応じてモデルが判断。
  - **Manual** (`trigger: manual`): `@` メンションで明示的に呼び出し。
- For **project-wide** architecture notes, use an always-on rule or root context (`GEMINI.md` / `AGENTS.md` / `.agents/rules/goal.md`).
- Within rule files, you can use `@filename` syntax to reference other project files (resolved relative to rule file or workspace root).
- The body should be brief (typically 10–30 lines): a heading, a short pointer to canonical documents under `docs/` or source files, and non-obvious cross-cutting notes.
- **Character limit**: Keep individual rule files well under the 12,000 character limit. If content grows large, split by topic or move long-form documentation to `docs/`.

## When to add a rule file

Whenever you discover knowledge that:

1. Spans multiple files or layers (domain ↔ API ↔ UI), AND
2. Is not obvious from reading any single file, AND
3. Is not yet covered by an existing rule or `GEMINI.md`/`AGENTS.md`,

add a new `.agents/rules/<topic>.md` without asking the user. Pick a topic name that matches the domain concept (e.g. `company-log.md`, `vault-schema.md`), not just generic folder names.

## Granularity guidelines

- Place each rule at the **narrowest topic scope** — one rule per feature/domain concept, not one rule per folder.
- The rule body itself should stay short (~30 lines). Put long-form documentation under `docs/` (e.g. `docs/<topic>/README.md`) and have the rule file point to it.
- Project-wide architecture notes live under `.agents/rules/goal.md` or root `GEMINI.md`/`AGENTS.md`.

