"""Single-process host and rate guards.

These limits live in this process only. A second Uvicorn worker or a second
container does not share them. V1 is one application instance.
"""

from __future__ import annotations

import json
import threading
import time

from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.settings import get_settings

_lock = threading.Lock()
_events: dict[tuple[str, str], list[float]] = {}


def reset_rate_limits() -> None:
    """Drop recorded requests. Tests use this so cases do not share a window."""
    with _lock:
        _events.clear()


def host_allowed(host_header: str, allowed: tuple[str, ...]) -> bool:
    """Match the hostname, ignoring a trailing port. Forwarded headers are not read."""
    name = _hostname(host_header)
    if not name:
        return False
    return name in {item.lower() for item in allowed}


class TrustedHostGuard:
    """Reject a Host header that is not on the configured list."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        host = _header(scope, b"host")
        if not host_allowed(host, get_settings().trusted_hosts):
            await _json(send, 400, "Invalid host.")
            return
        await self.app(scope, receive, send)


class RateLimitGuard:
    """Limit uploads and new processing jobs for one client address."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        settings = get_settings()
        kind = _limited_kind(scope.get("method", ""), scope.get("path", ""))
        if settings.rate_limit_enabled and kind is not None:
            limit = settings.upload_limit if kind == "upload" else settings.job_limit
            identity = _client(scope)
            if not _allow(identity, kind, limit, float(settings.rate_window_seconds)):
                detail = (
                    "Too many uploads. Wait and try again."
                    if kind == "upload"
                    else "Too many processing requests. Wait and try again."
                )
                await _json(send, 429, detail)
                return
        await self.app(scope, receive, send)


def _limited_kind(method: str, path: str) -> str | None:
    if method != "POST":
        return None
    if path == "/api/sessions":
        return "upload"
    if path.endswith("/pose-review") and "/frames/" not in path:
        return "job"
    if path.endswith("/measure"):
        return "job"
    return None


def _allow(identity: str, kind: str, limit: int, window_seconds: float) -> bool:
    now = time.monotonic()
    with _lock:
        bucket = _events.setdefault((identity, kind), [])
        cutoff = now - window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


def _client(scope: Scope) -> str:
    client = scope.get("client")
    if isinstance(client, tuple) and client:
        return str(client[0])
    return "unknown"


def _header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return ""


def _hostname(value: str) -> str:
    text = value.strip().lower()
    if text.startswith("["):
        end = text.find("]")
        return text[1:end] if end > 1 else ""
    if text.count(":") == 1:
        return text.split(":", 1)[0]
    return text


async def _json(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
