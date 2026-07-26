from fastapi import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import unexpected_error_response


class UnexpectedErrorMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_with_state(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_with_state)
        except Exception as exc:
            response = unexpected_error_response(Request(scope, receive), exc)
            if not response_started:
                await response(scope, receive, send)
