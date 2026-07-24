# 서버 아키텍처

이 문서는 `fastapi-server-test`의 코드 경계와 요청 처리 흐름을 설명한다. 실행 방법은
[README](../README.md), Node.js와 Python의 실행 모델은
[런타임 비교](node-python-runtime.md)를 참고한다.

## 구조 선택

이 저장소는 모노레포가 아니라 기능 중심 모듈형 모놀리스다. 하나의 FastAPI
애플리케이션, 하나의 PostgreSQL 데이터베이스, 하나의 배포 단위를 사용한다.
`auth`, `users`, `products`는 기능별 패키지로 분리하지만 독립 서비스나 독립
프로세스는 아니다.

비교 대상인 `nestjs-monorepo-test`는 `apps/` 아래에 API 서버, 워커, 웹 서버를
두고 `libs/`의 공용 라이브러리를 함께 사용하는 모노레포다. 이 프로젝트는 학습
범위를 REST API 하나로 제한했으므로 여러 앱을 억지로 만들지 않는다. 기능이나
배포 단위가 실제로 늘어날 때만 모노레포 또는 서비스 분리를 검토한다.

```text
fastapi-server-test/
├── app/
│   ├── main.py
│   ├── cli.py
│   ├── api/
│   │   └── router.py
│   ├── core/
│   │   ├── config.py
│   │   ├── errors.py
│   │   ├── logging.py
│   │   ├── middleware.py
│   │   ├── responses.py
│   │   └── security.py
│   ├── db/
│   │   ├── base.py
│   │   ├── errors.py
│   │   └── session.py
│   └── modules/
│       ├── auth/
│       ├── health/
│       ├── products/
│       └── users/
├── migrations/
├── openapi/
├── scripts/
└── tests/
    ├── documentation/
    ├── e2e/
    ├── integration/
    ├── operations/
    └── unit/
```

## 계층별 책임

### 라우터

`app/modules/*/router.py`가 HTTP 경계를 소유한다.

- 경로, 메서드, 상태 코드, 요청과 응답 모델을 선언한다.
- FastAPI `Depends`로 세션, 현재 사용자, 관리자 권한을 받는다.
- 서비스를 호출하고 `ApiResponse[T]` 또는 `PaginatedResponse[T]`를 반환한다.
- SQLAlchemy 쿼리와 비즈니스 규칙을 직접 작성하지 않는다.

### Pydantic 스키마

`schemas.py`가 외부 계약을 소유한다.

- 요청 본문, 쿼리 문자열, 응답 형식을 검증한다.
- 허용하지 않은 필드와 잘못된 타입을 HTTP 경계에서 거부한다.
- ORM 모델을 API에 직접 노출하지 않는다.
- 비밀번호 해시와 Refresh Token 해시는 응답 모델에 존재하지 않는다.

NestJS의 Zod 스키마와 DTO가 담당하던 역할에 가깝다. 차이는 Pydantic 모델이
Python 타입 힌트와 FastAPI OpenAPI 생성에 직접 연결된다는 점이다.

### 서비스

`service.py`가 유스케이스와 트랜잭션 경계를 소유한다.

- 가입, 로그인, 토큰 회전, 프로필 변경, 상품 관리 규칙을 구현한다.
- 여러 저장소 호출을 하나의 쓰기 트랜잭션으로 묶는다.
- HTTP `Request`나 `Response`에 의존하지 않는다.
- 예상 가능한 실패를 애플리케이션 오류로 변환한다.

### 저장소

`repository.py`가 SQLAlchemy 쿼리와 영속성 작업을 소유한다.

- `select`, 행 잠금, 추가, 수정, 소프트 삭제를 수행한다.
- 새 식별자가 필요할 때 `flush`할 수 있다.
- `commit`하지 않는다. 커밋 여부는 유스케이스를 아는 서비스가 결정한다.
- FastAPI 예외나 Pydantic 응답 모델을 알지 못한다.

### ORM 모델과 마이그레이션

`models.py`는 런타임 ORM 매핑을, `migrations/`는 데이터베이스 스키마 변경 이력을
정의한다. SQLAlchemy 모델을 바꿨다고 운영 데이터베이스가 자동 변경되지는 않는다.
모델 변경과 Alembic 리비전을 함께 검토하고 다음 명령으로 적용한다.

```bash
uv run alembic upgrade head
```

컨테이너 환경에서는 API 시작 전에 별도의 일회성 작업으로 실행한다.

```bash
docker compose run --rm migrate
```

API 컨테이너는 시작할 때 마이그레이션을 암묵적으로 수행하지 않는다. 여러 API
복제본이 동시에 스키마를 변경하는 경쟁을 피하고, 배포 단계에서 실패를 명확히
관찰하기 위한 경계다.

## 요청 처리 흐름

```text
HTTP 요청
  -> RequestContextMiddleware, trace_id 생성 또는 전달
  -> CORS 미들웨어
  -> FastAPI 라우터
  -> Pydantic 요청 검증
  -> 인증과 역할 의존성
  -> 서비스
  -> 저장소
  -> SQLAlchemy AsyncSession
  -> asyncpg
  -> PostgreSQL
```

