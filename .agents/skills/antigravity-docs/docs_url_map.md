# Docs URL -> raw Markdown mapping

**Update (2026-08-30): the old per-page mapping table below this note is dead.**
The site was restructured and the entire `https://antigravity.google/assets/docs/...`
prefix now 404s unconditionally (verified across every section: `antigravity-2-0`,
`editor`, `browser`, `settings`, etc.) — this is not page-specific drift, the
mechanism itself was replaced.

## Current rule (verified 2026-08-30)

Every `https://antigravity.google/docs/...` page has its raw Markdown twin at
**the same path with `.md` appended** — no prefix change, no per-section folder
remapping needed:

```
https://antigravity.google/docs/<path>       ->  https://antigravity.google/docs/<path>.md
https://antigravity.google/docs/skills       ->  https://antigravity.google/docs/skills.md
https://antigravity.google/docs/ide/tab      ->  https://antigravity.google/docs/ide/tab.md
https://antigravity.google/docs/cli/commands/agents
                                              ->  https://antigravity.google/docs/cli/commands/agents.md
```

Verified working at every depth tested (top-level, one level, two levels nested).
Non-`/docs/...` pages (`/pricing`, `/changelog`, `/product/...`, `/use-cases/...`,
etc.) still have **no** Markdown twin — `<path>.md` 404s there, same as before.

Since this is now a mechanical rule rather than a lookup, no static table is
needed anymore. If a `<path>.md` fetch 404s for a page that clearly exists at
`/docs/<path>`, treat that as a sign the site changed again (see the fallback
step in [SKILL.md](SKILL.md) step 3) rather than assuming the old table's
entry was simply stale.

---

The table below is kept only as a historical record of the pre-2026-08-30
scheme; **do not use it** — every entry in it 404s under the current site.

