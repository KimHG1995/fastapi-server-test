# FastAPI Server Test

FastAPI, PostgreSQL, SQLAlchemy 2로 웹과 모바일 앱이 함께 사용할 REST API를
구현한 학습용 서버다. 가입과 로그인, 회전형 Refresh Token, 역할 기반 상품
관리, 정형화된 성공 응답, RFC 9457 Problem Details, OpenAPI 계약을 실제 코드와
테스트로 보여준다.

비교 대상인 `nestjs-monorepo-test`와 통신 계약과 계층을 비교하되, 이 저장소는
모노레포가 아니다. 하나의 FastAPI 애플리케이션과 하나의 PostgreSQL을 기능별
패키지로 나눈 모듈형 모놀리스다.

## 무엇을 학습할 수 있나

- FastAPI와 기반 프레임워크 Starlette, ASGI 서버 Uvicorn의 역할 구분
- Pydantic 요청과 응답 검증, 자동 OpenAPI 생성
- SQLAlchemy 비동기 ORM, asyncpg, Alembic 마이그레이션
- JWT Access Token, 회전형 불투명 Refresh Token, 계열 재사용 탐지
- `USER`, `ADMIN` 역할과 FastAPI 의존성 기반 인증, 인가
- 공개 상품 조회, 관리자 전용 상품 생성, 수정, 소프트 삭제
- 성공 응답 `ApiResponse[T]`, 실패 응답 `application/problem+json`
- 요청 추적 ID와 structlog 구조화 로그
- 실제 PostgreSQL을 사용하는 통합 테스트와 HTTP E2E 테스트
- OpenAPI 기반 프론트엔드 TypeScript 타입과 클라이언트 생성

자세한 내부 설계는 [서버 아키텍처](docs/architecture.md), 실행 모델은
[Node.js와 Python 런타임 비교](docs/node-python-runtime.md)를 참고한다.

## 기술 스택

| 범위 | 선택 |
|---|---|
| 언어와 서버 | Python 3.13, FastAPI, Starlette, ASGI, Uvicorn |
| 데이터베이스 | PostgreSQL 18.4, SQLAlchemy 2, asyncpg, Alembic |
| 계약과 설정 | Pydantic v2, pydantic-settings, OpenAPI |
| 보안 | PyJWT, pwdlib, Argon2, SHA-256 Refresh Token 해시 |
| 관찰 가능성 | structlog, `x-request-id`, RFC 9457 Problem Details |
| 품질 | pytest, HTTPX, Testcontainers, Ruff, mypy, markdown-it-py |
| 도구 | uv, Docker, Docker Compose |

정확한 고정 버전은 [pyproject.toml](pyproject.toml)과 [uv.lock](uv.lock)에서
확인할 수 있다.

## 가장 빠른 시작, Docker Compose

### 1. 환경 파일과 JWT Secret 준비

```bash
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

두 번째 명령의 출력으로 `.env`의 `JWT_SECRET` 값을 교체한다. 예제 값을 개발
또는 운영 Secret으로 사용하지 않는다. `.env`는 Git에 포함되지 않는다.

Compose는 호스트 환경 또는 `.env`의 `JWT_SECRET`을 Compose Secret으로 읽고
컨테이너의 `/run/secrets/jwt_secret`에 파일로 마운트한다. 애플리케이션은
pydantic-settings를 통해 이 파일을 읽는다. Secret 값은 일반 서비스 환경변수에
복사되지 않는다.

### 2. 이미지 빌드, 데이터베이스 마이그레이션, API 시작

```bash
docker compose build api
docker compose up api
```

마이그레이션은 API 명령에 포함되지 않고 별도의 일회성 `migrate` 서비스가
담당한다. `docker compose up api`는 PostgreSQL이 준비된 뒤 `migrate`가 성공한
경우에만 API를 시작한다. 마이그레이션에 실패하면 API도 시작하지 않는다. 새
스키마만 명시적으로 적용하려면 `docker compose run --rm migrate`를 실행한다.

백그라운드로 실행하려면 마지막 명령에 `-d`를 추가한다.

```bash
docker compose up -d api
```

### 3. 상태와 API 문서 확인

- Liveness: [http://localhost:8000/health/live](http://localhost:8000/health/live)
- Readiness: [http://localhost:8000/health/ready](http://localhost:8000/health/ready)
- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- OpenAPI JSON: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

FastAPI의 기본 경로인 `/docs`, `/redoc`, `/openapi.json`을 그대로 사용한다.

### 호스트 포트 변경

로컬의 8000 또는 5432 포트를 이미 사용 중이면 `.env`에 다음 값을 추가한다.

```dotenv
API_PORT=18000
POSTGRES_PORT=15432
```

이후 API는 `http://localhost:18000`에서 접근한다. 컨테이너 사이에서는 계속
`postgres:5432`를 사용하므로 `COMPOSE_DATABASE_URL`을 호스트 주소로 바꾸지
않는다. 개발용 PostgreSQL 포트는 기본값과 변경된 포트 모두
`127.0.0.1`에만 게시되므로 다른 호스트에서 직접 접속할 수 없다.