응답은 역순으로 돌아온다. 성공 응답은 각 라우트가 명시한 Pydantic 응답 모델로
직접 만든다. 성공 결과를 사후 미들웨어에서 감싸지 않으므로 실제 JSON과 OpenAPI
계약이 일치한다.

### 세션과 트랜잭션

- 애플리케이션 수명 주기 시작 시 비동기 엔진과 `async_sessionmaker`를 만든다.
- 요청마다 `AsyncSession` 하나를 열고 요청 종료 시 닫는다.
- 저장소는 커밋하지 않는다.
- 쓰기 서비스가 트랜잭션을 완료하거나 예외 시 롤백한다.
- 애플리케이션 종료 시 엔진을 `dispose`한다.
- 통합 테스트도 실제 PostgreSQL을 사용한다. SQLite 대체 구현은 PostgreSQL의
  제약, 잠금, 타입 동작을 충분히 검증하지 못하기 때문이다.

## HTTP 프로토콜

### 성공

일반 성공 응답은 다음 구조다.

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

목록 응답은 같은 최상위 구조를 사용하고 `meta`에 `page`, `page_size`, `total`,
`total_pages`를 추가한다. 변경할 본문이 없는 비밀번호 변경과 상품 삭제는
`204 No Content`를 반환한다.

### 실패

실패 응답은 RFC 9457 Problem Details 형식과
`application/problem+json` 미디어 타입을 사용한다. 검증 오류는 필드별 정보를
`errors` 확장 멤버로 제공한다. 응답 본문 `trace_id`, 응답 헤더
`x-request-id`, 구조화 로그의 추적 ID는 같은 요청에서 동일하다.

NestJS의 Exception Filter에 해당하는 역할은 등록된 FastAPI 예외 핸들러가
수행한다. NestJS의 성공 응답 Interceptor와 달리, 이 프로젝트는 라우트별
`response_model`을 사용해 계약을 명시적으로 유지한다.

## 인증과 인가

### Access Token

- JWT Bearer Token이다.
- 기본 유효 시간은 15분이다.
- 보호된 라우트의 FastAPI 의존성이 서명, 만료, 사용자 활성 상태를 검증한다.
- 관리자 라우트는 추가 의존성으로 `ADMIN` 역할을 확인한다.

NestJS Guard에 가장 가까운 구성은 `get_current_user`와 `require_admin`
의존성이다.

### Refresh Token

- 암호학적으로 안전한 256비트 불투명 난수다.
- 데이터베이스에는 원문이 아니라 SHA-256 해시만 저장한다.
- 정상 교환 시 현재 행을 잠그고 기존 토큰을 폐기한 다음 같은 계열의 새 토큰을
  발급한다.
- 이미 사용한 토큰이 다시 제출되면 탈취 가능성으로 보고 같은 계열 전체를
  폐기한다.
- `logout`은 제출한 Refresh Token을, `logout-all`은 사용자의 모든 Refresh
  Token을 폐기한다.

Access Token 폐기 목록은 범위에 포함하지 않았다. 따라서 로그아웃은 Refresh
Token의 추가 발급을 막지만 이미 발급한 Access Token을 즉시 무효화하지 않는다.

## OpenAPI를 계약의 기준으로 사용하기

FastAPI는 라우트, Pydantic 모델, 응답 모델, 보안 의존성에서 OpenAPI 문서를
생성한다. `scripts/export_openapi.py`는 같은 애플리케이션 팩토리를 사용해
결정적인 JSON을 [openapi/openapi.json](../openapi/openapi.json)에 기록한다.

```bash
uv run python scripts/export_openapi.py
```

E2E 테스트는 경로, 보안 요구, Problem Details 스키마를 검증한다. 프론트엔드는
이 파일에서 TypeScript 타입이나 클라이언트를 생성할 수 있다. 생성 절차는
[README의 프론트엔드 연동](../README.md#프론트엔드에서-openapi-사용하기)을
참고한다.

## 확장 기준

- 긴 CPU 계산은 이벤트 루프에서 실행하지 않고 별도 프로세스나 작업 큐로 옮긴다.
- 이메일, 이미지 변환처럼 재시도와 지연 실행이 필요한 작업이 생기면 Celery,
  Dramatiq, ARQ 같은 작업 큐를 검토한다.
- 독립 확장, 독립 배포, 장애 격리가 필요한 기능이 실제로 생기기 전에는 현재
  모듈 경계를 유지한다.
- 외부 서비스 호출에는 비동기 클라이언트와 명시적인 제한 시간, 재시도 정책을
  사용한다.

## 공식 참고 자료

- [FastAPI 문서](https://fastapi.tiangolo.com/)
- [Starlette 문서](https://www.starlette.io/)
- [ASGI 사양](https://asgi.readthedocs.io/en/latest/)
- [Uvicorn 문서](https://www.uvicorn.org/)
- [Pydantic 문서](https://docs.pydantic.dev/latest/)
- [SQLAlchemy asyncio 문서](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Alembic 문서](https://alembic.sqlalchemy.org/en/latest/)
- [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457)
