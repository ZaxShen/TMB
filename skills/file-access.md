# Skill: File Access & Permissions

> Rules for reading and writing files within AIDE's permission model.

---

## Permission Layers

AIDE enforces three layers of access control:

1. **Global blacklist** — files no agent can ever access (`.env`, secrets, `AIDE/**` internals)
2. **AIDE write allowlist** — only these AIDE-managed files can be written by any agent:
   - `doc/DISCUSSION.md`, `doc/BLUEPRINT.md`, `doc/FLOWCHART.md`
   - `doc/EXECUTION.md`, `doc/QA_PLAN.md`
   - `aide_history.db`
3. **Node-specific restrictions** — certain doc files are restricted to specific agents

## Who Can Access What

| File | Architect | SWE | QA |
|---|---|---|---|
| `doc/GOALS.md` | read | — | — |
| `doc/DISCUSSION.md` | read/write | — | — |
| `doc/BLUEPRINT.md` | read/write | — | — |
| `doc/FLOWCHART.md` | read/write | — | — |
| `doc/EXECUTION.md` | read/write | read | read |
| `doc/QA_PLAN.md` | read/write | — | read |
| Project source files | read | read/write | read |

## Rules

1. **Never read or write blacklisted files.** The permission layer will redact their content.
2. **SWE and QA cannot access high-level planning docs** (`GOALS.md`, `DISCUSSION.md`, `BLUEPRINT.md`, `FLOWCHART.md`) — these would add noise to their context window and risk hallucination from planning-level language.
3. **Only the Architect updates planning docs.** When QA finds issues, it reports to the Architect who decides whether to update docs.
4. **All project file writes go through sandboxed tools** scoped to `project_root`.
