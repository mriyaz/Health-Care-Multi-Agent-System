"""Maps TaskType to orchestrator route keys (checklist #28 — task router)."""

from __future__ import annotations

from db.enums import TaskType

# Stable route keys stored in OrchestratorState.route_history / specialist_route.
ROUTE_DOCUMENT = "DOCUMENT_AGENT"
ROUTE_RCM = "RCM_AGENT"
ROUTE_PRIOR_AUTH = "PRIOR_AUTH_AGENT"
ROUTE_ENGAGE = "ENGAGE_AGENT"
ROUTE_TRIAGE = "TRIAGE_AGENT"
ROUTE_ORCHESTRATE = "ORCHESTRATE_AGENT"


def task_type_to_route(task_type: TaskType | str) -> str:
    """
    Map API/database task type enum to a specialist route identifier.

    CODE_AUDIT and legacy RCM_AUDIT share the RCM specialist until Section E is split out.
    """
    if isinstance(task_type, TaskType):
        tt = task_type
    else:
        tt = TaskType(str(task_type))

    return _TASK_TYPE_TO_ROUTE[tt]


_TASK_TYPE_TO_ROUTE: dict[TaskType, str] = {
    TaskType.DOCUMENT: ROUTE_DOCUMENT,
    TaskType.RCM_AUDIT: ROUTE_RCM,
    TaskType.CODE_AUDIT: ROUTE_RCM,
    TaskType.PRIOR_AUTH: ROUTE_PRIOR_AUTH,
    TaskType.ENGAGE: ROUTE_ENGAGE,
    TaskType.TRIAGE: ROUTE_TRIAGE,
    TaskType.ORCHESTRATE: ROUTE_ORCHESTRATE,
}
