# AIDE: AI Direction & Execution

> A multi-agent framework for building and maintaining **industrial-grade** software projects with LLMs.

## Why AIDE?

Most AI coding tools treat every session as a blank slate. They dump your entire codebase into a context window, generate code, and forget everything by the next run. That works for prototypes — it breaks down for real projects.

**The problem with current AI agents:**
- **No memory** — fix a bug today, the agent has no idea it existed tomorrow
- **No scoping** — a one-line config change triggers the same "read everything" process as a full rewrite
- **No verification** — code is generated but rarely validated against real criteria
- **No audit trail** — three months later, nobody knows *why* a change was made

**AIDE is different.** It models how a real engineering team works:

- A **Project Owner** (you) defines goals in plain language
- A **Planner** (LLM) discusses requirements, explores the codebase with tools, and produces a reviewable plan — before any code is written
- An **Executor** (LLM) executes atomic, scoped tasks — one module at a time, with detailed instructions
- A **Validator** (LLM) validates each task against defined criteria, with retries and escalation
- Everything is **logged to SQLite** — discussions, decisions, task results, verdicts. Run `uv run main.py report 12` six months later and see exactly what happened
- The system **resumes from any interrupt** — Ctrl+C, crash, "I'll continue tomorrow." No wasted LLM calls, no repeated work
- **Information firewalls** keep each agent focused — Executors see only their task and execution plan, not the full strategic context. This isn't security; it's attention management for LLMs

> **Configurable roles** — by default AIDE uses generic names (Project Owner, Planner, Executor, Validator). Run `uv run main.py setup` to pick a preset like **IT Company** (Chief Architect → Architect → SWE → QA Engineer) or define your own names. Role names flow into CLI output, SQLite logs, and agent prompts.

The result: maintainable, auditable software — not disposable demos.

---

## Quick Start

