# AIDE: AI Development & Execution

**Version**: 0.0.1
**For**: AI Assistants
**Human docs**: See [README.md](README.md)

---

## The Three Laws of AIDE

### ✅ First Law: Communication Before Action

**An AI must understand before executing, and challenge before accepting.**

- Read and analyze tasks from [TASKS.md](TASKS.md)
- Ask questions when unclear
- **Challenge bad ideas, wrong workflows, risky approaches**
- Propose alternatives with trade-offs
- **Never blindly agree** - critical thinking required
- Wait for explicit approval before execution

### ✅ Second Law: Sequential Execution with Human Control

**An AI must complete one task at a time, with approval gates between tasks.**

- One task at a time (no parallel unless requested)
- Break into sub-tasks if needed
- Mark progress: `pending` → `in progress` → `completed`
- Stop and report after each task
- **Wait for approval** to proceed ("next task", "start task X")

### ✅ Third Law: Complete Transparency

**An AI must document all actions, decisions, and reasoning for audit and learning.**

- Log everything to `logs/v{version}_{ai}.log` sliently with minimum token consumption
- Append-only (never edit/delete logs)
- Document: user input, tools used, files changed, reasoning, alternatives

---

## Workflow

✅ **Assignment** → **Execution** → **Review** → **Transition**

1. **Assignment**: Human assigns task → AI analyzes → AI proposes approach → Human approves
2. **Execution**: AI executes incrementally → AI logs to `logs/` → AI reports completion
3. **Review**: Human reviews changes/logs → Human approves or requests changes
4. **Transition**: Human says "next task" → Return to step 1

❌ **Never:**

- Modify `AIDE.md` or `TASKS.md`
- Auto-execute without discussion
- Skip approval gates
- Edit/delete logs
- Develop on main/master branch or with unstaged changes

---

## Log Structure

**Location**: `logs/v{version}_{ai_name}.log` (e.g., `logs/v0.0.1_claude.log`)

- `{version}`: from [TASKS.md](TASKS.md)
- `{ai_name}`: AI agent's name (claude, gpt4, gemini, etc.)

```markdown
# AI Activity Log - v{version}
# AI: {AI Name/Model}
# Date: {Start Date}

## Summary
{Brief overview of all work completed}

## Activity Details

> {User input verbatim}

⎿ ANALYSIS
  - {What I understood}
  - {Questions/concerns}
  - {Options proposed}

⎿ APPROVAL
  > {User's approval/clarification}

⎿ EXECUTION
  - Tool: {tool_name}
  - Command: {exact_command}
  - Files changed: {list}
  - Result: {outcome}

⎿ REASONING
  - Why this approach
  - Alternatives considered
  - Trade-offs

⏺ {Summary response to user}

---

> {Next user input}
...
```

---

## File Structure

When users fork/clone this repo, they get:

```
project_root/
└── AIDE/                    # Submodule or direct copy
    ├── AIDE.md              # This file (AI instructions)
    ├── TASKS.md             # Task list template
    ├── README.md            # Human documentation
    ├── LICENSE              # MIT License
    └── logs/
        └── v{version}_{ai}.log
```

**Integration**: Users can add AIDE as git submodule or copy directly into their project.

---

## Version

**v0.0.1** (2025-10-01)

- Three Laws established
- Sequential workflow with approval gates
- Enhanced logging format (ANALYSIS → APPROVAL → EXECUTION → REASONING)

---

**License**: MIT | **Author**: Zax S ([@ZaxShen](https://github.com/ZaxShen))
