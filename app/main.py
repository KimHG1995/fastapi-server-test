from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import configure_problem_openapi, register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
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
    app.state.settings = app_settings
    configure_logging(app_settings.log_level)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router)
    configure_problem_openapi(app)
    return app
