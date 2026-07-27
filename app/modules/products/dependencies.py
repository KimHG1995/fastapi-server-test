from typing import Annotated

from fastapi import Depends

from app.core.errors import AppError
from app.modules.auth.dependencies import get_current_user
from app.modules.users.models import User, UserRole


class ForbiddenError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="FORBIDDEN",
            status_code=403,
            title="Forbidden",
            detail="Administrator role is required.",
            type_slug="forbidden",
        )


async def require_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if current_user.role is not UserRole.ADMIN:
        raise ForbiddenError
    return current_user
