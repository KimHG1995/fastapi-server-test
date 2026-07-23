# FastAPI 학습용 서버 설계

## 1. 목적

이 저장소는 웹과 모바일 앱이 함께 사용할 수 있는 REST API 서버를 FastAPI와 PostgreSQL로 구현하는 학습용 프로젝트다.

기존 `nestjs-monorepo-test`와 기능과 통신 계약을 비교할 수 있도록 다음 내용을 실제 코드로 보여준다.

- 사용자 가입과 JWT 기반 인증
- 회전형 Refresh Token과 재사용 탐지
- 역할 기반 인가
- 관리자용 상품 CRUD
- Pydantic 기반 요청과 응답 검증
- RFC 9457 Problem Details 오류 응답
- Swagger UI, ReDoc, OpenAPI JSON
- SQLAlchemy 2 비동기 ORM과 Alembic 마이그레이션
- 단위, 통합, E2E 테스트
- Node.js, NestJS, Python, FastAPI의 실행 모델과 구조 비교

프로젝트 이름은 `fastapi-server-test`다. NestJS 프로젝트와 달리 여러 애플리케이션을 포함하는 모노레포로 만들지 않는다. 하나의 FastAPI 애플리케이션과 하나의 PostgreSQL 데이터베이스를 사용하는 기능 중심 모듈형 모놀리스로 구성한다.

## 2. 성공 기준

다음 조건을 모두 만족하면 첫 학습용 버전이 완성된 것으로 본다.

1. 일반 사용자가 가입하고 로그인할 수 있다.
2. 로그인 응답으로 JWT Access Token과 회전 가능한 Refresh Token을 받는다.
3. 정상적인 Refresh Token 교환은 기존 토큰을 폐기하고 새 토큰을 발급한다.
4. 이미 사용된 Refresh Token을 다시 제출하면 같은 토큰 계열 전체가 폐기된다.
5. 일반 사용자는 자신의 정보를 조회하고 표시 이름과 비밀번호를 변경할 수 있다.
6. 누구나 활성 상품을 조회할 수 있다.
7. `ADMIN` 역할만 상품을 생성, 수정, 소프트 삭제할 수 있다.
8. 성공 응답과 실패 응답이 정해진 프로토콜을 따른다.
9. OpenAPI 명세가 실제 요청과 응답 계약을 표현하며 파일로 내보내진다.
10. 프론트엔드가 OpenAPI 파일에서 TypeScript 타입이나 API 클라이언트를 생성할 수 있다.
11. 실제 PostgreSQL을 사용하는 통합 테스트와 전체 인증 흐름을 검증하는 E2E 테스트가 존재한다.
12. README가 Node.js와 Python의 실행 모델 차이를 정확하게 설명한다.
13. 모든 Markdown 문서에 가운뎃점 문자가 없다.

## 3. 범위

### 3.1 포함

- 이메일과 비밀번호 기반 사용자 가입
- Access Token과 Refresh Token 기반 로그인
- Refresh Token 회전, 로그아웃, 전체 로그아웃
- 내 정보 조회와 표시 이름 변경
- 현재 비밀번호 확인을 포함한 비밀번호 변경
- `USER`, `ADMIN` 역할
- 관리자 생성 CLI
- 상품 생성, 목록, 상세, 수정, 소프트 삭제
- 상품 검색, 페이지네이션, 정렬
- 비동기 PostgreSQL 접근
- 데이터베이스 마이그레이션
- 구조화 로그와 요청 추적 ID
- CORS 설정
- 상태 확인 API
- 자동 OpenAPI 생성과 정적 JSON 내보내기
- Docker Compose 기반 개발 환경
- 코드 품질과 테스트 자동화

### 3.2 제외

- 이메일 인증
- 비밀번호 찾기 메일
- 소셜 로그인
- 결제
- 장바구니와 주문
- 파일 업로드
- 다중 조직과 테넌트
- Redis
- Celery 또는 다른 작업 큐
- Access Token 즉시 폐기 목록
- 마이크로서비스 분리
- Kubernetes 배포

제외 항목은 현재 목표를 이해하는 데 필요하지 않으며 초기 구조를 불필요하게 복잡하게 만들기 때문에 구현하지 않는다.

## 4. 기술 선택

### 4.1 실행 환경

- Python 3.13
- FastAPI
- Uvicorn
- PostgreSQL
- Docker와 Docker Compose

