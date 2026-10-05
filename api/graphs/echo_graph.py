"""Minimal LangGraph used as a smoke test: typed state + single echo node."""

from __future__ import annotations

from typing_extensions import TypedDict

from langgraph.graph import END, START, StateGraph


class EchoGraphState(TypedDict, total=False):
    """Typed graph state for the P0#9 echo pipeline.

    ``total=False`` lets callers invoke the graph with only ``input_text``;
    ``output_text`` is produced by the echo node.
    """

    input_text: str
    output_text: str


def _echo_node(state: EchoGraphState) -> dict[str, str]:
    text = state.get("input_text", "")
    return {"output_text": text}


def compile_echo_graph():
    """Build and compile the echo graph (START → echo → END)."""
    graph = StateGraph(EchoGraphState)
    graph.add_node("echo", _echo_node)
    graph.add_edge(START, "echo")
    graph.add_edge("echo", END)
    return graph.compile()
