from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, StringConstraints, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=12, max_length=128)]
    display_name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=80),
    ]

    @field_validator("email", mode="before")
    @classmethod
    def strip_email(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def strip_email(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int
