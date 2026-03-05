"""Tool for creating and updating skills during agent execution."""

from __future__ import annotations

from langchain_core.tools import tool

from aide.config import _AIDE_ROOT
from aide.store import Store


def create_skill_tool(creator_node: str = "executor"):
    """Return a LangChain tool that lets agents create/update skills.

    Agent-created skills start as 'draft' and must be reviewed by the
    Architect before they become active and assignable to future tasks.
    """

    @tool
    def skill_create(name: str, description: str, content: str,
                     tags: str = "", when_to_use: str = "",
                     when_not_to_use: str = "") -> str:
        """Create or update a reusable skill file.

        New skills created by agents start as 'draft' — the Architect must
        approve them before they become available for future task assignment.

        Args:
            name: Skill identifier (kebab-case, e.g. 'api-patterns')
            description: One-line summary of what the skill teaches
            content: Full markdown content of the skill
            tags: Comma-separated tags (e.g. 'db,performance')
            when_to_use: When this skill is relevant (e.g. 'tasks involving SQLite queries')
            when_not_to_use: When this skill should NOT be used (e.g. 'simple file reads')
        """
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        file_path = f"skills/{name}.md"
        full_path = _AIDE_ROOT / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)

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
            store.submit_skill_for_review(name)
            return (
                f"Created skill '{name}' at {file_path} (status: pending_review). "
                f"The Architect must approve this skill before it can be assigned to future tasks."
            )

    return skill_create
