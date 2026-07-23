from collections.abc import AsyncIterator

import pytest
from fastapi import APIRouter, FastAPI, Query
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def protocol_app(test_settings: Settings) -> FastAPI:
    app = create_app(test_settings)
    router = APIRouter()

    @router.get("/api/v1/protocol-example")
    async def protocol_example(limit: int = Query(gt=0)) -> dict[str, int]:
        return {"limit": limit}

    app.include_router(router)
    return app


@pytest.fixture
async def client(protocol_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=protocol_app),
        base_url="http://test",
    ) as test_client:
        yield test_client


async def test_request_id_is_shared_by_header_body_and_logical_context(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/health/live",
        headers={"x-request-id": "11111111-1111-4111-8111-111111111111"},
    )

    assert response.headers["x-request-id"] == "11111111-1111-4111-8111-111111111111"
    assert response.json()["meta"]["trace_id"] == "11111111-1111-4111-8111-111111111111"


async def test_validation_failure_uses_problem_json(client: AsyncClient) -> None:
    response = await client.get("/api/v1/protocol-example", params={"limit": 0})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert response.json()["errors"][0]["field"] == "query.limit"
