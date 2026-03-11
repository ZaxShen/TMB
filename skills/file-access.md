# Skill: File Access & Permissions

> Rules for reading and writing files within TMB's permission model.

---

## Permission Layers

TMB enforces three layers of access control:

1. **Global blacklist** — files no agent can ever access (`.env`, secrets, `TMB/**` internals)
2. **Docs write allowlist** — only these user-facing files in `bro/` can be written by agents:
   - `DISCUSSION.md`, `BLUEPRINT.md`, `FLOWCHART.md`
   - `EXECUTION.md`, `QA_PLAN.md`, `EVOLUTION.md`
3. **Node-specific restrictions** — certain doc files are restricted to specific agents

## Who Can Access What

| File | Planner | Executor | Validator |
|---|---|---|---|
| `bro/GOALS.md` | read | — | — |
| `bro/DISCUSSION.md` | read/write | — | — |
| `bro/BLUEPRINT.md` | read/write | — | — |
| `bro/FLOWCHART.md` | read/write | — | — |
| `bro/EXECUTION.md` | read/write | read | read |
| `bro/QA_PLAN.md` | read/write | — | read |
| `.tmb/tmb.db` | read/write | read/write | read/write |
| Project source files | read | read/write | read |

## Directory Layout

```
bro/     ← user-facing docs (GOALS, BLUEPRINT, etc.)
.tmb/         ← hidden runtime state (DB, config overrides, agent-created skills)
TMB/          ← framework submodule (immutable during normal operation)
```

## Rules

1. **Never read or write blacklisted files.** The permission layer will redact their content.
2. **Executor and Validator cannot access high-level planning docs** (`GOALS.md`, `DISCUSSION.md`, `BLUEPRINT.md`, `FLOWCHART.md`) — these would add noise to their context window and risk hallucination from planning-level language.
3. **Only the Planner updates planning docs.** When the Validator finds issues, it reports to the Planner who decides whether to update docs.
4. **All project file writes go through sandboxed tools** scoped to `project_root`.
