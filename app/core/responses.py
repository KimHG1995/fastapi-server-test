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


class PageMeta(ResponseMeta):
    page: int
    page_size: int
    total: int
    total_pages: int


class PaginatedResponse[T](BaseModel):
    success: Literal[True] = True
    data: list[T]
    meta: PageMeta


def build_response[T](request: Request, data: T) -> ApiResponse[T]:
    return ApiResponse(
        data=data,
        meta=ResponseMeta(
            timestamp=datetime.now(UTC),
            path=request.url.path,
            trace_id=request.state.trace_id,
        ),
    )


def build_page_response[T](
    request: Request,
    items: list[T],
    page: int,
    page_size: int,
    total: int,
) -> PaginatedResponse[T]:
    total_pages = 0 if total == 0 else (total + page_size - 1) // page_size
    return PaginatedResponse(
        data=items,
        meta=PageMeta(
            timestamp=datetime.now(UTC),
            path=request.url.path,
            trace_id=request.state.trace_id,
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
        ),
    )
