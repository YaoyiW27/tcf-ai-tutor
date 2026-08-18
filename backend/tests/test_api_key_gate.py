"""The shared-secret gate in front of the API.

These exercise the real middleware; only the setting is swapped, because the
thing under test is exactly what stands between a public URL and your model
credits.
"""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import settings


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


@pytest.fixture
def gated(monkeypatch) -> str:
    key = "s3cret-key"
    monkeypatch.setattr(settings, "api_key", key)
    return key


def test_health_stays_open_so_a_platform_can_probe_it(client, gated):
    # A host checks health before it has any credential to present.
    assert client.get("/health").status_code == 200


def test_request_without_the_key_is_rejected(client, gated):
    assert client.get("/questions").status_code == 401


def test_request_with_a_wrong_key_is_rejected(client, gated):
    assert client.get("/questions", headers={"x-api-key": "nope"}).status_code == 401


def test_request_with_the_key_passes_the_gate(client, gated):
    # A route that needs no database, so this asserts the gate opened and
    # nothing else.
    assert client.get("/openapi.json", headers={"x-api-key": gated}).status_code == 200


def test_docs_are_behind_the_gate_too(client, gated):
    # /docs and /openapi.json describe the whole surface — leaving them open
    # publishes the API to anyone who guesses the path.
    assert client.get("/docs").status_code == 401
    assert client.get("/openapi.json").status_code == 401


def test_preflight_is_not_gated(client, gated):
    # A CORS preflight carries no custom headers to check; gating it would make
    # every browser request fail before the real request is ever sent.
    resp = client.options(
        "/questions",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code != 401


def test_no_key_configured_leaves_the_api_open(client, monkeypatch):
    # The local default. Documented and warned about at startup, not silent.
    monkeypatch.setattr(settings, "api_key", None)
    assert client.get("/openapi.json").status_code == 200


def test_cors_origins_parse_from_a_comma_separated_setting(monkeypatch):
    monkeypatch.setattr(
        settings, "cors_origins", "https://tcf.example.app, http://localhost:3000 ,"
    )
    assert main._allowed_origins() == ["https://tcf.example.app", "http://localhost:3000"]
