"""Request / response logging middleware with trace-ID propagation."""

import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.logging import get_logger
from app.utils.trace_id import bind_trace_id, clear_trace_context

logger = get_logger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    """Logs every request with method, path, status code, and latency."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        trace_id = bind_trace_id(request.headers.get("X-Trace-ID"))
        start = time.perf_counter()

        logger.info("request_started", method=request.method, path=request.url.path)

        try:
            response = await call_next(request)
        except Exception:
            logger.exception("request_failed", method=request.method, path=request.url.path)
            raise
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status=getattr(response, "status_code", 500) if "response" in dir() else 500,
                latency_ms=elapsed_ms,
            )
            response.headers["X-Trace-ID"] = trace_id
            clear_trace_context()

        return response
