"""StrategyQuant X REST API client for strategy settings extraction.

Uses standard library (urllib) for maximum stability on Windows.
Auto-detects SQX REST API port (8080-8099) with per-request retry.
"""

import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

# ── SQX Port Auto-Detection ────────────────────────────────────────
# SQX instances can run on any port (8080, 8081, etc.).
# We scan a range once, cache the result, and retry on failure.

_sqx_port_cache: int | None = None
_sqx_port_fail_count: int = 0
_SQX_PORT_RANGE = range(8080, 8100)  # scan 8080–8099


def _find_sqx_port(host: str = "localhost", timeout: float = 0.3) -> Optional[int]:
    """Scan common SQX ports to find the REST API.

    Uses a quick TCP probe — faster than HTTP and works even if
    SQX's API is temporarily unresponsive.
    """
    for port in _SQX_PORT_RANGE:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                return port
        except OSError:
            pass
    return None


def get_strategy_settings(
    project: str,
    databank: str,
    strategy_name: str,
    sqx_host: str = "localhost",
    sqx_port: int | None = None,
) -> Optional[str]:
    """Call SQX's `resultsPlugins/settings` endpoint and return raw XML.

    If *sqx_port* is None, auto-detects the SQX REST API port
    by scanning 8080–8099. Cache is invalidated on first failure
    and re-scanned on the next request.
    """
    global _sqx_port_cache, _sqx_port_fail_count

    # Resolve port: explicit > cached > auto-detect > default
    port = sqx_port
    if port is None:
        if _sqx_port_cache is not None and _sqx_port_fail_count == 0:
            port = _sqx_port_cache
        else:
            port = _find_sqx_port(sqx_host)
            if port is not None:
                _sqx_port_cache = port
                _sqx_port_fail_count = 0

    if port is None:
        port = 8080  # final fallback

    params = urllib.parse.urlencode({
        "projectName": project,
        "databankName": databank,
        "strategyName": strategy_name,
    })
    url = f"http://{sqx_host}:{port}/resultsPlugins/settings"

    try:
        req = urllib.request.Request(
            url,
            data=params.encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                body = resp.read().decode("utf-8", errors="replace")
                print(
                    f"[SQX] settings request failed: HTTP {resp.status}: "
                    f"{body[:300]}"
                )
                return None

            result = json.loads(resp.read().decode("utf-8"))
            if not result.get("success") == "ok":
                print(f"[SQX] settings returned non-ok: {result.get('error', 'unknown')}")
                return None

            return result.get("lastSettingsXml")

    except urllib.error.URLError as e:
        print(f"[SQX] Cannot connect to SQX at {sqx_host}:{port}: {e.reason}")
        _sqx_port_fail_count += 1
        _sqx_port_cache = None  # invalidate cache so we re-scan next time
        return None
    except Exception as exc:
        print(f"[SQX] settings request error: {exc}")
        _sqx_port_fail_count += 1
        _sqx_port_cache = None
        return None


def get_source_code(
    project: str,
    databank: str,
    strategy_name: str,
    sqx_host: str = "localhost",
    sqx_port: int | None = None,
) -> Optional[str]:
    """Call SQX's `sourcecode/print` endpoint and return MQ5 source code.

    This retrieves the actual compiled MQ5 source code from SQX's internal
    strategy engine — the same mechanism BotPulse uses. SQX must be running.

    Args:
        project: SQX project name.
        databank: SQX databank name.
        strategy_name: Strategy name within the databank.
        sqx_host: SQX host (default: localhost).
        sqx_port: SQX REST API port (auto-detected if None).

    Returns:
        MQ5 source code string, or None on failure.
    """
    global _sqx_port_cache, _sqx_port_fail_count

    port = sqx_port
    if port is None:
        if _sqx_port_cache is not None and _sqx_port_fail_count == 0:
            port = _sqx_port_cache
        else:
            port = _find_sqx_port(sqx_host)
            if port is not None:
                _sqx_port_cache = port
                _sqx_port_fail_count = 0

    if port is None:
        port = 8080  # final fallback

    # Determine money management type from SQX initialization data
    mm_type = _get_default_mm_type(sqx_host, port)

    params = urllib.parse.urlencode({
        "project": project,
        "databank": databank,
        "strategy": strategy_name,
        "fileName": re.sub(r"[^a-zA-Z0-9_]", "_", strategy_name),
        "type": "Expert Advisor for MetaTrader5 (*.MQ5)",
        "useVariables": "false",
        "periodParams": "true",
        "constantsParams": "false",
        "shiftParams": "false",
        "otherParams": "false",
        "entryParams": "false",
        "entryLogic": "false",
        "exitParamsUsed": "true",
        "exitParamsUnused": "false",
        "booleanParams": "false",
        "symmetricVariables": "true",
        "recommendedParams": "true",
        "mmType": mm_type,
    })
    url = f"http://{sqx_host}:{port}/sourcecode/print"

    try:
        req = urllib.request.Request(
            url,
            data=params.encode("utf-8"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                body = resp.read().decode("utf-8", errors="replace")
                print(
                    f"[SQX] sourcecode/print failed: HTTP {resp.status}: "
                    f"{body[:300]}"
                )
                return None

            result = json.loads(resp.read().decode("utf-8"))
            if not result.get("success") == "ok" or not result.get("code"):
                print(
                    f"[SQX] sourcecode/print non-ok or no code: "
                    f"{result.get('error', result.get('code', 'unknown'))}"
                )
                return None

            code = result["code"]
            if not code.strip().startswith("//"):
                print(
                    f"[SQX] sourcecode/print did not return valid MQL5 code: "
                    f"{code[:200]}"
                )
                return None

            return code

    except urllib.error.URLError as e:
        print(
            f"[SQX] Cannot connect to SQX at {sqx_host}:{port}: "
            f"{e.reason}"
        )
        _sqx_port_fail_count += 1
        _sqx_port_cache = None
        return None
    except Exception as exc:
        print(f"[SQX] sourcecode/print error: {exc}")
        _sqx_port_fail_count += 1
        _sqx_port_cache = None
        return None


def _get_default_mm_type(
    sqx_host: str, sqx_port: int,
) -> str:
    """Get the default money management type from SQX initialization data.

    Returns the first available mm type value, or "fromStrategy" as fallback.
    """
    try:
        params = urllib.parse.urlencode({})
        url = f"http://{sqx_host}:{sqx_port}/main/loadInitializationData"
        req = urllib.request.Request(
            url,
            data=params.encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                result = json.loads(resp.read().decode("utf-8"))
                mm_types = (
                    result.get("results", {})
                    .get("sourceCode", {})
                    .get("mmTypes", [])
                )
                if mm_types:
                    return mm_types[0].get("value", "fromStrategy")
    except Exception:
        pass
    return "fromStrategy"


def parse_backtest_settings(
    xml: str,
) -> "StrategyBacktestSettings":
    """Parse the lastSettings XML into a structured dataclass."""
    setup_match = re.search(
        r'<Setup\s+dateFrom="([\d.]+)"\s+dateTo="([\d.]*)"',
        xml,
    )

    chart_match = re.search(
        r'<Chart\b[^>]*symbol="([^"]*)"[^>]*timeframe="([^"]*)"',
        xml,
    )
    if chart_match:
        symbol_raw = chart_match.group(1)
        timeframe_str = chart_match.group(2)
    else:
        chart_match2 = re.search(
            r'<Chart\b[^>]*timeframe="([^"]*)"[^>]*symbol="([^"]*)"',
            xml,
        )
        if chart_match2:
            symbol_raw = chart_match2.group(2)
            timeframe_str = chart_match2.group(1)
        else:
            symbol_raw = None
            timeframe_str = None

    capital_match = re.search(
        r'<InitialCapital>([\d.]+)</InitialCapital>',
        xml,
    )

    return StrategyBacktestSettings(
        project="",
        databank="",
        strategy_name="",
        from_date=setup_match.group(1) if setup_match else None,
        to_date=setup_match.group(2) if setup_match else None,
        symbol=symbol_raw,
        timeframe=timeframe_str,
        initial_capital=float(capital_match.group(1)) if capital_match else None,
    )


# ── Data Models ───────────────────────────────────────────────────

from dataclasses import dataclass
from typing import Optional


@dataclass
class StrategyBacktestSettings:
    """Parsed backtest settings from an SQX strategy's lastSettings XML."""

    project: str
    databank: str
    strategy_name: str
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    initial_capital: Optional[float] = None
