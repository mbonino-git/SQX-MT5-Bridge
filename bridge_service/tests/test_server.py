"""Tests for server.py - health endpoint and startup."""

import sys
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure bridge_service is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import app
from config import settings


client = TestClient(app)


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_returns_200(self):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_ok_status(self):
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "ok"

    def test_health_includes_service_name(self):
        response = client.get("/health")
        data = response.json()
        assert data["service"] == settings.app_name


class TestSettings:
    """Tests for configuration settings."""

    def test_default_port(self):
        assert settings.port == 8080

    def test_default_host(self):
        assert settings.host == "0.0.0.0"

    def test_app_name(self):
        assert settings.app_name == "SQX-MT5 Bridge Service"

    def test_max_compile_retries(self):
        assert settings.max_compile_retries == 3

    def test_max_concurrent_backtests(self):
        assert settings.max_concurrent_backtests == 3
