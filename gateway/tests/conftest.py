"""Shared fixtures for the gateway tests."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    """In-process client for the gateway app (no network)."""
    return TestClient(app)
