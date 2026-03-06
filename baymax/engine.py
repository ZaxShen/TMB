"""Baymax engine — builds and compiles the LangGraph workflow.

Two graph variants:
  build_graph()           — full workflow: planner_plan → [owner interrupt] →
                            planner_execution_plan → Executor ↔ Validator.
                            Uses MemorySaver for the within-process interrupt_after=["planner_plan"].
  build_execution_graph() — execution-only: Executor ↔ Validator (no Planner, no interrupt).
                            Used for cross-process resume when the blueprint is already approved.

Gatekeeper and Discussion run pre-graph (they need terminal I/O).
"""

from __future__ import annotations

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from baymax.state import AgentState
from baymax.nodes.planner import planner_plan, planner_execution_plan
from baymax.nodes.executor import executor
from baymax.nodes.validator import validator


def _route(state: AgentState) -> str:
    return state["next_node"]


def build_graph() -> StateGraph:
    """Full graph with planner interrupt — used for fresh runs.

    Flow: planner_plan → [interrupt for approval] →
          planner_execution_plan → executor ↔ validator
    """
    graph = StateGraph(AgentState)

    graph.add_node("planner_plan", planner_plan)
    graph.add_node("planner_execution_plan", planner_execution_plan)
    graph.add_node("executor", executor)
    graph.add_node("validator", validator)

    graph.add_edge(START, "planner_plan")

    graph.add_conditional_edges("planner_plan", _route, {
        "human_review": "planner_execution_plan",
    })

    graph.add_conditional_edges("planner_execution_plan", _route, {
        "executor": "executor",
    })

    graph.add_conditional_edges("executor", _route, {
        "validator": "validator",
        "planner": END,
        "__end__": END,
    })

    graph.add_conditional_edges("validator", _route, {
        "executor": "executor",
        "planner": END,
        "__end__": END,
    })

    checkpointer = MemorySaver()
    compiled = graph.compile(interrupt_after=["planner_plan"], checkpointer=checkpointer)
    return compiled


def build_execution_graph() -> StateGraph:
    """Execution-only graph — starts at executor, no planner interrupt.

    Used for cross-process resume when the blueprint is already approved
    and we need to pick up from a pending/failed task.
    """
    graph = StateGraph(AgentState)

    graph.add_node("executor", executor)
    graph.add_node("validator", validator)

    graph.add_edge(START, "executor")

    graph.add_conditional_edges("executor", _route, {
        "validator": "validator",
        "planner": END,
        "__end__": END,
    })

    graph.add_conditional_edges("validator", _route, {
        "executor": "executor",
        "planner": END,
        "__end__": END,
    })

    return graph.compile()
