# Sample Prompts — Reference Only

These are domain-specialized prompt templates that TMB uses as reference material during setup. Each subdirectory contains a `planner.md` and `executor.md` tailored to a specific project type:

- **generic/** — Baseline prompts (mirrors `prompts/system/`). Used when no domain is detected.
- **software-engineering/** — Web apps, APIs, backend services, DevOps workflows.
- **data-analytics/** — SQL pipelines, ETL, dashboards, data modeling.

**Do not modify these files.** They serve as permanent few-shot references for TMB's auto-prompt generation. When you run `tmb setup`, TMB either copies the closest-matching sample or uses them as style references to LLM-generate custom prompts for your project.

Your project's actual prompts live in `.tmb/prompts/` — edit those if you need to customize.

See [ARCHITECTURE.md § Prompts](../../ARCHITECTURE.md) for the full prompt resolution order.
