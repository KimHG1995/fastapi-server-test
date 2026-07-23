# FastAPI Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-shaped learning server that demonstrates FastAPI, PostgreSQL, typed HTTP contracts, rotating refresh tokens, role-based product management, OpenAPI export, and direct comparisons with Node.js and NestJS.

**Architecture:** Use one feature-oriented modular monolith. FastAPI routers own HTTP boundaries, services own use cases and transactions, repositories own SQLAlchemy queries, Pydantic v2 models own external contracts, and SQLAlchemy 2 models own persistence. Every request receives one `AsyncSession`, successful responses use explicit generic response models, and failures use RFC 9457 Problem Details.

**Tech Stack:** Python 3.13, Hatchling 1.31.0, FastAPI 0.139.2, Uvicorn 0.51.0, Pydantic 2.13.4, Pydantic Settings 2.14.2, SQLAlchemy 2.0.51, asyncpg 0.31.0, Alembic 1.18.5, PostgreSQL 18.4, PyJWT 2.13.0, pwdlib 0.3.0 with Argon2, structlog 26.1.0, pytest 9.1.1, pytest-asyncio 1.4.0, HTTPX 0.28.1, Testcontainers 4.14.2, Ruff 0.15.22, mypy 2.3.0, uv 0.11.31.

## Global Constraints

- The repository name is `fastapi-server-test`.
- Use Python `>=3.13,<3.14`.
- Use PostgreSQL `18.4`.
- Keep one FastAPI application and one PostgreSQL database. Do not create a monorepo or microservices.
- Use a feature-oriented modular monolith with `auth`, `users`, and `products` packages.
- Public registration always creates `USER`. Only the CLI can create `ADMIN`.
- Product reads are public. Product writes require `ADMIN`.
- Access Tokens are JWTs with a 15-minute default lifetime.
- Refresh Tokens are 256-bit opaque values with a 30-day default lifetime.
- Store only SHA-256 Refresh Token hashes.
- Refresh rotation must lock the current row, replace it, and revoke the token family on reuse.
- Use explicit `ApiResponse[T]` response models. Do not transform successful responses after OpenAPI generation.
- Return RFC 9457 errors as `application/problem+json`.
- Use one `AsyncSession` per request. Repositories never commit.
- Use real PostgreSQL for integration tests. Do not substitute SQLite.
- Export deterministic OpenAPI JSON to `openapi/openapi.json`.
- Do not add Node.js packages to the Python project.
- Every Markdown document must contain no Unicode middle dot character.
- Keep secrets, password values, token values, and database URLs out of logs.
- The API container never applies migrations implicitly at startup.

---

## File Map

### Application foundation

- `pyproject.toml`, dependencies and Ruff, mypy, pytest configuration
- `uv.lock`, exact resolved dependency graph
- `.python-version`, Python 3.13 selection
- `.env.example`, documented non-secret configuration
- `.gitignore`, generated and secret files
- `Makefile`, stable developer commands
- `app/main.py`, application factory and lifespan
- `app/api/router.py`, versioned router composition
- `app/core/config.py`, validated settings
- `app/core/responses.py`, base success envelope used from the first endpoint
- `app/db/session.py`, async engine and session dependency

### Protocol and observability

- `app/core/responses.py`, pagination metadata and response helpers
- `app/core/errors.py`, application errors, Problem Details, handlers
- `app/core/middleware.py`, request ID propagation
- `app/core/logging.py`, structlog configuration

### Persistence and migrations

- `app/db/base.py`, typed declarative base and common timestamp fields
- `app/modules/users/models.py`, user ORM model and role enum
- `app/modules/auth/models.py`, refresh token ORM model
- `app/modules/products/models.py`, product ORM model
- `alembic.ini`, Alembic entry configuration
- `migrations/env.py`, async migration environment
- `migrations/versions/20260723_0001_baseline.py`, baseline schema

### Feature modules

- `app/modules/auth/schemas.py`, registration and token contracts
- `app/modules/auth/repository.py`, user lookup and refresh token queries
- `app/modules/auth/service.py`, registration, login, refresh, logout
- `app/modules/auth/dependencies.py`, Bearer authentication
- `app/modules/auth/router.py`, authentication routes
- `app/modules/users/schemas.py`, user output and update contracts
- `app/modules/users/repository.py`, user persistence
- `app/modules/users/service.py`, current user operations
- `app/modules/users/router.py`, current user routes
- `app/modules/products/schemas.py`, product input, output, and list contracts
- `app/modules/products/repository.py`, product queries
- `app/modules/products/service.py`, product business rules
- `app/modules/products/dependencies.py`, administrator dependency
- `app/modules/products/router.py`, product routes

### Operations and contract export

- `app/cli.py`, administrator creation command
- `scripts/export_openapi.py`, deterministic OpenAPI export
- `Dockerfile`, Python 3.13 runtime image
- `docker-compose.yml`, API and PostgreSQL 18.4
- `.github/workflows/ci.yml`, quality and test automation
- `README.md`, execution guide and Node.js comparison
- `openapi/openapi.json`, generated frontend contract

### Tests

- `tests/conftest.py`, application, session, PostgreSQL, and HTTP fixtures
- `tests/unit/`, pure security, response, and service tests
- `tests/integration/`, migration, constraint, repository, and refresh rotation tests
- `tests/e2e/`, HTTP behavior and OpenAPI tests

---

