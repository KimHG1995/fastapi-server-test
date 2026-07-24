from collections.abc import Mapping
from http import HTTPStatus
from typing import Any, cast
from uuid import UUID

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError


class ProblemField(BaseModel):
    field: str
    message: str
    code: str


class ProblemDetail(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    trace_id: UUID
    errors: list[ProblemField] = Field(default_factory=list)


class AppError(Exception):
    def __init__(
        self,
        code: str,
        status_code: int,
        title: str,
        detail: str,
        type_slug: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.status_code = status_code
        self.title = title
        self.detail = detail
        self.type_slug = type_slug
        self.headers = headers


def problem_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        status_code: {
            "description": HTTPStatus(status_code).phrase,
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ProblemDetail"}
                }
            },
        }
        for status_code in status_codes
    }


def configure_problem_openapi(app: FastAPI) -> None:
    default_openapi = app.openapi

    def custom_openapi() -> dict[str, Any]:
        schema = default_openapi()
        components = cast(dict[str, Any], schema.setdefault("components", {}))
        schemas = cast(dict[str, Any], components.setdefault("schemas", {}))
        security_schemes = cast(
            dict[str, Any],
            components.setdefault("securitySchemes", {}),
        )
        security_schemes.setdefault(
            "HTTPBearer",
            {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
        )
        problem_schema = ProblemDetail.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        definitions = cast(dict[str, Any], problem_schema.pop("$defs", {}))
        schemas.update(definitions)
        schemas["ProblemDetail"] = problem_schema
        return schema

    app.__dict__["openapi"] = custom_openapi


def _trace_id(request: Request) -> UUID:
    return cast(UUID, request.state.trace_id)


def _problem_response(
    request: Request,
    *,
    code: str,
    status_code: int,
    title: str,
    detail: str,
    type_slug: str,
    errors: list[ProblemField] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    response_headers = dict(headers or {})
    response_headers.setdefault("x-request-id", str(_trace_id(request)))
    problem = ProblemDetail(
        type=f"https://example.com/problems/{type_slug}",
        title=title,
        status=status_code,
        detail=detail,
        instance=request.url.path,
        code=code,
        trace_id=_trace_id(request),
        errors=errors or [],
    )
    return JSONResponse(
        status_code=status_code,
        content=problem.model_dump(mode="json"),
        headers=response_headers,
        media_type="application/problem+json",
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        errors = [
            ProblemField(
                field=".".join(str(part) for part in error["loc"]),
                message=error["msg"],
                code=error["type"],
            )
            for error in exc.errors()
        ]
        return _problem_response(
            request,
            code="VALIDATION_FAILED",
            status_code=422,
            title="Validation Failed",
            detail="Request data is invalid.",
            type_slug="validation-failed",
            errors=errors,
        )

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _problem_response(
            request,
            code=exc.code,
            status_code=exc.status_code,
            title=exc.title,
            detail=exc.detail,
            type_slug=exc.type_slug,
            headers=exc.headers,
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        try:
            title = HTTPStatus(exc.status_code).phrase
        except ValueError:
            title = "HTTP Error"
        detail = exc.detail if isinstance(exc.detail, str) else title
        return _problem_response(
            request,
            code="HTTP_ERROR",
            status_code=exc.status_code,
            title=title,
            detail=detail,
            type_slug="http-error",
            headers=exc.headers,
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        del exc
        return _problem_response(
            request,
            code="INTEGRITY_ERROR",
            status_code=409,
            title="Conflict",
            detail="The request conflicts with existing data.",
            type_slug="integrity-error",
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger = structlog.get_logger(__name__).bind(trace_id=str(_trace_id(request)))
        logger.exception("unexpected_error")
        is_production = request.app.state.settings.app_env == "production"
        detail = "An unexpected error occurred." if is_production else str(exc)
        return _problem_response(
            request,
            code="INTERNAL_SERVER_ERROR",
            status_code=500,
            title="Internal Server Error",
            detail=detail,
            type_slug="internal-server-error",
        )
