"""Unit tests for Orchestrator LangGraph (Section C) — MemorySaver, no external IO."""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from pydantic_settings import SettingsConfigDict

from api.graphs.orchestrator.graph import compile_orchestrator_graph
from api.graphs.orchestrator.routing import ROUTE_RCM, task_type_to_route
from api.graphs.orchestrator.state import OrchestratorState
from api.graphs.orchestrator import nodes as orch_nodes
from api.settings import Settings
from db.enums import TaskType
from langgraph.checkpoint.memory import MemorySaver


class SettingsNoDotEnv(Settings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")


def _minimal_settings() -> SettingsNoDotEnv:
    env = {
        "SESSION_SECRET_KEY": "s" * 32,
        "JWT_SECRET_KEY": "j" * 32,
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
        "HEALTHOS_ORCHESTRATOR_CHECKPOINTER": "memory",
    }
    with patch.dict(os.environ, env, clear=True):
        return SettingsNoDotEnv()


class OrchestratorRoutingTests(unittest.TestCase):
    def test_task_type_to_route_maps_rcm_aliases(self):
        self.assertEqual(task_type_to_route(TaskType.CODE_AUDIT), ROUTE_RCM)
        self.assertEqual(task_type_to_route(TaskType.RCM_AUDIT), ROUTE_RCM)


class OrchestratorGraphTests(unittest.TestCase):
    def test_document_task_completes_with_stub_specialist(self):
        settings = _minimal_settings()
        app = compile_orchestrator_graph(
            MemorySaver(),
            settings=settings,
            openrouter=None,
        )
        tid = "550e8400-e29b-41d4-a716-446655440000"
        initial: OrchestratorState = {
            "task_id": tid,
            "task_type": TaskType.DOCUMENT.value,
            "tenant_id": "660e8400-e29b-41d4-a716-446655440000",
            "patient_id": None,
            "encounter_id": None,
            "status": "RUNNING",
            "agent_outputs": {},
            "confidence_scores": {},
            "model_versions": {},
            "hitl_required": False,
            "tokens_used": 0,
            "token_budget": settings.orchestrator_token_budget_default,
            "route_history": [],
            "last_route_key": None,
            "routing_repeat_streak": 0,
            "loop_detected": False,
            "step_count": 0,
            "transient_retries": 0,
            "input_hash": None,
            "error_message": None,
            "pending_audit_events": [],
            "specialist_route": "",
        }
        result = asyncio.run(
            app.ainvoke(
                initial,
                {"configurable": {"thread_id": tid}},
            )
        )
        self.assertEqual(result.get("status"), "SUCCEEDED")
        self.assertIn("specialist", result.get("agent_outputs") or {})

    def test_low_confidence_triggers_hitl_interrupt(self):
        settings = _minimal_settings()

        async def fake_specialist(state: OrchestratorState):
            return {
                "agent_outputs": {
                    "specialist": {"route": "x", "text": "{}", "stub": True}
                },
                "confidence_scores": {"specialist": 0.5},
                "model_versions": {"specialist_model": "stub"},
                "tokens_used": 0,
                "pending_audit_events": [],
                "step_count": state.get("step_count", 0) + 1,
            }

        from langgraph.graph import END, START, StateGraph

        from api.graphs.orchestrator.nodes import (
            human_gate_node,
            maybe_hitl_node,
            route_after_route_task,
            route_task_node,
        )

        g = StateGraph(OrchestratorState)
        g.add_node("route_task", route_task_node)
        g.add_node("fail_loop", orch_nodes.fail_loop_node)
        g.add_node("run_specialist", fake_specialist)
        g.add_node("maybe_hitl", maybe_hitl_node)
        g.add_node("human_gate", human_gate_node)
        g.add_edge(START, "route_task")
        g.add_conditional_edges(
            "route_task",
            route_after_route_task,
            {"fail_loop": "fail_loop", "run_specialist": "run_specialist"},
        )
        g.add_edge("fail_loop", END)
        g.add_edge("run_specialist", "maybe_hitl")
        g.add_edge("maybe_hitl", "human_gate")
        g.add_edge("human_gate", END)
        app = g.compile(checkpointer=MemorySaver())

        tid = "550e8400-e29b-41d4-a716-446655440001"
        initial: OrchestratorState = {
            "task_id": tid,
            "task_type": TaskType.DOCUMENT.value,
            "tenant_id": "660e8400-e29b-41d4-a716-446655440000",
            "patient_id": None,
            "encounter_id": None,
            "status": "RUNNING",
            "agent_outputs": {},
            "confidence_scores": {},
            "model_versions": {},
            "hitl_required": False,
            "tokens_used": 0,
            "token_budget": settings.orchestrator_token_budget_default,
            "route_history": [],
            "last_route_key": None,
            "routing_repeat_streak": 0,
            "loop_detected": False,
            "step_count": 0,
            "transient_retries": 0,
            "input_hash": None,
            "error_message": None,
            "pending_audit_events": [],
            "specialist_route": "",
        }
        r1 = asyncio.run(app.ainvoke(initial, {"configurable": {"thread_id": tid}}))
        self.assertIsNotNone(r1.get("__interrupt__"))
        from langgraph.types import Command

        r2 = asyncio.run(
            app.ainvoke(
                Command(resume={"approved": True, "notes": "ok"}),
                {"configurable": {"thread_id": tid}},
            )
        )
        self.assertEqual(r2.get("status"), "SUCCEEDED")


if __name__ == "__main__":
    unittest.main()
