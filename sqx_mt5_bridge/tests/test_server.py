"""Tests for server.py - health endpoint, startup, and symbol resolution."""

import sys
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure sqx_mt5_bridge is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqx_mt5_bridge.server import app, _resolve_mt5_symbol
from sqx_mt5_bridge.config import settings


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
        assert settings.port == 8090

    def test_default_host(self):
        assert settings.host == "0.0.0.0"

    def test_app_name(self):
        assert settings.app_name == "SQX-MT5 Bridge"


class TestResolveMt5Symbol:
    """Tests for _resolve_mt5_symbol: SQX symbol → MT5 symbol mapping."""

    def test_exact_mapping_returns_mapped_value(self):
        assert _resolve_mt5_symbol("NAS100") == "US100.cash"

    def test_case_insensitive_mapping(self):
        assert _resolve_mt5_symbol("nas100") == "US100.cash"

    def test_empty_string_returns_empty(self):
        assert _resolve_mt5_symbol("") == ""

    def test_unmapped_with_suffix_returns_base(self):
        """XAUUSD_TickData_FTMO → XAUUSD (raw base, no mapping needed)."""
        result = _resolve_mt5_symbol("XAUUSD_TickData_FTMO")
        assert result == "XAUUSD"

    def test_stp_suffix_with_mapping_returns_mapped_value(self):
        """NAS100_STP → US100.cash (base 'NAS100' is in mapping)."""
        result = _resolve_mt5_symbol("NAS100_STP")
        assert result == "US100.cash"

    def test_multiple_underscores_returns_first_part(self):
        """AAPL_H1_DailyTick → AAPL."""
        result = _resolve_mt5_symbol("AAPL_H1_DailyTick")
        assert result == "AAPL"

    def test_unmapped_plain_symbol_unchanged(self):
        """Symbols without '_' and no mapping return unchanged."""
        result = _resolve_mt5_symbol("EURUSD")
        assert result == "EURUSD"
