# Skill: File Access & Permissions

> Rules for reading and writing files within Baymax's permission model.

---

## Permission Layers

Baymax enforces three layers of access control:

1. **Global blacklist** — files no agent can ever access (`.env`, secrets, `Baymax/**` internals)
2. **Docs write allowlist** — only these user-facing files in `baymax-docs/` can be written by agents:
   - `DISCUSSION.md`, `BLUEPRINT.md`, `FLOWCHART.md`
   - `EXECUTION.md`, `QA_PLAN.md`, `EVOLUTION.md`
3. **Node-specific restrictions** — certain doc files are restricted to specific agents

## Who Can Access What

| File | Planner | Executor | Validator |
|---|---|---|---|
| `baymax-docs/GOALS.md` | read | — | — |
| `baymax-docs/DISCUSSION.md` | read/write | — | — |
| `baymax-docs/BLUEPRINT.md` | read/write | — | — |
| `baymax-docs/FLOWCHART.md` | read/write | — | — |
| `baymax-docs/EXECUTION.md` | read/write | read | read |
| `baymax-docs/QA_PLAN.md` | read/write | — | read |
| `.baymax/baymax.db` | read/write | read/write | read/write |
| Project source files | read | read/write | read |

## Directory Layout

```
baymax-docs/     ← user-facing docs (GOALS, BLUEPRINT, etc.)
.baymax/         ← hidden runtime state (DB, config overrides, agent-created skills)
Baymax/          ← framework submodule (immutable during normal operation)
```

## Rules

1. **Never read or write blacklisted files.** The permission layer will redact their content.
2. **Executor and Validator cannot access high-level planning docs** (`GOALS.md`, `DISCUSSION.md`, `BLUEPRINT.md`, `FLOWCHART.md`) — these would add noise to their context window and risk hallucination from planning-level language.
3. **Only the Planner updates planning docs.** When the Validator finds issues, it reports to the Planner who decides whether to update docs.
4. **All project file writes go through sandboxed tools** scoped to `project_root`.
