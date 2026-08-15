"""Shared fixtures for the gateway tests."""

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from app.main import app


@pytest.fixture
def client() -> TestClient:
    """In-process client for the gateway app (no network)."""
    return TestClient(app)


@pytest.fixture
def counter():
    """Read a Prometheus counter sample by name + labels; 0.0 if not yet present.

    The gateway registers on the default global REGISTRY, so counters persist
    across tests in a session — assert on a before/after delta, never on an
    absolute value.
    """

    def _read(name: str, **labels: str) -> float:
        return REGISTRY.get_sample_value(name, labels) or 0.0

    return _read
