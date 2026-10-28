<!--
Sources (fetched 2026-09-01, raw Markdown twins at https://antigravity.google/docs/<path>.md — fetch rule: docs_url_map.md):
  https://antigravity.google/docs/subagents
  https://antigravity.google/docs/cli/subagents
  https://antigravity.google/docs/cli/commands/agents
  https://antigravity.google/docs/sdk/subagents
Refresh: re-fetch the sources above via docs.md when the docs change.
-->

# Antigravity Subagents Reference

How to delegate work to subagents in Google Antigravity, grounded in the official documentation:

- https://antigravity.google/docs/subagents
- https://antigravity.google/docs/cli/subagents
- https://antigravity.google/docs/cli/commands/agents
- https://antigravity.google/docs/sdk/subagents

## What subagents are

Subagents parallelize complex tasks and preserve the main agent's context. Instead
of executing every step serially, the main agent delegates work — running tests,
extensive codebase searches, multi-file generation — to dedicated subagents. The
main agent keeps working on other things in parallel, and its context window
isn't polluted by the subagent's step-by-step detail.

## Invoking a subagent

The main agent calls the `invoke_subagent` tool to spawn a new concurrent
session with a dedicated role and initial prompt.

- **Workspace options**: the subagent can `inherit` the parent's workspace,
  create an isolated Git worktree (`branch`), or `share` directory storage.
- **Context isolation**: the subagent uses the specified model tier but starts
  with a clean slate — it does not inherit the parent's conversation history.
- **Execution**: it starts immediately on invocation; the main agent can invoke
  multiple subagents concurrently.
- **Monitoring**: click into its conversation via the subagent panel (IDE), or
  press `Alt+J` in the CLI.

## Built-in subagents

| Name | Purpose |
| :-- | :-- |
| `research` | Codebase research, file navigation, structural exploration |
| `browser` | Sandboxed browser for interactive browser testing — invoked only via `/browser` |
| `self` | A direct clone of the calling agent: identical system instructions and toolset |

## Defining custom subagents (.md)

Custom subagents are reusable Markdown files (`<name>.md` or `<name>/agent.md`)
with YAML frontmatter, or transient ones created mid-session via the
`define_subagent` tool.

### Discovery locations

| Location | Path | Scope |
| :-- | :-- | :-- |
| Workspace | `.agents/agents/<name>.md` or `.agents/agents/<name>/agent.md` | This repo/workspace |
| Global | `~/.gemini/config/agents/<name>.md` or `.../agents/<name>/agent.md` | All workspaces |
| Plugin | `plugins/<plugin_name>/agents/` | Bundled with a plugin |

### Frontmatter fields

| Field | Type | Default | Description |
| :-- | :-- | :-- | :-- |
| `name` | string | *(required)* | Unique identifier for the custom agent |
| `description` | string | *(required)* | Used by the planner to decide when to delegate to this agent |
| `tools` | string[] | `[]` | Explicit allowed tools (e.g. `view_file`, `replace_file_content`, `grep_search`, `run_command`) |
| `mainAgent` | boolean | `true` | If `true`, selectable as the primary agent in chat interfaces |
| `subagent` | boolean | `true` | If `true`, invocable via `invoke_subagent` |
| `model` | string | `inherit` | Model tier when invoked (`inherit`, `flash`, `pro`) |
| `commandExecutionPolicy` | string | `sandbox` | Shell auto-execution policy (`off`, `auto`, `eager`, `sandbox`) |
| `mcpServers` | object[] | `[]` | Custom MCP servers for this subagent |
| `skills` / `plugins` | string[] | `[]` | Skill paths (e.g. `skills/my-helper-skill`) or plugin dependencies |

> **Known issue**: an unmapped or misspelled tool name in `tools` can hang the
> subagent process. Double-check exact tool names before shipping a custom
> subagent definition.

The content after the frontmatter `---` is the subagent's system prompt;
organize it with normal Markdown H1 headings.

```markdown
---
name: code-auditor
description: Specialized subagent for security audits, static analysis, and code quality reviews.
tools:
  - view_file
  - grep_search
  - run_command
subagent: true
mainAgent: false
model: pro
commandExecutionPolicy: sandbox
skills:
  - skills/security-checklist
---

# System Prompt
You are an expert security auditor and code reviewer. Your primary objective is to inspect source code for security vulnerabilities, memory leaks, and anti-patterns.

# Review Guidelines
1. Perform thorough static analysis without altering files unless explicitly asked.
2. Flag potential injection flaws, unvalidated inputs, or hardcoded secrets.
3. Provide concise, actionable remediation steps for each finding.
```

## Lifecycle states

Subagents run asynchronously in the background and are always in one of:

1. **Running** — actively executing tools/reasoning. Cancel from the subagent
   panel (**Stop Subagent**) or press `k` in the CLI `/agents` panel. The
   parent can also interrupt by sending it a message or terminating it.
2. **Idle** — finished, sent a result to its parent, and paused. It
   auto-re-awakens on receiving a new message and retains all prior context.
3. **Killed** — permanently terminated, cannot be re-awoken. Temporary Git
   worktrees are cleaned up automatically; the JSONL transcript stays readable.

## Inter-agent communication & nesting

- Agents message each other by conversation ID — parent, subagent, or any peer
  whose ID is known.
- Messaging an idle subagent auto-wakes it.
- Agents can read each other's transcripts to audit multi-step work.
- **Nesting depth is capped at 10 levels** beneath the primary agent, to
  prevent runaway recursion / resource exhaustion.

## Permissions inheritance

Subagents inherit their parent's safety configuration: allowed terminal
command prefixes, file read/write directory scopes, and sandbox settings. The
parent retains full access to a subagent's workspace, including isolated
worktrees. If a subagent hits a tool call needing authorization, the request
bubbles up to the main UI / subagent panel for approval.

## Choosing invoke_subagent vs. the multi-agent orchestrators

`invoke_subagent` is the low-level primitive for one-off delegation. Antigravity
2.0 also ships two higher-level orchestrators for larger jobs (plan-gated —
check current availability before relying on them):

| Orchestrator | Command | Use for |
| :-- | :-- | :-- |
| Boost deep reasoning | `/boost` | Tough concurrency bugs, algorithmic challenges, non-trivial refactors within an interactive session (seconds–hours), with independent verification loops. Three-tier hierarchy: `Orchestrator` → `DeepCoder`/`DeepInvestigator` coordinators → isolated execution workers |
| Teamwork | `/teamwork-preview` | Large software projects, multi-file refactors, complex research — milestone decomposition, parallel implementation, independent verification, coordinated by the platform |

See `/docs/boost` and `/docs/teamwork` for details.

## IDE: monitoring subagents

The subagent panel lists every active/completed/killed subagent for the
conversation; click a row to open its full transcript (thoughts, tool calls,
output) and to stop it.

## CLI: the `/agents` panel

Type `/agents` and press Enter to open the **Agent Manager Panel**. It serves
two purposes:

1. **Custom agent selection** — switch the primary agent among the default and
   any discovered custom agents. Switching while inside an active conversation
   forks the session (history is preserved, not rewritten); switching from a
   fresh session applies directly.
2. **Subagent monitoring** — spawned subagents appear under **Subagents**,
   grouped by triggering prompt, each with a live state: `running`, `done`,
   `error`, `killed`.

Creating a custom agent from inside the panel uses the same locations as
above; the panel header prints the exact paths
(`{workspace}/.agents/agents/{agent_name}/agent.md` and
`~/.gemini/config/agents/{agent_name}/agent.md`).

### Panel keybindings

| Key | Action |
| :-- | :-- |
| ↑ / ↓ | Navigate headers, subagents, available agents |
| Enter | Expand/collapse a group, open Subagent Detail View, or select an agent |
| `K` | Kill the highlighted **running** subagent (and its child threads) — no effect on completed ones |
| `A` / `D` | Approve / deny an inline tool-authorization request from a subagent |
| Esc | Back out / apply a prepared agent switch |

### Fast paths outside the panel

- **`Alt+J`** ("teleport"): jump straight from the main prompt into the Detail
  View of the next subagent awaiting your approval; `Esc` teleports back.
- **`Ctrl+K`** ("fast-path"): approve the pending action shown in the inline
  status notification above the prompt box, without opening the panel.
- **`/tasks`**: separate panel for *non-agentic* background work (plain shell
  commands, test runs, `/btw` queries) — not subagents.

### Common mistakes (official)

| Mistake | Why it fails | Fix |
| :-- | :-- | :-- |
| Expecting a custom-agent switch to rewrite turn history | Switching forks the conversation to preserve history | Continue in the newly forked session |
| Placing agent files directly in the config root | The scanner only looks inside `agents/` directories | Move to `.agents/agents/<name>/agent.md` |
| Pressing `K` on a completed subagent | `K` only targets `running` subagents | Press `Enter` to inspect its log instead |

## SDK: defining subagents programmatically

Two approaches, both in `google.antigravity`:

**Dynamic self-cloning** — let the main agent spawn subagents on demand that
inherit its own permissions/toolset:

```python
from google.antigravity import Agent, LocalAgentConfig, types

config = LocalAgentConfig(
    capabilities=types.CapabilitiesConfig(enable_subagents=True)
)

async with Agent(config) as agent:
    response = await agent.chat("Decompose and audit this codebase.")
    print(await response.text())
```

**Static custom subagents** — define a subagent with its own tools/system
instructions. Any custom tool assigned to a subagent must also be registered
in the parent's `tools` list:

```python
from google.antigravity import Agent, LocalAgentConfig, types

def my_custom_reviewer_tool(file_path: str) -> str:
    """Audits docstrings in a python file."""
    return f"Verified {file_path}"

reviewer = types.SubagentConfig(
    name="code_reviewer",
    description="Audits source code for style compliance.",
    system_instructions="Check function docstrings in Python files.",
    tools=[my_custom_reviewer_tool],
)

config = LocalAgentConfig(
    tools=[my_custom_reviewer_tool],
    subagents=[reviewer],
)

async with Agent(config) as agent:
    response = await agent.chat(
        "Check function docstrings in Python files under src/."
    )
    print(await response.text())
```

Full example: [`subagents.py`](https://github.com/google-antigravity/antigravity-sdk-python/blob/main/examples/getting_started/subagents.py).

## Keeping this reference fresh

This file is a snapshot of the official docs. When details matter (or
something here no longer matches observed behavior), use the
procedure in [docs.md](docs.md) to re-fetch the source pages listed at the top and
update this file.
