from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


async def test_liveness_does_not_require_database(test_settings: Settings) -> None:
    app = create_app(test_settings)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["data"] == {"status": "ok"}
