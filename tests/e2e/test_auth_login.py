from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

REGISTER_BODY = {
    "email": "Learner@Example.COM",
    "password": "correct-horse-battery-staple",
    "display_name": " Learner ",
}


def _contains_password_field(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            "password" in str(key).lower() or _contains_password_field(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_password_field(item) for item in value)
    return False


async def test_register_and_login_return_typed_success_envelopes(
    client: AsyncClient,
) -> None:
    register = await client.post("/api/v1/auth/register", json=REGISTER_BODY)

    assert register.status_code == 201
    register_body = register.json()
    assert register_body["success"] is True
    assert register_body["data"]["email"] == "learner@example.com"
    assert register_body["data"]["display_name"] == "Learner"
    assert register_body["data"]["role"] == "USER"
    assert register_body["meta"]["path"] == "/api/v1/auth/register"
    assert not _contains_password_field(register_body)

    login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": " LEARNER@example.com ",
            "password": "correct-horse-battery-staple",
        },
    )

    assert login.status_code == 200
    login_body = login.json()
    assert login_body["success"] is True
    assert login_body["data"]["token_type"] == "bearer"  # noqa: S105
    assert login_body["data"]["expires_in"] == 900
    assert login_body["data"]["access_token"]
    assert login_body["data"]["refresh_token"]
    assert login_body["meta"]["path"] == "/api/v1/auth/login"
    assert not _contains_password_field(login_body)


async def test_duplicate_registration_returns_email_conflict(
    client: AsyncClient,
) -> None:
    first = await client.post("/api/v1/auth/register", json=REGISTER_BODY)
    duplicate = await client.post(
        "/api/v1/auth/register",
        json={**REGISTER_BODY, "email": " learner@example.com "},
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.headers["content-type"].startswith("application/problem+json")
    assert duplicate.json()["code"] == "EMAIL_ALREADY_EXISTS"


async def test_unknown_email_and_bad_password_return_same_public_error(
    client: AsyncClient,
) -> None:
    registered = await client.post("/api/v1/auth/register", json=REGISTER_BODY)
    assert registered.status_code == 201

    unknown = await client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": "wrong-password"},
    )
    bad_password = await client.post(
        "/api/v1/auth/login",
        json={"email": "learner@example.com", "password": "wrong-password"},
    )

    assert unknown.status_code == bad_password.status_code == 401
    assert unknown.headers["www-authenticate"] == "Bearer"
    assert bad_password.headers["www-authenticate"] == "Bearer"
    public_fields = ("code", "status", "title", "detail", "type")
    assert {key: unknown.json()[key] for key in public_fields} == {
        key: bad_password.json()[key] for key in public_fields
    }
    assert unknown.json()["code"] == "INVALID_CREDENTIALS"


async def test_openapi_declares_http_bearer_authentication(
    test_settings: Settings,
) -> None:
    app = create_app(test_settings)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    bearer: dict[str, object] = schema["components"]["securitySchemes"]["HTTPBearer"]
    assert bearer["type"] == "http"
    assert bearer["scheme"] == "bearer"
    assert bearer["bearerFormat"] == "JWT"
    assert "security" not in schema["paths"]["/api/v1/auth/register"]["post"]
    assert "security" not in schema["paths"]["/api/v1/auth/login"]["post"]
