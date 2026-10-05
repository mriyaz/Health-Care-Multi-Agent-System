from datetime import (
    datetime,
    timezone,
)  # Used to generate an ISO-8601 UTC timestamp in the health response
from fastapi import (
    APIRouter,
    Depends,
    Request,
)  # APIRouter groups related endpoints; Request gives access to app state

from api.auth.deps import (
    get_current_active_principal,
)  # JWT required on all non-auth routes (P0#13)
from api.redis_client import (
    ping_redis,
)  # Async Redis PING used to surface broker/session store availability
from api.vectorstore.client import (
    ping_weaviate,
)  # Weaviate readiness (sync client; cheap is_ready check)

router = APIRouter(
    tags=["health"],
    dependencies=[Depends(get_current_active_principal)],
)


@router.get("/health")
async def health(request: Request):
    s = (
        request.app.state.settings
    )  # Read the Settings object stored on the FastAPI app (set in api/main.py)
    redis_ok = await ping_redis(
        request.app.state.redis
    )  # Startup already tested connectivity; this rechecks mid-flight
    weaviate_ok = ping_weaviate(getattr(request.app.state, "weaviate", None))
    return {  # Return a simple JSON payload that indicates the service is up and provides basic metadata
        "status": "ok",  # Conventional health indicator for load balancers/uptime checks
        "service": s.app_name,  # Human-readable service name (from env var APP_NAME or default)
        "env": s.env,  # Current environment name (from env var ENV or default)
        "version": s.service_version,  # Service version string (from env var SERVICE_VERSION or default)
        "time": datetime.now(
            timezone.utc
        ).isoformat(),  # Current UTC time as an ISO-8601 string
        "redis_ok": redis_ok,
        "weaviate_ok": weaviate_ok,
    }
