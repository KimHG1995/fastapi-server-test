from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import problem_responses
from app.core.responses import ApiResponse, build_response
from app.db.session import get_session
from app.modules.auth.dependencies import get_current_user
from app.modules.users.models import User
from app.modules.users.schemas import (
    ChangePasswordRequest,
    UpdateProfileRequest,
    UserRead,
)
from app.modules.users.service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=ApiResponse[UserRead],
    responses=problem_responses(401),
)
async def get_current(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApiResponse[UserRead]:
    user = UserService(session).get_current(current_user)
    return build_response(request, user)


@router.patch(
    "/me",
    response_model=ApiResponse[UserRead],
    responses=problem_responses(401, 422),
)
async def update_profile(
    request: Request,
    payload: UpdateProfileRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApiResponse[UserRead]:
    user = await UserService(session).update_profile(current_user.id, payload)
    return build_response(request, user)


@router.post(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=problem_responses(400, 401, 422),
)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    await UserService(session).change_password(current_user, payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
