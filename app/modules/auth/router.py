from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import problem_responses
from app.core.responses import ApiResponse, build_response
from app.db.session import get_session
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import (
    LoginRequest,
    LogoutResult,
    RefreshTokenRequest,
    RegisterRequest,
    TokenPair,
)
from app.modules.auth.service import AuthService
from app.modules.users.models import User
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


@router.post(
    "/refresh",
    response_model=ApiResponse[TokenPair],
    responses=problem_responses(401, 422),
)
async def refresh(
    request: Request,
    payload: RefreshTokenRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApiResponse[TokenPair]:
    settings = cast(Settings, request.app.state.settings)
    token_pair = await AuthService(session, settings).refresh(payload)
    return build_response(request, token_pair)


@router.post(
    "/logout",
    response_model=ApiResponse[LogoutResult],
    responses=problem_responses(401, 422),
)
async def logout(
    request: Request,
    payload: RefreshTokenRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApiResponse[LogoutResult]:
    settings = cast(Settings, request.app.state.settings)
    result = await AuthService(session, settings).logout(payload)
    return build_response(request, result)


@router.post(
    "/logout-all",
    response_model=ApiResponse[LogoutResult],
    responses=problem_responses(401),
)
async def logout_all(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApiResponse[LogoutResult]:
    settings = cast(Settings, request.app.state.settings)
    result = await AuthService(session, settings).logout_all(current_user.id)
    return build_response(request, result)