### Task 1: Reproducible project foundation and health API

**Files:**

- Create: `pyproject.toml`
- Create: `uv.lock`
- Create: `.python-version`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `Makefile`
- Create: `app/__init__.py`
- Create: `app/main.py`
- Create: `app/api/__init__.py`
- Create: `app/api/router.py`
- Create: `app/core/__init__.py`
- Create: `app/core/config.py`
- Create: `app/core/responses.py`
- Create: `app/db/__init__.py`
- Create: `app/db/session.py`
- Create: `app/modules/__init__.py`
- Create: `app/modules/health/__init__.py`
- Create: `app/modules/health/router.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/test_config.py`
- Create: `tests/e2e/test_health.py`

**Interfaces:**

- Produces: `Settings`, `get_settings() -> Settings`
- Produces: `ResponseMeta`, `ApiResponse[T]`, `build_response(request: Request, data: T) -> ApiResponse[T]`
- Produces: `create_app(settings: Settings | None = None) -> FastAPI`
- Produces: `create_engine_and_sessionmaker(settings: Settings) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]`
- Produces: `get_session(request: Request) -> AsyncIterator[AsyncSession]`
- Produces: `GET /health/live` and `GET /health/ready`

- [ ] **Step 1: Add the package and tool configuration**

Create `pyproject.toml` with these exact direct dependencies:

```toml
[project]
name = "fastapi-server-test"
version = "0.1.0"
description = "FastAPI and PostgreSQL learning server with typed REST contracts"
readme = "README.md"
requires-python = ">=3.13,<3.14"
dependencies = [
  "alembic==1.18.5",
  "asyncpg==0.31.0",
  "fastapi==0.139.2",
  "pydantic[email]==2.13.4",
  "pydantic-settings==2.14.2",
  "pyjwt==2.13.0",
  "pwdlib[argon2]==0.3.0",
  "sqlalchemy[asyncio]==2.0.51",
  "structlog==26.1.0",
  "uvicorn[standard]==0.51.0",
]

[project.optional-dependencies]
dev = [
  "httpx==0.28.1",
  "mypy==2.3.0",
  "pytest==9.1.1",
  "pytest-asyncio==1.4.0",
  "ruff==0.15.22",
  "testcontainers[postgres]==4.14.2",
]

[build-system]
requires = ["hatchling==1.31.0"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.pytest.ini_options]
addopts = "-ra --strict-config --strict-markers"
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
target-version = "py313"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "ASYNC", "S", "RUF"]

[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["S101"]

[tool.mypy]
python_version = "3.13"
strict = true
plugins = ["pydantic.mypy"]
exclude = ["migrations/versions/"]
```

Create `.python-version` containing `3.13`. Configure `.gitignore` for `.env`, `.venv`, `.uv-cache`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `__pycache__`, coverage output, and editor files. Create `.env.example` with non-secret example values for `APP_ENV`, `DATABASE_URL`, `JWT_SECRET`, `ACCESS_TOKEN_TTL_MINUTES`, `REFRESH_TOKEN_TTL_DAYS`, `CORS_ORIGINS`, and `LOG_LEVEL`.

Run:

```bash
uv lock
uv sync --extra dev
```

Expected: `uv.lock` is created and Python 3.13 dependencies install successfully.

- [ ] **Step 2: Write failing settings and liveness tests**

Create:

```python
# tests/unit/test_config.py
from pydantic import SecretStr

from app.core.config import Settings


def test_settings_parse_comma_separated_cors_origins() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://app:app@localhost:5432/app",
        JWT_SECRET=SecretStr("x" * 32),
        CORS_ORIGINS="http://localhost:3000,http://localhost:5173",
    )

    assert settings.cors_origins == [
        "http://localhost:3000",
        "http://localhost:5173",
    ]
```

```python
# tests/e2e/test_health.py
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
```

- [ ] **Step 3: Run the tests and verify RED**

Run:

```bash
uv run pytest tests/unit/test_config.py tests/e2e/test_health.py -q
```

Expected: collection fails because `app.core.config` and `app.main` do not exist.

- [ ] **Step 4: Implement settings, app factory, session setup, and health routes**

Use:

```python
# app/core/config.py
from functools import lru_cache
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str
    jwt_secret: SecretStr
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    cors_origins_raw: str = ""
    cors_origins: list[str] = []
    log_level: str = "INFO"

    @model_validator(mode="before")
    @classmethod
    def normalize_environment_input(cls, values: object) -> object:
        if not isinstance(values, dict):
            return values
        copied = dict(values)
        raw = copied.pop("CORS_ORIGINS", copied.pop("cors_origins_raw", ""))
        copied["cors_origins"] = [item.strip() for item in str(raw).split(",") if item.strip()]
        aliases = {
            "APP_ENV": "app_env",
            "DATABASE_URL": "database_url",
            "JWT_SECRET": "jwt_secret",
            "ACCESS_TOKEN_TTL_MINUTES": "access_token_ttl_minutes",
            "REFRESH_TOKEN_TTL_DAYS": "refresh_token_ttl_days",
            "LOG_LEVEL": "log_level",
        }
        for source, target in aliases.items():
            if source in copied:
                copied[target] = copied.pop(source)
        return copied

    @model_validator(mode="after")
    def validate_production_secret(self) -> Self:
        if len(self.jwt_secret.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Implement `create_app()` with a lifespan that stores `engine` and `sessionmaker` on `app.state`, includes the health router and versioned API router, configures CORS from validated origins, and disposes the engine on shutdown. Implement `/health/live` without database access and `/health/ready` with `SELECT 1`.

Create the base response contract in `app/core/responses.py` before implementing the health route:

```python
T = TypeVar("T")


