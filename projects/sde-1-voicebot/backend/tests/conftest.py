"""Shared pytest configuration and fixtures for backend test isolation."""

import pytest

from app.main import rate_limiter


@pytest.fixture(autouse=True)
def reset_rate_limiter_fixture():
    """Reset the sliding-window rate limiter before and after every test."""
    rate_limiter.reset()
    yield
    rate_limiter.reset()
