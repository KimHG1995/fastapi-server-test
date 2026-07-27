from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.core.responses import build_page_response, build_response


async def test_build_response_uses_the_request_trace_id() -> None:
    app = FastAPI()
    trace_id = UUID("11111111-1111-4111-8111-111111111111")

    @app.get("/")
    def response(request: Request) -> object:
        request.state.trace_id = trace_id
        return build_response(request, {"status": "ok"})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await client.get("/")

    assert result.status_code == 200
    assert result.json()["meta"]["trace_id"] == str(trace_id)


async def test_build_page_response_calculates_page_metadata() -> None:
    app = FastAPI()
    trace_id = uuid4()

    @app.get("/")
    def page(request: Request) -> object:
        request.state.trace_id = trace_id
        return build_page_response(
            request,
            items=[{"id": 1}, {"id": 2}],
            page=2,
            page_size=2,
            total=5,
        )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] == [{"id": 1}, {"id": 2}]
    assert body["meta"]["timestamp"].endswith("Z")
    assert {key: value for key, value in body["meta"].items() if key != "timestamp"} == {
        "path": "/",
        "trace_id": str(trace_id),
        "page": 2,
        "page_size": 2,
        "total": 5,
        "total_pages": 3,
    }


async def test_build_page_response_uses_zero_total_pages_for_empty_results() -> None:
    app = FastAPI()

    @app.get("/")
    def page(request: Request) -> object:
        request.state.trace_id = uuid4()
        return build_page_response(request, items=[], page=1, page_size=10, total=0)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.json()["meta"]["total_pages"] == 0
