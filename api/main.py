from api.event_loop import configure_windows_event_loop

configure_windows_event_loop()

import asyncio  # Used to run blocking Weaviate client bootstrap off the asyncio event loop
import httpx  # Shared async HTTP client for FHIR server calls (Section B)
from contextlib import (
    asynccontextmanager,
)  # Lets us define FastAPI startup/shutdown lifecycle via an async context manager
from pathlib import Path

from fastapi import FastAPI  # FastAPI application object and ASGI entrypoint
from fastapi.middleware.cors import (
    CORSMiddleware,
)  # Middleware to control cross-origin requests (browser clients)
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text  # Lightweight DB connectivity check at startup

from api.settings import (
    Settings,
)  # Central configuration loaded from environment variables / .env
from api.logging import (
    configure_logging,
    get_logger,
)  # Logging setup + a named logger for app-wide structured logs
from api.middleware.errors import (
    ErrorMiddleware,
)  # Middleware that adds request IDs + logs + catches unhandled exceptions
from api.middleware.redis_session import (
    RedisSessionMiddleware,
)  # Signed cookie + Redis payload for browseable sessions
from api.redis_client import (
    create_async_redis,
    ping_redis,
)  # Redis client wiring + ping helper shared with /health
from api.llm.openrouter_client import (
    OpenRouterClient,
)  # Async OpenRouter chat client for tier-routed LLM calls
from api.routes.auth import (
    router as auth_router,
)  # OAuth2 password grant + JWT refresh (P0#13)
from api.routes.fhir import router as fhir_router  # FHIR R4 integration (Section B)
from api.routes.health import router as health_router  # Router that exposes GET /health
from api.routes.llm import (
    router as llm_router,
)  # Dev-only LLM smoke routes when playground is allowed
from api.routes.document_tasks import (
    router as document_tasks_router,
)  # Clinical Documentation intake (Section D)
from api.routes.rcm_tasks import (
    router as rcm_tasks_router,
)  # Revenue Cycle coding audit (Section E)
from api.routes.rcm_portal import router as rcm_portal_router  # RCM P1 admin APIs
from api.routes.notes import (
    router as notes_router,
)  # Note approval + FHIR write-back (Section D)
from api.routes.tasks import router as tasks_router  # Orchestrator task API (Section C)
from api.routes.ui import router as ui_router  # SOAP review UI helpers (Section J #100)
from api.checkpointing import (
    create_checkpoint_pool,
    setup_async_postgres_checkpointer,
)
from api.graphs.orchestrator.graph import compile_orchestrator_graph
from langgraph.checkpoint.memory import MemorySaver
from db.session import (
    create_engine,
    create_session_factory,
)  # Shared async DB engine + sessions
from api.vectorstore.client import (
    close_weaviate_client,
    open_weaviate_client,
    ping_weaviate,
)  # Weaviate connection helpers
from api.vectorstore.collections import (
    ensure_healthos_collections,
)  # Idempotent schema creation for MVP collections
from api.services.rcm_payer_seed import seed_payer_rules_if_needed
from api.observability.langfuse_client import (
    flush_langfuse,
)  # Flush Langfuse spans on shutdown when tracing is enabled


