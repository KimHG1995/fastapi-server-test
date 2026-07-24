from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import register_exception_handlers
from app.core.middleware import RequestContextMiddleware
from app.core.security import create_access_token
from app.db.session import get_session
from app.modules.auth.dependencies import get_current_user
from app.modules.users.models import User, UserRole
from app.modules.users.repository import UserRepository


def _user(*, is_active: bool = True) -> User:
    now = datetime.now(UTC)
    return User(
        email="learner@example.com",
        password_hash="unused",  # noqa: S106
        display_name="Learner",
        role=UserRole.USER,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )


def _test_app(settings: Settings) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, object())

    app.dependency_overrides[get_session] = override_get_session

    @app.get("/protected")
    async def protected(
        user: Annotated[User, Depends(get_current_user)],
    ) -> dict[str, str]:
        return {"email": user.email}

    return app


async def _get(
    settings: Settings,
    authorization: str | None,
) -> tuple[int, str | None, dict[str, object]]:
    headers = {} if authorization is None else {"Authorization": authorization}
    async with AsyncClient(
        transport=ASGITransport(app=_test_app(settings)),
        base_url="http://test",
    ) as client:
        response = await client.get("/protected", headers=headers)
    return response.status_code, response.headers.get("www-authenticate"), response.json()


@pytest.mark.parametrize("authorization", [None, "Basic abc123"])
async def test_missing_or_non_bearer_credentials_return_bearer_401(
    test_settings: Settings,
    authorization: str | None,
) -> None:
    status_code, authenticate, body = await _get(test_settings, authorization)

    assert status_code == 401
    assert authenticate == "Bearer"
    assert body["code"] == "INVALID_ACCESS_TOKEN"


async def test_invalid_or_expired_jwt_returns_bearer_401(
    test_settings: Settings,
) -> None:
    user = _user()
    user.id = uuid4()
    expired = create_access_token(
        user,
        test_settings,
        now=datetime.now(UTC) - timedelta(hours=1),
    )

    invalid_result = await _get(test_settings, "Bearer invalid-token")
    expired_result = await _get(test_settings, f"Bearer {expired}")

    for status_code, authenticate, body in (invalid_result, expired_result):
        assert status_code == 401
        assert authenticate == "Bearer"
        assert body["code"] == "INVALID_ACCESS_TOKEN"


@pytest.mark.parametrize("stored_user", [None, _user(is_active=False)])
async def test_missing_or_inactive_user_returns_bearer_401(
    test_settings: Settings,
    monkeypatch: MonkeyPatch,
    stored_user: User | None,
) -> None:
    token_user = _user()
    token_user.id = uuid4()
    token = create_access_token(token_user, test_settings)

    async def fake_get_by_id(
        repository: UserRepository,
        user_id: object,
    ) -> User | None:
        del repository, user_id
        return stored_user

    monkeypatch.setattr(UserRepository, "get_by_id", fake_get_by_id)

    status_code, authenticate, body = await _get(test_settings, f"Bearer {token}")

    assert status_code == 401
    assert authenticate == "Bearer"
    assert body["code"] == "INVALID_ACCESS_TOKEN"
