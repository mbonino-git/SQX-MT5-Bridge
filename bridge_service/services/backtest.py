"""MT5 Backtest Runner: executes headless backtests using terminal64.exe.

Generates .ini configuration files, launches terminal64.exe in headless mode,
waits for completion with timeout handling, and resolves HTML report paths.
"""

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# ── Data Models ───────────────────────────────────────────────────


@dataclass
class BacktestResult:
    """Result of an MT5 backtest execution."""

    success: bool
    report_path: str | None = None
    ini_path: str | None = None
    error: str | None = None
    log: str = ""


# ── Timeframe Mapping ─────────────────────────────────────────────

# MT5 timeframe string -> Period value (minutes)
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


# ── Backtest Runner Class ─────────────────────────────────────────


class BacktestRunner:
    """Executes headless MT5 backtests via terminal64.exe.

    Args:
        terminal_path: Path to the terminal64.exe binary.
            Defaults to the config setting.
        timeout: Maximum seconds to wait for backtest completion.
    """

    def __init__(
        self,
        terminal_path: str = "",
        timeout: int = 300,
    ) -> None:
        if terminal_path:
            self.terminal_path = terminal_path
        else:
            from config import settings
            self.terminal_path = settings.terminal_path
        self.timeout = timeout

    def generate_ini(
        self,
        target: "MT5Target",  # noqa: F821 - forward ref
        ea_name: str,
        symbol: str,
        timeframe: str,
        date_from: datetime,
        date_to: datetime,
        output_path: str,
    ) -> str:
        """Generate an .ini configuration file for headless backtesting.

        Creates an MT5-compatible .ini file with the [Tester] section
        containing EA name, symbol, timeframe, date range, and data path.

        Args:
            target: The MT5 installation target.
            ea_name: Expert Advisor name (without .ex5 extension).
            symbol: Trading symbol (e.g. "EURUSD").
            timeframe: Timeframe string (e.g. "H1", "M30").
            date_from: Start date for the backtest.
            date_to: End date for the backtest.
            output_path: Path where the .ini file should be written.

        Returns:
            The path to the created .ini file.
        """
        # Resolve data folder path
        if target.is_portable:
            data_folder = str(Path(target.install_path) / "MQL5")
        else:
            data_folder = str(Path(target.data_path) / "MQL5")

        # Get period in minutes from timeframe string
        period = _TIMEFRAME_MAP.get(timeframe.upper(), 60)

        # Format dates as MT5 expects (YYYY.MM.DD)
        date_from_str = date_from.strftime("%Y.%m.%d")
        date_to_str = date_to.strftime("%Y.%m.%d")

        # Build INI content
        ini_content = f"""[Tester]
Expert={ea_name}
Symbol={symbol}
Period={period}
Model=0
Optimization=0
FromDate={date_from_str}
ToDate={date_to_str}
Forward=0
Deposit=10000
Currency=USD
Leverage=1:100
ExecutionMode=0
UpdateMode=0
Visual=0
Report={ea_name}_report
ReplaceReport=1
ShutdownTerminal=1
DataFolder={data_folder}
"""

        # Create parent directories and write file
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(ini_content)

        return str(output)

    def run_backtest(
        self,
        target: "MT5Target",  # noqa: F821 - forward ref
        ea_name: str,
        symbol: str,
        timeframe: str,
        date_from: datetime,
        date_to: datetime,
    ) -> BacktestResult:
        """Execute a headless backtest using terminal64.exe.

        Generates an .ini file, launches terminal64.exe with /config: flag,
        waits for completion, and resolves the HTML report path.

        Args:
            target: The MT5 installation target.
            ea_name: Expert Advisor name.
            symbol: Trading symbol.
            timeframe: Timeframe string.
            date_from: Backtest start date.
            date_to: Backtest end date.

        Returns:
            BacktestResult with success status, report path, and log.
        """
        # Determine working directory for .ini and reports
        if target.is_portable:
            base_path = Path(target.install_path)
        else:
            base_path = Path(target.data_path)

        # Generate .ini in a temp-like location under the base path
        tester_dir = base_path / "tester"
        tester_dir.mkdir(parents=True, exist_ok=True)

        ini_path = tester_dir / f"{ea_name}_backtest.ini"
        self.generate_ini(
            target=target,
            ea_name=ea_name,
            symbol=symbol,
            timeframe=timeframe,
            date_from=date_from,
            date_to=date_to,
            output_path=str(ini_path),
        )

        # Resolve expected report path
        report_path = str(tester_dir / f"{ea_name}_report.htm")

        # Build command
        cmd = [self.terminal_path, f"/config:{ini_path}"]

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = process.communicate(timeout=self.timeout)
            full_output = stdout + stderr

            if process.returncode != 0:
                return BacktestResult(
                    success=False,
                    ini_path=str(ini_path),
                    report_path=report_path,
                    error=f"terminal64.exe exited with code {process.returncode}",
                    log=full_output,
                )

            return BacktestResult(
                success=True,
                ini_path=str(ini_path),
                report_path=report_path,
                log=full_output,
            )

        except FileNotFoundError:
            return BacktestResult(
                success=False,
                ini_path=str(ini_path),
                error=f"terminal64.exe not found at: {self.terminal_path}",
            )
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            return BacktestResult(
                success=False,
                ini_path=str(ini_path),
                report_path=report_path,
                error=f"Backtest timed out after {self.timeout} seconds",
            )
