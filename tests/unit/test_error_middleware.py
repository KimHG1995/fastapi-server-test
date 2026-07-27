import json
from typing import cast
from uuid import UUID

import pytest
from starlette.types import Message, Receive, Scope, Send

from app.core.error_middleware import UnexpectedErrorMiddleware

TRACE_ID = UUID("11111111-1111-4111-8111-111111111111")


def _http_scope() -> Scope:
    return cast(
        Scope,
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/boom",
            "raw_path": b"/boom",
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
            "state": {"trace_id": TRACE_ID},
        },
    )


async def _receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


async def test_exception_before_response_start_returns_problem_without_reraising() -> None:
    sent: list[Message] = []

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        del scope, receive, send
        raise RuntimeError("Authorization: Bearer private-credential")

    async def capture(message: Message) -> None:
        sent.append(message)

    middleware = UnexpectedErrorMiddleware(downstream)

    await middleware(_http_scope(), _receive, capture)

    starts = [message for message in sent if message["type"] == "http.response.start"]
    assert len(starts) == 1
    assert starts[0]["status"] == 500
    headers = dict(starts[0]["headers"])
    assert headers[b"content-type"].startswith(b"application/problem+json")
    assert headers[b"x-request-id"] == str(TRACE_ID).encode()
    body = json.loads(cast(bytes, sent[1]["body"]))
    assert body["code"] == "INTERNAL_SERVER_ERROR"
    assert body["detail"] == "An unexpected error occurred."
    assert "private-credential" not in cast(bytes, sent[1]["body"]).decode()


async def test_exception_after_response_start_is_reraised_without_second_start() -> None:
    sent: list[Message] = []
    error = RuntimeError("stream failed")
    started: Message = {
        "type": "http.response.start",
        "status": 200,
        "headers": [],
    }

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        del scope, receive
        await send(started)
        raise error

    async def capture(message: Message) -> None:
        sent.append(message)

    middleware = UnexpectedErrorMiddleware(downstream)

    with pytest.raises(RuntimeError) as raised:
        await middleware(_http_scope(), _receive, capture)

    assert raised.value is error
    assert sent == [started]
