# Generate or Update Rule Files for AI Coding Agents (Full-Codebase Init)

Analyze this codebase and produce **rule files under `.agents/rules/<topic>.md`** that give an AI coding agent context it cannot efficiently derive from individual files.

This is a costly, usually one-time operation (a full pass over the repo, often with sub-agent delegation). If you weren't explicitly asked to initialize/bootstrap rules for this project, confirm with the user before running the full flow below.

## Prerequisite: file format is defined in `writing.md`

All file format, frontmatter spec, scoping rules (narrowest topic scope, ~30 line cap, no redundant folder rules), topic-naming conventions, and existing examples are defined in **`writing.md`** (same skill directory, `.agents/skills/writing-rules/writing.md`). Read and follow it before producing any rule file. This document only adds the _discovery_ and _delegation_ strategy on top.

Project-wide notes live in `.agents/rules/architecture.md` (or workspace-root `GEMINI.md` / `AGENTS.md`).

## Execution Strategy

### Sub-Agent Delegation

When the codebase contains more than ~5 top-level directories or multiple distinct services/packages, **you must delegate investigation to sub-agents rather than doing all the work yourself.**

1. **Scout phase** — Quickly scan the repo root (directory listing, README, top-level config files, existing `.agents/rules/`, `GEMINI.md`, `AGENTS.md`) to identify the major areas and the domain concepts already covered.
2. **Fan out** — Spawn one sub-agent per major area or candidate topic. Each sub-agent receives:
   - The area path or topic it owns
   - A directive to read `.agents/skills/writing-rules/writing.md` for format/scoping
   - The "What to Discover" priorities below
   - A directive to return draft rule file(s) — one per topic — including the intended path
3. **Parallelize aggressively** — Launch all sub-agents concurrently. Do NOT wait for one area to finish before starting the next.
4. **Synthesize** — Once sub-agents return, deduplicate overlapping rule files, write any missing ones under `.agents/rules/`.

### When NOT to Delegate

For small or single-package repos (≤5 top-level directories, single build system), do the analysis yourself.

### Sub-Agent Instructions Template

```
Analyze the area at `{path}` (or the topic `{concept}`).
Read `.agents/skills/writing-rules/writing.md` for file format, frontmatter, scoping, and naming — follow it exactly.
Apply the "What to Discover" priorities below (from `.agents/skills/writing-rules/init.md`).
Return the full file contents (frontmatter + body) for each proposed rule file,
prefixed with the intended path under `.agents/rules/`.
If a topic warrants long-form documentation, also propose a `docs/...` file and
have the rule body point to it (using `@docs/...`).
```

---

## What to Discover

Prioritize knowledge in this order:

1. **Architecture & Mental Model** — Component boundaries, service topology, data flow directions, and the _reasoning_ behind structural decisions. Highest-value content because it requires cross-file reading that wastes agent time.
2. **Non-Obvious Workflows** — Build, test, run, and deploy commands that aren't discoverable from `package.json`, `Makefile`, `*.sln`, or equivalent alone (required env vars, seed steps, order-dependent setup).
3. **Project-Specific Conventions** — Naming schemes, file placement rules, error-handling strategies, and patterns that _diverge from ecosystem defaults_. Include a concrete file path as an exemplar for each convention.
4. **Integration & Boundaries** — External service dependencies, API contracts between internal modules, shared-state mechanisms, and authentication flows.

### Exclusions

Do NOT document:

- Generic best practices ("write tests", "handle errors", "use meaningful names")
- Aspirational patterns not yet reflected in the actual code
- Information already expressed in config files, linter rules, or CI manifests that an agent will read anyway
- Dependency lists reproducible from lockfiles

## Merging with Existing Files

If a rule file already exists:

1. Read it fully before making changes.
2. Preserve any section the codebase still supports — delete only content contradicted by current code.
3. Keep the trigger pattern (e.g. `globs:`) in sync with where the topic actually lives. Add new paths; remove paths that no longer exist.
4. Append or update sections; do not reorder without reason.

If you find legacy or fragmented configuration files (e.g. from other tools) that should be rules, migrate their valid domain knowledge into appropriately named rule files under `.agents/rules/` or `GEMINI.md`/`AGENTS.md`.

## Style Guide

- Use imperative, present-tense prose ("Services communicate via gRPC", not "Services should communicate…").
- Lead each section with the single most important sentence — agents may truncate.
- When describing a pattern, always include at least one concrete file path as exemplar.
- Prefer tables or tight bullet lists over paragraphs.
- Match the language of existing docs in the repo (e.g. Japanese headings if surrounding rule files use them).