class ResponseMeta(BaseModel):
    timestamp: datetime
    path: str
    trace_id: UUID


class ApiResponse(BaseModel, Generic[T]):
    success: Literal[True] = True
    data: T
    meta: ResponseMeta


def build_response(request: Request, data: T) -> ApiResponse[T]:
    return ApiResponse(
        data=data,
        meta=ResponseMeta(
            timestamp=datetime.now(UTC),
            path=request.url.path,
            trace_id=request.state.trace_id,
        ),
    )
```

Register the request ID setup needed by this helper in `create_app`. Task 2 will extract the full context middleware, add header propagation, and connect the same ID to structured logging.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
uv run pytest tests/unit/test_config.py tests/e2e/test_health.py -q
```

Expected: both tests pass.

- [ ] **Step 6: Run static checks and commit**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app tests
git add pyproject.toml uv.lock .python-version .env.example .gitignore Makefile app tests
git commit -m "feat: scaffold FastAPI application foundation"
```

Expected: quality commands exit with code 0 and the commit is created.

---

### Task 2: Pagination envelopes, request IDs, logging, and Problem Details

**Files:**

- Modify: `app/core/responses.py`
- Create: `app/core/errors.py`
- Create: `app/core/middleware.py`
- Create: `app/core/logging.py`
- Modify: `app/main.py`
- Modify: `app/modules/health/router.py`
- Create: `tests/unit/test_responses.py`
- Create: `tests/e2e/test_protocol.py`

**Interfaces:**

- Consumes: `ResponseMeta`, `ApiResponse[T]`, `build_response`
- Produces: `PageMeta`, `PaginatedResponse[T]`, `build_page_response`
- Produces: `ProblemField`, `ProblemDetail`
- Produces: `AppError(code, status_code, title, detail, type_slug, headers=None)`
- Produces: `build_response(request: Request, data: T) -> ApiResponse[T]`
- Produces: `build_page_response(request, items, page, page_size, total) -> PaginatedResponse[T]`
- Produces: `RequestContextMiddleware`
- Produces: `register_exception_handlers(app: FastAPI) -> None`

- [ ] **Step 1: Write failing protocol tests**

Create tests that assert:

```python
async def test_request_id_is_shared_by_header_body_and_logical_context(client: AsyncClient) -> None:
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
```

Add a test-only protocol example router through `create_app` dependency injection or expose a small documented route only during tests. Prefer an internal fixture route so production OpenAPI remains clean.

- [ ] **Step 2: Run protocol tests and verify RED**

Run:

```bash
uv run pytest tests/unit/test_responses.py tests/e2e/test_protocol.py -q
```

Expected: assertions fail because envelopes, request IDs, and Problem Details are absent.

- [ ] **Step 3: Extend the response contracts with pagination**

Use generic Pydantic v2 models:

```python
T = TypeVar("T")


class PageMeta(ResponseMeta):
    page: int
    page_size: int
    total: int
    total_pages: int


class PaginatedResponse(BaseModel, Generic[T]):
    success: Literal[True] = True
    data: list[T]
    meta: PageMeta
```

`build_response` reads the UUID stored by middleware on `request.state.trace_id`. `build_page_response` calculates `total_pages` as zero when `total` is zero, otherwise `(total + page_size - 1) // page_size`.

- [ ] **Step 4: Implement request context and exception handlers**

The middleware must:

1. Accept an incoming valid UUID in `x-request-id`.
2. Generate UUIDv4 when the header is absent or invalid.
3. Store it in `request.state.trace_id`.
4. Bind it to structlog context variables.
5. Return it in the response header.
6. Clear context variables after every request.

Register handlers for `RequestValidationError`, `AppError`, `HTTPException`, `IntegrityError`, and `Exception`. The final handler logs the exception and hides details in production. Every handler returns `application/problem+json`.

- [ ] **Step 5: Verify GREEN and OpenAPI accuracy**

Run:

```bash
uv run pytest tests/unit/test_responses.py tests/e2e/test_protocol.py -q
uv run ruff check .
uv run mypy app tests
```

Expected: protocol tests and static checks pass.

- [ ] **Step 6: Commit**

```bash
git add app/core app/main.py app/modules/health tests/unit/test_responses.py tests/e2e/test_protocol.py
git commit -m "feat: standardize HTTP response protocol"
```

---

### Task 3: SQLAlchemy models, Alembic baseline, and PostgreSQL fixtures

**Files:**

- Create: `app/db/base.py`
- Create: `app/modules/users/__init__.py`
- Create: `app/modules/users/models.py`
- Create: `app/modules/auth/__init__.py`
- Create: `app/modules/auth/models.py`
- Create: `app/modules/products/__init__.py`
- Create: `app/modules/products/models.py`
- Create: `alembic.ini`
- Create: `migrations/README`
- Create: `migrations/script.py.mako`
- Create: `migrations/env.py`
- Create: `migrations/versions/20260723_0001_baseline.py`
- Modify: `tests/conftest.py`
- Create: `tests/integration/test_migrations.py`
- Create: `tests/integration/test_constraints.py`

**Interfaces:**

