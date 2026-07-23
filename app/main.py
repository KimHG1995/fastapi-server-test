from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import RequestResponseEndpoint

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.db.session import create_engine_and_sessionmaker
from app.modules.health.router import router as health_router


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine, sessionmaker = create_engine_and_sessionmaker(app_settings)
        app.state.engine = engine
        app.state.sessionmaker = sessionmaker
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def assign_trace_id(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.trace_id = uuid4()
        return await call_next(request)

    app.include_router(health_router)
    app.include_router(api_router)
    return app
