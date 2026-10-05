"""FastAPI application entrypoint."""

import logging

from fastapi import FastAPI, HTTPException

from app import __version__
from app.api.errors import http_exception_handler, unhandled_exception_handler
from app.api.routes import router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="Fast Bowling V1",
    version=__version__,
    description=(
        "Backend API for the Fast Bowling V1 prototype. "
        "Phases 1–3 provide identification, health checks, local video reading, "
        "and pose estimation. Video upload and biomechanical analysis are not implemented."
    ),
)

app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)
app.include_router(router)
