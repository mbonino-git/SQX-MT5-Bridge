"""Live MT5 symbol query — wraps MetaTrader5.py to read broker symbols.

On-demand pattern (no background connection):
    1. Snapshot running terminal PIDs, then connect when a symbol list is requested
    2. Read the broker symbol list
    3. Always disconnect (mt5.shutdown) and close any terminal this query launched

Why the explicit PID cleanup: MetaTrader5 5.0.6231's shutdown() only
disconnects — it does NOT close a terminal that initialize() launched.
So we record which terminal64.exe processes existed before the query and
force-close the ones that appeared during it. Terminals already running
(user-opened, or a test in progress) are never touched, and the server
additionally skips the query while a backtest job is active so a running
Strategy Tester is never interrupted.
"""

import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

# ── Config defaults (override via bridge_service/.env BRIDGE_TERMINAL_PATH) ──
_DEFAULT_TERMINAL = r"C:\Terminal\WORKBENCH-01\terminal64.exe"
_CONNECT_WAIT_S = 10            # max seconds to wait for account login
_INITIALIZE_TIMEOUT_MS = 10000  # mt5.initialize() timeout
_CLOSE_GRACE_S = 5              # seconds to wait for a graceful close before force-killing

# Serializes connect/query/shutdown so concurrent requests never overlap
_mt5_lock = threading.Lock()


def _running_terminal_pids(terminal_path: str) -> set[int]:
    """PIDs of running terminal64.exe processes whose executable path matches
    the configured terminal. Empty set if detection fails (nothing is killed
    in that case — fail-safe against closing a terminal we don't own)."""
    try:
        cmd = (
            '@(Get-Process terminal64 -ErrorAction SilentlyContinue | '
            'ForEach-Object { "$($_.Id)|$($_.Path)" }) -join "`n"'
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=15,
        ).stdout
    except Exception:
        return set()

    want = Path(terminal_path).resolve()
    pids: set[int] = set()
    for line in out.splitlines():
        if "|" not in line:
            continue
        pid_s, _, exe = line.partition("|")
        if not pid_s.isdigit() or not exe.strip():
            continue
        try:
            if Path(exe).resolve() == want:
                pids.add(int(pid_s))
        except Exception:
            continue
    return pids


def _close_launched_terminals(before: set[int], terminal_path: str) -> list[int]:
    """Close terminals this query launched (PIDs not present before it).

    Waits briefly for a graceful exit first, then force-kills what is left.
    Returns the PIDs that had to be force-closed."""
    try:
        now = _running_terminal_pids(terminal_path)
    except Exception:
        return []
    launched = now - before
    if not launched:
        return []

    deadline = time.time() + _CLOSE_GRACE_S
    while time.time() < deadline and launched:
        time.sleep(1)
        # keep only pids that are still running; empty once all are gone
        launched &= _running_terminal_pids(terminal_path)

    killed = []
    for pid in sorted(launched):
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True, timeout=10,
            )
            killed.append(pid)
        except Exception as exc:
            print(f"[MT5] Could not close terminal pid {pid}: {exc}")
    if killed:
        print(f"[MT5] Closed terminal(s) launched by symbol query: {killed}")
    return killed


def _connect(terminal_path: str):
    """Initialize MT5 (portable mode first, then normal).

    Returns (mt5_module, portable) on success, None on failure.
    """
    if not Path(terminal_path).exists():
        print(f"[MT5] Terminal not found: {terminal_path}")
        return None

    import MetaTrader5 as mt5  # noqa: PLC0415

    ok = mt5.initialize(
        path=terminal_path, portable=True, timeout=_INITIALIZE_TIMEOUT_MS
    )
    portable = True
    if not ok:
        portable_err = list(mt5.last_error())
        ok = mt5.initialize(path=terminal_path, timeout=_INITIALIZE_TIMEOUT_MS)
        portable = False
        if not ok:
            last_err = list(mt5.last_error())
            print(f"[MT5] Could not connect: {portable_err if portable_err[0] != 0 else last_err}")
            return None

    # Wait (bounded) for account login so symbols_get() sees the broker list
    deadline = time.time() + _CONNECT_WAIT_S
    while time.time() < deadline and mt5.account_info() is None:
        time.sleep(1)

    return mt5, portable


def query_live_symbols(terminal_path: Optional[str] = None) -> dict:
    """Connect to MT5, read the broker symbol list, then close MT5 again.

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
    path = terminal_path or _DEFAULT_TERMINAL

    with _mt5_lock:
        before = _running_terminal_pids(path)
        connected = _connect(path)
        if not connected:
            # initialize() may have launched a terminal without logging in
            _close_launched_terminals(before, path)
            return _cached_fallback()
        mt5, portable = connected
        try:
            symbols = mt5.symbols_get()
            if symbols is None:
                code, message = list(mt5.last_error())
                return {"ok": False, "error": f"Could not read symbols: {message}",
                        "lastError": [code, message]}

            account = mt5.account_info()
            server = account.server if account else None
            if not server:
                terminal = mt5.terminal_info()
                server = terminal.name if terminal else "MT5"
            terminal_info = mt5.terminal_info()
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
            # 1) disconnect from MT5 (closes it only on builds where that works)
            try:
                mt5.shutdown()
            except Exception as exc:
                print(f"[MT5] shutdown() failed: {exc}")
            # 2) make sure no terminal launched by this query is left running
            _close_launched_terminals(before, path)


def shutdown_persistent() -> None:
    """Kept for API compatibility — there is no persistent connection anymore."""
    pass


def _cached_fallback() -> dict:
    """Fallback when MT5 is unavailable — return env mapping symbols."""
    from sqx_mt5_bridge.config import settings  # noqa: PLC0415
    mapping = settings.symbol_mapping_dict
    symbol_names = list(mapping.keys())
    for mt5_name in mapping.values():
        if mt5_name not in symbol_names:
            symbol_names.append(mt5_name)
    return {
        "ok": False, "error": "MT5 unavailable",
        "symbols": [{"symbol": s, "servers": ["mapped"]} for s in symbol_names],
        "count": len(symbol_names), "fallback": True,
    }
