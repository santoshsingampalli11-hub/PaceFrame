"""Shared test fixtures. These do not touch demonstration sessions."""

from __future__ import annotations

import pytest

from app.api.http_guards import reset_rate_limits


@pytest.fixture(autouse=True)
def _isolated_rate_limit() -> None:
    reset_rate_limits()
    yield
    reset_rate_limits()