현재 개발 장비의 기본 Python은 3.9이므로 Docker Compose를 가장 재현성 높은 기본 실행 경로로 제공한다. 로컬 개발자를 위해 Python 3.13과 `uv` 사용법도 제공한다. `uv`를 사용할 수 없는 환경을 위해 표준 `venv`와 `pip` 실행 방법도 유지한다.

### 4.2 핵심 라이브러리

- Pydantic v2, 요청과 응답 모델 검증
- pydantic-settings, 환경변수 검증
- SQLAlchemy 2, 비동기 ORM과 쿼리
- asyncpg, PostgreSQL 비동기 드라이버
- Alembic, 스키마 마이그레이션
- PyJWT, Access Token 생성과 검증
- pwdlib와 Argon2, 비밀번호 해시
- structlog, 구조화 로그

### 4.3 개발 라이브러리

- pytest
- pytest-asyncio
- HTTPX
- Testcontainers for Python
- Ruff
- mypy

## 5. 아키텍처

### 5.1 전체 구조

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
│   │   └── session.py
│   └── modules/
│       ├── auth/
│       │   ├── dependencies.py
│       │   ├── models.py
│       │   ├── repository.py
│       │   ├── router.py
│       │   ├── schemas.py
│       │   └── service.py
│       ├── users/
│       │   ├── models.py
│       │   ├── repository.py
│       │   ├── router.py
│       │   ├── schemas.py
│       │   └── service.py
│       └── products/
│           ├── dependencies.py
│           ├── models.py
│           ├── repository.py
│           ├── router.py
│           ├── schemas.py
│           └── service.py
├── migrations/
├── scripts/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── openapi/
├── docs/
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

### 5.2 계층별 책임

#### 라우터

- HTTP 경로, 상태 코드, 요청 모델, 응답 모델을 선언한다.
- FastAPI 의존성으로 세션, 현재 사용자, 역할을 받는다.
- 비즈니스 규칙이나 SQLAlchemy 쿼리를 포함하지 않는다.

#### 서비스

- 유스케이스와 비즈니스 규칙을 구현한다.
- 쓰기 작업의 트랜잭션 경계를 관리한다.
- 도메인 오류를 명시적인 애플리케이션 예외로 변환한다.
- FastAPI의 `Request`나 `Response`에 의존하지 않는다.

#### 저장소

- SQLAlchemy 쿼리와 영속성 작업만 담당한다.
- `flush`는 수행할 수 있지만 `commit`은 수행하지 않는다.
- HTTP 오류나 Pydantic 응답 모델을 알지 못한다.

#### ORM 모델

- PostgreSQL 테이블, 제약, 관계를 정의한다.
- API 요청과 응답 계약으로 직접 사용하지 않는다.

#### Pydantic 스키마

- 외부 입력과 출력 계약을 정의한다.
- ORM 객체 변환에는 Pydantic v2의 `ConfigDict(from_attributes=True)`를 사용한다.
- 비밀번호 해시와 Refresh Token 해시는 출력 모델에 포함하지 않는다.

### 5.3 요청 처리 흐름

```text
HTTP 요청
  -> Request ID 미들웨어
  -> CORS와 구조화 로깅
  -> FastAPI 라우터
  -> Pydantic 요청 검증
  -> 인증과 역할 의존성
  -> 서비스
  -> 저장소
  -> SQLAlchemy AsyncSession
  -> PostgreSQL
```

성공 응답을 사후 미들웨어에서 변형하지 않는다. 각 라우트가 `ApiResponse[T]` 형태의 Pydantic 응답 모델을 명시한다. 이 원칙은 실제 응답과 OpenAPI 명세가 달라지는 문제를 방지한다.

## 6. 비동기 실행과 데이터베이스

### 6.1 이벤트 루프

Uvicorn은 ASGI 서버로서 FastAPI 애플리케이션을 실행한다. `async def` 라우트와 의존성은 asyncio 이벤트 루프에서 실행된다. 일반 `def` 라우트와 의존성은 FastAPI와 Starlette가 관리하는 스레드 풀에서 실행될 수 있다.

이 프로젝트의 데이터베이스 경로는 `async def`, SQLAlchemy `AsyncSession`, asyncpg로 통일한다. 이벤트 루프에서 동기 네트워크 요청, 동기 파일 I/O, 장시간 CPU 계산을 직접 수행하지 않는다.

CPU 집약 작업은 프로세스 풀이나 외부 작업 큐로 옮겨야 한다. 이 프로젝트에는 작업 큐를 구현하지 않지만 README에서 확장 기준을 설명한다.

