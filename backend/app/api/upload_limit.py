"""Reject oversized upload request bodies before they fill session storage.

Content-Length is checked when present, but the body is still counted while
it is received so a missing or incorrect header cannot bypass the limit.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from app.api.settings import get_settings

Receive = Callable[[], Awaitable[dict[str, object]]]
Send = Callable[[dict[str, object]], Awaitable[None]]

_UPLOAD_PATH = "/api/sessions"
_UPLOAD_METHOD = "POST"
_LIMIT_MESSAGE = "Upload exceeds the configured size limit."


class BodyLimitExceeded(Exception):
    """The request body grew past the configured byte limit."""


class UploadByteLimitMiddleware:
    """ASGI wrapper that caps POST /api/sessions request bodies."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, object], receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        if scope.get("method") != _UPLOAD_METHOD or scope.get("path") != _UPLOAD_PATH:
            await self.app(scope, receive, send)
            return

        limit = get_settings().max_request_bytes
        header_length = _content_length(scope)
        if header_length is not None and header_length > limit:
            await _drain(receive, limit)
            await _send_detail(send, 413, _LIMIT_MESSAGE)
            return

        received = 0
        response_started = False

        async def limited_receive() -> dict[str, object]:
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body") or b""
                received += len(body)
                if received > limit:
                    raise BodyLimitExceeded()
            return message

        async def tracked_send(message: dict[str, object]) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except BodyLimitExceeded:
            if not response_started:
                await _send_detail(send, 413, _LIMIT_MESSAGE)


def _content_length(scope: dict[str, object]) -> int | None:
    headers = scope.get("headers") or []
    for name, value in headers:
        if name == b"content-length":
            try:
                return int(value.decode("latin-1"))
            except (UnicodeDecodeError, ValueError):
                return None
    return None


async def _drain(receive: Receive, max_bytes: int) -> None:
    discarded = 0
    while discarded <= max_bytes:
        message = await receive()
        if message.get("type") == "http.disconnect":
            return
        if message.get("type") == "http.request":
            discarded += len(message.get("body") or b"")
            if not message.get("more_body"):
                return


async def _send_detail(send: Send, status_code: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
