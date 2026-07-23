from collections.abc import AsyncIterator

import pytest
from fastapi import APIRouter, FastAPI, HTTPException, Query
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

    @router.get("/api/v1/protocol-error")
    async def protocol_error() -> None:
        raise RuntimeError(
            "password=super-secret token=access-token-value "
            "secret=secret-value postgresql+asyncpg://db-user:db-password@db.example/app"
        )

    @router.get("/api/v1/nonstandard-status")
    async def nonstandard_status() -> None:
        raise HTTPException(status_code=499, detail="Client closed request")

    app.include_router(router)
    return app


@pytest.fixture
async def client(protocol_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=protocol_app, raise_app_exceptions=False),
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


async def test_unhandled_error_shares_request_id_between_header_and_problem_body(
    client: AsyncClient,
) -> None:
    trace_id = "11111111-1111-4111-8111-111111111111"

    response = await client.get("/api/v1/protocol-error", headers={"x-request-id": trace_id})

    assert response.status_code == 500
    assert response.headers["x-request-id"] == trace_id
    assert response.json()["trace_id"] == trace_id


async def test_unhandled_error_log_is_traceable_and_redacts_sensitive_values(
    client: AsyncClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    trace_id = "11111111-1111-4111-8111-111111111111"

    response = await client.get("/api/v1/protocol-error", headers={"x-request-id": trace_id})

    captured = capsys.readouterr().out
    assert response.status_code == 500
    assert trace_id in captured
    assert "RuntimeError" in captured
    assert "Traceback" in captured
    assert "super-secret" not in captured
    assert "access-token-value" not in captured
    assert "secret-value" not in captured
    assert "db-user:db-password" not in captured


def test_health_openapi_advertises_problem_details(protocol_app: FastAPI) -> None:
    openapi = protocol_app.openapi()
    responses = openapi["paths"]["/health/live"]["get"]["responses"]

    for status_code in ("422", "500"):
        schema = responses[status_code]["content"]["application/problem+json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ProblemDetail"}
    assert "ProblemDetail" in openapi["components"]["schemas"]
    assert "ProblemField" in openapi["components"]["schemas"]


async def test_nonstandard_http_status_uses_a_fallback_title(client: AsyncClient) -> None:
    response = await client.get("/api/v1/nonstandard-status")

    assert response.status_code == 499
    assert response.json()["title"] == "HTTP Error"
