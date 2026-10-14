---
name: antigravity-docs
description: Use when answering questions about Google Antigravity — the agentic coding platform, Antigravity 2.0, IDE, CLI, SDK, agent skills, rules, workflows, plugins, hooks, MCP servers, subagents, sandbox, permissions, artifacts, pricing, and use cases. Grounds answers in the latest official documentation from antigravity.google (llms.txt index plus per-page raw Markdown) instead of training-data memory, which may be stale.
meta:
  tag: []
  requires_repo_tools: none
  requires_env: none
  dependencies: python
  requires_install: none
  requires_hooks: none
  requires_skills: none
  status: stable
  description: no description
  version: 1.0.4
---

# Antigravity Documentation Reference

Use this skill to answer Google Antigravity questions from the official
documentation at `antigravity.google` instead of relying on training-data
memory.

## Workflow

1. **Download the official docs index**

   Run the downloader located next to this SKILL.md (run with `--help` first if
   unsure about options):

   ```bash
   python .agents/plugins/antigravity-meta/skills/antigravity-docs/download_antigravity_reference.py
   ```

   - Writes `output/llms.txt` (the official index of all pages)
   - Files fetched within the last 24 hours are reused. Pass `--force` to refresh

2. **Find the relevant page**

   - Search `output/llms.txt` to identify relevant page titles and URLs
   - The index lists URLs and one-line descriptions only — it contains **no
     page content** (the site does not publish `llms-full.txt`)

3. **Fetch the page content**

   Docs pages at `https://antigravity.google/docs/...` are JavaScript-rendered
   app shells: a plain HTTP fetch returns an empty shell with no readable
   content. Use one of these instead:

   - **Preferred — raw Markdown twin**: every `/docs/...` page has a
     plain-Markdown twin at **the same path with `.md` appended** — e.g.
     `https://antigravity.google/docs/skills` →
     `https://antigravity.google/docs/skills.md`,
     `https://antigravity.google/docs/ide/tab` →
     `https://antigravity.google/docs/ide/tab.md`. No path remapping is
     needed (this replaced an older `/assets/docs/<path>/<filename>.md`
     scheme with per-page folder remapping — see
     [docs_url_map.md](docs_url_map.md) for the retired table; do not use
     its entries, they all 404 under the current site).
   - **Fallback**: fetch the HTML page URL with a tool that renders
     JavaScript (e.g. the browser integration). If a `<path>.md` fetch 404s
     for a page that clearly exists at `/docs/<path>`, that's a signal the
     site changed its Markdown-twin mechanism again — re-verify the rule
     (try a few known-good pages) before assuming it's just page-specific
     drift, and update [docs_url_map.md](docs_url_map.md) with whatever the
     new rule turns out to be.

   Non-docs pages listed in the index (`/pricing`, `/changelog`,
   `/product/...`, `/use-cases/...`, etc.) have no Markdown twin — the
   `.md`-suffix trick 404s there too; fetch their HTML directly.

4. **Answer with sources**

   - Base the answer on the fetched content and cite the official docs URL
     (the `/docs/...` one, not the `/assets/...` one)
   - If the index has no relevant page, say so and, when necessary, explore
     `https://antigravity.google` directly

## Notes

- Scripts read and write `output/` relative to this skill directory
- `docs_url_map.md` now documents the live `<path>.md` rule (verified
  2026-08-30) plus a struck-through record of the old per-page table it
  replaced, kept only for history — don't resurrect those old URLs