### 6.2 세션과 트랜잭션

- 애플리케이션은 `create_async_engine`으로 엔진을 생성한다.
- `async_sessionmaker`는 `expire_on_commit=False`로 구성한다.
- 요청마다 `AsyncSession` 하나를 생성하고 요청 종료 시 닫는다.
- 쓰기 서비스는 명시적인 트랜잭션 블록을 연다.
- 예외가 발생하면 트랜잭션을 롤백한다.
- 저장소는 트랜잭션을 독자적으로 커밋하지 않는다.
- 관계 조회가 필요하면 `selectinload` 같은 eager loading을 명시한다.
- 테스트와 종료 과정에서 엔진을 명시적으로 해제한다.

### 6.3 애플리케이션 수명 주기

FastAPI의 `lifespan` 비동기 컨텍스트 관리자를 사용한다. 시작 시 공유 자원을 준비하고 종료 시 데이터베이스 엔진을 해제한다. 테스트는 수명 주기를 실행하는 방식으로 애플리케이션 시작과 종료를 검증한다.

## 7. 데이터 모델

### 7.1 users

| 필드 | 의미 |
|---|---|
| `id` | UUID 기본 키 |
| `email` | 소문자로 정규화한 고유 이메일 |
| `password_hash` | Argon2 비밀번호 해시 |
| `display_name` | 사용자 표시 이름 |
| `role` | `USER` 또는 `ADMIN` |
| `is_active` | 로그인 허용 여부 |
| `created_at` | UTC 생성 시각 |
| `updated_at` | UTC 수정 시각 |

공개 가입은 항상 `USER` 역할을 부여한다. 클라이언트 입력으로 역할을 변경할 수 없다.

### 7.2 refresh_tokens

| 필드 | 의미 |
|---|---|
| `id` | UUID 기본 키 |
| `user_id` | 사용자 외래 키 |
| `family_id` | 회전 계열 UUID |
| `token_hash` | Refresh Token SHA-256 해시 |
| `expires_at` | UTC 만료 시각 |
| `revoked_at` | 폐기 시각 |
| `replaced_by_id` | 다음 토큰 자기 참조 외래 키 |
| `created_at` | UTC 생성 시각 |

`token_hash`에는 고유 제약과 인덱스를 둔다. 원본 Refresh Token은 응답 시 한 번만 클라이언트에 전달한다.

### 7.3 products

| 필드 | 의미 |
|---|---|
| `id` | UUID 기본 키 |
| `sku` | 고유 상품 코드 |
| `name` | 상품 이름 |
| `description` | 선택 설명 |
| `price_in_minor_units` | 최소 화폐 단위의 정수 가격 |
| `currency` | ISO 4217 통화 코드 |
| `stock_quantity` | 0 이상의 정수 재고 |
| `is_active` | 판매와 공개 여부 |
| `created_by_id` | 생성한 관리자 외래 키 |
| `created_at` | UTC 생성 시각 |
| `updated_at` | UTC 수정 시각 |
| `deleted_at` | 소프트 삭제 시각 |

일반 상품 조회는 `deleted_at IS NULL`이고 `is_active = true`인 상품만 반환한다. SKU는 소프트 삭제 후에도 재사용하지 않는다.

## 8. 인증과 인가

### 8.1 비밀번호

- 비밀번호는 pwdlib의 권장 Argon2 설정으로 해시한다.
- 로그인 시 이메일이 존재하지 않아도 더미 해시 검증을 수행해 사용자 존재 여부에 따른 시간 차이를 줄인다.
- 비밀번호 원문은 로그에 기록하지 않는다.
- 비밀번호 변경은 현재 비밀번호를 먼저 검증한다.
- 비밀번호가 변경되면 사용자의 모든 Refresh Token 계열을 폐기한다.

### 8.2 Access Token

- JWT를 사용한다.
- 기본 만료 시간은 15분이다.
- `sub`에는 사용자 UUID를 넣는다.
- `role`, `iat`, `exp`, `jti`, 토큰 종류를 포함한다.
- 허용 알고리즘을 설정에서 고정하며 토큰 헤더가 선택하도록 두지 않는다.
- API는 `Authorization: Bearer <token>` 형식을 사용한다.

### 8.3 Refresh Token