**Prerequisites**: [uv](https://docs.astral.sh/uv/) and an LLM API key (Anthropic or OpenAI).

### Option A: Git Submodule (recommended)

Keeps AIDE as a versioned dependency — update with `git submodule update --remote`.

```bash
# 1. Add AIDE as a submodule
cd your-project/
git submodule add https://github.com/ZaxShen/AIDE.git

# 2. Tell git to ignore AIDE's runtime files (one-time)
git config submodule.AIDE.ignore dirty

# 3. Setup
cd AIDE
uv sync
uv run main.py setup    # creates your local config (gitignored)

# 4. Write your goals, then run
#    Edit doc/GOALS.md with what you want done
uv run main.py
```

To update AIDE later: `cd AIDE && git pull origin main`

**Cloning a project that already has AIDE as a submodule:**

```bash
git clone --recurse-submodules <your-project-url>
cd your-project/AIDE
uv sync
uv run main.py setup
```

### Option B: Clone

If you don't need version tracking:

```bash
cd your-project/
git clone https://github.com/ZaxShen/AIDE.git
cd AIDE
uv sync
uv run main.py setup
uv run main.py
```

**How it stays clean** — AIDE ships tracked defaults (`config/*.default.yaml`). Running `setup` creates your local configs (`config/project.yaml`, etc.) which are gitignored. All runtime files (`doc/`, `aide_history.db`, `.env`) are also gitignored. The submodule never appears dirty in your parent repo.

That's it. AIDE reads your goals, the Planner discusses them with you, builds a blueprint, and the Executor carries it out — all logged to SQLite.

### Quick Tasks

For simple changes that don't need the full pipeline:

```bash
uv run main.py "update our FLOWCHART based on current codebase"
uv run main.py "refresh QA_PLAN.md to cover the new auth module"
```

The Planner handles these directly — reads the codebase, makes the changes, done. No discussion, no downstream agents. Still logged to SQLite.

### Self-Evolution

AIDE can modify its own source code through a guarded self-evolution mode:

```bash
uv run main.py evolve "add a new CLI command to export tasks as CSV"
uv run main.py evolve "update README.md to reflect the new auth module"
```

**Safety gates** — every evolution goes through:

1. **Warning banner** — you'll see a prominent warning that agents will have full AIDE access
2. **Planner plans first** — explores AIDE's own codebase, writes `doc/EVOLUTION.md` with proposed changes and risk assessment
3. **Double approval** — the Planner designs the plan (its approval), then you review and press Enter (your approval)
4. **Automatic git snapshot** — AIDE commits its current state before any file is touched, so `git revert HEAD` always works
5. **Health check** — after changes, AIDE verifies it can still import and passes lint

If the health check fails, you get the exact rollback command. The `AIDE/**` blacklist is only lifted during the evolve session — normal workflow remains locked down.

---

## How It Works

### The Workflow

AIDE has three entry points:

**Full workflow** (`uv run main.py`) — for complex, multi-step work:

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
  │  3 documents      │    FLOWCHART.md  — architecture diagram
  │                   │    QA_PLAN.md    — testing framework
  └────────┬──────────┘
           ▼
    Project Owner reviews & approves
           │
           ▼
  ┌─── EXECUTION PLAN ┐
  │  Planner writes   │    EXECUTION.md — detailed steps per task
  │  detailed plan    │    Read by Executor, pruned on completion
  └────────┬──────────┘
           ▼
  ┌─── EXECUTION ──────┐
  │  Executor runs     │──→  Validator checks (against QA_PLAN.md)
  │  task (shell,      │←──  PASS → archive task, next
  │  files)            │←──  FAIL → retry (max 3)
  └────────┬──────────┘←──  MAX FAIL → Planner replans
           ▼
         DONE
```

**Quick task** (`uv run main.py "..."`) — for simple, self-contained changes:

```
Project Owner passes instruction via CLI
         │
         ▼
  ┌─── GATEKEEPER ───┐
  │  Scan project     │
  └────────┬─────────┘
           ▼
  ┌─── PLANNER ──────┐
  │  Read codebase   │    Uses file_read, search, file_write
  │  Make changes    │    No discussion, no blueprint, no downstream agents
  │  Log result      │
  └────────┬─────────┘
           ▼
         DONE
```

**Self-evolution** (`uv run main.py evolve "..."`) — for modifying AIDE itself:

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
  │  Scan AIDE/      │    (not the parent project)
  └────────┬─────────┘
           ▼
  ┌─── PLANNER ──────┐
  │  Explore AIDE    │    Full read access to AIDE/**
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
  │  Execute plan    │    Full read/write to AIDE/**
  │  Modify source   │
  └────────┬─────────┘
           ▼
  ┌─── HEALTH CHECK ─┐
  │  Import test     │    Verify AIDE still works
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
| **planner** | Planner | Architect | Discusses requirements. Designs blueprint, flowchart, QA plan. Writes execution plan. Handles escalations. |
| **executor** | Executor | SWE | Executes tasks using shell, filesystem, and search tools. Reports issues to Planner. |
| **validator** | Validator | QA Engineer | Verifies each task against QA plan and success criteria. Reports discrepancies to Planner. |

### The Documents

All artifacts live in `AIDE/doc/`:

| File | Written By | Read By | Purpose |
|------|-----------|---------|---------|
| `GOALS.md` | Owner (you) | Planner | What you want done — plain language |
| `DISCUSSION.md` | System | Owner, Planner | Planner–Owner Q&A transcript |
| `BLUEPRINT.md` | Planner | Owner | High-level system design and task breakdown |
| `FLOWCHART.md` | Planner | Owner | Architecture/data-flow diagram (Mermaid) |
| `EXECUTION.md` | Planner | Executor | Detailed execution plan — tasks removed on completion |
| `QA_PLAN.md` | Planner | Validator | Testing framework — risk areas, test types, edge cases |
| `EVOLUTION.md` | Planner | Owner | Self-evolution plan (only during `evolve` mode) |

### Permissions

| Resource | Owner | Planner | Executor | Validator |
|----------|-------|---------|----------|-----------|
| `doc/GOALS.md` | Edit | Read | — | — |
| `doc/DISCUSSION.md` | Read | Edit | — | — |
| `doc/BLUEPRINT.md` | Read | Edit | — | — |
| `doc/FLOWCHART.md` | Read | Edit | — | — |
| `doc/EXECUTION.md` | Read | Edit | Read | — |
| `doc/QA_PLAN.md` | Read | Edit | — | Read |
| `aide_history.db` | Read | Read / Write | Read / Write | Read / Write |
| DB: tasks | — | Write (create) | Read (own task) | Read (current task) |
| DB: ledger | Read | Write | Write | Write |
| Project files | — | — | Edit | Read |
| `.env`, secrets | — | — | — | — |
| `doc/EVOLUTION.md` | Read | Edit | — | — |
| `AIDE/**` (engine) | Edit (manual) | Edit (evolve mode only) | — | — |

**Key rules:**
- Executors never see GOALS.md, DISCUSSION.md, BLUEPRINT.md, or FLOWCHART.md — high-level context could mislead execution.
- Executors read EXECUTION.md for detailed task steps, and get their task assignment from the DB.
- Validators read QA_PLAN.md for testing requirements but never see high-level planning docs.
- Both Executors and Validators can report implementation-vs-design discrepancies to the Planner.
- Secrets and the AIDE engine itself are inaccessible to all agents during normal operation.
- In **evolve mode** (`uv run main.py evolve "..."`), the Planner gets temporary full access to AIDE source — gated by double approval and automatic git snapshot.

### The Database

Everything is persisted in `aide_history.db` (SQLite + JSON):

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

**Branch operations** — when you need to replace email login with phone login, `branch_id LIKE '1.%'` finds every related task across all issues. Task id=3 (dashboard) is untouched even though it was created between id=2 and id=4. Git can't do this because reverts are sequential — AIDE's branch IDs are semantic.

The Planner auto-generates branch IDs by reviewing the existing task tree before planning.

```bash
uv run main.py log               # List recent issues
uv run main.py log 1             # Full detail for issue #1
uv run main.py report 1          # Export full markdown report
uv run main.py "fix X"           # Quick task (Planner only)
uv run main.py evolve "fix Y"    # Self-evolution (modify AIDE itself)
```

### Skills

Skills are **reusable knowledge artifacts** — concise markdown guides that agents load on demand instead of re-deriving patterns or reading large source files every time.

```
AIDE/skills/
├── db-operations.md        # Store API: lightweight vs. full queries
├── branch-operations.md    # Hierarchical branch ID patterns
└── file-access.md          # Permission model rules
```

**How it works:**

1. **Planner assigns skills per task** — sees available skills with effectiveness scores and applicability conditions, assigns relevant ones to `skills_required`
2. **Executor and Validator load only assigned skills** — skill content is injected into context alongside the task prompt. No irrelevant knowledge, no wasted tokens
3. **Agents can create new skills** — Executor has a `skill_create` tool. New skills start as `draft` and must pass Planner review before becoming available
4. **Built-in skills auto-seed** — on first run, AIDE registers all `.md` files in `skills/` as curated, trusted skills

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

AIDE tries `<name>.yaml` first, falls back to `<name>.default.yaml`. You only create overrides for what you want to change.

### `config/project.yaml`

```yaml
name: my-project
root_dir: ..                  # Your project root, relative to AIDE/
test_command: pytest
max_retry_per_task: 3

# Role display names — shown in CLI, logs, and SQLite.
# roles:
#   preset: it-company          # loads prompts from prompts/samples/it-company/
#   owner: Chief Architect
#   planner: Architect
#   executor: SWE
#   validator: QA Engineer
```

### `config/nodes.yaml`

Each agent gets its own LLM — mix providers freely:

```yaml
planner:
  model:
    provider: anthropic
    name: claude-sonnet-4-20250514
    temperature: 0.3
  tools: [file_read, search]

executor:
  model:
    provider: anthropic
    name: claude-sonnet-4-20250514
    temperature: 0
  tools: [shell, file_read, file_write, search, skill_create]

validator:
  model:
    provider: anthropic
    name: claude-sonnet-4-20250514
    temperature: 0
  tools: [shell]
```

### API Keys

Set via `.env` (created by `setup`) or environment variables:

```bash
# AIDE/.env
ANTHROPIC_API_KEY=sk-ant-...
```

### Prompts

Agent prompts are Markdown files in `AIDE/prompts/`. Edit to change behavior without touching Python:

```
prompts/planner.md      # How the Planner thinks and plans
prompts/executor.md     # How the Executor executes and reports
prompts/validator.md    # How the Validator evaluates pass/fail
```

Prompts support template variables: `{role_owner}`, `{role_planner}`, `{role_executor}`, `{role_validator}` — replaced with display names from `project.yaml` at load time.

**Presets** — set `roles.preset: it-company` in `project.yaml` to load domain-specific prompts from `prompts/samples/it-company/` (falls back to defaults for missing files).

---

## Project Structure

```
your-project/                # ← AIDE operates on this
├── AIDE/                    # ← Framework lives here
│   ├── doc/
│   │   ├── GOALS.md         # You write this
│   │   ├── DISCUSSION.md    # Generated: Planner–Owner Q&A
│   │   ├── BLUEPRINT.md     # Generated: high-level task breakdown
│   │   ├── FLOWCHART.md     # Generated: architecture diagram (Mermaid)
│   │   ├── EXECUTION.md     # Generated: detailed plan (pruned on completion)
│   │   ├── QA_PLAN.md       # Generated: testing framework
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
│   │   ├── validator.md
│   │   └── samples/
│   │       └── it-company/    # IT Company preset prompts
│   ├── skills/              # Reusable knowledge artifacts
│   │   ├── db-operations.md
│   │   ├── branch-operations.md
│   │   ├── file-access.md
│   │   └── mcp-patterns.md
│   ├── mcp_servers/         # Generated MCP servers (auto-scaffold)
│   ├── aide/                # Engine (don't edit)
│   ├── main.py
│   ├── aide_history.db      # SQLite audit trail
│   └── .env
├── src/
└── ...
```

## MCP Integration

AIDE supports the [Model Context Protocol](https://modelcontextprotocol.io/) as both a **client** and a **server**, plus the ability to **generate** new MCP servers.

### AIDE as MCP Client

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

Run `uv run main.py setup` for an interactive wizard that configures common MCP servers.

### AIDE as MCP Server

Expose AIDE's store and workflow to external hosts (Claude Desktop, Cursor, etc.):

```bash
uv run main.py serve              # stdio (for Claude Desktop / Cursor)
uv run main.py serve --http 8080  # HTTP (for remote access)
```

**Exposed tools**: `aide_list_issues`, `aide_get_tasks`, `aide_get_ledger`, `aide_get_skills`, `aide_query_branch`, `aide_quick_task`, `aide_export_report`

**Exposed resources**: `aide://issues`, `aide://issues/{id}`, `aide://skills`, `aide://blueprint`

Add to Claude Desktop config:
```json
{
  "mcpServers": {
    "aide": {
      "command": "uv",
      "args": ["run", "main.py", "serve"],
      "cwd": "/path/to/project/AIDE"
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
- **Layered documents** — Strategic docs (BLUEPRINT, FLOWCHART) for Owner review; operational docs (EXECUTION, QA_PLAN) for agent consumption.
- **Living execution plan** — EXECUTION.md shrinks as tasks complete; completed work archived in SQLite.
- **Full audit trail** — Every action logged to SQLite with lightweight summaries. Full JSON stored but never bulk-read.
- **Skills over re-reading** — Agents compress discovered patterns into reusable skills, loaded on demand instead of re-scanning source files.
- **Config over code** — YAML and Markdown control behavior. Engine is immutable during normal operation.
- **Guarded self-evolution** — Agents can modify AIDE itself, but only with Planner plan + Owner approval + git snapshot + health check.
- **Configurable roles** — Generic by default, customizable to match your team's terminology via config.
- **Sandboxed execution** — Tools restricted to the project root directory.
- **MCP-native** — Connect to any MCP server as a client, expose AIDE as a server, or auto-generate project-specific servers.

## License

MIT License — See [LICENSE](LICENSE)

**Author**: Zax S ([@ZaxShen](https://github.com/ZaxShen))
