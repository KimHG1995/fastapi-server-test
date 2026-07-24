from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import AuthenticationError, decode_access_token
from app.db.session import get_session
from app.modules.users.models import User
from app.modules.users.repository import UserRepository

bearer_scheme = HTTPBearer(auto_error=False, bearerFormat="JWT")


async def get_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> User:
    if credentials is None:
        raise AuthenticationError

    settings = cast(Settings, request.app.state.settings)
    claims = decode_access_token(credentials.credentials, settings)
    user = await UserRepository(session).get_by_id(claims.sub)
    if user is None or not user.is_active:
        raise AuthenticationError
    return user
