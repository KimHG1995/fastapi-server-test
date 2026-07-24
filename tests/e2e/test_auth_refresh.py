from typing import cast

from httpx import AsyncClient

REGISTER_BODY = {
    "email": "learner@example.com",
    "password": "correct-horse-battery-staple",
    "display_name": "Learner",
}
LOGIN_BODY = {
    "email": "learner@example.com",
    "password": "correct-horse-battery-staple",
}


async def _register_and_login(client: AsyncClient) -> dict[str, str | int]:
    registration = await client.post("/api/v1/auth/register", json=REGISTER_BODY)
    assert registration.status_code == 201
    login = await client.post("/api/v1/auth/login", json=LOGIN_BODY)
    assert login.status_code == 200
    return cast(dict[str, str | int], login.json()["data"])


async def test_refresh_reuse_revokes_replacement_and_returns_problem_details(
    client: AsyncClient,
) -> None:
    original = await _register_and_login(client)

    rotated = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": original["refresh_token"]},
    )
    reused = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": original["refresh_token"]},
    )
    replacement_after_reuse = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": rotated.json()["data"]["refresh_token"]},
    )

    assert rotated.status_code == 200
    assert rotated.json()["success"] is True
    assert rotated.json()["data"]["refresh_token"] != original["refresh_token"]
    assert reused.status_code == 401
    assert reused.headers["content-type"].startswith("application/problem+json")
    assert reused.json()["code"] == "REFRESH_TOKEN_REUSED"
    assert replacement_after_reuse.status_code == 401
    assert replacement_after_reuse.json()["code"] == "REFRESH_TOKEN_REUSED"


async def test_logout_is_idempotent_for_known_token_but_rejects_unknown_token(
    client: AsyncClient,
) -> None:
    pair = await _register_and_login(client)
    payload = {"refresh_token": pair["refresh_token"]}

    first = await client.post("/api/v1/auth/logout", json=payload)
    second = await client.post("/api/v1/auth/logout", json=payload)
    refresh_after_logout = await client.post("/api/v1/auth/refresh", json=payload)
    unknown = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": "unknown-refresh-token"},
    )

    assert first.status_code == 200
    assert first.json()["data"] == {"logged_out": True}
    assert second.status_code == 200
    assert second.json()["data"] == {"logged_out": True}
    assert refresh_after_logout.status_code == 401
    assert refresh_after_logout.json()["code"] == "REFRESH_TOKEN_REUSED"
    assert unknown.status_code == 401
    assert unknown.headers["content-type"].startswith("application/problem+json")
    assert unknown.json()["code"] == "INVALID_REFRESH_TOKEN"


async def test_logout_all_requires_bearer_and_revokes_every_session(
    client: AsyncClient,
) -> None:
    first = await _register_and_login(client)
    second_login = await client.post("/api/v1/auth/login", json=LOGIN_BODY)
    assert second_login.status_code == 200
    second = second_login.json()["data"]

    unauthenticated = await client.post("/api/v1/auth/logout-all")
    logged_out = await client.post(
        "/api/v1/auth/logout-all",
        headers={"Authorization": f"Bearer {first['access_token']}"},
    )
    first_refresh = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first["refresh_token"]},
    )
    second_refresh = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": second["refresh_token"]},
    )

    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["www-authenticate"] == "Bearer"
    assert unauthenticated.json()["code"] == "INVALID_ACCESS_TOKEN"
    assert logged_out.status_code == 200
    assert logged_out.json()["data"] == {"logged_out": True}
    assert first_refresh.status_code == 401
    assert second_refresh.status_code == 401
    assert first_refresh.json()["code"] == "REFRESH_TOKEN_REUSED"
    assert second_refresh.json()["code"] == "REFRESH_TOKEN_REUSED"


async def test_refresh_and_logout_openapi_contracts(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()

    assert "security" not in schema["paths"]["/api/v1/auth/refresh"]["post"]
    assert "security" not in schema["paths"]["/api/v1/auth/logout"]["post"]
    assert schema["paths"]["/api/v1/auth/logout-all"]["post"]["security"] == [{"HTTPBearer": []}]
    for path in (
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/logout-all",
    ):
        operation = schema["paths"][path]["post"]
        assert "200" in operation["responses"]
        assert "401" in operation["responses"]
