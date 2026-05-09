"""Tests for the authentication middleware."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copilot_gateway.middleware import APIKeyMiddleware


@dataclass
class _FakeServerConfig:
    api_key: str


@dataclass
class _FakeConfig:
    server: _FakeServerConfig


def _make_app(api_key: str = "") -> FastAPI:
    """Create a minimal FastAPI app with the auth middleware."""
    app = FastAPI()
    app.state.config = _FakeConfig(server=_FakeServerConfig(api_key=api_key))
    app.add_middleware(APIKeyMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/v1/models")
    async def models():
        return {"data": []}

    return app


class TestNoApiKeyConfigured:
    """When api_key is empty, all requests pass through."""

    def test_health_allowed(self):
        client = TestClient(_make_app(""))
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_models_allowed_without_header(self):
        client = TestClient(_make_app(""))
        resp = client.get("/v1/models")
        assert resp.status_code == 200


class TestApiKeyConfigured:
    """When api_key is set, protected endpoints require Authorization."""

    def test_health_always_public(self):
        client = TestClient(_make_app("secret-key"))
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_missing_key_rejected(self):
        client = TestClient(_make_app("secret-key"))
        resp = client.get("/v1/models")
        assert resp.status_code == 401
        assert "invalid_api_key" in resp.json()["error"]["code"]

    def test_wrong_key_rejected(self):
        client = TestClient(_make_app("secret-key"))
        resp = client.get("/v1/models", headers={"Authorization": "Bearer wrong-key"})
        assert resp.status_code == 401

    def test_correct_key_accepted(self):
        client = TestClient(_make_app("secret-key"))
        resp = client.get("/v1/models", headers={"Authorization": "Bearer secret-key"})
        assert resp.status_code == 200

    def test_bearer_prefix_optional(self):
        client = TestClient(_make_app("secret-key"))
        resp = client.get("/v1/models", headers={"Authorization": "secret-key"})
        assert resp.status_code == 200