- Produces: `Base(AsyncAttrs, DeclarativeBase)`
- Produces: `UtcTimestampMixin`
- Produces: `UserRole(StrEnum)` with `USER` and `ADMIN`
- Produces: `User`, `RefreshToken`, `Product`
- Produces: `postgresql_url`, `migrated_database`, `db_session`, and `client` fixtures

- [ ] **Step 1: Write failing migration and constraint tests**

The migration test applies `upgrade head`, inspects PostgreSQL, and expects the exact tables `users`, `refresh_tokens`, `products`, and `alembic_version`.

The constraints test inserts duplicate normalized emails and duplicate SKUs and expects `IntegrityError`. It also asserts `price_in_minor_units` and `stock_quantity` reject negative values.

- [ ] **Step 2: Run integration tests and verify RED**

Run:

```bash
uv run pytest tests/integration/test_migrations.py tests/integration/test_constraints.py -q
```

Expected: tests fail because the Alembic configuration and ORM models are missing.

- [ ] **Step 3: Implement typed ORM models**

Use UUID primary keys generated by `uuid4`, timezone-aware timestamps with PostgreSQL `TIMESTAMP(timezone=True)`, named constraints, and explicit indexes.

Required model members:

```python
class UserRole(StrEnum):
    USER = "USER"
    ADMIN = "ADMIN"


class User(UtcTimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[UUID]
    email: Mapped[str]
    password_hash: Mapped[str]
    display_name: Mapped[str]
    role: Mapped[UserRole]
    is_active: Mapped[bool]


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[UUID]
    user_id: Mapped[UUID]
    family_id: Mapped[UUID]
    token_hash: Mapped[str]
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    replaced_by_id: Mapped[UUID | None]
    created_at: Mapped[datetime]


class Product(UtcTimestampMixin, Base):
    __tablename__ = "products"

    id: Mapped[UUID]
    sku: Mapped[str]
    name: Mapped[str]
    description: Mapped[str | None]
    price_in_minor_units: Mapped[int]
    currency: Mapped[str]
    stock_quantity: Mapped[int]
    is_active: Mapped[bool]
    created_by_id: Mapped[UUID]
    deleted_at: Mapped[datetime | None]
```

Normalize emails in the service before persistence. Preserve the original normalized value in the database. Define database checks for nonnegative price and stock and a three-character uppercase currency code.

- [ ] **Step 4: Implement async Alembic and baseline migration**

`migrations/env.py` imports all model modules, sets `target_metadata = Base.metadata`, builds the URL from `Settings`, uses `async_engine_from_config`, and invokes `await connection.run_sync(do_run_migrations)`.

The baseline migration creates PostgreSQL enum `user_role`, the three tables, all foreign keys, named check constraints, unique constraints, and indexes. Downgrade drops objects in reverse dependency order.

- [ ] **Step 5: Implement isolated PostgreSQL test fixtures**

Start PostgreSQL with `PostgresContainer("postgres:18.4-trixie")` once per test session. Convert the sync URL to `postgresql+asyncpg`. Create a fresh database schema for each test requiring isolation, apply the Alembic migration, and dispose every engine.

Override `get_session` in the test app so HTTP tests and repository tests use the migrated database.

- [ ] **Step 6: Verify GREEN and commit**

Run:

```bash
uv run pytest tests/integration/test_migrations.py tests/integration/test_constraints.py -q
uv run ruff check .
uv run mypy app tests
git add app/db app/modules alembic.ini migrations tests/conftest.py tests/integration
git commit -m "feat: add PostgreSQL persistence model"
```

Expected: migration, constraints, lint, and type checks pass.

---

### Task 4: Password security, registration, login, and Bearer authentication

**Files:**

- Create: `app/core/security.py`
- Create: `app/modules/auth/schemas.py`
- Create: `app/modules/auth/repository.py`
- Create: `app/modules/auth/service.py`
- Create: `app/modules/auth/dependencies.py`
- Create: `app/modules/auth/router.py`
- Create: `app/modules/users/schemas.py`
- Create: `app/modules/users/repository.py`
- Modify: `app/api/router.py`
- Create: `tests/unit/test_security.py`
- Create: `tests/unit/test_auth_service.py`
- Create: `tests/e2e/test_auth_login.py`

**Interfaces:**

- Produces: `hash_password(password: str) -> str`
- Produces: `verify_password(password: str, password_hash: str) -> bool`
- Produces: `create_access_token(user: User, settings: Settings, now: datetime | None = None) -> str`
- Produces: `decode_access_token(token: str, settings: Settings) -> AccessTokenClaims`
- Produces: `generate_refresh_token() -> str`
- Produces: `hash_refresh_token(token: str) -> str`
- Produces: `AuthRepository`
- Produces: `AuthService.register`, `AuthService.login`
- Produces: `get_current_user`
- Produces: `POST /api/v1/auth/register`, `POST /api/v1/auth/login`

- [ ] **Step 1: Write security tests and verify RED**

Tests must prove:

```python
def test_password_hash_uses_argon2_and_verifies() -> None:
    encoded = hash_password("correct-horse-battery-staple")

    assert encoded.startswith("$argon2")
    assert verify_password("correct-horse-battery-staple", encoded)
    assert not verify_password("wrong-password", encoded)


def test_refresh_token_contains_256_bits_of_entropy() -> None:
    token = generate_refresh_token()

    assert len(base64.urlsafe_b64decode(token + "==")) == 32
    assert hash_refresh_token(token) == hashlib.sha256(token.encode()).hexdigest()
```

