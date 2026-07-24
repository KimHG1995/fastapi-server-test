from typing import cast

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import Settings
from app.core.security import hash_password
from app.main import create_app
from app.modules.users.models import User, UserRole

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin-correct-horse-battery-staple"  # noqa: S105
USER_BODY = {
    "email": "user@example.com",
    "password": "user-correct-horse-battery-staple",
    "display_name": "Regular User",
}
PRODUCT_BODY = {
    "sku": " book-001 ",
    "name": " Async Python ",
    "description": "A server programming guide",
    "price_in_minor_units": 2500,
    "currency": "krw",
    "stock_quantity": 7,
    "is_active": True,
}


async def _login(
    client: AsyncClient,
    *,
    email: str,
    password: str,
) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    data = cast(dict[str, str], response.json()["data"])
    return {"Authorization": f"Bearer {data['access_token']}"}


async def _admin_headers(
    client: AsyncClient,
    engine: AsyncEngine,
) -> dict[str, str]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory.begin() as session:
        session.add(
            User(
                email=ADMIN_EMAIL,
                password_hash=hash_password(ADMIN_PASSWORD),
                display_name="Admin",
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
    return await _login(
        client,
        email=ADMIN_EMAIL,
        password=ADMIN_PASSWORD,
    )


async def _user_headers(client: AsyncClient) -> dict[str, str]:
    registered = await client.post("/api/v1/auth/register", json=USER_BODY)
    assert registered.status_code == 201
    return await _login(
        client,
        email=USER_BODY["email"],
        password=USER_BODY["password"],
    )


async def test_product_writes_require_an_active_administrator(
    client: AsyncClient,
    migrated_database: AsyncEngine,
) -> None:
    anonymous = await client.post("/api/v1/products", json=PRODUCT_BODY)
    user = await client.post(
        "/api/v1/products",
        headers=await _user_headers(client),
        json=PRODUCT_BODY,
    )
    admin = await client.post(
        "/api/v1/products",
        headers=await _admin_headers(client, migrated_database),
        json=PRODUCT_BODY,
    )

    assert anonymous.status_code == 401
    assert anonymous.headers["www-authenticate"] == "Bearer"
    assert anonymous.json()["code"] == "INVALID_ACCESS_TOKEN"
    assert user.status_code == 403
    assert user.json()["code"] == "FORBIDDEN"
    assert admin.status_code == 201
    assert admin.json()["data"]["sku"] == "BOOK-001"
    assert admin.json()["data"]["currency"] == "KRW"


async def test_admin_create_patch_and_soft_delete_product(
    client: AsyncClient,
    migrated_database: AsyncEngine,
) -> None:
    headers = await _admin_headers(client, migrated_database)
    created = await client.post(
        "/api/v1/products",
        headers=headers,
        json=PRODUCT_BODY,
    )
    product_id = created.json()["data"]["id"]

    public_before = await client.get(f"/api/v1/products/{product_id}")
    updated = await client.patch(
        f"/api/v1/products/{product_id}",
        headers=headers,
        json={
            "name": "  Updated Product  ",
            "description": None,
            "price_in_minor_units": 3000,
        },
    )
    deleted = await client.delete(
        f"/api/v1/products/{product_id}",
        headers=headers,
    )
    public_after = await client.get(f"/api/v1/products/{product_id}")
    repeated_delete = await client.delete(
        f"/api/v1/products/{product_id}",
        headers=headers,
    )

    assert created.status_code == 201
    assert public_before.status_code == 200
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "Updated Product"
    assert updated.json()["data"]["description"] is None
    assert updated.json()["data"]["sku"] == "BOOK-001"
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert public_after.status_code == 404
    assert public_after.json()["code"] == "PRODUCT_NOT_FOUND"
    assert repeated_delete.status_code == 404


async def test_product_input_contract_rejects_extra_sku_update_empty_and_fractional_price(
    client: AsyncClient,
    migrated_database: AsyncEngine,
) -> None:
    headers = await _admin_headers(client, migrated_database)
    extra = await client.post(
        "/api/v1/products",
        headers=headers,
        json={**PRODUCT_BODY, "created_by_id": "attacker-controlled"},
    )
    fractional = await client.post(
        "/api/v1/products",
        headers=headers,
        json={**PRODUCT_BODY, "price_in_minor_units": 25.5},
    )
    created = await client.post(
        "/api/v1/products",
        headers=headers,
        json=PRODUCT_BODY,
    )
    product_id = created.json()["data"]["id"]
    sku_update = await client.patch(
        f"/api/v1/products/{product_id}",
        headers=headers,
        json={"sku": "CHANGED"},
    )
    empty_update = await client.patch(
        f"/api/v1/products/{product_id}",
        headers=headers,
        json={},
    )

    for response in (extra, fractional, sku_update, empty_update):
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_FAILED"


async def test_public_list_search_pagination_and_visibility(
    client: AsyncClient,
    migrated_database: AsyncEngine,
) -> None:
    headers = await _admin_headers(client, migrated_database)
    requests = [
        {**PRODUCT_BODY, "sku": "PYTHON-002", "name": "Python Two"},
        {**PRODUCT_BODY, "sku": "PYTHON-001", "name": "Python One"},
        {
            **PRODUCT_BODY,
            "sku": "HIDDEN-001",
            "name": "Python Hidden",
            "is_active": False,
        },
        {**PRODUCT_BODY, "sku": "RUST-001", "name": "Rust"},
    ]
    for request in requests:
        response = await client.post(
            "/api/v1/products",
            headers=headers,
            json=request,
        )
        assert response.status_code == 201

    first_page = await client.get(
        "/api/v1/products",
        params={
            "query": "python",
            "page": 1,
            "page_size": 1,
            "sort": "sku",
            "order": "asc",
        },
    )
    second_page = await client.get(
        "/api/v1/products",
        params={
            "query": "PYTHON",
            "page": 2,
            "page_size": 1,
            "sort": "sku",
            "order": "asc",
        },
    )

    assert first_page.status_code == 200
    assert [item["sku"] for item in first_page.json()["data"]] == ["PYTHON-001"]
    assert first_page.json()["meta"]["page"] == 1
    assert first_page.json()["meta"]["page_size"] == 1
    assert first_page.json()["meta"]["total"] == 2
    assert first_page.json()["meta"]["total_pages"] == 2
    assert [item["sku"] for item in second_page.json()["data"]] == ["PYTHON-002"]


async def test_duplicate_sku_race_is_reported_as_domain_conflict(
    client: AsyncClient,
    migrated_database: AsyncEngine,
) -> None:
    headers = await _admin_headers(client, migrated_database)

    first = await client.post(
        "/api/v1/products",
        headers=headers,
        json=PRODUCT_BODY,
    )
    duplicate = await client.post(
        "/api/v1/products",
        headers=headers,
        json={**PRODUCT_BODY, "name": "Duplicate"},
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "SKU_ALREADY_EXISTS"


async def test_product_openapi_marks_only_writes_as_secured(
    test_settings: Settings,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app(test_settings)),
        base_url="http://test",
    ) as client:
        schema = (await client.get("/openapi.json")).json()
    collection = schema["paths"]["/api/v1/products"]
    detail = schema["paths"]["/api/v1/products/{product_id}"]

    assert "security" not in collection["get"]
    assert "security" not in detail["get"]
    assert collection["post"]["security"] == [{"HTTPBearer": []}]
    assert detail["patch"]["security"] == [{"HTTPBearer": []}]
    assert detail["delete"]["security"] == [{"HTTPBearer": []}]
    assert "201" in collection["post"]["responses"]
    assert "204" in detail["delete"]["responses"]
    assert "content" not in detail["delete"]["responses"]["204"]
