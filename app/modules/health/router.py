from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import problem_responses
from app.core.responses import ApiResponse, build_response
from app.db.session import get_session

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "/live",
    response_model=ApiResponse[dict[str, str]],
    responses=problem_responses(422, 500),
)
async def live(request: Request) -> ApiResponse[dict[str, str]]:
    return build_response(request, {"status": "ok"})


@router.get(
    "/ready",
    response_model=ApiResponse[dict[str, str]],
    responses=problem_responses(422, 500),
)
async def ready(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApiResponse[dict[str, str]]:
    await session.execute(text("SELECT 1"))
    return build_response(request, {"status": "ok"})
