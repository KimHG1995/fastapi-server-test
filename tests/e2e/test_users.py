from typing import cast

from httpx import AsyncClient

REGISTER_BODY = {
    "email": "learner@example.com",
    "password": "correct-horse-battery-staple",
    "display_name": "Learner",
}


async def _register_and_login(client: AsyncClient) -> dict[str, str | int]:
    registration = await client.post("/api/v1/auth/register", json=REGISTER_BODY)
    assert registration.status_code == 201
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": REGISTER_BODY["email"],
            "password": REGISTER_BODY["password"],
        },
    )
    assert login.status_code == 200
    return cast(dict[str, str | int], login.json()["data"])


def _authorization(pair: dict[str, str | int]) -> dict[str, str]:
    return {"Authorization": f"Bearer {pair['access_token']}"}


async def test_current_user_routes_require_bearer_authentication(
    client: AsyncClient,
) -> None:
    get_response = await client.get("/api/v1/users/me")
    patch_response = await client.patch(
        "/api/v1/users/me",
        json={"display_name": "New Name"},
    )
    password_response = await client.post(
        "/api/v1/users/me/password",
        json={
            "current_password": "correct-horse-battery-staple",
            "new_password": "new-correct-horse-battery-staple",
        },
    )

    for response in (get_response, patch_response, password_response):
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json()["code"] == "INVALID_ACCESS_TOKEN"


async def test_get_and_patch_current_profile_return_typed_public_user(
    client: AsyncClient,
) -> None:
    pair = await _register_and_login(client)
    headers = _authorization(pair)

    current = await client.get("/api/v1/users/me", headers=headers)
    updated = await client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"display_name": "  Updated Learner  "},
    )

    assert current.status_code == 200
    assert current.json()["data"]["email"] == "learner@example.com"
    assert current.json()["data"]["display_name"] == "Learner"
    assert "password_hash" not in current.json()["data"]
    assert updated.status_code == 200
    assert updated.json()["data"]["display_name"] == "Updated Learner"
    assert updated.json()["meta"]["path"] == "/api/v1/users/me"


async def test_profile_patch_rejects_identity_and_privilege_fields(
    client: AsyncClient,
) -> None:
    pair = await _register_and_login(client)

    response = await client.patch(
        "/api/v1/users/me",
        headers=_authorization(pair),
        json={
            "display_name": "Updated Learner",
            "email": "attacker@example.com",
            "role": "ADMIN",
            "is_active": False,
        },
    )
    current = await client.get(
        "/api/v1/users/me",
        headers=_authorization(pair),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    forbidden_fields = {error["field"] for error in response.json()["errors"]}
    assert forbidden_fields == {"body.email", "body.role", "body.is_active"}
    assert current.json()["data"]["email"] == "learner@example.com"
    assert current.json()["data"]["role"] == "USER"
    assert current.json()["data"]["is_active"] is True


async def test_wrong_current_password_does_not_change_password(
    client: AsyncClient,
) -> None:
    pair = await _register_and_login(client)

    response = await client.post(
        "/api/v1/users/me/password",
        headers=_authorization(pair),
        json={
            "current_password": "wrong-current-password",
            "new_password": "new-correct-horse-battery-staple",
        },
    )
    old_login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": REGISTER_BODY["email"],
            "password": REGISTER_BODY["password"],
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_CURRENT_PASSWORD"
    assert old_login.status_code == 200


async def test_password_change_rehashes_and_revokes_every_refresh_session(
    client: AsyncClient,
) -> None:
    first = await _register_and_login(client)
    second_login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": REGISTER_BODY["email"],
            "password": REGISTER_BODY["password"],
        },
    )
    assert second_login.status_code == 200
    second = cast(dict[str, str | int], second_login.json()["data"])

    changed = await client.post(
        "/api/v1/users/me/password",
        headers=_authorization(first),
        json={
            "current_password": REGISTER_BODY["password"],
            "new_password": "new-correct-horse-battery-staple",
        },
    )
    old_login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": REGISTER_BODY["email"],
            "password": REGISTER_BODY["password"],
        },
    )
    new_login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": REGISTER_BODY["email"],
            "password": "new-correct-horse-battery-staple",
        },
    )
    first_refresh = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first["refresh_token"]},
    )
    second_refresh = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": second["refresh_token"]},
    )

    assert changed.status_code == 204
    assert changed.content == b""
    assert old_login.status_code == 401
    assert new_login.status_code == 200
    assert first_refresh.status_code == 401
    assert second_refresh.status_code == 401
    assert first_refresh.json()["code"] == "REFRESH_TOKEN_REUSED"
    assert second_refresh.json()["code"] == "REFRESH_TOKEN_REUSED"


async def test_password_change_rejects_current_password_reuse(
    client: AsyncClient,
) -> None:
    pair = await _register_and_login(client)

    response = await client.post(
        "/api/v1/users/me/password",
        headers=_authorization(pair),
        json={
            "current_password": REGISTER_BODY["password"],
            "new_password": REGISTER_BODY["password"],
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "PASSWORD_REUSE_NOT_ALLOWED"


async def test_users_openapi_contracts(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()

    assert schema["paths"]["/api/v1/users/me"]["get"]["security"] == [{"HTTPBearer": []}]
    assert schema["paths"]["/api/v1/users/me"]["patch"]["security"] == [{"HTTPBearer": []}]
    password_operation = schema["paths"]["/api/v1/users/me/password"]["post"]
    assert password_operation["security"] == [{"HTTPBearer": []}]
    assert "204" in password_operation["responses"]
    assert "content" not in password_operation["responses"]["204"]