- 암호학적으로 안전한 256비트 난수로 생성한다.
- 기본 만료 시간은 30일이다.
- 원문 대신 SHA-256 해시를 저장한다.
- 갱신 시 대상 행을 잠그고 아직 사용되지 않은 유효한 토큰인지 확인한다.
- 유효하면 기존 토큰을 폐기하고 같은 `family_id`의 새 토큰을 만든다.
- 이미 폐기된 토큰이 다시 제출되면 같은 `family_id` 전체를 폐기한다.
- 로그아웃은 제시된 Refresh Token을 폐기한다.
- 전체 로그아웃은 해당 사용자의 모든 활성 Refresh Token을 폐기한다.

Access Token은 서버 상태를 매 요청 조회하지 않으므로 로그아웃 뒤에도 최대 15분 동안 유효할 수 있다. 이 동작을 README와 API 문서에 명시한다.

### 8.4 역할

- 상품 조회는 공개한다.
- 상품 생성, 수정, 삭제는 `ADMIN`만 허용한다.
- 인증 실패는 `401`을 반환한다.
- 인증은 성공했지만 역할이 부족하면 `403`을 반환한다.
- 관리자 계정은 공개 API가 아니라 CLI로 생성한다.

## 9. HTTP API

기본 경로는 `/api/v1`이다.

### 9.1 인증과 사용자

| 메서드 | 경로 | 인증 | 동작 |
|---|---|---|---|
| `POST` | `/api/v1/auth/register` | 없음 | 일반 사용자 가입 |
| `POST` | `/api/v1/auth/login` | 없음 | 토큰 발급 |
| `POST` | `/api/v1/auth/refresh` | Refresh Token 본문 | 토큰 회전 |
| `POST` | `/api/v1/auth/logout` | Refresh Token 본문 | 현재 세션 폐기 |
| `POST` | `/api/v1/auth/logout-all` | Access Token | 전체 세션 폐기 |
| `GET` | `/api/v1/users/me` | Access Token | 내 정보 조회 |
| `PATCH` | `/api/v1/users/me` | Access Token | 표시 이름 수정 |
| `POST` | `/api/v1/users/me/password` | Access Token | 비밀번호 변경 |

로그인은 JSON 요청을 사용한다. OpenAPI에는 HTTP Bearer 보안 스키마를 등록한다. Swagger UI 사용자는 로그인 응답에서 받은 Access Token을 `Authorize` 대화 상자에 입력한다.

### 9.2 상품

| 메서드 | 경로 | 인증 | 동작 |
|---|---|---|---|
| `GET` | `/api/v1/products` | 없음 | 검색, 페이지네이션, 정렬 |
| `GET` | `/api/v1/products/{product_id}` | 없음 | 활성 상품 상세 |
| `POST` | `/api/v1/products` | `ADMIN` | 상품 생성 |
| `PATCH` | `/api/v1/products/{product_id}` | `ADMIN` | 상품 부분 수정 |
| `DELETE` | `/api/v1/products/{product_id}` | `ADMIN` | 상품 소프트 삭제 |

목록 조회는 다음 쿼리를 지원한다.

- `page`, 1 이상의 페이지 번호
- `page_size`, 기본 20, 최대 100
- `query`, SKU와 이름 검색
- `sort`, 허용 목록에 포함된 정렬 필드
- `order`, `asc` 또는 `desc`

정렬 필드 문자열을 SQL에 직접 삽입하지 않고 허용된 ORM 열 매핑을 사용한다.

### 9.3 상태 확인

| 메서드 | 경로 | 동작 |
|---|---|---|
| `GET` | `/health/live` | 프로세스 생존 확인 |
| `GET` | `/health/ready` | PostgreSQL 연결 준비 확인 |

## 10. 통신 프로토콜

### 10.1 성공 응답

일반 성공 응답은 다음 형태다.

```json
{
  "success": true,
  "data": {},
  "meta": {
    "timestamp": "2026-07-23T00:00:00Z",
    "path": "/api/v1/products",
    "trace_id": "7db7f5ce-6ba2-4620-a671-7d93984f22f5"
  }
}
```

목록 응답의 `meta`는 다음 필드를 추가한다.

```json
{
  "page": 1,
  "page_size": 20,
  "total": 42,
  "total_pages": 3
}
```

`DELETE` 성공과 본문이 필요하지 않은 작업은 `204 No Content`를 반환하며 성공 응답 래퍼를 사용하지 않는다.

### 10.2 오류 응답

오류는 RFC 9457 Problem Details를 따르고 `application/problem+json`으로 반환한다.

