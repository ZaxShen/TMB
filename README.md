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

- A **Chief Architect** (you) defines goals in plain language
- An **Architect** (LLM) discusses requirements, explores the codebase with tools, and produces a reviewable plan — before any code is written
- **SWEs** (LLMs) execute atomic, scoped tasks — one module at a time, with detailed instructions
- **QA** (LLM) validates each task against defined criteria, with retries and escalation
- Everything is **logged to SQLite** — discussions, decisions, task results, verdicts. Run `uv run main.py report 12` six months later and see exactly what happened
- The system **resumes from any interrupt** — Ctrl+C, crash, "I'll continue tomorrow." No wasted LLM calls, no repeated work
- **Information firewalls** keep each agent focused — SWEs see only their task and execution plan, not the full strategic context. This isn't security; it's attention management for LLMs

The result: maintainable, auditable software — not disposable demos.

---

## Quick Start

**Prerequisites**: [uv](https://docs.astral.sh/uv/) and an LLM API key (Anthropic or OpenAI).

```bash
# 1. Add AIDE to your project
cd your-project/
git clone https://github.com/ZaxShen/AIDE.git

# 2. Setup
cd AIDE
uv sync
uv run main.py setup

# 3. Write your goals
#    Edit doc/GOALS.md with what you want done

# 4. Run
uv run main.py
```

That's it. AIDE reads your goals, the Architect discusses them with you, builds a blueprint, and the SWEs execute it — all logged to SQLite.

### Quick Tasks

For simple changes that don't need the full pipeline:

```bash
uv run main.py "update our FLOWCHART based on current codebase"
uv run main.py "refresh QA_PLAN.md to cover the new auth module"
```

The Architect handles these directly — reads the codebase, makes the changes, done. No discussion, no SWE, no QA. Still logged to SQLite.

### Self-Evolution

AIDE can modify its own source code through a guarded self-evolution mode:

```bash
uv run main.py evolve "add a new CLI command to export tasks as CSV"
uv run main.py evolve "update README.md to reflect the new auth module"
```

**Safety gates** — every evolution goes through:

1. **Warning banner** — you'll see a prominent warning that agents will have full AIDE access
2. **Architect plans first** — explores AIDE's own codebase, writes `doc/EVOLUTION.md` with proposed changes and risk assessment
3. **Double approval** — the Architect designs the plan (its approval), then you review and press Enter (your approval)
4. **Automatic git snapshot** — AIDE commits its current state before any file is touched, so `git revert HEAD` always works
5. **Health check** — after changes, AIDE verifies it can still import and passes lint

If the health check fails, you get the exact rollback command. The `AIDE/**` blacklist is only lifted during the evolve session — normal workflow remains locked down.

---

## How It Works

### The Workflow

AIDE has three entry points:

**Full workflow** (`uv run main.py`) — for complex, multi-step work:

```
Chief Architect writes doc/GOALS.md
         │
         ▼
  ┌─── DISCUSSION ───┐
  │  Architect ↔      │    Interactive Q&A via doc/DISCUSSION.md
  │  Chief Architect  │    → saved to SQLite
  └────────┬──────────┘
           ▼
  ┌─── PLANNING ──────┐
  │  Architect writes: │    BLUEPRINT.md  — task breakdown
  │  3 documents       │    FLOWCHART.md  — architecture diagram
  │                    │    QA_PLAN.md    — testing framework
  └────────┬──────────┘
           ▼
    Chief Architect reviews & approves
           │
           ▼
  ┌─── EXECUTION PLAN ┐
  │  Architect writes  │    EXECUTION.md — detailed steps per task
  │  detailed plan     │    Read by SWE, pruned on completion
  └────────┬──────────┘
           ▼
  ┌─── EXECUTION ──────┐
  │  SWE runs task     │──→  QA validates (against QA_PLAN.md)
  │  (shell, files)    │←──  PASS → archive task, next
  │                    │←──  FAIL → retry (max 3)
  └────────┬──────────┘←──  MAX FAIL → Architect replans
           ▼
         DONE
```

**Quick task** (`uv run main.py "..."`) — for simple, self-contained changes:

```
Chief Architect passes instruction via CLI
         │
         ▼
  ┌─── GATEKEEPER ───┐
  │  Scan project     │
  └────────┬─────────┘
           ▼
  ┌─── ARCHITECT ────┐
  │  Read codebase   │    Uses file_read, search, file_write
  │  Make changes    │    No discussion, no blueprint, no SWE/QA
  │  Log result      │
  └────────┬─────────┘
           ▼
         DONE
```

**Self-evolution** (`uv run main.py evolve "..."`) — for modifying AIDE itself:

```
Chief Architect passes instruction via CLI
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
  ┌─── ARCHITECT ────┐
  │  Explore AIDE    │    Full read access to AIDE/**
  │  source code     │    Writes doc/EVOLUTION.md
  │  Generate plan   │
  └────────┬─────────┘
           ▼
    Chief Architect reviews & approves
           │
           ▼
  ┌─── GIT SNAPSHOT ─┐
  │  Auto-commit     │    Safety rollback point
  │  current state   │
  └────────┬─────────┘
           ▼
  ┌─── ARCHITECT ────┐
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

| Role | Who | Responsibility |
|------|-----|-----------|
| **Chief Architect** | You | Writes goals. Discusses with Architect. Reviews blueprints. |
| **Architect** | LLM Agent | Discusses requirements. Designs blueprint, flowchart, QA plan. Writes execution plan. Handles escalations. |
| **SWE** | LLM Agent | Executes tasks using shell, filesystem, and search tools. Reports issues to Architect. |
| **QA** | LLM Agent | Verifies each task against QA plan and success criteria. Reports discrepancies to Architect. |

### The Documents

All artifacts live in `AIDE/doc/`:

| File | Written By | Read By | Purpose |
|------|-----------|---------|---------|
| `GOALS.md` | Chief Architect (you) | Architect | What you want done — plain language |
| `DISCUSSION.md` | System | Chief Architect, Architect | Architect–Chief Architect Q&A transcript |
| `BLUEPRINT.md` | Architect | Chief Architect | High-level system design and task breakdown |
| `FLOWCHART.md` | Architect | Chief Architect | Architecture/data-flow diagram (Mermaid) |
| `EXECUTION.md` | Architect | SWE | Detailed execution plan — tasks removed on completion |
| `QA_PLAN.md` | Architect | QA | Testing framework — risk areas, test types, edge cases |
| `EVOLUTION.md` | Architect | Chief Architect | Self-evolution plan (only during `evolve` mode) |

### Permissions

| Resource | Chief Architect | Architect | SWE (Executor) | QA (Validator) |
|----------|----------------|-----------|----------------|----------------|
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
- SWEs never see GOALS.md, DISCUSSION.md, BLUEPRINT.md, or FLOWCHART.md — high-level context could mislead execution.
- SWEs read EXECUTION.md for detailed task steps, and get their task assignment from the DB.
- QA reads QA_PLAN.md for testing requirements but never sees high-level planning docs.
- Both SWE and QA can report implementation-vs-design discrepancies to the Architect.
- Secrets and the AIDE engine itself are inaccessible to all agents during normal operation.
- In **evolve mode** (`uv run main.py evolve "..."`), the Architect gets temporary full access to AIDE source — gated by double approval and automatic git snapshot.

### The Database

Everything is persisted in `aide_history.db` (SQLite + JSON):

| Table | What's In It |
|-------|-------------|
| `issues` | Each run's objective, status, `parent_issue_id` for cross-issue links |
| `discussions` | Full Architect–Chief Architect Q&A exchange |
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

The Architect auto-generates branch IDs by reviewing the existing task tree before planning.

```bash
uv run main.py log               # List recent issues
uv run main.py log 1             # Full detail for issue #1
uv run main.py report 1          # Export full markdown report
uv run main.py "fix X"           # Quick task (Architect only)
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

1. **Architect assigns skills per task** — sees available skills with effectiveness scores and applicability conditions, assigns relevant ones to `skills_required`
2. **SWE and QA load only assigned skills** — skill content is injected into context alongside the task prompt. No irrelevant knowledge, no wasted tokens
3. **Agents can create new skills** — SWE has a `skill_create` tool. New skills start as `draft` and must pass Architect review before becoming available
4. **Built-in skills auto-seed** — on first run, AIDE registers all `.md` files in `skills/` as curated, trusted skills

**Validation and trust:**

| Aspect | Mechanism |
|---|---|
| **Trust tiers** | `curated` (system/human — always trusted) vs. `agent` (created during execution — requires review) |
| **Status lifecycle** | `draft` → `pending_review` → `active` → `deprecated` |
| **Quality gate** | Agent-created skills are auto-submitted for Architect review. The Architect approves or rejects before the skill becomes assignable |
| **Effectiveness tracking** | Every task verdict (PASS/FAIL) updates counters on assigned skills. Effectiveness = successes / uses |
| **Auto-deprecation** | Agent-tier skills with 5+ uses and < 30% effectiveness are automatically deprecated and excluded from future assignment |
| **Applicability conditions** | Each skill has `when_to_use` and `when_not_to_use` metadata — the Architect sees these when deciding which skills to assign |

This design follows the agentic skills lifecycle from research (Voyager 2023, SoK 2026): discovery → practice → distillation → storage → evaluation → update. The key insight from the literature: **curated skills improve agent success rates by +16pp, while unvalidated self-generated skills can degrade them** — hence the mandatory review gate.

---

## Configuration

### `config/project.yaml`

```yaml
name: my-project
root_dir: ..                  # Your project root, relative to AIDE/
test_command: pytest
max_retry_per_task: 3
```

### `config/nodes.yaml`

Each agent gets its own LLM — mix providers freely:

```yaml
architect:
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
prompts/architect.md    # How the Architect thinks and plans
prompts/executor.md     # How the SWE executes and reports
prompts/validator.md    # How QA evaluates pass/fail
```

---

## Project Structure

```
your-project/                # ← AIDE operates on this
├── AIDE/                    # ← Framework lives here
│   ├── doc/
│   │   ├── GOALS.md         # You write this
│   │   ├── DISCUSSION.md    # Generated: Architect–Chief Architect Q&A
│   │   ├── BLUEPRINT.md     # Generated: high-level task breakdown
│   │   ├── FLOWCHART.md     # Generated: architecture diagram (Mermaid)
│   │   ├── EXECUTION.md     # Generated: detailed plan (pruned on completion)
│   │   ├── QA_PLAN.md       # Generated: testing framework
│   │   └── EVOLUTION.md     # Generated: self-evolution plan (evolve mode)
│   ├── config/
│   │   ├── nodes.yaml
│   │   ├── project.yaml
│   │   └── mcp.yaml           # MCP server connections
│   ├── prompts/
│   │   ├── architect.md
│   │   ├── executor.md
│   │   └── validator.md
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
    agents: [architect]          # only architect can use

  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: ${GITHUB_TOKEN}
    agents: [architect, executor]
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

The Architect can scaffold project-specific MCP servers using the `mcp_generate` tool:

```bash
# Available templates: rest_api, database, file_based
# Generated servers go to mcp_servers/<name>/server.py
# Auto-registered in config/mcp.yaml
```

Templates handle common patterns (REST wrappers, DB connectors, file servers). Generated servers use FastMCP and are immediately usable.

---

## Design Principles

- **File-driven** — Write goals in Markdown, not CLI arguments.
- **Discussion first** — Architect clarifies before planning. No blind execution.
- **Layered documents** — Strategic docs (BLUEPRINT, FLOWCHART) for Chief Architect review; operational docs (EXECUTION, QA_PLAN) for agent consumption.
- **Living execution plan** — EXECUTION.md shrinks as tasks complete; completed work archived in SQLite.
- **Full audit trail** — Every action logged to SQLite with lightweight summaries. Full JSON stored but never bulk-read.
- **Skills over re-reading** — Agents compress discovered patterns into reusable skills, loaded on demand instead of re-scanning source files.
- **Config over code** — YAML and Markdown control behavior. Engine is immutable during normal operation.
- **Guarded self-evolution** — Agents can modify AIDE itself, but only with Architect plan + Chief Architect approval + git snapshot + health check.
- **Sandboxed execution** — Tools restricted to the project root directory.
- **MCP-native** — Connect to any MCP server as a client, expose AIDE as a server, or auto-generate project-specific servers.

## License

MIT License — See [LICENSE](LICENSE)

**Author**: Zax S ([@ZaxShen](https://github.com/ZaxShen))
