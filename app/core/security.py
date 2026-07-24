import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

import jwt
from jwt.exceptions import PyJWTError
from pwdlib import PasswordHash
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.users.models import User, UserRole

ALGORITHM = "HS256"
_PASSWORD_HASH = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = _PASSWORD_HASH.hash("dummy-password-used-for-login-timing")


class AuthenticationError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="INVALID_ACCESS_TOKEN",
            status_code=401,
            title="Unauthorized",
            detail="Authentication credentials are invalid.",
            type_slug="invalid-access-token",
            headers={"WWW-Authenticate": "Bearer"},
        )


class AccessTokenClaims(BaseModel):
    sub: UUID
    role: UserRole
    type: Literal["access"]
    jti: UUID
    iat: datetime
    exp: datetime


def hash_password(password: str) -> str:
    return _PASSWORD_HASH.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _PASSWORD_HASH.verify(password, password_hash)


def create_access_token(
    user: User,
    settings: Settings,
    now: datetime | None = None,
) -> str:
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + timedelta(minutes=settings.access_token_ttl_minutes)
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "type": "access",
        "jti": str(uuid4()),
        "iat": issued_at,
        "exp": expires_at,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=ALGORITHM,
    )


def decode_access_token(token: str, settings: Settings) -> AccessTokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[ALGORITHM],
            options={
                "require": ["sub", "role", "type", "jti", "iat", "exp"],
            },
        )
        return AccessTokenClaims.model_validate(payload)
    except (PyJWTError, ValidationError, ValueError, TypeError) as exc:
        raise AuthenticationError from exc


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
