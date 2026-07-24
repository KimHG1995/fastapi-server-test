# Node.js와 Python 서버 런타임 비교

이 문서는 Node.js와 NestJS에 익숙한 개발자가 FastAPI 서버의 동시성 모델을
잘못된 비유 없이 이해하도록 돕는다. 프로젝트 구조와 데이터 흐름은
[서버 아키텍처](architecture.md), 실행 명령은 [README](../README.md)를 참고한다.

## 먼저 바로잡을 표현

`V8 엔진이 nonblocking이다`라는 표현은 정확하지 않다. V8은 JavaScript를
실행하는 엔진이다. Node.js 런타임은 V8에 libuv, event loop, 운영체제의 I/O
polling, 제한된 worker pool, Node 표준 API를 결합한다. 네트워크 준비 상태는
운영체제의 epoll, kqueue, IOCP 같은 메커니즘을 이용하고, 일부 파일 시스템,
DNS, 암호화 작업은 libuv worker pool로 보낸다. JavaScript 콜백 자체가 오래
실행되면 event loop는 여전히 막힌다.

`Python 서버는 멀티스레드다`라는 표현도 정확하지 않다. Python 언어 자체가 웹
서버 실행 방식을 정하지 않는다. 이 프로젝트를 나누어 보면 다음과 같다.

- CPython 3.13은 기본 빌드의 GIL 아래에서 Python 바이트코드를 실행한다.
- Uvicorn은 ASGI 서버로 FastAPI 애플리케이션을 구동한다.
- `async def` 경로는 worker process 안의 asyncio event loop에서 협력적으로
  실행된다.
- 일반 `def` 경로와 동기 의존성은 Starlette가 관리하는 thread pool에서 실행될
  수 있다.
- Uvicorn worker 수를 늘리면 서로 메모리를 공유하지 않는 별도 프로세스가
  생긴다.

thread pool, asyncio Task, worker process는 서로 바꿔 쓸 수 있는 이름이 아니다.
각각 동기 블로킹 코드 격리, 비동기 I/O 동시성, 프로세스 수준 병렬성과 장애
격리라는 다른 문제를 해결한다.

## 용어 대응

| Node.js와 NestJS | Python과 FastAPI | 주의점 |
|---|---|---|
| Promise | Coroutine 또는 Task | Coroutine 객체와 실행 예약된 Task는 같은 것이 아니다 |
| `Promise.all` | `asyncio.gather` | 실패와 취소 전파 규칙을 각각 확인해야 한다 |
| `setTimeout` | `asyncio.sleep` | 둘 다 CPU 작업을 병렬화하지 않는다 |
| Node.js event loop | asyncio event loop | 구현과 스케줄링 규칙은 다르다 |
| Express 또는 NestJS | FastAPI | 프레임워크 계층의 대응이다 |
| Node HTTP server | Uvicorn ASGI server | FastAPI 자체는 소켓 서버가 아니다 |
| cluster worker | Uvicorn worker process | 각 프로세스는 독립 메모리를 가진다 |
| BullMQ | Celery, Dramatiq, ARQ | 이 저장소에는 작업 큐가 없다 |
| Zod DTO | Pydantic model | 런타임 검증과 스키마 생성 역할이 유사하다 |
| Prisma | SQLAlchemy와 Alembic | ORM과 마이그레이션 도구의 경계를 함께 비교한다 |
| Guard | dependency | 인증과 인가 의존성으로 요청을 중단할 수 있다 |
| Exception Filter | exception handler | Problem Details 응답을 중앙에서 만든다 |

## Node.js가 요청을 처리하는 관점

일반적인 Node.js 서버에서 JavaScript는 event loop의 실행 흐름에서 콜백과
Promise 후속 작업을 처리한다. 네트워크 I/O 대기는 운영체제가 감시하고, 준비가
되면 libuv가 해당 이벤트를 다시 event loop에 연결한다. 운영체제가 동일한
비동기 인터페이스를 제공하지 않는 일부 작업은 worker pool을 사용한다.

이 구조는 I/O 대기가 많은 요청을 적은 스레드로 다루는 데 유리하지만 다음 코드는
event loop를 막을 수 있다.

- 매우 큰 JSON을 동기적으로 파싱하거나 직렬화하는 코드
- 복잡한 정규식이나 장시간 반복문
- 동기 파일 시스템 API
- 콜백 안에서 수행하는 큰 CPU 계산

Node.js도 모든 작업이 자동으로 비동기가 되는 런타임은 아니다.

## FastAPI 요청을 처리하는 관점

### ASGI와 Uvicorn

ASGI는 비동기 Python 웹 서버와 애플리케이션 사이의 호출 계약이다. Uvicorn이
HTTP 연결을 받고 ASGI 메시지로 변환하며, FastAPI와 기반 프레임워크인
Starlette가 라우팅, 의존성, 미들웨어, 응답 처리를 수행한다.

```text
클라이언트
  -> Uvicorn, HTTP와 ASGI 서버
  -> FastAPI와 Starlette, 애플리케이션
  -> asyncpg, 비동기 PostgreSQL 드라이버
  -> PostgreSQL
```

### Coroutine과 Task

`async def` 함수를 호출하면 결과가 즉시 계산되는 것이 아니라 Coroutine 객체가
생긴다. `await`는 현재 Coroutine이 기다릴 수 있는 지점에서 제어권을 event
loop에 돌려준다. `asyncio.create_task`는 Coroutine을 event loop에서 실행하도록
예약한 Task를 만든다.

```python
async def load_user() -> User:
    return await repository.get_user()

user_task = asyncio.create_task(load_user())
user = await user_task
```