### 종료

```bash
docker compose down
```

PostgreSQL 데이터는 `fastapi-server-test-postgres-data` 볼륨에 남는다.
볼륨 삭제는 데이터 삭제 작업이므로 이 프로젝트의 기본 종료 명령에 포함하지
않는다.

## 로컬 실행, uv

Python 3.13, uv, 실행 가능한 PostgreSQL이 필요하다. PostgreSQL만 Compose로
실행하고 API는 호스트에서 실행할 수 있다.

```bash
cp .env.example .env
docker compose up -d postgres
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:create_app --factory --reload
```

`.env.example`의 `DATABASE_URL`은 호스트 프로세스가
`localhost:5432`의 PostgreSQL에 접속하는 값이다. `.env`에는 앞 절에서 생성한
안전한 `JWT_SECRET`을 설정한다.

`uv run`은 잠긴 개발 환경의 명령을 실행한다. 서버는 기본적으로
`http://127.0.0.1:8000`에서 열린다. `--reload`는 개발 중 파일 변경 감지용이며
운영 배포 설정이 아니다.

## 로컬 실행, 표준 venv와 pip

uv를 설치하지 않은 환경에서도 실행할 수 있다.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:create_app --factory --reload
```

프로젝트의 지원 범위는 Python `>=3.13,<3.14`다. 시스템 기본 Python이 다른
버전이면 Python 3.13 인터프리터를 명시한다.

## 관리자 계정 만들기

공개 가입은 항상 `USER`를 만든다. `ADMIN`은 CLI에서만 생성한다. 명령은 터미널에서
비밀번호를 대화식으로 요청하며 입력값을 화면에 표시하지 않는다.

uv 환경:

```bash
uv run python -m app.cli create-admin \
  --email admin@example.com \
  --display-name Admin
```

Makefile 단축 명령:

```bash
make create-admin EMAIL=admin@example.com DISPLAY_NAME=Admin
```

Compose 환경:

```bash
docker compose run --rm api uv run python -m app.cli create-admin \
  --email admin@example.com \
  --display-name Admin
