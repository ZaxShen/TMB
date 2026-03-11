# TMB — Architecture & Configuration

> Technical reference for contributors, integrators, and power users.
> For basic usage, see [README.md](README.md).

---

## Table of Contents

- [Workflow](#workflow)
- [Roles](#roles)
- [Documents](#documents)
- [Permissions](#permissions)
- [Database](#database)
- [Skills](#skills)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [MCP Integration](#mcp-integration)
- [Self-Evolution](#self-evolution)
- [Design Principles](#design-principles)

---

## Workflow

TMB has three entry points, each following the same plan-execute-validate pipeline.

### Full workflow (`tmb`)

For complex, multi-step work with interactive discussion:

```
Project Owner writes bro/GOALS.md
         |
         v
  +--- DISCUSSION ---+
  |  Planner <->      |    Interactive Q&A via bro/DISCUSSION.md
  |  Project Owner    |    -> saved to SQLite (.tmb/tmb.db)
  +--------+----------+
           v
  +--- PLANNING ------+
  |  Planner writes:  |    BLUEPRINT.md  -- task breakdown
  |  1-2 documents    |    FLOWCHART.md  -- project architecture (when needed)
  +--------+----------+
           v
    Project Owner reviews & approves
           |
           v
  +--- EXECUTION PLAN +
  |  Planner generates |    Per-task plans stored in SQLite
  |  per-task plans    |    EXECUTION.md -- lightweight summary for humans
  +--------+----------+
           v
  +--- EXECUTION ------+
  |  Executor runs     |--->  Planner validates (same agent, full context)
  |  task (shell,      |<---  PASS -> next task
  |  files)            |<---  FAIL -> retry (max 3)
  +--------+----------+<---  MAX FAIL -> escalate to human
           v
         DONE
```

### Quick task (`tmb "..."`)

Same pipeline, no interactive steps. Auto-approved blueprint.

### Self-evolution (`tmb evolve "..."`)

Modifies TMB's own source code through a guarded flow:

1. Warning banner displayed
2. Planner explores TMB codebase, writes `bro/EVOLUTION.md`
3. Owner reviews and approves (press Enter)
4. Git snapshot auto-committed (rollback: `git revert HEAD`)
5. Planner executes the approved plan
6. Health check verifies TMB still imports and passes lint

The `TMB/**` blacklist is only lifted during the evolve session.

---

## Roles

Role names are configurable via `.tmb/config/project.yaml`. Defaults shown, with IT Company preset in parentheses:

| Role | Default | IT Company | Responsibility |
|------|---------|------------|----------------|
| **owner** | Project Owner | Chief Architect | Writes goals. Discusses with Planner. Reviews blueprints. |
| **planner** | Planner | Architect | Discusses requirements. Designs blueprint and flowchart. Writes per-task execution plans. **Validates** each task (has full context). Handles escalations. |
| **executor** | Executor | SWE | Executes tasks using shell, filesystem, and search tools. Reports issues to Planner. |

---

## Documents

All user-facing artifacts live in `bro/` at the project root:

| File | Written By | Read By | Purpose |
|------|-----------|---------|---------|
| `GOALS.md` | Owner (you) | Planner | What you want done — plain language |
| `DISCUSSION.md` | System | Owner, Planner | Planner–Owner Q&A transcript |
| `BLUEPRINT.md` | Planner | Owner | Task breakdown as JSON |
| `FLOWCHART.md` | Planner | Owner | Project architecture overview (Mermaid, max 12 nodes, generated when needed) |
| `EXECUTION.md` | Planner | Owner | Per-task plan summary (full plans in SQLite) |
| `EVOLUTION.md` | Planner | Owner | Self-evolution plan (evolve mode only) |

---

## Permissions

| Resource | Owner | Planner | Executor |
|----------|-------|---------|----------|
| `bro/GOALS.md` | Edit | Read | — |
| `bro/DISCUSSION.md` | Read | Edit | — |
| `bro/BLUEPRINT.md` | Read | Edit | — |
| `bro/FLOWCHART.md` | Read | Edit | — |
| `bro/EXECUTION.md` | Read | Edit | — |
| `.tmb/tmb.db` | Read | Read / Write | Read / Write |
| DB: tasks | — | Write (create) | Read (own task) |
| DB: ledger | Read | Write | Write |
| Project files | — | — | Edit |
| `.env`, secrets | — | — | — |
| `bro/EVOLUTION.md` | Read | Edit | — |
| `TMB/**` (engine) | Edit (manual) | Edit (evolve only) | — |

**Key rules:**
- Executors never see GOALS, DISCUSSION, BLUEPRINT, or FLOWCHART — high-level context could mislead execution.
- Executors get their task's plan from SQLite (not a shared file), keeping their context window focused.
- The Planner validates each task directly — it already holds full project context, so no re-learning is needed.
- Secrets and the TMB engine are inaccessible to all agents during normal operation.

---

## Database

Everything is persisted in `.tmb/tmb.db` (SQLite + JSON):

| Table | Contents |
|-------|----------|
| `issues` | Each run's objective, status, `parent_issue_id` for cross-issue links |
| `discussions` | Full Planner–Owner Q&A exchange |
| `tasks` | Blueprint items with hierarchical `branch_id`, `parent_branch_id`, `title`, `skills_required` |
| `ledger` | Every agent action with a `summary` one-liner — full JSON detail stored but never bulk-read |
| `skills` | Registered skill files — name, description, tags, file path |
| `token_usage` | Per-invocation token counts by node |
| `file_registry` | Persistent map of discovered project files — enables zero-rescan upgrades |

### Branch IDs

Every task has two identifiers:

- `id` — autoincrement primary key (stable, used for internal DB references)
- `branch_id` — hierarchical string encoding semantic relationships

```
id=1  branch_id="1"       <- Email login feature
id=2  branch_id="1.1"     <- Add email verification (extends login)
id=3  branch_id="2"       <- Dashboard redesign (unrelated to login)
id=4  branch_id="1.1.1"   <- Handle expired verification tokens
```

Branch operations: `branch_id LIKE '1.%'` finds every related task across all issues. The Planner auto-generates branch IDs by reviewing the existing task tree before planning.

---

## Skills

Skills are **reusable knowledge artifacts** — concise markdown guides that agents load on demand instead of re-deriving patterns every time.

### Two skill locations

```
TMB/skills/              <- curated seed skills (shipped with framework)
  db-operations.md
  branch-operations.md
  file-access.md
  mcp-patterns.md

.tmb/skills/             <- agent-created skills (project-specific, persisted)
  csv-handling.md
```

### How it works

1. **Planner assigns skills per task** — sees available skills with effectiveness scores and applicability conditions
2. **Executor loads only assigned skills** — injected into context alongside the task prompt
3. **Agents can request new skills** — Executor has a `skill_request` tool; Planner creates and reviews
4. **Built-in skills auto-seed** — on first run, `TMB/skills/*.md` are registered as curated skills
5. **Agent-created skills go to `.tmb/skills/`** — survives TMB upgrades

### Trust and validation

| Aspect | Mechanism |
|---|---|
| **Trust tiers** | `curated` (system/human — always trusted) vs. `agent` (requires review) |
| **Status lifecycle** | `draft` -> `pending_review` -> `active` -> `deprecated` |
| **Quality gate** | Agent-created skills auto-submitted for Planner review |
| **Effectiveness tracking** | Every PASS/FAIL verdict updates counters. Effectiveness = successes / uses |
| **Auto-deprecation** | Agent-tier skills with 5+ uses and < 30% effectiveness are deprecated |
| **Applicability** | Each skill has `when_to_use` and `when_not_to_use` metadata |

Design follows the agentic skills lifecycle from research (Voyager 2023, SoK 2026): curated skills improve agent success rates by +16pp, while unvalidated self-generated skills can degrade them — hence the mandatory review gate.

---

## Configuration

Config files use a **three-layer resolution** for seamless upgrades:

1. `.tmb/config/<name>.yaml` — project-level user overrides (created by `setup`)
2. `TMB/config/<name>.yaml` — legacy overrides inside framework (backward compat)
3. `TMB/config/<name>.default.yaml` — tracked defaults

TMB tries each in order. You only create overrides for what you want to change.

### `.tmb/config/project.yaml`

```yaml
name: my-project
test_command: pytest
max_retry_per_task: 3

# root_dir — auto-detected by default:
#   `uv run tmb` from project root -> uses CWD
#   `cd TMB && uv run main.py`     -> uses parent of TMB/
# Uncomment to override:
# root_dir: ..            # relative to TMB/
# root_dir: /abs/path     # absolute

# Path overrides (defaults shown):
# paths:
#   docs_dir: bro
#   runtime_dir: .tmb
#   db_name: tmb.db

# Role display names:
# roles:
#   preset: it-company
#   owner: Chief Architect
#   planner: Architect
#   executor: SWE
```

### `.tmb/config/nodes.yaml`

Each agent gets its own LLM — mix providers freely:

```yaml
planner:
  model:
    provider: anthropic
    name: claude-sonnet-4-20250514
    temperature: 0.3
    # base_url: https://custom-endpoint.example.com/v1
  tools: [file_inspect, search, web_search, skill_create]

executor:
  model:
    provider: anthropic
    name: claude-sonnet-4-20250514
    temperature: 0
  tools: [shell, file_read, file_write, search, skill_request]
```

### Supported Providers

Anthropic and OpenAI are included by default. Other providers are optional — install only what you need:

| Provider | Config name | Env var | Install command |
|----------|------------|---------|-----------------|
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` | included |
| OpenAI | `openai` | `OPENAI_API_KEY` | included |
| Google Gemini | `google` | `GOOGLE_API_KEY` | `uv add tmb[google]` |
| Groq | `groq` | `GROQ_API_KEY` | `uv add tmb[groq]` |
| Mistral | `mistral` | `MISTRAL_API_KEY` | `uv add tmb[mistral]` |
| DeepSeek | `deepseek` | `DEEPSEEK_API_KEY` | `uv add tmb[deepseek]` |
| Ollama (local) | `ollama` | none | `uv add tmb[ollama]` |
| All providers | -- | -- | `uv add tmb[all]` |

Every provider supports `base_url` for custom endpoints (proxies, self-hosted, Vercel AI Gateway, etc.).

### API Keys

Set via `.env` at the project root (created by `setup`) or environment variables:

```bash
ANTHROPIC_API_KEY=sk-ant-...
# GOOGLE_API_KEY=...
# GROQ_API_KEY=gsk_...
```

### Prompts

Agent prompts are Markdown files in `TMB/prompts/`. Edit to change behavior without touching Python:

```
prompts/planner.md      # How the Planner plans, validates, and manages skills
prompts/executor.md     # How the Executor executes and reports
```

Prompts support template variables: `{role_owner}`, `{role_planner}`, `{role_executor}` — replaced with display names from config at load time.

**Presets** — set `roles.preset: it-company` in `project.yaml` to load domain-specific prompts from `prompts/samples/it-company/`.

---

## Project Structure

```
your-project/                    # <- project root (run `uv run tmb` here)
|-- .venv/                       # <- shared venv (TMB deps + your deps)
|-- pyproject.toml               # <- references TMB as path dependency
|-- .env                         # <- API keys (gitignored)
|
|-- bro/                 # <- user interaction zone
|   |-- GOALS.md                 #    You write this
|   |-- DISCUSSION.md            #    Generated: Planner-Owner Q&A
|   |-- BLUEPRINT.md             #    Generated: task breakdown
|   |-- FLOWCHART.md             #    Generated when needed: project architecture overview
|   |-- EXECUTION.md             #    Generated: per-task plan summary
|   +-- EVOLUTION.md             #    Generated: self-evolution plan
|
|-- .tmb/                     # <- hidden runtime state (gitignored)
|   |-- tmb.db                #    SQLite audit trail
|   |-- config/                  #    User config overrides
|   |   |-- project.yaml
|   |   |-- nodes.yaml
|   |   +-- mcp.yaml
|   +-- skills/                  #    Agent-created skills
|
|-- TMB/                      # <- framework (don't touch)
|   |-- tmb/                  #    Engine code
|   |-- config/                  #    *.default.yaml only (tracked defaults)
|   |-- prompts/                 #    Agent prompts (Markdown)
|   |-- skills/                  #    Curated seed skills only
|   +-- main.py                  #    Backward-compat shim
|
|-- src/
+-- ...
```

### Path Registry

All paths are centralized in `tmb/paths.py`:
- **Framework paths** — immutable, resolved from `__file__`
- **Project defaults** — directory names (`bro`, `.tmb`, `tmb.db`)
- **Config overrides** — users customize via `.tmb/config/project.yaml` -> `paths:`

No hardcoded paths in the engine. Changing a directory name is a one-line config change.

---

## MCP Integration

TMB supports the [Model Context Protocol](https://modelcontextprotocol.io/) as both a **client** and a **server**, plus the ability to **generate** new MCP servers.

### TMB as MCP Client

Connect agents to external services (Notion, GitHub, Slack, etc.) via `.tmb/config/mcp.yaml`:

```yaml
servers:
  notion:
    command: npx
    args: ["-y", "@notionhq/notion-mcp-server"]
    env:
      NOTION_TOKEN: ${NOTION_TOKEN}
    agents: [planner]

  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: ${GITHUB_TOKEN}
    agents: [planner, executor]
```

MCP tools are auto-discovered at startup, converted to LangChain tools, and prefixed (`mcp_notion_search_pages`). The `agents` field controls per-node access. Tool output goes through the blacklist scrubber.

### TMB as MCP Server

Expose TMB's store and workflow to external hosts (Claude Desktop, Cursor):

```bash
tmb serve              # stdio (for Claude Desktop / Cursor)
tmb serve --http 8080  # HTTP (for remote access)
```

**Exposed tools**: `tmb_list_issues`, `tmb_get_tasks`, `tmb_get_ledger`, `tmb_get_skills`, `tmb_query_branch`, `tmb_quick_task`, `tmb_export_report`

**Exposed resources**: `tmb://issues`, `tmb://issues/{id}`, `tmb://skills`, `tmb://blueprint`

Claude Desktop config:
```json
{
  "mcpServers": {
    "tmb": {
      "command": "uv",
      "args": ["run", "tmb", "serve"],
      "cwd": "/path/to/your-project"
    }
  }
}
```

### MCP Server Generator

The Planner can scaffold project-specific MCP servers using the `mcp_generate` tool. Templates: `rest_api`, `database`, `file_based`. Generated servers go to `.tmb/mcp_servers/<name>/server.py` and are auto-registered.

---

## Self-Evolution

TMB can modify its own source code through a guarded flow:

```bash
uv run tmb evolve "add a new CLI command to export tasks as CSV"
```

Safety gates:

1. **Warning banner** — prominent warning about full TMB access
2. **Plan first** — Planner explores TMB codebase, writes `bro/EVOLUTION.md`
3. **Double approval** — Planner designs + Owner reviews
4. **Git snapshot** — auto-commit before changes (`git revert HEAD` to rollback)
5. **Health check** — import test + lint after changes

---

## Design Principles

- **File-driven** — Write goals in Markdown, not CLI arguments.
- **Discussion first** — Planner clarifies before planning. No blind execution.
- **Layered documents** — Strategic docs for Owner review; per-task plans in SQLite for agents.
- **Full audit trail** — Every action logged with lightweight summaries.
- **Skills over re-reading** — Agents compress patterns into reusable skills, loaded on demand.
- **Config over code** — YAML and Markdown control behavior. Engine is immutable.
- **Guarded self-evolution** — Double approval + git snapshot + health check.
- **Configurable roles** — Generic by default, customizable via config.
- **Sandboxed execution** — Tools restricted to the project root directory.
- **MCP-native** — Client, server, and auto-generated MCP servers.
- **Zero-rescan upgrades** — `file_registry` table persists project file knowledge across TMB versions.
