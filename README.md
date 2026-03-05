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

---

## How It Works

### The Workflow

AIDE has two entry points:

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
| `AIDE/**` (engine) | Edit (manual) | — | — | — |

**Key rules:**
- SWEs never see GOALS.md, DISCUSSION.md, BLUEPRINT.md, or FLOWCHART.md — high-level context could mislead execution.
- SWEs read EXECUTION.md for detailed task steps, and get their task assignment from the DB.
- QA reads QA_PLAN.md for testing requirements but never sees high-level planning docs.
- Both SWE and QA can report implementation-vs-design discrepancies to the Architect.
- Secrets and the AIDE engine itself are inaccessible to all agents.

### The Database

Everything is persisted in `aide_history.db` (SQLite + JSON):

| Table | What's In It |
|-------|-------------|
| `issues` | Each run's objective, status, `parent_issue_id` for cross-issue links |
| `discussions` | Full Architect–Chief Architect Q&A exchange |
| `tasks` | Blueprint items with hierarchical `task_id`, `parent_task_id`, lightweight `title` |
| `ledger` | Every agent action with a `summary` one-liner — full JSON detail stored but never bulk-read |

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
uv run main.py log           # List recent issues
uv run main.py log 1         # Full detail for issue #1
uv run main.py report 1      # Export full markdown report
uv run main.py "fix X"       # Quick task (Architect only)
```

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
  tools: [shell, file_read, file_write, search]

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
│   │   └── QA_PLAN.md       # Generated: testing framework
│   ├── config/
│   │   ├── nodes.yaml
│   │   └── project.yaml
│   ├── prompts/
│   │   ├── architect.md
│   │   ├── executor.md
│   │   └── validator.md
│   ├── aide/                # Engine (don't edit)
│   ├── main.py
│   ├── aide_history.db      # SQLite audit trail
│   └── .env
├── src/
└── ...
```

## Design Principles

- **File-driven** — Write goals in Markdown, not CLI arguments.
- **Discussion first** — Architect clarifies before planning. No blind execution.
- **Layered documents** — Strategic docs (BLUEPRINT, FLOWCHART) for Chief Architect review; operational docs (EXECUTION, QA_PLAN) for agent consumption.
- **Living execution plan** — EXECUTION.md shrinks as tasks complete; completed work archived in SQLite.
- **Full audit trail** — Every action logged to SQLite with lightweight summaries. Full JSON stored but never bulk-read.
- **Config over code** — YAML and Markdown control behavior. Engine is immutable.
- **Sandboxed execution** — Tools restricted to the project root directory.

## License

MIT License — See [LICENSE](LICENSE)

**Author**: Zax S ([@ZaxShen](https://github.com/ZaxShen))