```

먼저 마이그레이션이 적용되어 있어야 한다. 기존 이메일과 중복되거나 비밀번호가
12자 미만이면 생성되지 않는다.

## API 경로

모든 기능 API는 `/api/v1` 아래에 있다. 상품 읽기는 공개이며, 상품 쓰기는
`Authorization: Bearer <access-token>` 헤더와 `ADMIN` 역할이 필요하다.

| 메서드 | 경로 | 인증 | 역할 |
|---|---|---|---|
| `POST` | `/api/v1/auth/register` | 없음 | `USER` 가입 |
| `POST` | `/api/v1/auth/login` | 없음 | Access, Refresh Token 발급 |
| `POST` | `/api/v1/auth/refresh` | Refresh Token 본문 | Token 회전 |
| `POST` | `/api/v1/auth/logout` | Refresh Token 본문 | 해당 Token 폐기 |
| `POST` | `/api/v1/auth/logout-all` | Bearer | 사용자 Token 전체 폐기 |
| `GET` | `/api/v1/users/me` | Bearer | 내 정보 조회 |
| `PATCH` | `/api/v1/users/me` | Bearer | 표시 이름 변경 |
| `POST` | `/api/v1/users/me/password` | Bearer | 비밀번호 변경 |
| `GET` | `/api/v1/products` | 없음 | 활성 상품 목록 |
| `GET` | `/api/v1/products/{product_id}` | 없음 | 활성 상품 상세 |
| `POST` | `/api/v1/products` | Bearer | `ADMIN` 생성 |
| `PATCH` | `/api/v1/products/{product_id}` | Bearer | `ADMIN` 수정 |
| `DELETE` | `/api/v1/products/{product_id}` | Bearer | `ADMIN` 소프트 삭제 |

상품 목록은 `page`, `page_size`, `query`, `sort`, `order` 쿼리를 지원한다.
`page`는 최대 10,000, `page_size`는 최대 100이며 이 범위를 넘으면 422
검증 오류를 반환한다. `sort`는 `created_at`, `name`,
`price_in_minor_units`, `sku` 중 하나다.

### 가입과 로그인 예시

```bash
curl -s http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"user@example.com","password":"correct-horse-123","display_name":"Learner"}'

curl -s http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"user@example.com","password":"correct-horse-123"}'
```

### 성공과 실패 계약

성공 응답은 라우트가 선언한 `ApiResponse[T]` 형식이다.

```json
{
  "success": true,
  "data": {
    "status": "ok"
  },
  "meta": {
    "timestamp": "2026-07-24T00:00:00Z",
    "path": "/health/live",
    "trace_id": "6d55b497-e365-4a2f-9981-cb5d8ae81f52"
  }
}
```

실패 응답은 RFC 9457 Problem Details이며 Content-Type은
`application/problem+json`이다. Pydantic 검증 오류에는 필드별 `errors`가
포함된다. `x-request-id` 헤더, 응답의 `trace_id`, 서버 로그의 추적 ID를 이용해
같은 요청을 찾을 수 있다.

## 인증 설계와 로그아웃 주의사항

Access Token은 기본 15분 유효한 JWT다. Refresh Token은 256비트 불투명 난수이며
기본 30일 동안 유효하다. 서버는 Refresh Token 원문이 아니라 SHA-256 해시만
저장한다.

정상적인 refresh 요청은 현재 토큰 행을 잠그고 사용 처리한 뒤 같은 token family의
새 Refresh Token을 발급한다. 이미 사용한 Refresh Token이 다시 제출되면 탈취
가능성이 있다고 보고 같은 family 전체를 폐기한다.

`logout`은 제출한 Refresh Token을 폐기하고, `logout-all`은 해당 사용자의 모든
Refresh Token을 폐기한다. 이 프로젝트에는 Access Token denylist가 없다.
Access Token은 로그아웃 후에도 최대 15분 동안 유효할 수 있습니다. 중요한
서비스에서는 더 짧은 수명, 서버 측 세션, denylist 같은 선택지를 위험 모델에
맞게 검토한다.

Refresh Token 회전은 여러 브라우저 탭이나 클라이언트가 같은 토큰으로 동시에
refresh할 때 한 요청만 성공할 수 있다. 클라이언트는 한 계정의 refresh 요청을
직렬화하고 새 토큰을 원자적으로 저장해야 한다. 사용된 이전 토큰을 재전송하면
계열 재사용 탐지가 작동한다.

## 프론트엔드에서 OpenAPI 사용하기

실행 중인 서버의 `/openapi.json`을 직접 볼 수 있고, 저장소의 결정적인 계약
파일도 생성할 수 있다.

```bash
uv run python scripts/export_openapi.py
git diff -- openapi/openapi.json
```

출력은 [openapi/openapi.json](openapi/openapi.json)이다. API 변경과 함께 이
파일의 diff를 검토하고 커밋한다.

### openapi-typescript

다음 명령은 이 Python 저장소가 아니라 프론트엔드 프로젝트에서 실행한다.
프론트엔드가 `./openapi/openapi.json`에 내보낸 계약 파일을 복사하거나 CI에서
가져왔다고 가정한다. Node.js 패키지를 이 Python 저장소에 추가할 필요가 없다.

```bash
npx openapi-typescript ./openapi/openapi.json -o src/api/schema.d.ts
```

생성된 타입은 프론트엔드 HTTP 클라이언트가 경로, 요청 본문, 성공 응답, Problem
Details 타입을 공유하는 데 사용할 수 있다.

### Orval

프론트엔드의 `orval.config.ts` 예시는 다음과 같다.

```typescript
import { defineConfig } from "orval";

