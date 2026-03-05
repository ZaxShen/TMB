"""AIDE engine — builds and compiles the LangGraph workflow.

Two graph variants:
  build_graph()           — full workflow: architect_plan → [Chief Architect interrupt] →
                            architect_execution_plan → Executor ↔ Validator.
                            Uses MemorySaver for the within-process interrupt_after=["architect_plan"].
  build_execution_graph() — execution-only: Executor ↔ Validator (no Architect, no interrupt).
                            Used for cross-process resume when the blueprint is already approved.

Gatekeeper and Discussion run pre-graph (they need terminal I/O).
"""

from __future__ import annotations

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from aide.state import AgentState
from aide.nodes.architect import architect_plan, architect_execution_plan
from aide.nodes.executor import executor
from aide.nodes.validator import validator


def _route(state: AgentState) -> str:
    return state["next_node"]


def build_graph() -> StateGraph:
    """Full graph with architect interrupt — used for fresh runs.

    Flow: architect_plan → [interrupt for approval] →
          architect_execution_plan → executor ↔ validator
    """
    graph = StateGraph(AgentState)

    graph.add_node("architect_plan", architect_plan)
    graph.add_node("architect_execution_plan", architect_execution_plan)
    graph.add_node("executor", executor)
    graph.add_node("validator", validator)

    graph.add_edge(START, "architect_plan")

    graph.add_conditional_edges("architect_plan", _route, {
        "human_review": "architect_execution_plan",
    })

    graph.add_conditional_edges("architect_execution_plan", _route, {
        "executor": "executor",
    })

    graph.add_conditional_edges("executor", _route, {
        "validator": "validator",
        "architect": END,
        "__end__": END,
    })

    graph.add_conditional_edges("validator", _route, {
        "executor": "executor",
        "architect": END,
        "__end__": END,
    })

    checkpointer = MemorySaver()
    compiled = graph.compile(interrupt_after=["architect_plan"], checkpointer=checkpointer)
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
        "architect": END,
        "__end__": END,
    })

    graph.add_conditional_edges("validator", _route, {
        "executor": "executor",
        "architect": END,
        "__end__": END,
    })

    return graph.compile()
