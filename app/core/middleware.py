from uuid import UUID, uuid4

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        trace_id = self._get_trace_id(request.headers.get("x-request-id"))
        request.state.trace_id = trace_id
        structlog.contextvars.bind_contextvars(trace_id=str(trace_id))
        try:
            response = await call_next(request)
            response.headers["x-request-id"] = str(trace_id)
            return response
        finally:
            structlog.contextvars.clear_contextvars()

    @staticmethod
    def _get_trace_id(value: str | None) -> UUID:
        if value is None:
            return uuid4()
        try:
            return UUID(value)
        except ValueError:
            return uuid4()
