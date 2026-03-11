# TMB

> Your reliable agents framework — maintainable, token-efficient, and built to production standards.

---

## What You Need to Know

TMB works through two files in the `bro/` folder. That's your only interaction point.

### 1. Write your goals

Open `bro/GOALS.md` and describe what you want done in plain language:

```markdown
# Goals

Build a matching algorithm that pairs users by school and gender preference.
Prioritize maximizing the number of matched users over match quality.
Output results to output/matchings.csv.
```

No special syntax required. Write like you're explaining to a colleague.

### 2. Run TMB

```bash
uv run tmb
```

TMB reads your goals, then the Planner will ask you clarifying questions in `bro/DISCUSSION.md`. Open that file, write your answers below the marker, save, and press Enter in the terminal.

When the Planner has enough clarity, it produces a plan for your review. Approve it, and TMB executes — task by task, with automatic validation.

### 3. That's it

Everything else happens automatically:
- `bro/BLUEPRINT.md` — the task breakdown (generated for your review)
- `bro/FLOWCHART.md` — project architecture overview (generated when needed)
- `bro/EXECUTION.md` — execution summary (generated)

You can interrupt at any time (Ctrl+C, close your laptop). Run `uv run tmb` again and it picks up exactly where it left off.

---

## Setup

**Prerequisites**: [uv](https://docs.astral.sh/uv/) and an LLM API key (Anthropic, OpenAI, Google, Groq, Mistral, DeepSeek — or Ollama for local models).

**New project:**

```bash
cd your-project/
git clone https://github.com/ZaxShen/TMB.git
./TMB/install
uv run tmb
```

**Joining an existing project** (someone already set up TMB):

```bash
cd your-project/
./TMB/install
uv run tmb
```

The install script creates `pyproject.toml` (if needed) and installs dependencies. The first time you run `uv run tmb`, TMB walks you through naming your project, choosing an LLM provider, and setting your API key — then continues straight into the workflow.

After setup your project looks like this:

```
your-project/
├── bro/         ← you interact here (GOALS.md, DISCUSSION.md)
├── .tmb/             ← runtime state (automatic, hidden)
├── TMB/              ← framework (don't touch)
├── .env                 ← your API key
└── ...
```

> **Important**: Always run commands from your **project root** (the parent of `TMB/`), not from inside `TMB/`.

To update TMB later: `cd TMB && git pull origin dev && cd .. && ./TMB/install`

---

## Quick Commands

| Command | What it does |
|---|---|
| `uv run tmb` | Full workflow — reads your goals, discusses, plans, executes |
| `uv run tmb "fix the login bug"` | Quick task — skips discussion, auto-approves the plan |
| `uv run tmb log` | Show recent issues |
| `uv run tmb log 3` | Show details for issue #3 |
| `uv run tmb report 3` | Export a full markdown report for issue #3 |
| `uv run tmb tokens` | Show token usage across all issues |
| `uv run tmb tokens 3` | Show token usage for issue #3 |
| `uv run tmb setup` | Re-run setup (change LLM provider, role names, etc.) |

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
Planner produces BLUEPRINT.md (+ FLOWCHART.md if needed)
       |
       v
You review and approve
       |
       v
TMB executes, validates each task, reports results
```

Every discussion, decision, and result is saved. Run `uv run tmb report 3` six months later and see exactly what happened.

---

## Technical Details

For architecture, configuration, permissions, skills, MCP integration, and database schema, see [ARCHITECTURE.md](ARCHITECTURE.md).

## License

MIT License — See [LICENSE](LICENSE)

**Author**: Zax S ([@ZaxShen](https://github.com/ZaxShen))
