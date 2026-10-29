"""Live MT5 symbol query — wraps MetaTrader5.py to read broker symbols.

Persistent connection pattern:
    1. Connect once on server startup (background thread)
    2. Reuse the connection for all subsequent queries
    3. Only shut down when the server process stops

This avoids the visible MT5 launch/close flash on every plugin tab load.
"""

import threading
import time
from pathlib import Path
from typing import Optional

# ── Config defaults (override via bridge_service/.env BRIDGE_TERMINAL_PATH) ──
_DEFAULT_TERMINAL = r"C:\Terminal\WORKBENCH-01\terminal64.exe"
_CONNECT_WAIT_S = 25           # max seconds to wait for account login
_INITIALIZE_TIMEOUT_MS = 60000  # mt5.initialize() timeout

# ── Persistent connection state ──
_mt5_instance = None   # MetaTrader5 module reference
_mt5_portable = None   # bool: how we connected
_mt5_terminal_name: str = ""
_mt5_server: str = ""
_mt5_ready = False     # connection established successfully
_mt5_lock = threading.Lock()
_mt5_terminal_path: str = _DEFAULT_TERMINAL


def _init_persistent(terminal_path: str):
    """Background thread: connect to MT5 once on startup."""
    global _mt5_instance, _mt5_portable, _mt5_ready, _mt5_terminal_name, _mt5_server, _mt5_terminal_path
    _mt5_terminal_path = terminal_path
    if not Path(terminal_path).exists():
        print(f"[MT5] Terminal not found: {terminal_path}")
        return

    import MetaTrader5 as mt5  # noqa: PLC0415

    ok_portable = mt5.initialize(
        path=terminal_path, portable=True, timeout=_INITIALIZE_TIMEOUT_MS
    )
    if ok_portable:
        _mt5_instance = mt5
        _mt5_portable = True
    else:
        portable_err = list(mt5.last_error())
        ok_normal = mt5.initialize(
            path=terminal_path, timeout=_INITIALIZE_TIMEOUT_MS
        )
        if ok_normal:
            _mt5_instance = mt5
            _mt5_portable = False
        else:
            last_err = list(mt5.last_error())
            print(f"[MT5] Could not connect: {portable_err if portable_err[0] != 0 else last_err}")
            return

    # Wait for account login
    deadline = time.time() + _CONNECT_WAIT_S
    while time.time() < deadline and _mt5_instance.account_info() is None:
        time.sleep(1)

    account = _mt5_instance.account_info()
    _mt5_server = account.server if account else None
    if not _mt5_server:
        terminal = _mt5_instance.terminal_info()
        _mt5_server = terminal.name if terminal else "MT5"

    _mt5_terminal_name = (_mt5_instance.terminal_info().name
                          if _mt5_instance.terminal_info() else "")
    _mt5_ready = True
    print(f"[MT5] Connected ({'portable' if _mt5_portable else 'normal'}), server={_mt5_server}")


def _ensure_connected():
    """Acquire the connection lock. Returns True if ready."""
    if not _mt5_ready:
        return False
    _mt5_lock.acquire()
    return True


def _release_connection():
    """Release the connection lock."""
    _mt5_lock.release()


def shutdown_persistent():
    """Shut down the persistent MT5 connection (call on server stop)."""
    global _mt5_instance
    with _mt5_lock:
        if _mt5_instance:
            _mt5_instance.shutdown()
            _mt5_instance = None
            _mt5_ready = False
            print("[MT5] Shutdown")


def query_live_symbols(terminal_path: Optional[str] = None) -> dict:
    """Read symbols from the persistent MT5 connection.

    Returns:
        {
            "ok": True/False,
            "count": N,
            "symbols": [{"symbol": "...", "servers": ["..."]}],
            "server": "FTMO-Demo",
            "terminal": "BlackBull Markets MT5",
            "portable": True/False,
        }
        on error: {"ok": False, "error": "...", "lastError": [...]}
    """
    global _mt5_ready, _mt5_instance
    if terminal_path and terminal_path != _mt5_terminal_path:
        # Terminal changed — fall back to connect-on-demand
        return _query_fallback(terminal_path)

    if not _ensure_connected():
        if _mt5_ready is False and Path(_mt5_terminal_path).exists():
            # Connection thread hasn't started or is still initializing.
            # Return cached env mapping so the UI stays responsive.
            return _cached_fallback()
        return _cached_fallback()

    try:
        symbols = _mt5_instance.symbols_get()
        if symbols is None:
            code, message = list(_mt5_instance.last_error())
            # Connection lost — reset for reconnect on next request
            _mt5_ready = False
            with _mt5_lock:
                if _mt5_instance:
                    _mt5_instance.shutdown()
                    _mt5_instance = None
            return _query_fallback(_mt5_terminal_path)

        entries = sorted(symbols, key=lambda s: s.name)
        entries = [{"symbol": s.name, "servers": [_mt5_server]} for s in entries]

        return {
            "ok": True,
            "server": _mt5_server,
            "terminal": _mt5_terminal_name,
            "portable": _mt5_portable,
            "count": len(entries),
            "symbols": entries,
        }
    finally:
        _release_connection()


def _query_fallback(terminal_path: str) -> dict:
    """Fallback: connect on-demand (old launch-on-demand pattern)."""
    import MetaTrader5 as mt5  # noqa: PLC0415

    ok_portable = mt5.initialize(
        path=terminal_path, portable=True, timeout=_INITIALIZE_TIMEOUT_MS
    )
    if ok_portable:
        mt5_instance, portable = mt5, True
    else:
        portable_err = list(mt5.last_error())
        ok_normal = mt5.initialize(
            path=terminal_path, timeout=_INITIALIZE_TIMEOUT_MS
        )
        if ok_normal:
            mt5_instance, portable = mt5, False
        else:
            last_err = list(mt5.last_error())
            detail = portable_err if portable_err[0] != 0 else last_err
            return {"ok": False, "error": f"Could not connect to MT5: {detail}", "lastError": detail}

    try:
        deadline = time.time() + _CONNECT_WAIT_S
        while time.time() < deadline and mt5_instance.account_info() is None:
            time.sleep(1)

        symbols = mt5_instance.symbols_get()
        if symbols is None:
            code, message = list(mt5_instance.last_error())
            return {"ok": False, "error": f"Could not read symbols: {message}", "lastError": [code, message]}

        account = mt5_instance.account_info()
        server = account.server if account else None
        if not server:
            terminal = mt5_instance.terminal_info()
            server = terminal.name if terminal else "MT5"

        terminal_info = mt5_instance.terminal_info()
        terminal_name = terminal_info.name if terminal_info else ""

        entries = sorted(symbols, key=lambda s: s.name)
        entries = [{"symbol": s.name, "servers": [server]} for s in entries]

        return {
            "ok": True,
            "server": server,
            "terminal": terminal_name,
            "portable": portable,
            "count": len(entries),
            "symbols": entries,
        }
    finally:
        mt5_instance.shutdown()


def _cached_fallback() -> dict:
    """Fallback when MT5 is unavailable — return env mapping symbols."""
    from sqx_mt5_bridge.config import settings  # noqa: PLC0415
    mapping = settings.symbol_mapping_dict
    symbols = list(mapping.keys())
    for mt5_name in mapping.values():
        if mt5_name not in symbols:
            symbols.append(mt5_name)
    return {
        "ok": False, "error": "MT5 initializing…",
        "symbols": symbols, "count": len(symbols), "fallback": True,
    }
