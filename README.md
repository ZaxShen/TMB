# AIDE: AI Direction & Execution

> A multi-agent workflow engine that simulates how an IT company ships software — CTO sets direction, Architect designs, SWEs execute, QA validates.

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

---

## How It Works

### The Workflow

```
  CTO writes doc/GOALS.md
           │
           ▼
  ┌─── DISCUSSION ───┐
  │  Architect ↔ CTO  │    Interactive Q&A in terminal
  │  (clarify goals)  │    → saved to doc/DISCUSSION.md + SQLite
  └────────┬──────────┘
           ▼
  ┌─── BLUEPRINT ────┐
  │  Architect plans  │    Atomic tasks with success criteria
  │  tasks            │    → saved to doc/BLUEPRINT.md + SQLite
  └────────┬──────────┘
           ▼
    CTO reviews & approves
           │
           ▼
  ┌─── EXECUTION ────┐
  │  SWE runs task    │──→  QA validates
  │  (shell, files)   │←──  PASS → next task
  │                   │←──  FAIL → retry (max 3)
  └────────┬──────────┘←──  MAX FAIL → Architect replans
           ▼
         DONE
```

### The Roles

| Role | Who | Does What |
|------|-----|-----------|
| **CTO** | You | Writes goals. Discusses with Architect. Reviews blueprints. |
| **Architect** | LLM Agent | Discusses requirements. Designs the blueprint. Handles escalations. |
| **SWE** | LLM Agent | Executes tasks using shell, filesystem, and search tools. |
| **QA** | LLM Agent | Verifies each task against success criteria. Pass or fail. |

### The Documents

All artifacts live in `AIDE/doc/`:

| File | Written By | Purpose |
|------|-----------|---------|
| `doc/GOALS.md` | CTO (you) | What you want done — plain language |
| `doc/DISCUSSION.md` | System | Architect-CTO Q&A transcript (current only; history in DB) |
| `doc/BLUEPRINT.md` | System | Task breakdown with success criteria |

### Permissions

| Resource | CTO | Architect | SWE (Executor) | QA (Validator) |
|----------|-----|-----------|----------------|----------------|
| `doc/GOALS.md` | Edit | Read | — | — |
| `doc/DISCUSSION.md` | Read | Edit | — | — |
| `doc/BLUEPRINT.md` | Read | Edit | — | — |
| `aide_history.db` | Read | Read / Write | Read / Write | Read / Write |
| DB: tasks | — | Write (create) | Read (own task only) | Read (current task) |
| DB: ledger | Read | Write | Write | Write |
| Project files | — | — | Edit | Read |
| `.env`, secrets | — | — | — | — |
| `AIDE/**` (engine, config, prompts) | Edit (manual) | — | — | — |

**Key rules:**
- SWEs never see GOALS.md or DISCUSSION.md — high-level context could mislead execution.
- SWEs get only their assigned task (description + success criteria) from the DB.
- Secrets and the AIDE engine itself are inaccessible to all agents.
- Project files are the SWE's workspace; QA can read but not modify.

### The Database

Everything is also persisted in `aide_history.db` (SQLite + JSON):

| Table | What's In It |
|-------|-------------|
| `issues` | Each run's objective, status, timestamps |
| `discussions` | Full Architect-CTO Q&A exchange |
| `tasks` | Blueprint items with status and attempt counts |
| `ledger` | Every agent action — append-only audit trail |

View history anytime:

```bash
uv run main.py log           # List recent issues
uv run main.py log 1         # Full detail for issue #1
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
  tools: []

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
│   │   ├── DISCUSSION.md    # Generated: Architect-CTO Q&A
│   │   └── BLUEPRINT.md     # Generated: task breakdown
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
- **Full audit trail** — Every action logged to SQLite + JSON. Markdown docs for humans.
- **Config over code** — YAML and Markdown control behavior. Engine is immutable.
- **Sandboxed execution** — Tools restricted to the project root directory.

## License

MIT License — See [LICENSE](LICENSE)

**Author**: Zax S ([@ZaxShen](https://github.com/ZaxShen))
