# System Prompts — Do Not Modify

These are TMB's core system prompts that define how the Planner, Executor, and Chat agents behave. They contain the canonical feature set — JSON schemas, validation rules, tool conventions, and workflow logic that TMB depends on.

**Basic users**: Don't touch these. TMB auto-generates tailored prompts for your project during `tmb setup` and stores them in `.tmb/prompts/`. Those are the ones you should customize if needed.

**Advanced users / contributors**: If you modify these files, you're changing TMB's core behavior for all projects. Make sure you understand the downstream impact on prompt generation (these are used as base templates) and on the samples in `prompts/samples/`.

See [ARCHITECTURE.md § Prompts](../../ARCHITECTURE.md) for the full prompt resolution order.
