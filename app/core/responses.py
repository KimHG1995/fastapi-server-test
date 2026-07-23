from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel


class ResponseMeta(BaseModel):
    timestamp: datetime
    path: str
    trace_id: UUID


class ApiResponse[T](BaseModel):
    success: Literal[True] = True
    data: T
    meta: ResponseMeta


def build_response[T](request: Request, data: T) -> ApiResponse[T]:
    return ApiResponse(
        data=data,
        meta=ResponseMeta(
            timestamp=datetime.now(UTC),
            path=request.url.path,
            trace_id=request.state.trace_id,
        ),
    )
