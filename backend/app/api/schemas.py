"""Typed API responses for the current foundation endpoints."""

from pydantic import BaseModel, Field


class RootResponse(BaseModel):
    name: str = Field(examples=["Fast Bowling V1"])
    version: str = Field(examples=["0.1.0"])


class HealthResponse(BaseModel):
    status: str = Field(examples=["healthy"])


class ErrorResponse(BaseModel):
    detail: str
