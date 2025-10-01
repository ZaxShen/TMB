# AIDE: AI Development & Execution

> Minimum best practice workflow for human-AI collaboration on high-impact work.

**AIDE** stands for **AI Instruction Definition & Execution** - a lightweight framework that keeps humans in control while leveraging AI capabilities for complex, high-stakes tasks.

---

## Why AIDE?

**The Problem**: Agentic AI is great for research and analysis, but high-impact work requires careful control. One bad decision in code, infrastructure, legal docs, or financial analysis can cascade into serious consequences.

**The Solution**: AIDE uses approval gates and sequential execution - slower than autonomous AI, but predictable, auditable, and safe for work that matters.

### AIDE vs. Agentic AI

| Approach | Best For | Risk Level |
|----------|----------|------------|
| **Agentic AI** | Research, data analysis, content generation, brainstorming | Low impact, reversible |
| **AIDE** | Code, infrastructure, legal docs, financial analysis, compliance, medical | High impact, careful control needed |

**Trade-off**: AIDE sacrifices speed for safety and transparency. For high-stakes work, this is a feature, not a bug.

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

Copy required part from [DEMO_TASKS.md](DEMO_TASKS.md) to [TASKS.md](TASKS.md) and write your tasks, for example:

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
"Read [AIDE/AIDE.md](AIDE.md), then start task 1 from [AIDE/TASKS.md](TASKS.md)"
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

AIDE is built on three core principles (see [AIDE.md](AIDE.md) for full details):

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

## Real Examples

### Example 1: Software Development

**Task**: Upgrade Python version for backend (v2.5.0)

**What happened**:
1. **Human**: "Start task 1: Upgrade Python"
2. **AI**: "I'll check dependencies on Python 3.13 and 3.14..."
3. **AI**: "All deps work on 3.13. Recommend 3.13 (stable) over 3.14 (alpha). 15-20% faster. Proceed?"
4. **Human**: "Proceed with 3.13"
5. **AI**: *[Updates Dockerfiles, pyproject.toml, tests app]* "✅ Complete. Python 3.13.7 installed, all tests passing."
6. **Human**: "Confirmed. Next task."

**Result**: 5 tasks completed, zero breaking changes, complete audit trail, human in control throughout.

### Example 2: Other High-Impact Use Cases

**Legal Contract Review**: AI analyzes contract → Flags risky clauses → Proposes redlines → Human approves each change

**Financial Model Updates**: AI updates spreadsheet formulas → Explains assumptions → Human verifies before publishing

**Infrastructure Changes**: AI proposes AWS config → Explains cost/security impact → Human approves before applying

**Compliance Documentation**: AI drafts policy updates → Cites regulations → Human reviews before official release

**Common pattern**: AI does analysis/drafting, human makes final decisions on anything with real-world impact.

---

## Task Examples

See [DEMO_TASKS.md](DEMO_TASKS.md) for realistic task formats (including common human mistakes that AI should catch)

---

## What Makes AIDE Different?

### vs. Other AI Frameworks

Most frameworks assume "more autonomy = better." AIDE recognizes that for high-impact work, human control is essential.

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

**AIDE + GitHub Copilot [AGENTS.md](https://github.blog/news-insights/product-news/github-copilot-workspace/)**: Use AGENTS.md for project context, AIDE for task workflow

**AIDE + Cursor [.cursorrules](https://docs.cursor.com/context/rules-for-ai)**: Use .cursorrules for code style rules, AIDE for project tasks

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
→ Point to [AIDE.md First Law](AIDE.md#first-law-communication-before-action): "Never blindly agree - critical thinking required"

**"AI isn't logging"**
→ Check AIDE/logs/ directory exists, remind AI to follow logging format in [AIDE.md](AIDE.md#log-structure)

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