def _bootstrap_weaviate(settings: Settings):
    client = open_weaviate_client(settings)
    ensure_healthos_collections(client)
    return client


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = (
        app.state.settings
    )  # Retrieve Settings stored on app.state during app creation
    logger = get_logger()  # Use the app's named logger (configured for JSON output)
    logger.info(  # Emit a structured "starting" event for observability
        "app_starting",
        extra={
            "env": settings.env,
            "service": settings.app_name,
            "version": settings.service_version,
        },
    )
    redis = create_async_redis(
        settings.redis_url
    )  # Singleton async Redis client reused per request via app.state.redis
    app.state.redis = redis  # RedisSessionMiddleware and route handlers resolve this attribute at request time
    if not await ping_redis(
        redis
    ):  # Fail fast so the API never silently runs without persistence primitives
        await redis.aclose()  # Close the transient client before aborting startup
        raise RuntimeError(f"Redis not reachable at {settings.redis_url!r}")
    app.state.fhir_http = httpx.AsyncClient(
        timeout=httpx.Timeout(60.0),
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    )
    try:
        weaviate_client = await asyncio.to_thread(
            _bootstrap_weaviate, settings
        )  # Sync client; avoid blocking the loop
    except Exception as exc:
        await redis.aclose()
        raise RuntimeError(
            f"Weaviate bootstrap failed ({settings.weaviate_http_host}:{settings.weaviate_http_port}). "
            "Ensure the container is up and on server >= 1.27 for weaviate-client 4.21."
        ) from exc
    if not ping_weaviate(weaviate_client):
        close_weaviate_client(weaviate_client)
        await redis.aclose()
        raise RuntimeError("Weaviate connected but is_ready() returned false")
    try:
        await asyncio.to_thread(seed_payer_rules_if_needed, weaviate_client)
    except Exception:
        logger.exception("payer_rules_seed_failed")
    app.state.weaviate = weaviate_client  # Used by /health and future RAG routes
    app.state.openrouter = OpenRouterClient(
        settings
    )  # Shared OpenRouter HTTP client for /llm smoke tests and future agents
    if settings.orchestrator_checkpoint_backend == "memory":
        checkpointer = MemorySaver()
        app.state.checkpoint_pool = None
    else:
        checkpoint_pool = await create_checkpoint_pool(settings)
        app.state.checkpoint_pool = checkpoint_pool
        checkpointer = await setup_async_postgres_checkpointer(checkpoint_pool)
    app.state.orchestrator_checkpointer = checkpointer
    db_engine = create_engine(settings)
    app.state.db_engine = db_engine
    app.state.session_factory = create_session_factory(db_engine)
    async with db_engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    app.state.orchestrator_graph = compile_orchestrator_graph(
        checkpointer,
        settings=settings,
        openrouter=app.state.openrouter,
        session_factory=app.state.session_factory,
        weaviate_client=weaviate_client,
    )
    if settings.langfuse_tracing_enabled:
        logger.info(
            "langfuse_tracing_enabled",
            extra={"base_url": settings.langfuse_base_url},
        )
    try:
        yield  # Hand control back to FastAPI while Redis + Weaviate stay connected
    finally:
        try:
            flush_langfuse(settings)
        except Exception:
            logger.exception("langfuse_flush_failed")
        openrouter: OpenRouterClient | None = getattr(app.state, "openrouter", None)
        if openrouter is not None:
            await openrouter.aclose()
        close_weaviate_client(getattr(app.state, "weaviate", None))
        db_engine = getattr(app.state, "db_engine", None)
        if db_engine is not None:
            await db_engine.dispose()
        fh: httpx.AsyncClient | None = getattr(app.state, "fhir_http", None)
        if fh is not None:
            await fh.aclose()
        cp_pool = getattr(app.state, "checkpoint_pool", None)
        if cp_pool is not None:
            await cp_pool.close()
        await redis.aclose()  # Release sockets when uvicorn shuts down so reloads/tests do not leak connections
        logger.info(  # Emit a structured "shutting down" event when the app stops
            "app_shutting_down",
            extra={
                "env": settings.env,
                "service": settings.app_name,
                "version": settings.service_version,
            },
        )


def create_app() -> FastAPI:
    settings = (
        Settings()
    )  # Load configuration (reads from environment variables and optionally .env)
    configure_logging(
        settings
    )  # Configure global/root logging early so all subsequent logs are structured JSON

    app = FastAPI(  # Create the FastAPI app instance
        title=settings.app_name,  # Shows up in OpenAPI/Swagger UI as the API title
        version=settings.service_version,  # Exposed via OpenAPI schema and can be returned in health checks
        lifespan=lifespan,  # Hooks startup/shutdown behavior using the async context manager above
    )
    app.state.settings = settings  # Store settings on app.state so route handlers can access it via Request.app.state

    app.add_middleware(
        ErrorMiddleware
    )  # Inner layer: attaches request IDs, logs errors/failures globally

    app.add_middleware(
        RedisSessionMiddleware,  # Persists Mutable session dictionaries in Redis instead of stuffing them into cookies
        fastapi_app=app,
    )

    app.add_middleware(
        CORSMiddleware,  # Outermost in this stack — handles preflight and CORS wrapping first
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router)  # POST /auth/token, /auth/refresh; GET /auth/me
    app.include_router(fhir_router)  # /integrations/fhir/* (Section B)
    app.include_router(
        document_tasks_router
    )  # POST /tasks/document — must register before /tasks/{id}
    app.include_router(rcm_tasks_router)  # POST /tasks/code-audit (Section E)
    app.include_router(tasks_router)  # POST/GET /tasks — orchestrator (Section C)
    app.include_router(rcm_portal_router)  # Section E P1 — /rcm/*
    app.include_router(notes_router)  # POST /notes/{id}/approve
    app.include_router(ui_router)  # GET /ui/encounters, POST /ui/demo/bootstrap
    app.include_router(health_router)  # Register the health router (adds GET /health)

    ui_dir = Path(__file__).resolve().parents[1] / "ui"
    if ui_dir.is_dir():
        app.mount("/ui", StaticFiles(directory=str(ui_dir), html=True), name="ui")
    if settings.llm_playground_allowed:
        app.include_router(
            llm_router
        )  # Tier smoke tests: GET /llm/models, POST /llm/infer

    return app  # Return the configured FastAPI app instance


app = create_app()  # Module-level ASGI app object (e.g. uvicorn loads "api.main:app")
