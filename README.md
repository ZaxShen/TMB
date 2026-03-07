# Baymax

> A multi-agent framework for building and maintaining **industrial-grade** software projects with LLMs.

## Why Baymax?

Most AI coding tools treat every session as a blank slate. They dump your entire codebase into a context window, generate code, and forget everything by the next run. That works for prototypes — it breaks down for real projects.

**The problem with current AI agents:**
- **No memory** — fix a bug today, the agent has no idea it existed tomorrow
- **No scoping** — a one-line config change triggers the same "read everything" process as a full rewrite
- **No verification** — code is generated but rarely validated against real criteria
- **No audit trail** — three months later, nobody knows *why* a change was made

**Baymax is different.** It models how a real engineering team works:

- A **Project Owner** (you) defines goals in plain language
- A **Planner** (LLM) discusses requirements, explores the codebase with tools, produces a reviewable plan, and **validates** each task — before and after code is written
- An **Executor** (LLM) executes atomic, scoped tasks — one module at a time, with detailed instructions
- Everything is **logged to SQLite** — discussions, decisions, task results, verdicts. Run `baymax report 12` six months later and see exactly what happened
- The system **resumes from any interrupt** — Ctrl+C, crash, "I'll continue tomorrow." No wasted LLM calls, no repeated work
- **Information firewalls** keep each agent focused — Executors see only their task and execution plan, not the full strategic context. This isn't security; it's attention management for LLMs

> **Configurable roles** — by default Baymax uses generic names (Project Owner, Planner, Executor). Run `baymax setup` to pick a preset like **IT Company** (Chief Architect → Architect → SWE) or define your own names. Role names flow into CLI output, SQLite logs, and agent prompts.

The result: maintainable, auditable software — not disposable demos.

---

## Quick Start