export default defineConfig({
  api: {
    input: "./openapi/openapi.json",
    output: {
      target: "./src/api/generated.ts",
      client: "fetch",
      clean: true,
    },
  },
});
```

프론트엔드 프로젝트에서 Orval을 개발 의존성으로 설치한 뒤 실행한다.

```bash
npx orval --config ./orval.config.ts
```

생성 코드가 모든 런타임 정책을 대신하지는 않는다. 인증 토큰 저장 방식,
refresh 직렬화, 제한 시간, 재시도, 오류 화면 정책은 프론트엔드에서 별도로
설계한다.

## Node.js 개발자를 위한 핵심 대응표

V8은 JavaScript 실행 엔진이다. V8 자체를 nonblocking이라고 부르는 것은
부정확하다. Node.js는 V8, libuv, event loop, 운영체제 I/O polling, 제한된
worker pool을 결합한다.

Python은 본질적으로 multithread 웹 서버가 아니다. 이 프로젝트의 CPython 기본
빌드는 GIL을 사용한다. `async def`는 asyncio event loop, 동기 경로는 필요할 때
thread pool, 여러 Uvicorn 인스턴스는 별도 worker process에서 실행된다.

| Node.js와 NestJS | Python과 FastAPI |
|---|---|
| Promise | Coroutine 또는 Task |
| `Promise.all` | `asyncio.gather` |
| `setTimeout` | `asyncio.sleep` |
| Node.js event loop | asyncio event loop |
| Express 또는 NestJS | FastAPI |
| Node HTTP server | Uvicorn ASGI server |
| cluster worker | Uvicorn worker process |
| BullMQ | Celery, Dramatiq, ARQ |
| Zod DTO | Pydantic model |
| Prisma | SQLAlchemy와 Alembic |
| Guard | dependency |
| Exception Filter | exception handler |

자세한 차이는 [런타임 비교 문서](docs/node-python-runtime.md)에 설명했다.

### NestJS 모노레포와 이 저장소

`nestjs-monorepo-test`는 `apps/`의 여러 실행 애플리케이션과 `libs/`의 공유
패키지를 포함한다. 이 저장소는 하나의 배포 단위 안에서 `app/modules/auth`,
`users`, `products`를 나눈다.

| NestJS 관점 | 이 저장소 |
|---|---|
| Module | 기능 패키지와 API router 조립 |
| Controller | FastAPI `APIRouter` 경로 함수 |
| Provider와 Service | 명시적으로 생성한 service와 repository |
| Zod와 DTO | Pydantic 요청과 응답 model |
| Prisma | SQLAlchemy ORM |
| Prisma Migrate | Alembic |
| Guard | FastAPI dependency |
| Exception Filter | FastAPI exception handler |
| Interceptor 응답 변환 | 라우트의 명시적 `response_model` |
| Swagger module | FastAPI 자동 OpenAPI |

두 구조의 이름을 기계적으로 일대일 복사하기보다 책임 경계를 비교한다.

## FastAPI, Django, Flask를 비교할 때

Django와 Flask도 웹과 모바일 앱이 함께 쓰는 재사용 가능한 API를 만들 수 있다.
Django나 Flask로 만든 API를 모바일 앱 때문에 따로 다시 개발해야 한다는 설명은
정확하지 않다. Django REST Framework 같은 선택지도 있다.

FastAPI는 타입 힌트와 Pydantic 검증, OpenAPI, Swagger UI, ReDoc, ASGI 처리가
API 개발의 기본 흐름에 긴밀하게 연결된 점이 특징이다. Django는 ORM, 관리자,
템플릿, 인증을 포함한 큰 웹 프레임워크이고 Flask는 작은 코어에 확장을 조합한다.
요구사항과 팀 경험에 맞춰 선택한다.

FastAPI가 효율적인 비동기 API를 만들 수 있다는 것과 모든 작업에서 Node.js 또는
Go와 같은 성능을 보장한다는 것은 다르다. 실제 처리량은 작업 특성, 데이터베이스
쿼리와 잠금, 직렬화, worker 수, 연결 풀, 배포 설정에 따라 달라진다. 실제 서비스
형태로 측정한다.

## 개발 명령

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy app tests scripts
uv run --extra dev python scripts/check_docs.py
uv run python scripts/export_openapi.py
```

