"""
FastAPI Middleware for Request ID Tracking and Performance Observability.

Injects/extracts a unique request_id for each API invocation,
binds it to the request's contextvars, tracks total request latency,
and adds the X-Request-ID header to the HTTP response.
"""
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from observability.context import generate_request_id, set_request_id, reset_request_id
from observability.logging import get_structured_logger
from observability.metrics import get_metrics_collector

logger = get_structured_logger()
metrics = get_metrics_collector()


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware that manages request_id lifecycle:
    1. Extracts 'X-Request-ID' header or generates a fresh one.
    2. Binds request_id to contextvars for deep call propagation.
    3. Records request latency into the metrics registry.
    4. Attaches 'X-Request-ID' header to the response.
    """
    async def dispatch(self, request: Request, call_next) -> Response:
        header_req_id = request.headers.get("X-Request-ID") or request.headers.get("x-request-id")
        request_id = header_req_id.strip() if header_req_id else generate_request_id()

        request.state.request_id = request_id
        token = set_request_id(request_id)
        start_time = time.perf_counter()

        # Log request receipt
        logger.info(
            event="api_request_started",
            stage="api",
            request_id=request_id,
            status="STARTED",
            path=request.url.path,
            method=request.method,
        )

        try:
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start_time) * 1000.0

            # Record total request duration metric
            metrics.record_request_duration(duration_ms)

            # Log request completion
            logger.info(
                event="api_request_completed",
                stage="api",
                request_id=request_id,
                duration_ms=duration_ms,
                status=str(response.status_code),
                path=request.url.path,
                method=request.method,
            )

            # Propagate back to client in response header
            response.headers["X-Request-ID"] = request_id
            return response

        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            metrics.record_request_duration(duration_ms)

            logger.error(
                event="api_request_failed",
                stage="api",
                request_id=request_id,
                duration_ms=duration_ms,
                status="ERROR",
                path=request.url.path,
                method=request.method,
                error=str(exc),
            )
            raise
        finally:
            reset_request_id(token)
