"""AIDE engine — builds and compiles the LangGraph workflow."""

from __future__ import annotations

from langgraph.graph import StateGraph, START, END

from aide.state import AgentState
from aide.nodes.architect import architect
from aide.nodes.executor import executor
from aide.nodes.validator import validator


def _route(state: AgentState) -> str:
    return state["next_node"]


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("architect", architect)
    graph.add_node("executor", executor)
    graph.add_node("validator", validator)

    graph.add_edge(START, "architect")

    graph.add_conditional_edges("architect", _route, {
        "human_review": "executor",  # placeholder — interrupt inserted below
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

    compiled = graph.compile(interrupt_after=["architect"])
    return compiled
