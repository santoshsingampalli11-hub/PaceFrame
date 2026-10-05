"""Safe HTTP error responses that do not leak internals."""

import logging

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("fast_bowling.api")


def error_payload(message: str) -> dict[str, str]:
    return {"detail": message}


def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=error_payload(str(exc.detail)))


def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled API exception: %s", type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content=error_payload("Internal server error"),
    )