Makefile을 사용하면 같은 작업을 실행할 수 있다.

```bash
make install
make test
make lint
make format
make typecheck
make docs-check
make openapi
make verify
```

`scripts/check_docs.py`는 모든 Markdown을 UTF-8로 읽고 금지된 가운뎃점 문자와
깨진 로컬 Markdown 링크를 검사한다. CommonMark 문법 해석에는 개발 의존성인
markdown-it-py를 사용한다. 따라서 개발 환경을 `uv sync --extra dev` 또는
`pip install -e '.[dev]'`로 설치한 뒤 실행한다. `make docs-check`는 필요한
dev extra를 명시해 같은 검사를 수행한다.

`make verify`는 잠금 파일, Ruff 검사와 형식, mypy, 문서, 전체 pytest,
OpenAPI 스냅샷을 한 번에 검증한다. OpenAPI 검증은 임시 파일로 명세를 내보낸
뒤 추적 중인 `openapi/openapi.json`과 바이트 단위로 비교한다. 따라서 검증
과정이 기존 스냅샷을 덮어써 변경을 숨기지 않는다.

## 지속적 통합

GitHub Actions는 Python 3.13과 고정된 uv 0.11.31 환경에서 품질 검사, 단위
테스트, PostgreSQL 18.4 통합 테스트, HTTP E2E 테스트, Docker 이미지 빌드,
OpenAPI drift 검사를 각각 실행한다. 통합 테스트와 E2E 테스트는 CI 서비스
PostgreSQL에 Alembic 마이그레이션을 먼저 적용한다. 테스트 본체의
Testcontainers PostgreSQL은 임의의 호스트 포트를 사용하므로 CI 서비스의
5432 포트와 충돌하지 않는다.

## 테스트 구성

- `tests/unit`: 외부 시스템 없이 보안 함수와 서비스 규칙 검증
- `tests/integration`: Testcontainers의 실제 PostgreSQL로 마이그레이션,
  제약, 저장소, Refresh Token 회전 검증
- `tests/e2e`: ASGI HTTP 요청으로 인증, 사용자, 상품, OpenAPI 계약 검증
- `tests/operations`: Docker Compose와 이미지 운영 계약 검증
- `tests/documentation`: 학습 문서의 필수 내용, 명령, 링크 검증

통합 테스트에는 실행 가능한 Docker가 필요하다.

## 공식 참고 자료

- [FastAPI](https://fastapi.tiangolo.com/)
- [FastAPI 첫 단계와 자동 문서](https://fastapi.tiangolo.com/tutorial/first-steps/)
- [Starlette](https://www.starlette.io/)
- [ASGI](https://asgi.readthedocs.io/en/latest/)
- [Uvicorn](https://www.uvicorn.org/)
- [Pydantic](https://docs.pydantic.dev/latest/)
- [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Alembic](https://alembic.sqlalchemy.org/en/latest/)
- [PostgreSQL](https://www.postgresql.org/docs/current/)
- [Python asyncio](https://docs.python.org/3.13/library/asyncio.html)
- [Node.js 소개](https://nodejs.org/en/learn)
- [Node.js event loop와 worker pool](https://nodejs.org/en/learn/asynchronous-work/dont-block-the-event-loop)
- [OpenAPI](https://spec.openapis.org/oas/latest.html)
- [openapi-typescript](https://openapi-ts.dev/)
- [Orval](https://orval.dev/)