```json
{
  "type": "https://example.com/problems/validation-failed",
  "title": "Validation Failed",
  "status": 422,
  "detail": "요청 데이터가 유효하지 않습니다.",
  "instance": "/api/v1/products",
  "code": "VALIDATION_FAILED",
  "trace_id": "7db7f5ce-6ba2-4620-a671-7d93984f22f5",
  "errors": [
    {
      "field": "price_in_minor_units",
      "message": "0 이상의 정수여야 합니다.",
      "code": "greater_than_equal"
    }
  ]
}
```

전역 예외 처리기는 다음 오류를 변환한다.

- Pydantic 요청 검증 실패
- 인증 실패
- 역할 부족
- 리소스 없음
- 이메일 또는 SKU 충돌
- 데이터베이스 제약 위반
- 예상하지 못한 서버 오류

운영 환경의 `500` 응답에는 내부 예외 메시지와 스택 추적을 노출하지 않는다. 로그에는 `trace_id`와 전체 예외 정보를 남긴다.

## 11. OpenAPI와 프론트엔드 계약

- Swagger UI는 `/docs`에서 제공한다.
- ReDoc은 `/redoc`에서 제공한다.
- OpenAPI JSON은 `/openapi.json`에서 제공한다.
- 정적 명세는 `openapi/openapi.json`에 결정적으로 내보낸다.
- 요청 모델, 응답 래퍼, 페이지 메타데이터, Problem Details를 모두 스키마에 포함한다.
- 인증이 필요한 경로에는 HTTP Bearer 보안 요구가 표시되어야 한다.
- OpenAPI 내보내기 스크립트는 변경된 명세를 코드 리뷰할 수 있게 한다.

README에는 다음 프론트엔드 명령 예를 제공한다.

```bash
npx openapi-typescript ./openapi/openapi.json -o src/api/schema.d.ts
```

Orval을 사용하는 경우 생성기 설정에서 같은 OpenAPI JSON을 입력으로 사용할 수 있음을 설명한다. Python 저장소에 Node.js 생성 도구를 필수 의존성으로 추가하지 않는다.

## 12. 테스트

### 12.1 단위 테스트

- 비밀번호 해시와 검증
- Access Token 생성과 검증
- Refresh Token 생성과 해시
- 역할 검사
- 상품 입력 규칙
- 서비스의 충돌과 리소스 없음 처리

단위 테스트는 가능한 한 데이터베이스와 네트워크를 사용하지 않는다.

### 12.2 통합 테스트

Testcontainers for Python으로 실제 PostgreSQL을 실행한다.

- Alembic 마이그레이션 적용
- ORM 매핑
- 이메일과 SKU 고유 제약
- 상품 소프트 삭제 쿼리
- Refresh Token 행 잠금과 회전
- Refresh Token 재사용 시 계열 폐기

SQLite는 PostgreSQL의 제약, 잠금, 타입 동작을 동일하게 재현하지 못하므로 통합 테스트 대체제로 사용하지 않는다.

### 12.3 E2E 테스트

HTTPX 비동기 클라이언트로 다음 흐름을 검증한다.

1. 사용자 가입
2. 로그인
3. 내 정보 조회
4. 관리자 생성
5. 일반 사용자의 상품 생성 거부
6. 관리자의 상품 생성, 수정, 삭제
7. 공개 상품 검색과 페이지네이션
8. Refresh Token 회전
9. 사용된 Refresh Token 재사용 탐지
10. 로그아웃과 전체 로그아웃

### 12.4 OpenAPI 테스트

- 주요 경로가 존재한다.
- 요청과 응답 모델이 등록된다.
- 보호된 경로에 HTTP Bearer 요구가 있다.
- 공개 경로에 불필요한 보안 요구가 없다.
- Problem Details 스키마가 오류 응답에 연결된다.
- 정적 OpenAPI JSON이 현재 애플리케이션 스키마와 일치한다.

### 12.5 문서 테스트

다음 검사에서 결과가 나오면 실패한다.

```bash
rg -n $'\u00B7' . --glob '*.md'
```

## 13. 코드 품질

- Ruff로 포맷과 린트를 수행한다.
- mypy를 엄격 모드로 실행한다.
- pytest로 테스트를 실행한다.
- 공개 함수와 복잡한 도메인 규칙에는 타입과 설명을 남긴다.
- ORM 모델과 Pydantic 모델을 섞어 쓰지 않는다.
- 비밀번호, 토큰, 데이터베이스 연결 문자열은 로그에 기록하지 않는다.
- 환경변수는 Pydantic Settings로 시작 시 검증한다.
- 운영 설정에서 임의의 CORS 전체 허용을 기본값으로 두지 않는다.

