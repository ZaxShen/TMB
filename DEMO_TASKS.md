# Demo Tasks

**For humans**: This simulates how real people write tasks - incomplete, sometimes wrong order, missing context. AI should challenge these and ask questions under `AIDE.md`. Copy to `TASKS.md` and write your own tasks!

**For AI**: These are realistic human task descriptions. Practice challenging them - ask questions, spot issues, propose better approaches before executing.

---

## v0.0.1 (Example 1: Too Vague)

### 1. Upgrade Python

Evaluate the dependcies and see which latest Python version we can upgrade to for better performance.

---

### 2. Remove uncessary files and configurations

There are a bunch of .bak files and old stuff from when we used Conda. Delete them.

---

### 3. Reorganize the project

The file structure is messy. Organize it better with modern Python standards.

---

### 3.1 Update configs

Fix .gitignore and pyproject.toml after the migration. I forget this step. Added 3.1 task.

---

### 4. Update README

The README has outdated info. Update it.

---

## v0.0.1 (Example 2: Wrong Order, Missing Info)

### 1. Update README

Update README to reflect new Python 3.13 setup.

---

### 2. Upgrade Python

Upgrade to Python 3.13.

---

### 3. Remove .bak files

Delete all .bak files.

---

## v0.0.1 (Example 3: Better, But Still Has Issues)

### 1. Upgrade Python version

Check if we can upgrade to Python 3.13 or 3.14. Research performance improvements and test dependencies. Let me know what you find before upgrading.

**Done when**:

- Dependencies tested
- Dockerfiles updated
- App runs successfully

---

### 2. Remove unnecessary files

Remove .bak files and old configs from Conda/Pip migrations. Also check for old AWS ECS stuff like Procfile.

**Challenge AI**: Before deleting, verify files aren't used in production.

---

### 3. Organize file structure

Reorganize files following modern Python standards. Move Docker files somewhere logical. Make sure Flask still works and git submodules aren't broken.

Give me options before doing it.

---

### 4. Update .gitignore and pyproject.toml

Update these files to reflect the uv migration and Python 3.13 upgrade.

---

### 5. Update README

Remove outdated content, add new setup instructions. Be concise - cut about 20% of current length.

---

## Task Template (Minimal)

```markdown
### Task Name

What needs to be done and why.

**Done when** (optional):
- Completion criteria

**Challenge AI** (optional): What to question
```

---

## What AI Should Do With These Tasks

### Example 1 (Too Vague)

**Problems**: No requirements, no context, no "done when"

**AI should**:

- Ask: "Which Python version? Should I check dependency compatibility first?"
- Ask: "Which .bak files? Should I verify they're unused in production?"
- Ask: "What does 'better organization' mean? Should I propose options?"

### Example 2 (Wrong Order)

**Problems**: README update before actual work, no verification steps, no context

**AI should**:

- Challenge: "You want README updated first, but shouldn't we do the upgrades first so README reflects actual changes?"
- Ask: "Before deleting .bak files, should I check if they're referenced anywhere?"
- Suggest: "I'll research Python 3.13 vs 3.14 compatibility and recommend which to use"

### Example 3 (Better, But Issues)

**Problems**: Still missing some context, task 3 lacks specific requirements, task 4 too vague

**AI should**:

- Confirm: "You mentioned `xxx-api` are git submodules - got it, I'll verify they still work after reorganization"
- Ask: "For file organization, should I prioritize minimal changes or full restructure? What's the deployment impact?"
- Ask: "Task 4 is vague - what specific changes need to happen in .gitignore and pyproject.toml?"
- Propose: "For README, should I remove sections about old deployment methods (AWS ECS)? conda commands?"

---

## Best Practices for Humans

**Don't overthink**: Write rough tasks, AI will ask for clarification

**Include context when relevant**: "This project migrated from X to Y" helps AI understand

**Mark destructive operations**: "Verify before deleting" reminds AI to be careful

**Ask for options**: "Give me choices before doing it" triggers trade-off analysis

**It's okay to be vague**: AI should challenge and clarify, not blindly execute
