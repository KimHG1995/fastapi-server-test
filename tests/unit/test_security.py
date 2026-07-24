import base64
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from pytest import MonkeyPatch

from app.core.config import Settings
from app.core.security import (
    AuthenticationError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_password_async,
    hash_refresh_token,
    verify_password,
    verify_password_async,
)
from app.modules.users.models import User, UserRole


def _user() -> User:
    return User(
        id=UUID("2ff2e20e-3ce0-4e44-993f-da9614303de1"),
        email="learner@example.com",
        password_hash="unused",  # noqa: S106
        display_name="Learner",
        role=UserRole.USER,
        is_active=True,
    )


def test_password_hash_uses_argon2_and_verifies() -> None:
    encoded = hash_password("correct-horse-battery-staple")

    assert encoded.startswith("$argon2")
    assert verify_password("correct-horse-battery-staple", encoded)
    assert not verify_password("wrong-password", encoded)


def test_refresh_token_contains_256_bits_of_entropy() -> None:
    token = generate_refresh_token()

    assert len(base64.urlsafe_b64decode(token + "==")) == 32
    assert hash_refresh_token(token) == hashlib.sha256(token.encode()).hexdigest()


async def test_async_password_helpers_offload_cpu_work_to_a_thread(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[tuple[Callable[..., object], tuple[object, ...]]] = []

    async def fake_to_thread(
        function: Callable[..., object],
        *args: object,
        **kwargs: Any,
    ) -> object:
        assert not kwargs
        calls.append((function, args))
        return function(*args)

    monkeypatch.setattr("app.core.security.asyncio.to_thread", fake_to_thread)

    encoded = await hash_password_async("correct-horse-battery-staple")
    verified = await verify_password_async("correct-horse-battery-staple", encoded)

    assert verified
    assert calls == [
        (hash_password, ("correct-horse-battery-staple",)),
        (verify_password, ("correct-horse-battery-staple", encoded)),
    ]


def test_access_token_contains_required_claims(test_settings: Settings) -> None:
    now = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)

    token = create_access_token(_user(), test_settings, now=now)
    payload = jwt.decode(
        token,
        test_settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        options={"verify_exp": False, "verify_iat": False},
    )

    assert payload["sub"] == "2ff2e20e-3ce0-4e44-993f-da9614303de1"
    assert payload["role"] == "USER"
    assert payload["type"] == "access"
    assert UUID(payload["jti"])
    assert datetime.fromtimestamp(payload["iat"], UTC) == now
    assert datetime.fromtimestamp(payload["exp"], UTC) == now + timedelta(minutes=15)


def test_decode_access_token_returns_typed_claims(test_settings: Settings) -> None:
    now = datetime.now(UTC)
    token = create_access_token(_user(), test_settings, now=now)

    claims = decode_access_token(token, test_settings)

    assert claims.sub == _user().id
    assert claims.role is UserRole.USER
    assert claims.type == "access"
    assert claims.iat == now.replace(microsecond=0)
    assert claims.exp == (now + timedelta(minutes=15)).replace(microsecond=0)


@pytest.mark.parametrize(
    ("payload", "algorithm"),
    [
        (
            {
                "sub": str(uuid4()),
                "role": "USER",
                "type": "access",
                "jti": str(uuid4()),
                "iat": datetime.now(UTC),
            },
            "HS256",
        ),
        (
            {
                "sub": str(uuid4()),
                "role": "USER",
                "type": "refresh",
                "jti": str(uuid4()),
                "iat": datetime.now(UTC),
                "exp": datetime.now(UTC) + timedelta(minutes=5),
            },
            "HS256",
        ),
        (
            {
                "sub": str(uuid4()),
                "role": "USER",
                "type": "access",
                "jti": str(uuid4()),
                "iat": datetime.now(UTC) - timedelta(minutes=20),
                "exp": datetime.now(UTC) - timedelta(minutes=5),
            },
            "HS256",
        ),
        (
            {
                "sub": str(uuid4()),
                "role": "USER",
                "type": "access",
                "jti": str(uuid4()),
                "iat": datetime.now(UTC),
                "exp": datetime.now(UTC) + timedelta(minutes=5),
            },
            "none",
        ),
    ],
)
def test_invalid_access_tokens_raise_one_authentication_error(
    test_settings: Settings,
    payload: dict[str, object],
    algorithm: str,
) -> None:
    token = jwt.encode(
        payload,
        None if algorithm == "none" else test_settings.jwt_secret.get_secret_value(),
        algorithm=algorithm,
    )

    with pytest.raises(AuthenticationError) as raised:
        decode_access_token(token, test_settings)

    assert raised.value.code == "INVALID_ACCESS_TOKEN"
    assert raised.value.status_code == 401
    assert raised.value.headers == {"WWW-Authenticate": "Bearer"}
