"""Tests for Symbol Resolution: SQX -> MT5 symbol mapping.

Tests resolve_symbol() with explicit mappings, fallback suffixes, and
case-insensitive lookups.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.backtest import resolve_symbol


# ── Explicit Mapping Tests ──────────────────────────────────────────


class TestExplicitMapping:
    """Tests for explicit symbol mapping lookups."""

    def test_exact_match_returns_mapped_value(self):
        mapping = {"NAS100": "NAS100.cash", "US500": "US500.cash"}
        result = resolve_symbol("NAS100", mapping=mapping)
        assert result == "NAS100.cash"

    def test_exact_match_case_insensitive(self):
        mapping = {"NAS100": "NAS100.cash"}
        # lowercase SHOULD match via case-insensitive lookup
        result = resolve_symbol("nas100", mapping=mapping)
        assert result == "NAS100.cash"

    def test_unmapped_symbol_falls_back(self):
        mapping = {"NAS100": "NAS100.cash"}
        result = resolve_symbol("UNKNOWN", mapping=mapping)
        # Should fall back to appending ".cash"
        assert result == "UNKNOWN.cash"

    def test_empty_mapping_falls_back(self):
        result = resolve_symbol("EURUSD", mapping={})
        assert result == "EURUSD.cash"

    def test_null_mapping_uses_defaults(self):
        """When mapping=None, resolve_symbol falls back to default suffixes."""
        result = resolve_symbol("TEST", mapping=None)
        # Uses default fallbacks from _FALLBACK_SUFFIXES
        assert result.endswith(".cash") or result.endswith("USD") or result == "TEST"


# ── Case-Insensitive Mapping Tests ──────────────────────────────────


class TestCaseInsensitiveMapping:
    """Tests for case-insensitive symbol mapping lookups."""

    def test_case_insensitive_lookup(self):
        mapping = {"NAS100": "NAS100.cash"}
        result = resolve_symbol("nas100", mapping=mapping)
        assert result == "NAS100.cash"

    def test_case_insensitive_lookup_mixed_case(self):
        mapping = {"EURUSD": "EURUSD"}
        result = resolve_symbol("EurUsd", mapping=mapping)
        assert result == "EURUSD"

    def test_case_insensitive_lookup_uppercase(self):
        mapping = {"btcusd": "BTCUSD"}
        result = resolve_symbol("BTCUSD", mapping=mapping)
        assert result == "BTCUSD"


# ── Fallback Suffix Tests ───────────────────────────────────────────


class TestFallbackSuffixes:
    """Tests for fallback suffix application."""

    def test_first_fallback_suffix_is_cash(self):
        """The first fallback suffix should be '.cash'."""
        mapping = {}
        result = resolve_symbol("NAS100", mapping=mapping)
        assert result == "NAS100.cash"

    def test_fallback_applied_when_no_match(self):
        """Fallback should be applied when symbol is not in mapping."""
        mapping = {"KNOWN": "KNOWN.cash"}
        result = resolve_symbol("UNKNOWN", mapping=mapping)
        assert result == "UNKNOWN.cash"

    def test_empty_string_suffix_not_used_first(self):
        """Empty suffix should not be the first fallback."""
        mapping = {}
        result = resolve_symbol("TEST", mapping=mapping)
        # Should get ".cash", not empty string appended
        assert result == "TEST.cash"


# ── SQX Internal Symbol Name Tests ──────────────────────────────────


class TestSqxInternalSymbolNames:
    """Tests for SQX internal symbol names with data-source suffixes.

    SQX strategies often use symbols like 'XAUUSD_TickData_FTMO' where
    the part before '_' is the actual MT5 symbol. The resolver should
    strip the suffix and return the base name directly.
    """

    def test_tickdata_suffix_strips_to_base(self):
        """XAUUSD_TickData_FTMO → XAUUSD (no mapping needed)."""
        result = resolve_symbol("XAUUSD_TickData_FTMO", mapping={})
        assert result == "XAUUSD"

    def test_stp_suffix_strips_to_base(self):
        """NAS100_STP → NAS100 (no mapping needed)."""
        result = resolve_symbol("NAS100_STP", mapping={})
        assert result == "NAS100"

    def test_multiple_underscores_strips_first_part(self):
        """AAPL_H1_DailyTick → AAPL (takes part before first '_')."""
        result = resolve_symbol("AAPL_H1_DailyTick", mapping={})
        assert result == "AAPL"

    def test_base_in_mapping_still_uses_mapping(self):
        """XAUUSD in mapping → use mapped value, not raw base."""
        mapping = {"XAUUSD": "XAUUSD"}
        result = resolve_symbol("XAUUSD_TickData_FTMO", mapping=mapping)
        assert result == "XAUUSD"

    def test_base_in_mapping_with_different_value(self):
        """NAS100_STP → NAS100.cash (base 'NAS100' IS in mapping, uses it)."""
        mapping = {"NAS100": "NAS100.cash"}
        result = resolve_symbol("NAS100_STP", mapping=mapping)
        assert result == "NAS100.cash"

    def test_plain_symbol_without_suffix_unchanged(self):
        """Symbols without '_' go to suffix fallback as before."""
        result = resolve_symbol("EURUSD", mapping={})
        assert result == "EURUSD.cash"


# ── Integration with Config ─────────────────────────────────────────


class TestConfigIntegration:
    """Tests for config.py symbol_mapping parsing."""

    def test_json_format_parsed(self):
        from config import Settings
        original = Settings.model_fields["symbol_mapping"].default
        assert "NAS100" in original
        assert "NAS100.cash" in original

    def test_symbol_mapping_dict_returns_dict(self):
        from config import settings
        result = settings.symbol_mapping_dict
        assert isinstance(result, dict)
        assert "NAS100" in result
        # NAS100 (SQX) → US100.cash (MT5/FTMO)
        assert result["NAS100"] == "US100.cash"

    def test_pipe_format_parsed(self):
        """Pipe-separated format should be parsed correctly."""
        from config import Settings
        # Create a settings instance with pipe format
        settings = Settings(symbol_mapping="NAS100=NAS100.cash|US500=US500.cash")
        result = settings.symbol_mapping_dict
        assert result == {"NAS100": "NAS100.cash", "US500": "US500.cash"}

    def test_empty_string_returns_empty_dict(self):
        from config import Settings
        settings = Settings(symbol_mapping="")
        result = settings.symbol_mapping_dict
        assert result == {}

    def test_invalid_json_falls_back_to_pipe(self):
        from config import Settings
        settings = Settings(symbol_mapping="not valid json")
        result = settings.symbol_mapping_dict
        # Should be empty since it's neither valid JSON nor key=value
        assert result == {}


# ── Timeframe Resolution Tests ──────────────────────────────────────


class TestTimeframeResolution:
    """Tests for resolve_timeframe: validate/sanitize SQX timeframe."""

    def test_known_timeframes_return_as_is(self):
        from services.backtest import resolve_timeframe
        for tf in ("M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"):
            assert resolve_timeframe(tf) == tf

    def test_lowercase_timeframe_normalized(self):
        from services.backtest import resolve_timeframe
        assert resolve_timeframe("m30") == "M30"
        assert resolve_timeframe("h1") == "H1"
        assert resolve_timeframe("d1") == "D1"

    def test_empty_timeframe_returns_default(self):
        from services.backtest import resolve_timeframe
        assert resolve_timeframe("") == "M30"
        assert resolve_timeframe(None) == "M30"

    def test_custom_default(self):
        from services.backtest import resolve_timeframe
        assert resolve_timeframe("", default="H4") == "H4"

    def test_unknown_timeframe_returns_default(self):
        from services.backtest import resolve_timeframe
        import io
        import sys

        # Capture the warning printed to stdout
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            result = resolve_timeframe("H2")
            assert result == "M30"  # default
        finally:
            sys.stdout = old_stdout

    def test_whitespace_stripped(self):
        from services.backtest import resolve_timeframe
        assert resolve_timeframe("  H4  ") == "H4"
