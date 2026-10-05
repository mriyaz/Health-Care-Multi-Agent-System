"""Compile the Orchestrator LangGraph (Section C — routing, HITL, checkpoint-ready)."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from api.graphs.orchestrator.nodes import (
    compile_specialist_node,
    fail_loop_node,
    human_gate_node,
    maybe_hitl_node,
    route_after_route_task,
    route_task_node,
)
from api.graphs.orchestrator.state import OrchestratorState
from api.llm.openrouter_client import OpenRouterClient
from api.settings import Settings


def compile_orchestrator_graph(
    checkpointer: Any,
    *,
    settings: Settings,
    openrouter: OpenRouterClient | None,
    session_factory: Any | None = None,
    weaviate_client: Any | None = None,
) -> Any:
    """
    Build START → route → (fail | specialist) → HITL gate → END.

    Tests pass ``openrouter=None`` and Settings without API keys so specialists run the
    deterministic JSON stub path (no network).
    """
    graph = StateGraph(OrchestratorState)
    graph.add_node("route_task", route_task_node)
    graph.add_node("fail_loop", fail_loop_node)
    graph.add_node(
        "run_specialist",
        compile_specialist_node(
            settings,
            openrouter,
            session_factory=session_factory,
            weaviate_client=weaviate_client,
        ),
    )
    graph.add_node("maybe_hitl", maybe_hitl_node)
    graph.add_node("human_gate", human_gate_node)

    graph.add_edge(START, "route_task")
    graph.add_conditional_edges(
        "route_task",
        route_after_route_task,
        {"fail_loop": "fail_loop", "run_specialist": "run_specialist"},
    )
    graph.add_edge("fail_loop", END)
    graph.add_edge("run_specialist", "maybe_hitl")
    graph.add_edge("maybe_hitl", "human_gate")
    graph.add_edge("human_gate", END)

    return graph.compile(checkpointer=checkpointer)