**Prerequisites**: [uv](https://docs.astral.sh/uv/) and an LLM API key (Anthropic or OpenAI).

### Option A: Git Submodule (recommended)

Keeps Baymax as a versioned dependency — update with `git submodule update --remote`.

```bash
# 1. Add Baymax as a submodule
cd your-project/
git submodule add https://github.com/ZaxShen/Baymax.git

# 2. Tell git to ignore Baymax's runtime files (one-time)
git config submodule.Baymax.ignore dirty

# 3. Install — creates a shared venv at your project root
#    (setup will offer to create a pyproject.toml if you don't have one)
uv run --directory Baymax baymax setup

# 4. Write your goals, then run
#    Edit Baymax/doc/GOALS.md with what you want done
uv run baymax
```

After setup your project looks like this:

```
your-project/
├── .venv/              ← shared venv (Baymax deps + your deps)
├── pyproject.toml      ← references Baymax as a path dependency
├── Baymax/             ← submodule
├── src/
└── ...
```

All commands run from your **project root** — no more `cd Baymax`.

To update Baymax later: `cd Baymax && git pull origin dev`

**Cloning a project that already has Baymax as a submodule:**

```bash
git clone --recurse-submodules <your-project-url>
cd your-project
uv sync
uv run baymax setup
```

### Option B: Clone

If you don't need version tracking:

```bash
cd your-project/
git clone https://github.com/ZaxShen/Baymax.git
uv run --directory Baymax baymax setup
uv run baymax
```

**How it stays clean** — Baymax ships tracked defaults (`config/*.default.yaml`). Running `setup` creates your local configs (`config/project.yaml`, etc.) which are gitignored. All runtime files (`doc/`, `baymax_history.db`, `.env`) are also gitignored. The submodule never appears dirty in your parent repo.

That's it. Baymax reads your goals, the Planner discusses them with you, builds a blueprint, and the Executor carries it out — all logged to SQLite.

### Quick Tasks

For simple changes that don't need the full discussion step:

```bash
uv run baymax "update our FLOWCHART based on current codebase"
uv run baymax "add error handling to the login module"
```

Same full pipeline (plan → execute → validate), just skips the interactive discussion and manual approval. Still logged to SQLite.

### Self-Evolution

Baymax can modify its own source code through a guarded self-evolution mode:

```bash
uv run baymax evolve "add a new CLI command to export tasks as CSV"
uv run baymax evolve "update README.md to reflect the new auth module"
```

**Safety gates** — every evolution goes through:

1. **Warning banner** — you'll see a prominent warning that agents will have full Baymax access
2. **Planner plans first** — explores Baymax's own codebase, writes `doc/EVOLUTION.md` with proposed changes and risk assessment
3. **Double approval** — the Planner designs the plan (its approval), then you review and press Enter (your approval)
4. **Automatic git snapshot** — Baymax commits its current state before any file is touched, so `git revert HEAD` always works
5. **Health check** — after changes, Baymax verifies it can still import and passes lint

If the health check fails, you get the exact rollback command. The `Baymax/**` blacklist is only lifted during the evolve session — normal workflow remains locked down.

---

## How It Works

### The Workflow

Baymax has three entry points:

**Full workflow** (`baymax`) — for complex, multi-step work:

```
Project Owner writes doc/GOALS.md
         │
         ▼
  ┌─── DISCUSSION ───┐
  │  Planner ↔        │    Interactive Q&A via doc/DISCUSSION.md
  │  Project Owner    │    → saved to SQLite
  └────────┬──────────┘
           ▼
  ┌─── PLANNING ──────┐
  │  Planner writes:  │    BLUEPRINT.md  — task breakdown
  │  2 documents      │    FLOWCHART.md  — architecture diagram (max 12 nodes)
  └────────┬──────────┘
           ▼
    Project Owner reviews & approves
           │
           ▼
  ┌─── EXECUTION PLAN ┐
  │  Planner generates │    Per-task plans stored in SQLite
  │  per-task plans    │    EXECUTION.md — lightweight summary for humans
  └────────┬──────────┘
           ▼
  ┌─── EXECUTION ──────┐
  │  Executor runs     │──→  Planner validates (same agent, full context)
  │  task (shell,      │←──  PASS → next task
  │  files)            │←──  FAIL → retry (max 3)
  └────────┬──────────┘←──  MAX FAIL → escalate to human
           ▼
         DONE
```

**Quick task** (`baymax "..."`) — same pipeline, no interactive steps:

```
Project Owner passes instruction via CLI
         │
         ▼
  ┌─── GATEKEEPER ───┐
  │  Scan project     │
  └────────┬─────────┘
           ▼
  ┌─── PLANNING ──────┐
  │  Blueprint (auto-  │    Same planning, auto-approved
  │  approved)         │
  └────────┬──────────┘
           ▼
  ┌─── EXECUTION ──────┐
  │  Executor runs     │──→  Planner validates
  │  task              │←──  PASS → next / FAIL → retry
  └────────┬──────────┘
           ▼
         DONE
```

**Self-evolution** (`baymax evolve "..."`) — for modifying Baymax itself:

```
Project Owner passes instruction via CLI
         │
         ▼
  ┌─── WARNING ────┐
  │  Display safety │
  │  banner         │
  └────────┬───────┘
           ▼
  ┌─── GATEKEEPER ───┐
  │  Scan Baymax/      │    (not the parent project)
  └────────┬─────────┘
           ▼
  ┌─── PLANNER ──────┐
  │  Explore Baymax    │    Full read access to Baymax/**
  │  source code     │    Writes doc/EVOLUTION.md
  │  Generate plan   │
  └────────┬─────────┘
           ▼
    Project Owner reviews & approves
           │
           ▼
  ┌─── GIT SNAPSHOT ─┐
  │  Auto-commit     │    Safety rollback point
  │  current state   │
  └────────┬─────────┘
           ▼
  ┌─── PLANNER ──────┐
  │  Execute plan    │    Full read/write to Baymax/**
  │  Modify source   │
  └────────┬─────────┘
           ▼
  ┌─── HEALTH CHECK ─┐
  │  Import test     │    Verify Baymax still works
  │  Lint check      │
  └────────┬─────────┘
           ▼
         DONE
```

### The Roles

Role names are configurable via `config/project.yaml`. Defaults shown, with IT Company preset in parentheses:

| Role | Default | IT Company | Responsibility |
|------|---------|------------|----------------|
| **owner** | Project Owner | Chief Architect | Writes goals. Discusses with Planner. Reviews blueprints. |
| **planner** | Planner | Architect | Discusses requirements. Designs blueprint and flowchart. Writes per-task execution plans. **Validates** each task (has full context — no re-learning needed). Handles escalations. |
| **executor** | Executor | SWE | Executes tasks using shell, filesystem, and search tools. Reports issues to Planner. |

### The Documents

All artifacts live in `Baymax/doc/`:

| File | Written By | Read By | Purpose |
|------|-----------|---------|---------|
| `GOALS.md` | Owner (you) | Planner | What you want done — plain language |
| `DISCUSSION.md` | System | Owner, Planner | Planner–Owner Q&A transcript |
| `BLUEPRINT.md` | Planner | Owner | High-level system design and task breakdown |
| `FLOWCHART.md` | Planner | Owner | Architecture/data-flow diagram (Mermaid, max 12 nodes) |
| `EXECUTION.md` | Planner | Owner | Lightweight summary of per-task plans (full plans in SQLite) |
| `EVOLUTION.md` | Planner | Owner | Self-evolution plan (only during `evolve` mode) |

### Permissions

| Resource | Owner | Planner | Executor |
|----------|-------|---------|----------|
| `doc/GOALS.md` | Edit | Read | — |
| `doc/DISCUSSION.md` | Read | Edit | — |
| `doc/BLUEPRINT.md` | Read | Edit | — |
| `doc/FLOWCHART.md` | Read | Edit | — |
| `doc/EXECUTION.md` | Read | Edit | — |
| `baymax_history.db` | Read | Read / Write | Read / Write |
| DB: tasks | — | Write (create) | Read (own task) |
| DB: ledger | Read | Write | Write |
| Project files | — | — | Edit |
| `.env`, secrets | — | — | — |
| `doc/EVOLUTION.md` | Read | Edit | — |
| `Baymax/**` (engine) | Edit (manual) | Edit (evolve mode only) | — |

**Key rules:**
- Executors never see GOALS.md, DISCUSSION.md, BLUEPRINT.md, or FLOWCHART.md — high-level context could mislead execution.
- Executors get their task's execution plan from SQLite (not a shared file), keeping their context window focused.
- The Planner validates each task directly — it already holds the full project context (data schema, algorithm design, edge cases), so no re-learning is needed.
- Executors can report implementation-vs-design discrepancies to the Planner.
- Secrets and the Baymax engine itself are inaccessible to all agents during normal operation.
- In **evolve mode** (`baymax evolve "..."`), the Planner gets temporary full access to Baymax source — gated by double approval and automatic git snapshot.

### The Database

Everything is persisted in `baymax_history.db` (SQLite + JSON):

| Table | What's In It |
|-------|-------------|
| `issues` | Each run's objective, status, `parent_issue_id` for cross-issue links |
| `discussions` | Full Planner–Owner Q&A exchange |
| `tasks` | Blueprint items with hierarchical `branch_id`, `parent_branch_id`, lightweight `title`, `skills_required` |
| `ledger` | Every agent action with a `summary` one-liner — full JSON detail stored but never bulk-read |
| `skills` | Registered skill files — name, description, tags, file path |

#### Branch IDs

Every task has two identifiers:

- `id` — autoincrement primary key (stable, used for internal DB references)
- `branch_id` — hierarchical string encoding semantic relationships

```
id=1  branch_id="1"       ← Email login feature
id=2  branch_id="1.1"     ← Add email verification (extends login)
id=3  branch_id="2"       ← Dashboard redesign (unrelated to login)
id=4  branch_id="1.1.1"   ← Handle expired verification tokens
```

**Branch operations** — when you need to replace email login with phone login, `branch_id LIKE '1.%'` finds every related task across all issues. Task id=3 (dashboard) is untouched even though it was created between id=2 and id=4. Git can't do this because reverts are sequential — Baymax's branch IDs are semantic.

The Planner auto-generates branch IDs by reviewing the existing task tree before planning.

```bash
baymax log               # List recent issues
baymax log 1             # Full detail for issue #1
baymax report 1          # Export full markdown report
baymax "fix X"           # Quick task (full pipeline, no interactive steps)
baymax evolve "fix Y"    # Self-evolution (modify Baymax itself)
```

### Skills

Skills are **reusable knowledge artifacts** — concise markdown guides that agents load on demand instead of re-deriving patterns or reading large source files every time.

```
Baymax/skills/
├── db-operations.md        # Store API: lightweight vs. full queries
├── branch-operations.md    # Hierarchical branch ID patterns
└── file-access.md          # Permission model rules
```

**How it works:**

1. **Planner assigns skills per task** — sees available skills with effectiveness scores and applicability conditions, assigns relevant ones to `skills_required`
2. **Executor loads only assigned skills** — skill content is injected into context alongside the task prompt. No irrelevant knowledge, no wasted tokens
3. **Agents can request new skills** — Executor has a `skill_request` tool. The Planner creates and reviews all skills
4. **Built-in skills auto-seed** — on first run, Baymax registers all `.md` files in `skills/` as curated, trusted skills

**Validation and trust:**

| Aspect | Mechanism |
|---|---|
| **Trust tiers** | `curated` (system/human — always trusted) vs. `agent` (created during execution — requires review) |
| **Status lifecycle** | `draft` → `pending_review` → `active` → `deprecated` |
| **Quality gate** | Agent-created skills are auto-submitted for Planner review. The Planner approves or rejects before the skill becomes assignable |
| **Effectiveness tracking** | Every task verdict (PASS/FAIL) updates counters on assigned skills. Effectiveness = successes / uses |
| **Auto-deprecation** | Agent-tier skills with 5+ uses and < 30% effectiveness are automatically deprecated and excluded from future assignment |
| **Applicability conditions** | Each skill has `when_to_use` and `when_not_to_use` metadata — the Planner sees these when deciding which skills to assign |

This design follows the agentic skills lifecycle from research (Voyager 2023, SoK 2026): discovery → practice → distillation → storage → evaluation → update. The key insight from the literature: **curated skills improve agent success rates by +16pp, while unvalidated self-generated skills can degrade them** — hence the mandatory review gate.

---

## Configuration

Config files use a **default/override pattern** for submodule compatibility:
- `config/*.default.yaml` — tracked by git, ship with sane defaults
- `config/*.yaml` — created by `setup`, gitignored, override the defaults

Baymax tries `<name>.yaml` first, falls back to `<name>.default.yaml`. You only create overrides for what you want to change.

### `config/project.yaml`

```yaml
name: my-project
test_command: pytest
max_retry_per_task: 3

# root_dir — auto-detected by default:
#   `uv run baymax` from project root → uses CWD
#   `cd Baymax && uv run main.py`     → uses parent of Baymax/
# Uncomment to override:
# root_dir: ..            # relative to Baymax/
# root_dir: /abs/path     # absolute

# Role display names — shown in CLI, logs, and SQLite.
# roles:
#   preset: it-company          # loads prompts from prompts/samples/it-company/
#   owner: Chief Architect
#   planner: Architect
#   executor: SWE
```

### `config/nodes.yaml`

Each agent gets its own LLM — mix providers freely:

```yaml
planner:
  model:
    provider: anthropic
    name: claude-sonnet-4-20250514
    temperature: 0.3
  tools: [file_inspect, search, skill_create]

executor:
  model:
    provider: anthropic
    name: claude-sonnet-4-20250514
    temperature: 0
  tools: [shell, file_read, file_write, search, skill_request]
```

### API Keys

Set via `.env` (created by `setup`) or environment variables. Baymax checks the project root first, then `Baymax/.env` as fallback:

```bash
# your-project/.env  (recommended — shared with your project)
ANTHROPIC_API_KEY=sk-ant-...
```

### Prompts

Agent prompts are Markdown files in `Baymax/prompts/`. Edit to change behavior without touching Python:

```
prompts/planner.md      # How the Planner plans, validates, and manages skills
prompts/executor.md     # How the Executor executes and reports
```

Prompts support template variables: `{role_owner}`, `{role_planner}`, `{role_executor}` — replaced with display names from `project.yaml` at load time.

**Presets** — set `roles.preset: it-company` in `project.yaml` to load domain-specific prompts from `prompts/samples/it-company/` (falls back to defaults for missing files).

---

## Project Structure

```
your-project/                # ← project root (run `uv run baymax` here)
├── .venv/                   # ← shared venv (Baymax deps + your deps)
├── pyproject.toml           # ← references Baymax as path dependency
├── .env                     # ← API keys (gitignored)
├── Baymax/                  # ← framework (submodule)
│   ├── doc/
│   │   ├── GOALS.md         # You write this
│   │   ├── DISCUSSION.md    # Generated: Planner–Owner Q&A
│   │   ├── BLUEPRINT.md     # Generated: high-level task breakdown
│   │   ├── FLOWCHART.md     # Generated: architecture diagram (Mermaid)
│   │   ├── EXECUTION.md     # Generated: lightweight summary (full plans in SQLite)
│   │   └── EVOLUTION.md     # Generated: self-evolution plan (evolve mode)
│   ├── config/
│   │   ├── nodes.default.yaml    # Tracked — LLM providers & tools
│   │   ├── project.default.yaml  # Tracked — project settings template
│   │   ├── mcp.default.yaml      # Tracked — MCP template
│   │   ├── nodes.yaml            # Gitignored — your overrides
│   │   ├── project.yaml          # Gitignored — your project config
│   │   └── mcp.yaml              # Gitignored — your MCP connections
│   ├── prompts/
│   │   ├── planner.md
│   │   ├── executor.md
│   │   └── samples/
│   │       └── it-company/    # IT Company preset prompts
│   ├── skills/              # Reusable knowledge artifacts
│   ├── baymax/              # Engine (don't edit)
│   ├── main.py              # Backward-compat shim (prefer `baymax` CLI)
│   └── baymax_history.db    # SQLite audit trail
├── src/
└── ...
```

## MCP Integration

Baymax supports the [Model Context Protocol](https://modelcontextprotocol.io/) as both a **client** and a **server**, plus the ability to **generate** new MCP servers.

### Baymax as MCP Client

Connect agents to external services (Notion, GitHub, Slack, etc.) by configuring `config/mcp.yaml`:

```yaml
servers:
  notion:
    command: npx
    args: ["-y", "@notionhq/notion-mcp-server"]
    env:
      NOTION_TOKEN: ${NOTION_TOKEN}
    agents: [planner]          # only planner can use

  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: ${GITHUB_TOKEN}
    agents: [planner, executor]
```

MCP tools are auto-discovered at startup, converted to LangChain tools, and prefixed (`mcp_notion_search_pages`). The `agents` field controls per-node access — same permission model as built-in tools. Tool output goes through the blacklist scrubber.

Run `baymax setup` for an interactive wizard that configures common MCP servers.

### Baymax as MCP Server

Expose Baymax's store and workflow to external hosts (Claude Desktop, Cursor, etc.):

```bash
baymax serve              # stdio (for Claude Desktop / Cursor)
baymax serve --http 8080  # HTTP (for remote access)
```

**Exposed tools**: `baymax_list_issues`, `baymax_get_tasks`, `baymax_get_ledger`, `baymax_get_skills`, `baymax_query_branch`, `baymax_quick_task`, `baymax_export_report`

**Exposed resources**: `baymax://issues`, `baymax://issues/{id}`, `baymax://skills`, `baymax://blueprint`

Add to Claude Desktop config:
```json
{
  "mcpServers": {
    "baymax": {
      "command": "uv",
      "args": ["run", "baymax", "serve"],
      "cwd": "/path/to/your-project"
    }
  }
}
```

### MCP Server Generator

The Planner can scaffold project-specific MCP servers using the `mcp_generate` tool:

```bash
# Available templates: rest_api, database, file_based
# Generated servers go to mcp_servers/<name>/server.py
# Auto-registered in config/mcp.yaml
```

Templates handle common patterns (REST wrappers, DB connectors, file servers). Generated servers use FastMCP and are immediately usable.

---

## Design Principles

- **File-driven** — Write goals in Markdown, not CLI arguments.
- **Discussion first** — Planner clarifies before planning. No blind execution.
- **Layered documents** — Strategic docs (BLUEPRINT, FLOWCHART) for Owner review; per-task execution plans in SQLite for agent consumption.
- **Per-task execution plans** — Each task gets its own plan in SQLite. Executors load only their current task. EXECUTION.md is a lightweight summary for humans.
- **Full audit trail** — Every action logged to SQLite with lightweight summaries. Full JSON stored but never bulk-read.
- **Skills over re-reading** — Agents compress discovered patterns into reusable skills, loaded on demand instead of re-scanning source files.
- **Config over code** — YAML and Markdown control behavior. Engine is immutable during normal operation.
- **Guarded self-evolution** — Agents can modify Baymax itself, but only with Planner plan + Owner approval + git snapshot + health check.
- **Configurable roles** — Generic by default, customizable to match your team's terminology via config.
- **Sandboxed execution** — Tools restricted to the project root directory.
- **MCP-native** — Connect to any MCP server as a client, expose Baymax as a server, or auto-generate project-specific servers.

## License

MIT License — See [LICENSE](LICENSE)

**Author**: Zax S ([@ZaxShen](https://github.com/ZaxShen))