Access Token tests fix `now`, decode the JWT, and assert `sub`, `role`, `type`, `jti`, `iat`, and `exp`. A token with a missing claim, wrong type, expired time, or disallowed algorithm must fail with one authentication error.

- [ ] **Step 2: Implement minimal security functions and verify GREEN**

Use `PasswordHash.recommended()` from pwdlib. Use a module-level dummy hash for unknown-user login timing. Decode JWT with an explicit algorithm list and required claims.

Run:

```bash
uv run pytest tests/unit/test_security.py -q
```

Expected: all security tests pass.

- [ ] **Step 3: Write registration and login service tests**

Test these behaviors independently:

1. Registration lowercases and trims email.
2. Registration always assigns `USER`.
3. Duplicate email raises `EMAIL_ALREADY_EXISTS` with `409`.
4. Login returns the same generic `INVALID_CREDENTIALS` result for an unknown email and a bad password.
5. Inactive users cannot log in.
6. Successful login creates one refresh row containing only the hash.

- [ ] **Step 4: Implement schemas, repository, and service**

Required contracts:

```python
class RegisterRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=12, max_length=128)]
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    display_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime
```

`AuthService.register` opens a transaction, checks normalized email, hashes the password, persists `USER`, and returns `UserRead`. `AuthService.login` performs the dummy hash check for unknown email, verifies active status, creates the JWT and refresh row in one transaction, and returns `TokenPair`.

- [ ] **Step 5: Write and implement HTTP tests**

E2E tests assert `201` registration, `200` login, response envelopes, `409` duplicate email, generic `401` credentials errors, no password fields in responses, and an OpenAPI HTTP Bearer scheme.

Implement `HTTPBearer(auto_error=False)` and `get_current_user`. It decodes the token, loads the user, verifies `is_active`, and returns `401` with `WWW-Authenticate: Bearer` for every authentication failure.

- [ ] **Step 6: Verify and commit**

```bash
uv run pytest tests/unit/test_security.py tests/unit/test_auth_service.py tests/e2e/test_auth_login.py -q
uv run ruff check .
uv run mypy app tests
git add app/core/security.py app/modules/auth app/modules/users app/api/router.py tests
git commit -m "feat: add user registration and login"
```

---

### Task 5: Refresh rotation, reuse detection, logout, and concurrency

**Files:**

- Modify: `app/modules/auth/schemas.py`
- Modify: `app/modules/auth/repository.py`
- Modify: `app/modules/auth/service.py`
- Modify: `app/modules/auth/router.py`
- Create: `tests/integration/test_refresh_rotation.py`
- Create: `tests/e2e/test_auth_refresh.py`

**Interfaces:**

- Produces: `AuthRepository.get_refresh_for_update(token_hash) -> RefreshToken | None`
- Produces: `AuthRepository.revoke_family(family_id, revoked_at) -> None`
- Produces: `AuthRepository.revoke_all_for_user(user_id, revoked_at) -> None`
- Produces: `AuthService.refresh`, `AuthService.logout`, `AuthService.logout_all`
- Produces: `POST /api/v1/auth/refresh`
- Produces: `POST /api/v1/auth/logout`
- Produces: `POST /api/v1/auth/logout-all`

- [ ] **Step 1: Write failing rotation tests**

Test:

1. A valid refresh returns a new pair.
2. The old row receives `revoked_at` and `replaced_by_id`.
3. The replacement keeps the same `family_id`.
4. The raw replacement token is absent from all database string fields.
5. Reusing the old token revokes every row in the family.
6. Expired tokens fail.
7. Unknown tokens fail.
8. Two concurrent refresh attempts cannot both succeed.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/integration/test_refresh_rotation.py -q
```

Expected: failures because refresh operations do not exist.

- [ ] **Step 3: Implement row-locked rotation**

Use:

```python
statement = (
    select(RefreshToken)
    .where(RefreshToken.token_hash == token_hash)
    .with_for_update()
)
```

Inside one transaction:

1. Hash the submitted token.
2. Lock and load the row.
3. Reject missing or expired rows.
4. If already revoked, revoke the family and return `REFRESH_TOKEN_REUSED`.
5. Generate a new opaque token and row with the same family.
6. Flush the new row.
7. Set the old row's `revoked_at` and `replaced_by_id`.
8. Create a new Access Token.
9. Commit before returning the raw new Refresh Token.

- [ ] **Step 4: Implement logout routes and E2E tests**

`logout` accepts `RefreshTokenRequest`, uses the same lock, and is idempotent for a known already-revoked token. An unknown token returns `401`. `logout-all` requires Access Token authentication and revokes every active refresh row for the user.

HTTP tests assert response status, Problem Details, and failure of tokens after logout.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/integration/test_refresh_rotation.py tests/e2e/test_auth_refresh.py -q
uv run ruff check .
uv run mypy app tests
git add app/modules/auth tests/integration/test_refresh_rotation.py tests/e2e/test_auth_refresh.py
git commit -m "feat: rotate and revoke refresh tokens"
```

---

### Task 6: Current user profile and password change

**Files:**

- Modify: `app/modules/users/schemas.py`
- Modify: `app/modules/users/repository.py`
- Create: `app/modules/users/service.py`
- Create: `app/modules/users/router.py`
- Modify: `app/api/router.py`
- Create: `tests/unit/test_user_service.py`
- Create: `tests/e2e/test_users.py`

