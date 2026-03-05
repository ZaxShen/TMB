"""AIDE engine — builds and compiles the LangGraph workflow.

Two graph variants:
  build_graph()           — full workflow: Architect → [CTO interrupt] → Executor ↔ Validator.
                            Uses MemorySaver for the within-process interrupt_after=["architect"].
  build_execution_graph() — execution-only: Executor ↔ Validator (no Architect, no interrupt).
                            Used for cross-process resume when the blueprint is already approved.

Gatekeeper and Discussion run pre-graph (they need terminal I/O).
"""

from __future__ import annotations

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from aide.state import AgentState
from aide.nodes.architect import architect
from aide.nodes.executor import executor
from aide.nodes.validator import validator


def _route(state: AgentState) -> str:
    return state["next_node"]


def build_graph() -> StateGraph:
    """Full graph with architect interrupt — used for fresh runs."""
    graph = StateGraph(AgentState)

    graph.add_node("architect", architect)
    graph.add_node("executor", executor)
    graph.add_node("validator", validator)

    graph.add_edge(START, "architect")

    graph.add_conditional_edges("architect", _route, {
        "human_review": "executor",
    })

    graph.add_conditional_edges("executor", _route, {
        "validator": "validator",
        "architect": "architect",
        "__end__": END,
    })

    graph.add_conditional_edges("validator", _route, {
        "executor": "executor",
        "architect": "architect",
        "__end__": END,
    })

    checkpointer = MemorySaver()
    compiled = graph.compile(interrupt_after=["architect"], checkpointer=checkpointer)
    return compiled


def build_execution_graph() -> StateGraph:
    """Execution-only graph — starts at executor, no architect interrupt.

    Used for cross-process resume when the blueprint is already approved
    and we need to pick up from a pending/failed task.
    """
    graph = StateGraph(AgentState)

    graph.add_node("executor", executor)
    graph.add_node("validator", validator)

    graph.add_edge(START, "executor")

    graph.add_conditional_edges("executor", _route, {
        "validator": "validator",
        "architect": "executor",
        "__end__": END,
    })

    graph.add_conditional_edges("validator", _route, {
        "executor": "executor",
        "architect": "executor",
        "__end__": END,
    })

    return graph.compile()