서로 독립적인 비동기 작업은 `asyncio.gather`로 함께 기다릴 수 있다.

```python
user, products = await asyncio.gather(
    load_user(),
    load_products(),
)
```

`asyncio.gather`를 데이터베이스 쿼리마다 무조건 적용하면 안 된다. 같은
SQLAlchemy `AsyncSession`을 여러 Task에서 동시에 사용하는 것은 안전한 기본
패턴이 아니다. 독립 세션과 실제 병렬 I/O가 필요한지 먼저 판단한다.

`asyncio.sleep`은 event loop를 막지 않고 현재 Coroutine을 일정 시간 양보한다.
`time.sleep`을 `async def` 안에서 호출하면 해당 worker의 event loop를 막는다.

### 동기 함수와 thread pool

FastAPI에서 일반 `def` 경로 함수와 동기 의존성은 thread pool에서 실행될 수
있다. 이는 기존 동기 라이브러리가 event loop를 직접 막지 않도록 돕는다. 하지만
스레드는 무제한 자원이 아니며, 동기 데이터베이스나 외부 API 호출이 쌓이면
thread pool 고갈과 긴 대기가 생길 수 있다.

CPython 기본 빌드의 GIL 때문에 여러 Python 스레드가 일반적인 Python
바이트코드를 동시에 여러 코어에서 계속 실행하는 CPU 병렬화 수단이라고 볼 수
없다. 일부 C 확장은 GIL을 해제할 수 있지만 라이브러리별 동작을 확인해야 한다.

### worker process

운영 환경에서 Uvicorn worker를 여러 개 실행하면 각 worker process가 별도
인터프리터, event loop, 데이터베이스 연결 풀을 가진다. 프로세스 수를 늘리면
여러 CPU 코어를 활용할 수 있지만 메모리와 데이터베이스 연결 수도 함께 늘어난다.
컨테이너 오케스트레이션에서는 컨테이너당 프로세스 수와 복제본 수를 함께
설계해야 한다.

개발용 `--reload`와 다중 worker는 목적이 다르다. `--reload`는 소스 변경 감지용,
worker 증가는 운영 동시성과 병렬성 조정용이다.

## 이 프로젝트가 async를 사용하는 범위

라우터, 서비스, 저장소, SQLAlchemy `AsyncSession`, asyncpg까지 데이터베이스
경로를 비동기로 유지한다. 다음 규칙을 따른다.

- 비동기 함수 안에서는 비동기 데이터베이스와 HTTP 클라이언트를 사용한다.
- 동기 네트워크 호출, 동기 파일 I/O, `time.sleep`을 event loop에서 직접
  실행하지 않는다.
- 짧은 비밀번호 해시 작업은 thread pool로 명시적으로 보낸다.
- 장시간 CPU 작업은 별도 프로세스나 외부 작업 큐로 분리한다.
- 요청마다 하나의 `AsyncSession`을 사용하고 요청이 끝나면 닫는다.

## Django, Flask, FastAPI의 차이

Django와 Flask도 웹과 모바일 클라이언트가 공통으로 쓰는 재사용 가능한 API를
만들 수 있다. Django REST Framework 같은 도구도 성숙한 선택이다. Django나
Flask로 만든 API를 모바일 앱용으로 반드시 다시 작성해야 한다는 주장은 틀리다.

FastAPI의 차별점은 Python 타입 힌트와 Pydantic 검증, OpenAPI 생성, Swagger UI,
ReDoc, ASGI 비동기 처리가 API 개발의 기본 경로에 가깝게 통합되어 있다는 점이다.
Django는 관리자, ORM, 템플릿, 인증을 포함한 큰 웹 프레임워크이고, Flask는 작은
코어에 확장을 조합하는 접근이다. 우열보다 제품 요구와 팀 경험으로 선택해야 한다.

## 성능을 읽는 법

FastAPI가 Starlette와 ASGI 위에서 효율적인 비동기 API를 만들 수 있다는 사실과,
모든 실제 서비스에서 Node.js 또는 Go와 같은 성능을 낸다는 주장은 다르다. 실제
처리량과 지연 시간은 다음 요소에 좌우된다.

- 요청이 I/O 중심인지 CPU 중심인지
- 데이터베이스 쿼리 수, 인덱스, 잠금, 연결 풀 크기
- 검증과 JSON 직렬화 비용
- worker process 수와 컨테이너 복제본 수
- 네트워크, 프록시, TLS, 로깅 설정
- 응답 크기와 외부 서비스 지연

자신의 요청 형태, 데이터, 배포 설정으로 부하 테스트한 결과를 기준으로 결정한다.
프레임워크 벤치마크 하나로 전체 시스템 성능을 단정하지 않는다.

## 공식 참고 자료

- [Node.js 소개](https://nodejs.org/en/learn)
- [Node.js event loop와 worker pool](https://nodejs.org/en/learn/asynchronous-work/dont-block-the-event-loop)
- [libuv 설계](https://docs.libuv.org/en/v1.x/design.html)
- [Python asyncio](https://docs.python.org/3.13/library/asyncio.html)
- [Python Coroutine과 Task](https://docs.python.org/3.13/library/asyncio-task.html)
- [Python GIL FAQ](https://docs.python.org/3.13/faq/library.html#can-t-we-get-rid-of-the-global-interpreter-lock)
- [FastAPI async 설명](https://fastapi.tiangolo.com/async/)
- [FastAPI 배포 개념](https://fastapi.tiangolo.com/deployment/concepts/)
- [Starlette thread pool](https://www.starlette.io/threadpool/)
- [ASGI 사양](https://asgi.readthedocs.io/en/latest/)
- [Uvicorn 배포 문서](https://www.uvicorn.org/deployment/)
