"""Request middleware: body-size guard, structured logging, and metrics.

Logs one structured line per request with method, path, status, latency, and a
request id (also returned as `X-Request-ID` for correlation), records Prometheus
metrics, and rejects oversized requests before their body is read.
"""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings
from app.logging_config import request_id_ctx
from app.metrics import http_request_duration_seconds, http_requests_total

logger = logging.getLogger("taskpilot.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self._max_request_bytes = get_settings().max_request_bytes

    def _endpoint(self, request: Request) -> str:
        # Use the route template (e.g. /tasks/{task_id}) to keep label
        # cardinality bounded; fall back to the raw path if routing missed.
        route = request.scope.get("route")
        return getattr(route, "path", request.url.path)

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        token = request_id_ctx.set(request_id)
        start = time.perf_counter()

        # Reject oversized bodies up front (bounds memory; cheap header check).
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self._max_request_bytes:
                    request_id_ctx.reset(token)
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "code": "payload_too_large",
                                "message": "Request body exceeds the maximum allowed size.",
                            }
                        },
                        headers={"X-Request-ID": request_id},
                    )
            except ValueError:
                pass

        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000
            endpoint = self._endpoint(request)
            http_requests_total.labels(request.method, endpoint, 500).inc()
            http_request_duration_seconds.labels(request.method, endpoint).observe(
                elapsed_ms / 1000
            )
            logger.exception(
                "request_failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "latency_ms": round(elapsed_ms, 2),
                },
            )
            request_id_ctx.reset(token)
            raise

        elapsed_ms = (time.perf_counter() - start) * 1000
        endpoint = self._endpoint(request)
        http_requests_total.labels(request.method, endpoint, response.status_code).inc()
        http_request_duration_seconds.labels(request.method, endpoint).observe(elapsed_ms / 1000)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "latency_ms": round(elapsed_ms, 2),
            },
        )
        request_id_ctx.reset(token)
        return response
