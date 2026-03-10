"""Skill tools — create (Planner only) and request (all nodes)."""

from __future__ import annotations

from langchain_core.tools import tool

from baymax.paths import BAYMAX_ROOT, user_skills_dir
from baymax.store import Store


def create_skill_tool(creator_node: str = "planner"):
    """Return a tool that creates/updates skills. Intended for the Planner only.

    Skills created by curated roles (planner, owner, system) are immediately active.
    """

    @tool
    def skill_create(name: str, description: str, content: str,
                     tags: str = "", when_to_use: str = "",
                     when_not_to_use: str = "") -> str:
        """Create or update a reusable skill file. Only the Planner should use this.

        Args:
            name: Skill identifier (kebab-case, e.g. 'csv-handling')
            description: One-line summary of what the skill teaches
            content: Full markdown content of the skill
            tags: Comma-separated tags (e.g. 'csv,pandas,data')
            when_to_use: When this skill is relevant
            when_not_to_use: When this skill should NOT be used
        """
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        skills_dir = user_skills_dir()
        skills_dir.mkdir(parents=True, exist_ok=True)
        full_path = skills_dir / f"{name}.md"
        full_path.write_text(content)
        file_path = f"skills/{name}.md"

        store = Store()
        existing = store.get_skill(name)
        if existing:
            store.update_skill(
                name, description=description, file_path=file_path,
                tags=tag_list if tag_list else None,
                when_to_use=when_to_use or None,
                when_not_to_use=when_not_to_use or None,
            )
            return f"Updated skill '{name}' at {file_path} (status: {existing['status']})"
        else:
            store.create_skill(
                name, description, file_path,
                created_by=creator_node, tags=tag_list,
                when_to_use=when_to_use, when_not_to_use=when_not_to_use,
            )
            return f"Created skill '{name}' at {file_path} (status: active)"

    return skill_create


def create_skill_request_tool(requester_node: str = "executor"):
    """Return a tool that any node can use to request a skill.

    First searches existing active skills by keyword. If a match is found,
    returns it immediately. Otherwise logs a request for the Planner.
    """

    @tool
    def skill_request(need: str, context: str = "") -> str:
        """Request a skill you need. The system will either find an existing match
        or log the request for the Planner to create.

        Args:
            need: What you need (e.g. 'how to read and process CSV files with pandas')
            context: Why you need it (e.g. 'task requires parsing a 67k-row CSV')
        """
        store = Store()

        matches = store.search_skills(need)
        if matches:
            best = matches[0]
            skill_path = BAYMAX_ROOT / best["file_path"]
            if not skill_path.exists():
                skill_path = user_skills_dir() / best["file_path"].replace("skills/", "", 1)
            content_preview = ""
            if skill_path.exists():
                raw = skill_path.read_text()
                content_preview = raw[:2000] + ("\n... (truncated)" if len(raw) > 2000 else "")

            if len(matches) == 1:
                return (
                    f"Found existing skill: **{best['name']}**\n"
                    f"Description: {best['description']}\n"
                    f"When to use: {best.get('when_to_use', '(any)')}\n\n"
                    f"{content_preview}"
                )
            other_names = [m["name"] for m in matches[1:4]]
            return (
                f"Found {len(matches)} matching skill(s). Best match: **{best['name']}**\n"
                f"Description: {best['description']}\n"
                f"When to use: {best.get('when_to_use', '(any)')}\n"
                f"Also related: {', '.join(other_names)}\n\n"
                f"{content_preview}"
            )

        req_id = store.create_skill_request(requester_node, need, context)
        return (
            f"No existing skill matches '{need}'. "
            f"Request #{req_id} logged — the Planner will create or assign this skill "
            f"in the next planning cycle. Continue with your current task using your best judgment."
        )

    return skill_request
