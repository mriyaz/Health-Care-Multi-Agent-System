import time  # Used to measure request duration
import uuid  # Used to generate a unique request ID when one is not provided by the client/proxy
import logging  # Standard Python logging
from starlette.middleware.base import (
    BaseHTTPMiddleware,
)  # Base class for building ASGI/Starlette middleware
from starlette.requests import (
    Request,
)  # Request object with method, headers, URL, and app reference
from starlette.responses import (
    JSONResponse,
)  # Convenience response class for JSON payloads

logger = logging.getLogger(
    "healthos.api"
)  # Named logger (configured to emit structured JSON in api/logging.py)


class ErrorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or str(
            uuid.uuid4()
        )  # Use inbound ID or generate one
        start = (
            time.perf_counter()
        )  # High-resolution timer start for latency measurement

        try:
            response = await call_next(
                request
            )  # Call the downstream handler chain (next middleware + route)
        except Exception:
            logger.exception(  # Log the full stack trace for unexpected errors
                "unhandled_exception",
                extra={  # Add request context fields for correlation in logs
                    "request_id": request_id,
                    "method": request.method,
                    "path": str(request.url.path),
                },
            )
            return JSONResponse(
                status_code=500,  # Generic internal server error
                content={  # Stable error envelope clients can rely on
                    "error": {
                        "type": "internal_server_error",
                        "message": "Internal server error",
                        "request_id": request_id,
                    }
                },
                headers={
                    "X-Request-Id": request_id
                },  # Echo request ID back to clients for debugging
            )

        duration_ms = int(
            (time.perf_counter() - start) * 1000
        )  # Convert elapsed time to milliseconds
        logger.info(  # Log a structured access log entry for every request
            "request_completed",
            extra={
                "request_id": request_id,  # Correlation ID for linking request logs and error logs
                "method": request.method,  # HTTP method (GET/POST/etc.)
                "path": str(request.url.path),  # Request path (e.g. /health)
                "status_code": response.status_code,  # Response status code (200/404/500/etc.)
                "duration_ms": duration_ms,  # Request duration in milliseconds
            },
        )
        response.headers["X-Request-Id"] = (
            request_id  # Ensure the response always includes a request ID header
        )
        return (
            response  # Return the downstream response untouched (aside from the header)
        )