## 14. Docker와 실행

Docker Compose는 다음 서비스를 제공한다.

- `api`, FastAPI와 Uvicorn
- `postgres`, 개발 PostgreSQL

애플리케이션 시작과 마이그레이션은 분리한다. 운영 환경에서 여러 프로세스가 동시에 자동 마이그레이션을 실행하지 않도록 API 컨테이너가 스키마를 암묵적으로 변경하지 않는다.

개발 명령은 Makefile 또는 문서화된 명령으로 다음 작업을 제공한다.

- 의존성 설치
- 개발 서버 실행
- 마이그레이션 생성과 적용
- 관리자 생성
- 테스트
- 린트
- 타입 검사
- OpenAPI 내보내기
- Docker Compose 시작과 종료

## 15. README 구성

README는 코드 실행법과 함께 다음 학습 내용을 설명한다.

1. V8은 JavaScript 실행 엔진이며 Node.js의 비동기 I/O는 이벤트 루프와 libuv를 포함한 런타임 구조에서 나온다.
2. Python이 자동으로 멀티스레드 웹 서버가 되는 것은 아니다.
3. 일반 CPython 빌드의 GIL, 운영체제 스레드, 프로세스, asyncio의 역할은 서로 다르다.
4. FastAPI, Starlette, ASGI, Uvicorn의 관계를 설명한다.
5. `async def` 라우트와 일반 `def` 라우트의 실행 경로를 비교한다.
6. 이벤트 루프를 막는 코드와 안전한 비동기 I/O를 예제로 비교한다.
7. Promise, Coroutine, Task, `Promise.all`, `asyncio.gather`의 대응 관계를 설명한다.
8. Node.js cluster와 Uvicorn worker 프로세스를 비교한다.
9. NestJS Module, Controller, Provider, Guard, Interceptor, Exception Filter를 FastAPI 구성요소와 비교한다.
10. Zod와 Pydantic의 런타임 검증과 타입 생성 방식을 비교한다.
11. Prisma와 SQLAlchemy, Alembic의 책임 차이를 설명한다.
12. Swagger UI, ReDoc, OpenAPI JSON을 사용하는 방법을 설명한다.
13. 프론트엔드에서 OpenAPI 기반 TypeScript 타입과 클라이언트를 생성하는 방법을 설명한다.
14. 개발 서버와 운영용 다중 worker 구성 차이를 설명한다.

Python이 멀티스레드인지 여부를 하나의 문장으로 단순화하지 않는다. 이 프로젝트는 일반 GIL 포함 CPython 빌드를 기준으로 하며, 비동기 I/O, 스레드 풀, worker 프로세스를 각각 어떤 상황에 사용하는지 구분해서 설명한다.

## 16. 보안 기준

- 비밀번호는 Argon2로 해시한다.
- Refresh Token 원문을 저장하지 않는다.
- JWT 알고리즘과 필수 클레임을 검증한다.
- 로그인 오류 메시지로 이메일 존재 여부를 구분하지 않는다.
- 역할은 가입과 사용자 수정 요청에서 받지 않는다.
- 정렬 필드는 허용 목록을 사용한다.
- SQLAlchemy 표현식과 바인딩을 사용하며 문자열 SQL 조합을 피한다.
- 모든 비밀값은 환경변수로 받는다.
- 예제 환경 파일에는 실제 비밀값을 넣지 않는다.
- 운영 오류 응답에 내부 정보를 노출하지 않는다.
- 의존성 버전은 잠금 파일로 재현 가능하게 관리한다.

속도 제한, 계정 잠금, 이메일 인증은 운영 서비스에서 필요할 수 있지만 이 학습 범위에는 포함하지 않는다. README의 운영 확장 항목에서 그 필요성을 설명한다.

## 17. 참고 기준

설계와 구현은 다음 공식 문서를 기준으로 한다.

- FastAPI 문서, <https://fastapi.tiangolo.com/>
- SQLAlchemy 2 문서, <https://docs.sqlalchemy.org/en/20/>
- Pydantic 문서, <https://docs.pydantic.dev/>
- Alembic 문서, <https://alembic.sqlalchemy.org/>
- Python asyncio 문서, <https://docs.python.org/3/library/asyncio.html>
- RFC 9457 Problem Details, <https://www.rfc-editor.org/rfc/rfc9457>

구현 시 현재 공식 문서의 권장 API를 다시 확인하고 의존성 잠금 파일에 실제 버전을 기록한다.