**Interfaces:**

- Produces: `UpdateProfileRequest(display_name)`
- Produces: `ChangePasswordRequest(current_password, new_password)`
- Produces: `UserService.get_current`, `UserService.update_profile`, `UserService.change_password`
- Produces: `GET /api/v1/users/me`
- Produces: `PATCH /api/v1/users/me`
- Produces: `POST /api/v1/users/me/password`

- [ ] **Step 1: Write failing user behavior tests**

Test authentication requirement, current profile response, trimmed display name, password mismatch, password rehash, and refresh-family revocation after password change.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/unit/test_user_service.py tests/e2e/test_users.py -q
```

Expected: route and service imports fail.

- [ ] **Step 3: Implement the service and routes**

`update_profile` only changes `display_name`. It must not accept `email`, `role`, or `is_active`.

`change_password` verifies the current password, rejects reuse of the current password, hashes the new password, updates the user, and revokes all refresh rows in one transaction. Return `204 No Content`.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest tests/unit/test_user_service.py tests/e2e/test_users.py -q
uv run ruff check .
uv run mypy app tests
git add app/modules/users app/api/router.py tests/unit/test_user_service.py tests/e2e/test_users.py
git commit -m "feat: add current user management"
```

---

### Task 7: Public product reads and administrator product management

**Files:**

- Create: `app/modules/products/schemas.py`
- Create: `app/modules/products/repository.py`
- Create: `app/modules/products/service.py`
- Create: `app/modules/products/dependencies.py`
- Create: `app/modules/products/router.py`
- Modify: `app/api/router.py`
- Create: `tests/unit/test_product_service.py`
- Create: `tests/integration/test_product_repository.py`
- Create: `tests/e2e/test_products.py`

**Interfaces:**

- Produces: `ProductCreate`, `ProductUpdate`, `ProductRead`, `ProductListQuery`
- Produces: `ProductSortField`, `SortOrder`
- Produces: `ProductRepository.create`, `get_public_by_id`, `list_public`, `update`, `soft_delete`
- Produces: `ProductService.create`, `get_public`, `list_public`, `update`, `delete`
- Produces: `require_admin`
- Produces: product routes under `/api/v1/products`

- [ ] **Step 1: Write schema and service tests**

Required schemas:

```python
class ProductCreate(BaseModel):
    sku: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=64)]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: Annotated[str | None, StringConstraints(max_length=2000)] = None
    price_in_minor_units: int = Field(ge=0)
    currency: Annotated[str, StringConstraints(to_upper=True, pattern=r"^[A-Z]{3}$")]
    stock_quantity: int = Field(ge=0)
    is_active: bool = True


class ProductUpdate(BaseModel):
    name: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] = None
    description: Annotated[str | None, StringConstraints(max_length=2000)] = None
    price_in_minor_units: int | None = Field(default=None, ge=0)
    currency: Annotated[str | None, StringConstraints(to_upper=True, pattern=r"^[A-Z]{3}$")] = None
    stock_quantity: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
```

Reject an update where every field is unset. SKU is immutable after creation.

- [ ] **Step 2: Verify RED and implement service rules**

Run:

```bash
uv run pytest tests/unit/test_product_service.py -q
```

Expected: import failure, then behavior failures until service rules are complete.

Implement duplicate SKU as `409 SKU_ALREADY_EXISTS`, missing or deleted product as `404 PRODUCT_NOT_FOUND`, and soft deletion as setting `deleted_at` without physical deletion.

- [ ] **Step 3: Write repository tests**

Test:

1. Public list excludes inactive and deleted products.
2. Search matches SKU and name case-insensitively.
3. `page`, `page_size`, and total count are correct.
4. Sort fields map through an enum to ORM columns.
5. Stable ordering adds `id` as a tie breaker.
6. Public detail excludes inactive and deleted products.

- [ ] **Step 4: Implement repository queries and verify**

Return `(list[Product], total)` from `list_public`. Build filters once and reuse them for the count and data statements. Never interpolate user strings into SQL or use `text()` for sort fields.

- [ ] **Step 5: Implement HTTP routes and authorization tests**

Assert:

- Anonymous and `USER` calls to writes return `401` and `403` respectively.
- `ADMIN` can create, patch, and delete.
- Reads require no `security` entry in OpenAPI.
- Create returns `201`.
- Delete returns `204` with an empty body.
- List returns `PaginatedResponse[ProductRead]`.

- [ ] **Step 6: Verify and commit**

```bash
uv run pytest tests/unit/test_product_service.py tests/integration/test_product_repository.py tests/e2e/test_products.py -q
uv run ruff check .
uv run mypy app tests
git add app/modules/products app/api/router.py tests
git commit -m "feat: add role-protected product API"
```

---

### Task 8: Administrator CLI and deterministic OpenAPI export

**Files:**

- Create: `app/cli.py`
- Create: `scripts/export_openapi.py`
- Create: `scripts/check_docs.py`
- Create: `tests/integration/test_admin_cli.py`
- Create: `tests/e2e/test_openapi.py`
- Create: `openapi/openapi.json`
- Modify: `Makefile`

**Interfaces:**

- Produces: `python -m app.cli create-admin --email EMAIL --display-name NAME`
- Produces: `python scripts/export_openapi.py`
- Produces: `python scripts/check_docs.py`

