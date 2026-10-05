"""Tests for application import and the foundation endpoints."""

from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.errors import http_exception_handler, unhandled_exception_handler
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_application_imports() -> None:
    assert app.title == "Fast Bowling V1"
    assert app.version == "0.1.0"


def test_root() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "name": "Fast Bowling V1",
        "version": "0.1.0",
    }


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_unknown_route_is_404() -> None:
    response = client.get("/no-such-route")

    assert response.status_code == 404
    assert "detail" in response.json()


def test_wrong_method_is_405() -> None:
    response = client.post("/health")

    assert response.status_code == 405
    assert "detail" in response.json()


def test_http_exception_keeps_status_and_message() -> None:
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = http_exception_handler(request, HTTPException(status_code=400, detail="bad input"))

    assert response.status_code == 400
    assert response.body == b'{"detail":"bad input"}'


def test_unhandled_exception_does_not_leak_internals() -> None:
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    response = unhandled_exception_handler(
        request, RuntimeError(r"C:\Users\secret\video.mp4 failed")
    )

    assert response.status_code == 500
    assert response.body == b'{"detail":"Internal server error"}'
    assert b"secret" not in response.body
    assert b"video.mp4" not in response.body
