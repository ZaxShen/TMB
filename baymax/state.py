"""Shared state schema for the Baymax graph."""

from __future__ import annotations

from typing import TypedDict, Literal
from langgraph.graph import MessagesState


class Task(TypedDict):
    branch_id: str
    title: str
    description: str
    tools_required: list[str]
    success_criteria: str


class AgentState(MessagesState):
    objective: str
    project_context: str
    discussion: str
    issue_id: int
    blueprint: list[Task]
    current_task_idx: int
    execution_log: str
    review_feedback: str
    iteration_count: int
    next_node: Literal["planner", "planner_plan", "planner_execution_plan", "planner_validate", "executor", "human_review", "__end__"]
