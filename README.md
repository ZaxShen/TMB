# AIDE: AI Development & Execution

> Minimum best practice for human-AI collaboration in software development.

**AIDE** stands for **AI Instruction Definition & Execution** - a lightweight framework that keeps humans in control while leveraging AI capabilities for code development.

---

## Why AIDE?

**The Problem**: Agentic AI is great for research and analysis, but code has severe impact. One bad change can cascade into broken production systems.

**The Solution**: AIDE uses approval gates and sequential execution - slower than autonomous AI, but predictable, auditable, and safe for high-impact work.

### AIDE vs. Agentic AI

| Approach | Best For | Risk Level |
|----------|----------|------------|
| **Agentic AI** | Research, data analysis, content generation | Low impact, reversible |
| **AIDE** | Code development, infrastructure, production systems | High impact, careful control needed |

**Trade-off**: AIDE sacrifices speed for safety and transparency. For code, this is a feature, not a bug.

---

## Quick Start

### 1. Get AIDE

**Option A: Git Submodule** (Recommended)
```bash
cd your-project/
git submodule add https://github.com/ZaxShen/AIDE.git
git submodule update --init --recursive
```

**Option B: Direct Copy**
```bash
cd your-project/
git clone https://github.com/ZaxShen/AIDE.git
# Copy files you need, delete .git/
```

### 2. Create Your Tasks

Copy required part from `AIDE/DEMO_TASKS.md` to `AIDE/TASKS.md` and write your tasks, for example:

```markdown
## v0.0.1

### 1. Upgrade Python

Evaluate the dependcies and see which latest Python version we can upgrade to for better performance.

### 2. Update README

The README has outdated info. Update it.
```

**Don't overthink it** - write rough drafts. AI will ask questions.

### 3. Update .gitignore

Add to your project's `.gitignore` to exclude AIDE files from version control:

```gitignore
# AIDE framework (if using submodule, only ignore logs)
AIDE/logs/
AIDE/TASKS.md

# Or if direct copy (ignore AIDE demo/docs, keep only what you need)
AIDE/DEMO_TASKS.md
AIDE/AI_TODO.md
AIDE/AI_COLLABORATION_GUIDE.md
```

**Recommended**: Commit `AIDE/AIDE.md` and `AIDE/README.md` so team members get the framework. Only ignore logs and your specific `TASKS.md`.

### 4. Start Working with AI

Tell your AI assistant:

```
"Read AIDE/AIDE.md, and AIDE/TASKS.md"
```

**What happens:**

1. AI reads the framework rules
2. AI analyzes your task and asks clarifying questions
3. AI proposes approach with options
4. You approve
5. AI executes and logs everything to `AIDE/logs/`
6. You review changes and logs
7. You say "next task" or request changes

---

## The Three Laws of AIDE

AIDE is built on three core principles, see more details at `AIDE/AIDE.md`:

### 1. Communication Before Action

AI must understand before executing, and challenge before accepting.

### 2. Sequential Execution with Human Control

AI must complete one task at a time, with approval gates between tasks.

### 3. Complete Transparency

AI must document all actions, decisions, and reasoning.

---

## File Structure

```
your-project/
├── AIDE/                    # Framework (submodule or direct copy)
│   ├── AIDE.md              # Rules for AI (technical spec)
│   ├── TASKS.md             # Your tasks (copy format from DEMO_TASKS.md)
│   ├── DEMO_TASKS.md        # Example tasks showing good/bad formats
│   ├── README.md            # This file (for humans)
│   ├── LICENSE              # MIT License
│   └── logs/
│       └── v0.0.1_claude.log
├── your-code/
└── ...
```

---

## Real Example

See `AIDE/DEMO_TASKS.md`

---

## What Makes AIDE Different?

### vs. Other AI Frameworks

TODO: make update this description based on three laws
Most frameworks assume "more autonomy = better." AIDE recognizes that for coding or other scentive works, human control is essential, challenging human is the second.

**AIDE encourages AI to:**

- Question your assumptions
- Challenge bad ideas
- Propose better alternatives
- Ask before executing

**Example from DEMO_TASKS.md**: If you write "Update README" as task 1 before doing actual work, AI should challenge: "Shouldn't we do the upgrades first, then update README to reflect actual changes?"

---

## Best Practices

### For Humans

**Do:**

- Write rough task descriptions - AI will clarify
- Include context when relevant ("Update Python with all compatibilty")
- Mark destructive operations ("Verify before deleting")
- Ask for options ("Give me choices before doing it")
- Let AI challenge your ideas

**Don't:**

- Overthink task descriptions
- Skip reading logs
- Rush approvals without review

### For AI Assistants

See [AIDE.md](AIDE.md) for full technical specification.

---

## Integration

### With Other Tools

**AIDE + GitHub Copilot AGENTS.md**: Use AGENTS.md for project context, AIDE for task workflow

**AIDE + Cursor .cursorrules**: Use .cursorrules for code style rules, AIDE for project tasks

**AIDE + Your IDE**: Works with any AI assistant (Claude Code, Cursor, GitHub Copilot, ChatGPT, etc.)

### Multiple AI Assistants

Each AI gets its own log:
- `logs/v0.0.1_claude.log`
- `logs/v0.0.1_gpt4.log`

Compare approaches, learn from different AI reasoning styles.

---

## Troubleshooting

**"AI is doing too much at once"**
→ Remind: "One task at a time, wait for approval before proceeding"

**"AI isn't challenging my ideas"**
→ Point to AIDE.md First Law: "Never blindly agree - critical thinking required"

**"AI isn't logging"**
→ Check AIDE/logs/ directory exists, remind AI to follow logging format in AIDE.md

**"I want faster iteration"**
→ Batch approve subtasks: "Complete steps 1-3 then report" - but keep approval gates between major tasks

---

## Contributing

This framework is open source and evolving. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

**Quick ways to help:**

- 🐛 [Report issues](https://github.com/ZaxShen/AIDE/issues/new?template=bug_report.md): What worked? What didn't?
- 💡 [Suggest improvements](https://github.com/ZaxShen/AIDE/issues/new?template=feature_request.md): Better workflows, clearer docs
- 📝 **Share examples**: Your task templates, real-world results
- ⭐ **Star if useful**: Help others discover AIDE

---

## License

MIT License - See [LICENSE](LICENSE)

**Author**: Zax S ([@ZaxShen](https://github.com/ZaxShen))

**Repository**: https://github.com/ZaxShen/AIDE

---

## Version

**v0.0.1** (2025-10-01)

- Three Laws of AIDE established
- Sequential workflow with approval gates
- Enhanced logging format (ANALYSIS → APPROVAL → EXECUTION → REASONING)
- Framework optimized for code development (vs. agentic AI for research)

---

## Project Files

- [AIDE.md](AIDE.md) - Technical specification for AI assistants
- [DEMO_TASKS.md](DEMO_TASKS.md) - Example tasks showing good/bad formats
- [CONTRIBUTING.md](CONTRIBUTING.md) - Contribution guidelines
- [logs/EXAMPLE_v1.0.0_claude.log](logs/EXAMPLE_v1.0.0_claude.log) - Sample activity log
