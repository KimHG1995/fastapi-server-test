from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import RefreshToken
from app.modules.users.models import User


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def add_user(self, user: User) -> User:
        self._session.add(user)
        await self._session.flush()
        return user

    async def add_refresh_token(self, refresh_token: RefreshToken) -> RefreshToken:
        self._session.add(refresh_token)
        await self._session.flush()
        return refresh_token
