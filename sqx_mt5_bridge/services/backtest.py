"""MT5 Backtest Runner: executes headless backtests using terminal64.exe.

Generates .ini configuration files, launches terminal64.exe in headless mode,
waits for completion with timeout handling, resolves HTML report paths, and
archives reports.
"""

import logging
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Symbol Resolution ─────────────────────────────────────────────

_DEFAULT_SUFFIXES = (".cash", "USD", "")


def resolve_symbol(
    sqx_symbol: str,
    mapping: dict[str, str] | None = None,
) -> str:
    """Resolve a StrategyQuant symbol name to the matching MT5 symbol.

    Resolution order:
      1. Exact case-insensitive match in mapping.
      2. Base-name match against mapping (strip SQX suffix after '_').
      3. Return base name directly for SQX-style names without mapping
         (e.g. XAUUSD_TickData_FTMO → XAUUSD).
      4. Try appending fallback suffixes (.cash, USD, "").
      5. Return unchanged.
    """
    if mapping is None:
        from config import settings

        mapping = settings.symbol_mapping_dict

    # 1. Exact lookup
    if sqx_symbol in mapping:
        return mapping[sqx_symbol]

    # 2. Case-insensitive lookup
    sqx_upper = sqx_symbol.upper()
    for sqx_key, mt5_val in mapping.items():
        if sqx_key.upper() == sqx_upper:
            return mt5_val

    # 3. Base-name match against mapping (strip SQX suffix after '_')
    base = sqx_symbol.split("_")[0]
    for sqx_key, mt5_val in mapping.items():
        if sqx_key.upper() == base.upper():
            return mt5_val

    # 4. Try raw base name before adding fallback suffixes.
    # Handles names like XAUUSD_TickData_FTMO → XAUUSD so MT5
    # can resolve it directly.
    if base and base != sqx_symbol:
        return base

    # 5. Fallback: try appending common suffixes
    for suffix in _DEFAULT_SUFFIXES:
        return f"{sqx_symbol}{suffix}"

    return sqx_symbol  # unchanged


# ── Timeframe Mapping ─────────────────────────────────────────────

_TIMEFRAME_MAP: dict[str, int] = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
    "W1": 10080,
    "MN1": 43200,
}

_VALID_TIMEFRAMES: frozenset[str] = frozenset(_TIMEFRAME_MAP.keys())


def resolve_timeframe(sqx_timeframe: str, default: str = "M30") -> str:
    """Validate and normalize a timeframe string from SQX settings."""
    if not sqx_timeframe:
        return default

    upper = sqx_timeframe.strip().upper()
    if upper in _VALID_TIMEFRAMES:
        return upper

    print(
        f"[backtest] Unknown timeframe '{sqx_timeframe}' "
        f"-- defaulting to {default}"
    )
    return default


# ── Report helpers ─────────────────────────────────────────────────

_REPORT_PATTERN = re.compile(
    r"^[^/\\]+_(?:\d{13}(-[A-Za-z0-9]+)?)?\.?"
    r"(htm|html|png|ini)$",
    re.IGNORECASE,
)


def find_report(
    base_path: Path,
    ea_name: str,
    since_ms: int | None = None,
) -> str | None:
    """Locate the HTML report written by MT5."""
    candidates: list[Path] = [
        base_path / f"{ea_name}_report.htm",
        base_path / f"{ea_name}_report.html",
    ]
    for f in base_path.iterdir():
        if f.is_file() and f.name.startswith(f"{ea_name}_report_"):
            candidates.append(f)

    for path in candidates:
        if path.exists() and (
            since_ms is None
            or path.stat().st_mtime * 1000 >= since_ms
        ):
            return str(path)

    # Fallback: tester/ subdirectory
    tester_dir = base_path / "tester"
    for ext in ("htm", "html"):
        candidate = tester_dir / f"{ea_name}_report.{ext}"
        if candidate.exists():
            return str(candidate)

    return None


def archive_reports(
    base_path: Path,
    cutoff_seconds: int = 60,
) -> dict[str, list[str]]:
    """Move report artifacts into reports/<YYYY-MM-DD>/ subfolders.

    Only archives files older than *cutoff_seconds* to avoid moving
    a report that is still being written by a concurrent backtest.
    """
    if not base_path.exists():
        return {}

    cutoff_ms = int(time.time() * 1000) - cutoff_seconds * 1000
    moved: dict[str, list[str]] = {}

    try:
        for entry in base_path.iterdir():
            if not entry.is_file():
                continue
            if not _REPORT_PATTERN.match(entry.name):
                continue

            try:
                mtime_ms = int(entry.stat().st_mtime * 1000)
                if mtime_ms >= cutoff_ms:
                    continue

                day = datetime.fromtimestamp(
                    entry.stat().st_mtime,
                ).strftime("%Y-%m-%d")
                dest_dir = base_path / "reports" / day
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / entry.name
                entry.rename(dest)
                moved.setdefault(day, []).append(str(dest))
            except OSError:
                pass
    except OSError:
        pass

    return moved