- [ ] **Step 1: Write failing CLI and OpenAPI tests**

The CLI test invokes the command with a supplied password through `getpass` monkeypatching, verifies `ADMIN`, normalized email, Argon2 hash, and duplicate rejection.

The OpenAPI test asserts:

1. Every approved route exists.
2. Bearer authentication appears only where required.
3. Success envelopes, pagination metadata, and Problem Details appear in components.
4. `401`, `403`, `404`, `409`, and `422` responses reference Problem Details.
5. A second export produces byte-identical JSON.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/integration/test_admin_cli.py tests/e2e/test_openapi.py -q
```

Expected: CLI and export modules are missing.

- [ ] **Step 3: Implement the CLI**

Use standard `argparse` and `getpass`, not a new CLI dependency. Validate email and password through the same Pydantic schemas and security functions as the API. Open an `AsyncSession`, reject duplicate email, create `ADMIN`, commit, print only the new user ID and normalized email, and dispose the engine.

- [ ] **Step 4: Implement deterministic OpenAPI export**

Use:

```python
from pathlib import Path
import json

from app.main import create_app


def main() -> None:
    document = create_app().openapi()
    target = Path("openapi/openapi.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
```

The application factory must not connect to PostgreSQL while generating OpenAPI.

- [ ] **Step 5: Implement document character validation**

`scripts/check_docs.py` recursively reads `*.md`, checks for `chr(0xB7)`, prints each violating path and line, and exits nonzero when found. It never contains the forbidden literal in its own source or messages.

- [ ] **Step 6: Verify and commit**

```bash
uv run python scripts/export_openapi.py
uv run python scripts/check_docs.py
uv run pytest tests/integration/test_admin_cli.py tests/e2e/test_openapi.py -q
git add app/cli.py scripts openapi Makefile tests
git commit -m "feat: add admin CLI and OpenAPI export"
```

---

### Task 9: Docker environment and operational workflow

**Files:**

- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`
- Modify: `Makefile`
- Create: `tests/operations/test_compose_config.py`

**Interfaces:**

- Produces: `docker compose up -d postgres`
- Produces: `docker compose run --rm migrate`
- Produces: `docker compose up --build api`
- Produces: API on `http://localhost:8000`

- [ ] **Step 1: Write a failing Compose configuration test**

The test runs `docker compose config --format json` and asserts:

- PostgreSQL image is `postgres:18.4-trixie`.
- The volume target is `/var/lib/postgresql`, matching PostgreSQL 18 image behavior.
- PostgreSQL has a `pg_isready` health check.
- API waits for healthy PostgreSQL.
- Migration is a separate one-shot service.
- API command does not contain `alembic`.
- No host secret is embedded in the rendered configuration.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/operations/test_compose_config.py -q
```

Expected: failure because Compose files do not exist.

- [ ] **Step 3: Implement Docker files**

Use `python:3.13.13-slim-trixie` as the runtime base. Copy `uv` `0.11.31` from the official `ghcr.io/astral-sh/uv:0.11.31` image. Install from `pyproject.toml` and `uv.lock` with `uv sync --frozen --no-dev`. Run as a non-root application user.

Compose services:

- `postgres`, `postgres:18.4-trixie`
- `migrate`, application image with `uv run alembic upgrade head`
- `api`, application image with `uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000`

Use environment variables from `.env`, expose only the API and PostgreSQL development ports, and use a named PostgreSQL volume.

- [ ] **Step 4: Verify runtime**

Run:

```bash
docker compose config
docker compose build api
docker compose up -d postgres
docker compose run --rm migrate
docker compose up -d api
curl --fail http://localhost:8000/health/ready
```

Expected: the ready endpoint returns `200`.

- [ ] **Step 5: Verify tests and commit**

```bash
uv run pytest tests/operations/test_compose_config.py -q
git add Dockerfile docker-compose.yml .dockerignore Makefile tests/operations
git commit -m "build: add reproducible Docker environment"
```

---

### Task 10: Learning README and frontend contract guide

**Files:**

- Create: `README.md`
- Create: `docs/architecture.md`
- Create: `docs/node-python-runtime.md`
- Create: `tests/documentation/test_readme_commands.py`
- Modify: `scripts/check_docs.py`

**Interfaces:**

- Produces: complete Korean learning guide
- Produces: Node.js to Python terminology and runtime comparison
- Produces: executable setup, migration, test, OpenAPI, and frontend generation commands

- [ ] **Step 1: Write failing documentation tests**

Assert README contains:

- `FastAPI`, `Starlette`, `ASGI`, `Uvicorn`
- `V8`, `libuv`, `event loop`
- `CPython`, `GIL`, `thread pool`, `worker process`
- `Promise`, `Coroutine`, `Task`, `asyncio.gather`
- `NestJS`, `Pydantic`, `Zod`, `SQLAlchemy`, `Alembic`
- `/docs`, `/redoc`, `/openapi.json`
- `openapi-typescript`, `Orval`
- `docker compose run --rm migrate`
- the warning that Access Tokens can remain valid for up to 15 minutes after logout

The test also extracts every local Markdown link and verifies the target exists.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/documentation/test_readme_commands.py -q
```

Expected: README and supporting documents are missing.

- [ ] **Step 3: Write the learning documentation**

Use this runtime explanation as the conceptual baseline:

```text
V8 executes JavaScript. Node.js combines V8 with libuv, an event loop, operating
system polling, and a worker pool. Calling V8 itself nonblocking is inaccurate.

Python is not inherently a multithreaded web server. This project uses a normal
CPython build with the GIL. Async FastAPI handlers share an asyncio event loop,
sync handlers may run in a thread pool, and multiple Uvicorn workers are separate
processes. Each mechanism solves a different kind of concurrency problem.
```

Include a mapping table:

| Node.js and NestJS | Python and FastAPI |
|---|---|
| Promise | Coroutine or Task |
| `Promise.all` | `asyncio.gather` |
| `setTimeout` | `asyncio.sleep` |
| Node.js event loop | asyncio event loop |
| Express or NestJS | FastAPI |
| Node HTTP server | Uvicorn ASGI server |
| cluster worker | Uvicorn worker process |
| BullMQ | Celery, Dramatiq, or ARQ |
| Zod DTO | Pydantic model |
| Prisma | SQLAlchemy and Alembic |
| Guard | dependency |
| Exception Filter | exception handler |

Explain that Django and Flask can also expose reusable APIs. Avoid claiming that an API built with Django or Flask must be rewritten for mobile applications. Compare FastAPI's API-first defaults, typed validation, and automatic OpenAPI generation instead.

Explain performance without claiming universal Node.js or Go parity. State that workload, database behavior, serialization, worker count, and deployment settings determine real throughput.

- [ ] **Step 4: Document commands and frontend use**

Provide exact Docker, local `uv`, standard `venv`, Alembic, admin CLI, test, lint, mypy, and OpenAPI export commands. Show:

```bash
npx openapi-typescript ./openapi/openapi.json -o src/api/schema.d.ts
```

Explain that this command is run in the frontend project and is not a dependency of this Python repository. Include an Orval configuration example that reads the same file.

- [ ] **Step 5: Verify documents and commit**

```bash
uv run python scripts/check_docs.py
uv run pytest tests/documentation/test_readme_commands.py -q
git add README.md docs scripts/check_docs.py tests/documentation
git commit -m "docs: explain FastAPI server architecture"
```

---

### Task 11: CI, full verification, and release-ready baseline

**Files:**

- Create: `.github/workflows/ci.yml`
- Create: `tests/test_quality_contract.py`
- Modify: `Makefile`
- Modify: `README.md`

**Interfaces:**

- Produces: `make verify`
- Produces: GitHub Actions jobs for quality, unit tests, PostgreSQL integration tests, E2E tests, Docker build, and OpenAPI drift

- [ ] **Step 1: Write the quality contract test**

Assert:

- `make verify` includes Ruff check, Ruff format check, mypy, all pytest suites, document validation, and OpenAPI drift validation.
- CI uses Python 3.13 and PostgreSQL 18.4.
- CI runs `uv sync --frozen --extra dev`.
- CI runs Alembic before integration and E2E tests.
- CI builds the Docker image.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/test_quality_contract.py -q
```

Expected: failure because the CI workflow and complete verification target do not exist.

- [ ] **Step 3: Implement CI and verification targets**

Use the official uv setup action pinned to a commit SHA. Use `actions/checkout` and `actions/setup-python` pinned to reviewed major versions or commit SHAs. Configure a PostgreSQL 18.4 service with health checks. Never echo secrets.

Add an OpenAPI drift command that exports to a temporary file and compares it byte-for-byte with `openapi/openapi.json`.

- [ ] **Step 4: Run full fresh verification**

Run:

```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run mypy app tests
uv run python scripts/check_docs.py
uv run pytest -q
uv run python scripts/export_openapi.py
git diff --exit-code -- openapi/openapi.json
docker compose config
docker compose build api
```

Expected:

- Dependency lock is current.
- Ruff reports no errors and no formatting changes.
- mypy reports success.
- Document validation reports no forbidden character.
- pytest reports zero failures.
- OpenAPI export produces no diff.
- Compose renders successfully.
- Docker image builds successfully.

- [ ] **Step 5: Perform requirements audit**

Read the design document from top to bottom and map every success criterion to a passing test or a documented command. Check:

1. Registration and login.
2. JWT Access Token.
3. Refresh rotation.
4. Refresh reuse family revocation.
5. Current user operations.
6. Public product reads.
7. Administrator product writes.
8. Typed success and Problem Details contracts.
9. OpenAPI export.
10. Frontend generation guide.
11. Real PostgreSQL integration tests.
12. Accurate Node.js and Python runtime explanation.
13. No forbidden character in Markdown.

If an item has no evidence, add the smallest failing test and implement the missing behavior before continuing.

- [ ] **Step 6: Commit final automation**

```bash
git add .github Makefile README.md tests/test_quality_contract.py openapi/openapi.json
git commit -m "ci: verify FastAPI server baseline"
git status --short
```

Expected: the final status is clean.

---

## Execution Notes

- Follow RED, GREEN, REFACTOR for every behavior. Never add production behavior before observing the matching test fail.
- Do not share one `AsyncSession` between concurrent tasks.
- Do not catch `BaseException`.
- Convert only expected domain failures into `AppError`. Let unexpected failures reach the global handler and logs.
- Keep generated `uv.lock` and `openapi/openapi.json` under version control.
- Re-run document validation after every Markdown edit.
- Before every completion claim, run the full verification commands from Task 11 and read the complete output.
