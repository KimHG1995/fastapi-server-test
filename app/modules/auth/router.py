from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import problem_responses
from app.core.responses import ApiResponse, build_response
from app.db.session import get_session
from app.modules.auth.schemas import LoginRequest, RegisterRequest, TokenPair
from app.modules.auth.service import AuthService
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiResponse[UserRead],
    responses=problem_responses(409, 422),
)
async def register(
    request: Request,
    payload: RegisterRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApiResponse[UserRead]:
    settings = cast(Settings, request.app.state.settings)
    user = await AuthService(session, settings).register(payload)
    return build_response(request, user)


@router.post(
    "/login",
    response_model=ApiResponse[TokenPair],
    responses=problem_responses(401, 422),
)
async def login(
    request: Request,
    payload: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApiResponse[TokenPair]:
    settings = cast(Settings, request.app.state.settings)
    token_pair = await AuthService(session, settings).login(payload)
    return build_response(request, token_pair)