| Section         | Docs page                                                   | Raw Markdown (DEAD — do not use)                                                  |
| :-------------- | :---------------------------------------------------------- | :-------------------------------------------------------------------------------- |
| Home            | https://antigravity.google/docs/home                        | ~~https://antigravity.google/assets/docs/home/home.md~~                           |
| Antigravity 2.0 | https://antigravity.google/docs/overview                    | ~~https://antigravity.google/assets/docs/antigravity-2-0/overview.md~~            |
| Antigravity 2.0 | https://antigravity.google/docs/getting-started             | ~~https://antigravity.google/assets/docs/antigravity-2-0/getting-started.md~~     |
| Antigravity 2.0 | https://antigravity.google/docs/build-with-google           | ~~https://antigravity.google/assets/docs/antigravity-2-0/build-with-google.md~~   |
| Antigravity 2.0 | https://antigravity.google/docs/features                    | ~~https://antigravity.google/assets/docs/antigravity-2-0/features.md~~            |
| Antigravity 2.0 | https://antigravity.google/docs/models                      | ~~https://antigravity.google/assets/docs/antigravity-2-0/models.md~~              |
| Antigravity 2.0 | https://antigravity.google/docs/projects                    | ~~https://antigravity.google/assets/docs/antigravity-2-0/projects.md~~            |
| Antigravity 2.0 | https://antigravity.google/docs/settings                    | ~~https://antigravity.google/assets/docs/antigravity-2-0/settings.md~~            |
| Antigravity 2.0 | https://antigravity.google/docs/agent-settings              | ~~https://antigravity.google/assets/docs/antigravity-2-0/agent-settings.md~~      |
| Antigravity 2.0 | https://antigravity.google/docs/artifact-review             | ~~https://antigravity.google/assets/docs/antigravity-2-0/artifact-review.md~~     |
| Antigravity 2.0 | https://antigravity.google/docs/mcp                         | ~~https://antigravity.google/assets/docs/antigravity-2-0/mcp.md~~                 |
| Antigravity 2.0 | https://antigravity.google/docs/skills                      | ~~https://antigravity.google/assets/docs/antigravity-2-0/skills.md~~              |
| Antigravity 2.0 | https://antigravity.google/docs/rules-workflows             | ~~https://antigravity.google/assets/docs/antigravity-2-0/rules-workflows.md~~     |
| Antigravity 2.0 | https://antigravity.google/docs/plugins                     | ~~https://antigravity.google/assets/docs/antigravity-2-0/plugins.md~~             |
| Antigravity 2.0 | https://antigravity.google/docs/hooks                       | ~~https://antigravity.google/assets/docs/antigravity-2-0/hooks.md~~               |
| Antigravity 2.0 | https://antigravity.google/docs/sidecars                    | ~~https://antigravity.google/assets/docs/antigravity-2-0/sidecars.md~~            |
| Antigravity 2.0 | https://antigravity.google/docs/permissions                 | ~~https://antigravity.google/assets/docs/antigravity-2-0/permissions.md~~         |
| Antigravity 2.0 | https://antigravity.google/docs/subagents                   | ~~https://antigravity.google/assets/docs/antigravity-2-0/subagents.md~~           |
| Antigravity 2.0 | https://antigravity.google/docs/artifacts                   | ~~https://antigravity.google/assets/docs/antigravity-2-0/artifacts.md~~           |
| Antigravity 2.0 | https://antigravity.google/docs/implementation-plan         | ~~https://antigravity.google/assets/docs/antigravity-2-0/implementation-plan.md~~ |
| Antigravity 2.0 | https://antigravity.google/docs/walkthrough                 | ~~https://antigravity.google/assets/docs/antigravity-2-0/walkthrough.md~~         |
| Antigravity 2.0 | https://antigravity.google/docs/screenshots                 | ~~https://antigravity.google/assets/docs/antigravity-2-0/screenshots.md~~         |
| Antigravity CLI | https://antigravity.google/docs/cli/overview                | ~~https://antigravity.google/assets/docs/cli/cli-overview.md~~                    |
| Antigravity CLI | https://antigravity.google/docs/cli/getting-started         | ~~https://antigravity.google/assets/docs/cli/cli-getting-started.md~~             |
| Antigravity CLI | https://antigravity.google/docs/cli/install                 | ~~https://antigravity.google/assets/docs/cli/cli-install.md~~                     |
| Antigravity CLI | https://antigravity.google/docs/cli/tutorial                | ~~https://antigravity.google/assets/docs/cli/cli-tutorial.md~~                    |
| Antigravity CLI | https://antigravity.google/docs/cli/using                   | ~~https://antigravity.google/assets/docs/cli/cli-using.md~~                       |
| Antigravity CLI | https://antigravity.google/docs/cli/features                | ~~https://antigravity.google/assets/docs/cli/cli-features.md~~                    |
| Antigravity CLI | https://antigravity.google/docs/cli/gcli-migration          | ~~https://antigravity.google/assets/docs/cli/gcli-migration.md~~                  |
| Antigravity CLI | https://antigravity.google/docs/cli/prompting               | ~~https://antigravity.google/assets/docs/cli/cli-prompting.md~~                   |
| Antigravity CLI | https://antigravity.google/docs/cli/artifacts               | ~~https://antigravity.google/assets/docs/cli/cli-artifacts.md~~                   |
| Antigravity CLI | https://antigravity.google/docs/cli/conversations           | ~~https://antigravity.google/assets/docs/cli/cli-conversations.md~~               |
| Antigravity CLI | https://antigravity.google/docs/cli/modes                   | ~~https://antigravity.google/assets/docs/cli/cli-modes.md~~                       |
| Antigravity CLI | https://antigravity.google/docs/cli/projects                | ~~https://antigravity.google/assets/docs/cli/cli-projects.md~~                    |
| Antigravity CLI | https://antigravity.google/docs/cli/subagents               | ~~https://antigravity.google/assets/docs/cli/cli-subagents.md~~                   |
| Antigravity CLI | https://antigravity.google/docs/cli/sandbox                 | ~~https://antigravity.google/assets/docs/cli/cli-sandbox.md~~                     |
| Antigravity CLI | https://antigravity.google/docs/cli/settings                | ~~https://antigravity.google/assets/docs/cli/cli-settings.md~~                    |
| Antigravity CLI | https://antigravity.google/docs/cli/credits                 | ~~https://antigravity.google/assets/docs/cli/cli-credits.md~~                     |
| Antigravity CLI | https://antigravity.google/docs/cli/plugins                 | ~~https://antigravity.google/assets/docs/cli/cli-plugins.md~~                     |
| Antigravity CLI | https://antigravity.google/docs/cli/permissions             | ~~https://antigravity.google/assets/docs/cli/cli-permissions.md~~                 |
| Antigravity CLI | https://antigravity.google/docs/cli/statusline              | ~~https://antigravity.google/assets/docs/cli/cli-statusline.md~~                  |
| Antigravity CLI | https://antigravity.google/docs/cli/title                   | ~~https://antigravity.google/assets/docs/cli/cli-title.md~~                       |
| Antigravity CLI | https://antigravity.google/docs/cli/commands/agents         | ~~https://antigravity.google/assets/docs/cli/commands/agents.md~~                 |
| Antigravity CLI | https://antigravity.google/docs/cli/commands/codesearch     | ~~https://antigravity.google/assets/docs/cli/commands/codesearch.md~~             |
| Antigravity CLI | https://antigravity.google/docs/cli/commands/credits        | ~~https://antigravity.google/assets/docs/cli/commands/credits.md~~                |
| Antigravity CLI | https://antigravity.google/docs/cli/commands/diff           | ~~https://antigravity.google/assets/docs/cli/commands/diff.md~~                   |
| Antigravity CLI | https://antigravity.google/docs/cli/commands/permissions    | ~~https://antigravity.google/assets/docs/cli/commands/permissions.md~~            |
| Antigravity CLI | https://antigravity.google/docs/cli/commands/resume         | ~~https://antigravity.google/assets/docs/cli/commands/resume.md~~                 |
| Antigravity CLI | https://antigravity.google/docs/cli/commands/statusline     | ~~https://antigravity.google/assets/docs/cli/commands/statusline.md~~             |
| Antigravity CLI | https://antigravity.google/docs/cli/commands/title          | ~~https://antigravity.google/assets/docs/cli/commands/title.md~~                  |
| Antigravity CLI | https://antigravity.google/docs/cli/commands/usage          | ~~https://antigravity.google/assets/docs/cli/commands/usage.md~~                  |
| Antigravity CLI | https://antigravity.google/docs/cli/best-practices          | ~~https://antigravity.google/assets/docs/cli/cli-best-practices.md~~              |
| Antigravity CLI | https://antigravity.google/docs/cli/troubleshooting         | ~~https://antigravity.google/assets/docs/cli/cli-troubleshooting.md~~             |
| Antigravity CLI | https://antigravity.google/docs/cli/reference               | ~~https://antigravity.google/assets/docs/cli/cli-reference.md~~                   |
| Antigravity SDK | https://antigravity.google/docs/sdk/overview                | ~~https://antigravity.google/assets/docs/sdk/sdk-overview.md~~                    |
| Antigravity IDE | https://antigravity.google/docs/ide/overview                | ~~https://antigravity.google/assets/docs/ide/ide-overview.md~~                    |
| Antigravity IDE | https://antigravity.google/docs/ide/getting-started         | ~~https://antigravity.google/assets/docs/ide/ide-getting-started.md~~             |
| Antigravity IDE | https://antigravity.google/docs/ide/tab                     | ~~https://antigravity.google/assets/docs/editor/tab.md~~                          |
| Antigravity IDE | https://antigravity.google/docs/ide/agent-side-panel        | ~~https://antigravity.google/assets/docs/editor/agent-side-panel.md~~             |
| Antigravity IDE | https://antigravity.google/docs/ide/review-changes-editor   | ~~https://antigravity.google/assets/docs/editor/review-changes-editor.md~~        |
| Antigravity IDE | https://antigravity.google/docs/ide/implementation-plan     | ~~https://antigravity.google/assets/docs/editor/ide-implementation-plan.md~~      |
| Antigravity IDE | https://antigravity.google/docs/ide/walkthrough             | ~~https://antigravity.google/assets/docs/editor/ide-walkthrough.md~~              |
| Antigravity IDE | https://antigravity.google/docs/ide/screenshots             | ~~https://antigravity.google/assets/docs/editor/ide-screenshots.md~~              |
| Antigravity IDE | https://antigravity.google/docs/ide/browser-recordings      | ~~https://antigravity.google/assets/docs/editor/ide-browser-recordings.md~~       |
| Antigravity IDE | https://antigravity.google/docs/ide/browser                 | ~~https://antigravity.google/assets/docs/browser/browser.md~~                     |
| Antigravity IDE | https://antigravity.google/docs/ide/allowlist-denylist      | ~~https://antigravity.google/assets/docs/browser/allowlist-denylist.md~~          |
| Antigravity IDE | https://antigravity.google/docs/ide/separate-chrome-profile | ~~https://antigravity.google/assets/docs/browser/separate-chrome-profile.md~~     |
| Antigravity IDE | https://antigravity.google/docs/ide/mcp                     | ~~https://antigravity.google/assets/docs/antigravity-2-0/mcp.md~~                 |
| Antigravity IDE | https://antigravity.google/docs/ide/skills                  | ~~https://antigravity.google/assets/docs/editor/ide-skills.md~~                   |
| Antigravity IDE | https://antigravity.google/docs/ide/rules                   | ~~https://antigravity.google/assets/docs/editor/ide-rules.md~~                    |
| Antigravity IDE | https://antigravity.google/docs/ide/workflows               | ~~https://antigravity.google/assets/docs/editor/ide-workflows.md~~                |
| Antigravity IDE | https://antigravity.google/docs/ide/plugins                 | ~~https://antigravity.google/assets/docs/editor/ide-plugins.md~~                  |
| Antigravity IDE | https://antigravity.google/docs/ide/hooks                   | ~~https://antigravity.google/assets/docs/editor/ide-hooks.md~~                    |
| Antigravity IDE | https://antigravity.google/docs/ide/settings                | ~~https://antigravity.google/assets/docs/settings/ide-settings.md~~               |
| Migration       | https://antigravity.google/docs/firebase-studio-migration   | ~~https://antigravity.google/assets/docs/migration/firebase-studio-migration.md~~ |
| Enterprise      | https://antigravity.google/docs/enterprise                  | ~~https://antigravity.google/assets/docs/enterprise/enterprise.md~~               |
| Plans           | https://antigravity.google/docs/plans                       | ~~https://antigravity.google/assets/docs/plans/plans.md~~                         |
| FAQ             | https://antigravity.google/docs/faq                         | ~~https://antigravity.google/assets/docs/faq/faq.md~~                             |
