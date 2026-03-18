# TMB — Trust My Bot

> "I don't trust LLM, but I trust my bro." — Zax Shen    
> "Trust Me Bro, it works." - Your Bro

Agentic AI & multi-agent framework that harnesses LLMs into reliable engineering workflows — through structured planning, execution, and validation.

---

## Why "Trust Me Bro"?

You've used AI coding assistants. You've typed "build X" and watched them hallucinate file paths, skip edge cases, and produce code that looks right but breaks on real data. You can't trust a single agent with a blank canvas and hope for the best.

TMB doesn't ask you to hope. It earns trust through structure:

```
  YOU decide WHAT to build          Agents figure out HOW
  ────────────────────────          ────────────────────
  Write goals in plain English  →   Planner explores your codebase first
  Answer clarifying questions   →   Planner challenges your assumptions
  Review the blueprint          →   You approve before anything executes
  Walk away                     →   Executor builds, Planner validates each step
                                    Failed? Auto-retry with new solutions from multi-agent collaboration
                                    Still failed? Escalate back to you
```

The key insight: **you stay at the system-design level**. You never argue about the minior issues. You define the *what* and the *why*. The agents handle the *how* — and they check each other's work.

### The trust contract, specifically

**1. Nothing runs without your approval.** The Planner produces a blueprint (task breakdown) that you read and approve before a single line of code is written.

**2. Agents can't see what they shouldn't.** The Executor only sees its own task — never your goals, discussion history, or the full blueprint. This isn't just about security; it prevents the LLM from getting distracted by irrelevant context and hallucinating connections.

**3. Every task is validated.** After the Executor finishes, the Planner (which holds full project context) independently validates the output against success criteria — running tests, inspecting files, checking results. It's a built-in code review that never gets lazy.

**4. Everything is recorded.** Every discussion, decision, tool call, and validation result is persisted in SQLite. Run `bot report 3` six months later and reconstruct exactly what happened, why, and what the agents saw.

**5. You can interrupt anytime.** Close your laptop mid-task. Run `bot` again — it picks up exactly where it left off. State lives in the database, not in memory.

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
bot
```

TMB reads your goals, then the Planner will ask you clarifying questions in `bro/DISCUSSION.md`. Open that file, write your answers below the marker, save, and press Enter in the terminal.

When the Planner has enough clarity, it produces a plan for your review. Approve it, and TMB executes — task by task, with automatic validation.

### 3. That's it

Everything else happens automatically:

- `bro/BLUEPRINT.md` — the task breakdown (generated for your review)
- `bro/FLOWCHART.md` — project architecture overview (generated when needed)
- `bro/EXECUTION.md` — execution summary (generated)

---

## Setup

**Prerequisites**: An LLM API key (Anthropic, OpenAI, Google, Groq, Mistral, DeepSeek — or Ollama for local models). Or just [Claude Code](https://docs.anthropic.com/en/docs/claude-code) with a Claude subscription.

**Install** (pick one):

```bash
# Recommended — works everywhere
curl -LsSf https://raw.githubusercontent.com/ZaxShen/TMB/main/get-bro.sh | sh

# macOS (Homebrew)
brew tap ZaxShen/tmb && brew install trustmybot

# Python users
uv tool install trustmybot
```

> **Bleeding edge?** Install from dev: `curl -LsSf https://raw.githubusercontent.com/ZaxShen/TMB/dev/get-bro.sh | sh -s -- dev`

**Start:**

```bash
cd your-project/
bot
```

The first time you run `bot`, it walks you through naming your project, choosing an LLM provider, and setting your API key — then continues straight into the workflow.

After setup your project looks like this:

```
your-project/
├── bro/              ← you interact here (GOALS.md, DISCUSSION.md)
├── .tmb/             ← runtime state (automatic, hidden)
├── .env              ← your API key
└── your files...
```

To update: `bro upgrade`

> **Tip**: `bro` is an alias for `bot` — use whichever you prefer.

> **Developers**: For local/editable install, `uv` commands, and optional providers, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Quick Commands


| Command            | What it does                                                 |
| ------------------ | ------------------------------------------------------------ |
| `bro`              | Chat mode (default) — ask anything, bro handles it           |
| `bro plan`         | Full workflow — reads your goals, discusses, plans, executes |
| `bro chat`         | Chat mode (explicit)                                         |
| `bro scan`         | Scan project for TMB context (file registry, git history)    |
| `bro log`          | Show recent issues                                           |
| `bro log 3`        | Show details for issue #3                                    |
| `bro report 3`     | Export a full markdown report for issue #3                   |
| `bro tokens`       | Show token usage across all issues                           |
| `bro tokens 3`     | Show token usage for issue #3                                |
| `bro setup`        | Re-run setup (change LLM provider, role names, etc.)         |
| `bro evolve "..."` | Self-modify TMB's own code (guarded, git-snapshotted)        |
| `bro serve`        | Expose TMB as an MCP server (for Claude Desktop, Cursor)     |


### MCP — External Integrations

Need Notion, GitHub, Slack, or any other service? No problem — Trust Me Bro, your agents can connect to anything via [MCP](https://modelcontextprotocol.io/). Configure in `.tmb/config/mcp.yaml`. See [ARCHITECTURE.md § MCP Integration](ARCHITECTURE.md#mcp-integration) for details.

To use TMB as an MCP server in Claude Desktop or Cursor, add this to your MCP config:

```json
{
  "mcpServers": {
    "trustmybot": {
      "command": "bot",
      "args": ["serve"],
      "cwd": "/path/to/your-project"
    }
  }
}
```

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
(repeat until Planner says "TRUST ME BRO, LET'S BUILD")
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

---

## Technical Details

For architecture, configuration, permissions, skills, MCP integration, and database schema, see [ARCHITECTURE.md](ARCHITECTURE.md).

## License

AGPL-3.0 — See [LICENSE](LICENSE)

**Author**: Zax S ([@ZaxShen](https://github.com/ZaxShen))