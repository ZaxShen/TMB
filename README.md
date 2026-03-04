# AIDE: AI Direction & Execution

> A multi-agent workflow engine that simulates how an IT company ships software — CTO sets direction, Architect designs, SWEs execute, QA validates.

## The Paradigm

AIDE models a real engineering organization as a LangGraph state machine:

| Role | Agent | Responsibility |
|------|-------|---------------|
| **CTO** | Human | Sets objectives. Reviews blueprints. Only cares about results. |
| **Architect** | LLM Agent | Designs the blueprint — atomic tasks with success criteria. Handles escalations from SWEs. |
| **SWE (Executor)** | LLM Agent | Executes tasks from the blueprint using tools (shell, filesystem, search). |
| **QA (Validator)** | LLM Agent | Verifies each task against its success criteria. Pass or fail, no fixing. |

### Why This Works

Autonomous AI agents are unreliable for high-impact work. One bad decision cascades. AIDE solves this by **separating concerns** — the agent that plans never executes, the agent that executes never plans, and an independent agent validates everything. The human (CTO) only intervenes at the blueprint level.

## Architecture

```
START → Architect → [CTO REVIEWS BLUEPRINT] → Executor → Validator
             ↑              ↑                      │          │
             │              │    (escalate)        ←┘          │
             │              └──────────────────────────────────┘ (fail, max retries)
             │              (pass + more tasks)  Executor  ←───┘
             └───────────── (all tasks pass) → END
```

**Edges:**
- **Architect → Human Interrupt**: CTO reviews the blueprint before any execution.
- **Executor → Validator**: Normal path after task execution.
- **Executor → Architect**: Escalation when a task is unclear or blocked.
- **Validator → Executor**: On PASS (next task) or FAIL (retry with feedback).
- **Validator → Architect**: On FAIL after max retries — the task needs re-design.
- **Validator → END**: All tasks pass.

## Quick Start

```bash
# Install
git clone https://github.com/ZaxShen/AIDE.git
cd AIDE
uv sync

# Configure
cp config/project.yaml config/project.yaml   # Edit for your project
# Set your API key
export ANTHROPIC_API_KEY=sk-...

# Run
uv run python main.py "Upgrade the project to Python 3.13"
```

## Project Structure

```
AIDE/
├── config/
│   ├── nodes.yaml          # Per-node LLM provider, model, temperature, tools
│   └── project.yaml        # Project root, test command, retry limits
├── prompts/
│   ├── architect.md        # Architect system prompt
│   ├── executor.md         # Executor system prompt
│   └── validator.md        # Validator system prompt
├── aide/
│   ├── engine.py           # LangGraph graph construction and compilation
│   ├── state.py            # Shared state schema (AgentState)
│   ├── config.py           # YAML config loader
│   ├── nodes/
│   │   ├── architect.py    # Architect node
│   │   ├── executor.py     # Executor node
│   │   └── validator.py    # Validator node
│   └── tools/
│       ├── shell.py        # Sandboxed shell (project root only)
│       ├── filesystem.py   # File read/write (project root only)
│       └── search.py       # Code search (ripgrep wrapper)
├── main.py                 # CLI entry point
├── pyproject.toml
└── LICENSE
```

## Configuration

### `config/nodes.yaml`

Define the LLM and tools for each agent:

```yaml
architect:
  model:
    provider: anthropic       # anthropic | openai | google
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

### `config/project.yaml`

Project-specific settings:

```yaml
name: my-project
root_dir: .
test_command: pytest
max_retry_per_task: 3
```

## Design Principles

- **Config over code** — Change behavior through YAML and prompt files, never the engine source.
- **Separation of concerns** — Planning, execution, and validation are isolated agents with no role overlap.
- **Fail fast** — Validate config, connections, and prerequisites at startup before any work begins.
- **Idempotent tasks** — Every task in the blueprint is safe to re-run.
- **Sandboxed execution** — All shell and file operations are restricted to the project root directory.

## Roadmap

- [x] Phase 1: Static graph with 3 nodes, in-memory state, single run
- [ ] Phase 2: SqliteSaver checkpointing + thread_id for resumability
- [ ] Phase 3: LangGraph Studio compatibility
- [ ] Phase 4: Plugin system for custom tools

## License

MIT License — See [LICENSE](LICENSE)

**Author**: Zax S ([@ZaxShen](https://github.com/ZaxShen))
