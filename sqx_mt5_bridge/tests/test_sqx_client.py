"""Tests for SQX client: settings extraction from strategy XML."""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import sqx_client


# ── XML Parsing Tests ──────────────────────────────────────────────


SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Settings>
  <RiskMoneyManagement>
    <MoneyManagement>
      <InitialCapital>10000</InitialCapital>
    </MoneyManagement>
  </RiskMoneyManagement>
  <Data>
    <Setups>
      <Setup dateFrom="2023.01.15" dateTo="2026.10.01" testPrecision="2"
             session="No Session" slippage="0.0" engine="MetaTrader5 (hedged)">
        <Chart symbol="NAS100_TickData_FTMO" timeframe="H1" spread="173" />
        <Commissions>
          <Method type="SizeBased" use="true">
            <Params>
              <Param key="Cost" className="SizeBased">1.0</Param>
            </Params>
        </Commissions>
      </Setup>
    </Setups>
  </Data>
</Settings>
"""


def test_parse_backtest_settings_full():
    """All fields extracted from a typical SQX settings XML."""
    result = sqx_client.parse_backtest_settings(SAMPLE_XML)
    assert result.from_date == "2023.01.15"
    assert result.to_date == "2026.10.01"
    assert result.timeframe == "H1"
    assert result.symbol == "NAS100_TickData_FTMO"
    assert result.initial_capital == 10000.0


def test_parse_backtest_settings_symbol_and_tf_reversed():
    """timeframe attribute appears before symbol in <Chart>."""
    xml = """<Settings>
      <Data><Setups>
      <Setup dateFrom="2022.01.01" dateTo="2024.01.01">
        <Chart timeframe="M30" symbol="BTCUSD" />
      </Setup>
      </Setups></Data></Settings>"""
    result = sqx_client.parse_backtest_settings(xml)
    assert result.from_date == "2022.01.01"
    assert result.to_date == "2024.01.01"
    assert result.symbol == "BTCUSD"
    assert result.timeframe == "M30"


def test_parse_backtest_settings_missing_timeframe():
    """No <Chart> element → timeframe and symbol are None."""
    xml = """<Settings>
      <Data>
        <Setups>
          <Setup dateFrom="2022.01.01" dateTo="2024.01.01" />
        </Setups>
      </Data>
    </Settings>"""
    result = sqx_client.parse_backtest_settings(xml)
    assert result.from_date == "2022.01.01"
    assert result.to_date == "2024.01.01"
    assert result.timeframe is None
    assert result.symbol is None


def test_parse_backtest_settings_missing_capital():
    """No <InitialCapital> element → capital is None."""
    xml = """<Settings>
      <Data>
        <Setups>
          <Setup dateFrom="2023.06.01" dateTo="2025.06.01">
            <Chart symbol="EURUSD" timeframe="M30" />
          </Setup>
        </Setups>
      </Data>
    </Settings>"""
    result = sqx_client.parse_backtest_settings(xml)
    assert result.from_date == "2023.06.01"
    assert result.to_date == "2025.06.01"
    assert result.timeframe == "M30"
    assert result.initial_capital is None


def test_parse_backtest_settings_empty():
    """Empty XML → all fields None."""
    result = sqx_client.parse_backtest_settings("")
    assert result.from_date is None
    assert result.to_date is None
    assert result.timeframe is None
    assert result.initial_capital is None


def test_parse_backtest_settings_date_format_unchanged():
    """SQX returns dates in YYYY.MM.DD — they should not be re-parsed."""
    result = sqx_client.parse_backtest_settings(
        '<Settings><Data><Setups>'
        '<Setup dateFrom="2022.12.31" dateTo="2023.01.01"/>'
        '</Setups></Data></Settings>'
    )
    assert result.from_date == "2022.12.31"
    assert result.to_date == "2023.01.01"


# ── resolve_timeframe Tests (via backtest) ─────────────────────────


def test_resolve_timeframe_valid():
    from services.backtest import resolve_timeframe
    for tf in ("M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"):
        assert resolve_timeframe(tf) == tf


def test_resolve_timeframe_lowercase():
    from services.backtest import resolve_timeframe
    assert resolve_timeframe("m30") == "M30"
    assert resolve_timeframe("h1") == "H1"


def test_resolve_timeframe_default_on_unknown():
    from services.backtest import resolve_timeframe
    assert resolve_timeframe("") == "M30"
    assert resolve_timeframe(None) == "M30"
