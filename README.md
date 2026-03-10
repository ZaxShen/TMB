# Baymax

> Your reliable agents framework — maintainable, token-efficient, and built to production standards.

---

## What You Need to Know

Baymax works through two files in the `baymax-docs/` folder. That's your only interaction point.

### 1. Write your goals

Open `baymax-docs/GOALS.md` and describe what you want done in plain language:

```markdown
# Goals

Build a matching algorithm that pairs users by school and gender preference.
Prioritize maximizing the number of matched users over match quality.
Output results to output/matchings.csv.
```

No special syntax required. Write like you're explaining to a colleague.

### 2. Run Baymax

```bash
uv run baymax
```

Baymax reads your goals, then the Planner will ask you clarifying questions in `baymax-docs/DISCUSSION.md`. Open that file, write your answers below the marker, save, and press Enter in the terminal.

When the Planner has enough clarity, it produces a plan for your review. Approve it, and Baymax executes — task by task, with automatic validation.

### 3. That's it

Everything else happens automatically:
- `baymax-docs/BLUEPRINT.md` — the task breakdown (generated for your review)
- `baymax-docs/FLOWCHART.md` — architecture diagram (generated)
- `baymax-docs/EXECUTION.md` — execution summary (generated)

You can interrupt at any time (Ctrl+C, close your laptop). Run `uv run baymax` again and it picks up exactly where it left off.

---

## Setup

**Prerequisites**: [uv](https://docs.astral.sh/uv/) and an API key (Anthropic or OpenAI).

```bash
cd your-project/
git submodule add https://github.com/ZaxShen/Baymax.git
./Baymax/install
```

That's it. The install script creates your `pyproject.toml` and installs dependencies. The first time you run `uv run baymax`, Baymax walks you through naming your project, choosing an LLM provider, and setting your API key — then continues straight into the workflow.

After setup your project looks like this:

```
your-project/
├── baymax-docs/         ← you interact here (GOALS.md, DISCUSSION.md)
├── .baymax/             ← runtime state (automatic, hidden)
├── Baymax/              ← framework (don't touch)
├── .env                 ← your API key
└── ...
```

To update Baymax later: `cd Baymax && git pull origin dev`

---

## Quick Commands

| Command | What it does |
|---|---|
| `uv run baymax` | Full workflow — reads your goals, discusses, plans, executes |
| `uv run baymax "fix the login bug"` | Quick task — skips discussion, auto-approves the plan |
| `uv run baymax log` | Show recent issues |
| `uv run baymax log 3` | Show details for issue #3 |
| `uv run baymax report 3` | Export a full markdown report for issue #3 |
| `uv run baymax setup` | Re-run setup (change LLM provider, role names, etc.) |

---

## How the Conversation Works

```
You write GOALS.md
       |
       v
Planner reads goals, explores your codebase
       |
       v
Planner asks questions --> DISCUSSION.md
       |
       v
You answer in DISCUSSION.md, press Enter
       |
       v
(repeat until Planner says "READY TO BUILD")
       |
       v
Planner produces BLUEPRINT.md + FLOWCHART.md
       |
       v
You review and approve
       |
       v
Baymax executes, validates each task, reports results
```

Every discussion, decision, and result is saved. Run `uv run baymax report 3` six months later and see exactly what happened.

---

## Technical Details

For architecture, configuration, permissions, skills, MCP integration, and database schema, see [ARCHITECTURE.md](ARCHITECTURE.md).

## License

MIT License — See [LICENSE](LICENSE)

**Author**: Zax S ([@ZaxShen](https://github.com/ZaxShen))
