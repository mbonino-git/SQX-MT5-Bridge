"""Tests for BacktestRunner: headless MT5 backtest execution.

Tests .ini file generation, backtest execution via subprocess, timeout handling,
and report path resolution.
"""

import os
import subprocess
import sys

import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

# Adjust import path for tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import MT5Target
from services.backtest import BacktestRunner, BacktestResult


# ── Fixtures ──────────────────────────────────────────────────────


def _to_posix(path_str: str) -> str:
    """Normalize a path string to POSIX separators for comparison."""
    return path_str.replace("\\", "/")


@pytest.fixture
def runner():
    """Create a BacktestRunner with a fake terminal path."""
    return BacktestRunner(terminal_path="/fake/terminal64.exe")


@pytest.fixture
def portable_target():
    """MT5Target in portable mode."""
    return MT5Target(
        name="Portable Test",
        install_path="/fake/mt5_portable",
        data_path=None,
        is_portable=True,
    )


@pytest.fixture
def normal_target():
    """MT5Target in normal mode."""
    return MT5Target(
        name="Normal Test",
        install_path="/fake/mt5_normal",
        data_path="/fake/mt5_data",
        is_portable=False,
    )


# ── BacktestResult Model Tests ────────────────────────────────────


class TestBacktestResult:
    """Tests for BacktestResult data model."""

    def test_successful_result(self):
        result = BacktestResult(
            success=True,
            report_path="/reports/backtest.htm",
        )
        assert result.success is True
        assert result.report_path == "/reports/backtest.htm"
        assert result.error is None
        assert result.ini_path is None
        assert result.log == ""

    def test_failed_result_with_error(self):
        result = BacktestResult(
            success=False,
            error="terminal64.exe not found",
        )
        assert result.success is False
        assert result.error == "terminal64.exe not found"
        assert result.report_path is None

    def test_result_with_ini_path(self):
        result = BacktestResult(
            success=True,
            ini_path="/tmp/backtest.ini",
            report_path="/reports/backtest.htm",
        )
        assert result.ini_path == "/tmp/backtest.ini"

    def test_result_with_log(self):
        result = BacktestResult(
            success=True,
            log="Backtest completed in 5.2s",
            report_path="/reports/backtest.htm",
        )
        assert result.log == "Backtest completed in 5.2s"

    def test_result_timeout(self):
        result = BacktestResult(
            success=False,
            error="Backtest timed out after 300 seconds",
        )
        assert result.success is False
        assert "timed out" in result.error


# ── BacktestRunner Initialization Tests ───────────────────────────


class TestBacktestRunnerInit:
    """Tests for BacktestRunner class initialization."""

    def test_create_with_default_terminal_path(self):
        r = BacktestRunner()
        assert r.terminal_path is not None
        assert "terminal64" in r.terminal_path.lower()

    def test_create_with_custom_terminal_path(self):
        r = BacktestRunner(terminal_path="/custom/terminal64.exe")
        assert r.terminal_path == "/custom/terminal64.exe"

    def test_create_with_empty_string_uses_default(self):
        r = BacktestRunner(terminal_path="")
        assert r.terminal_path is not None

    def test_default_timeout(self):
        r = BacktestRunner()
        assert r.timeout == 300

    def test_custom_timeout(self):
        r = BacktestRunner(timeout=600)
        assert r.timeout == 600


# ── .ini File Generation Tests ────────────────────────────────────


class TestGenerateIni:
    """Tests for generate_ini() method."""

    def test_generate_ini_creates_file(self, runner, portable_target, tmp_path):
        """Should create an .ini file at the given path."""
        ini_path = str(tmp_path / "backtest.ini")
        result = runner.generate_ini(
            target=portable_target,
            ea_name="TestEA",
            symbol="EURUSD",
            timeframe="H1",
            date_from=datetime(2024, 1, 1),
            date_to=datetime(2024, 6, 30),
            output_path=ini_path,
        )
        assert os.path.isfile(ini_path)
        assert result == ini_path

    def test_generate_ini_contains_ea_name(self, runner, portable_target, tmp_path):
        """INI file should reference the EA name."""
        ini_path = str(tmp_path / "backtest.ini")
        runner.generate_ini(
            target=portable_target,
            ea_name="MyExpert",
            symbol="EURUSD",
            timeframe="H1",
            date_from=datetime(2024, 1, 1),
            date_to=datetime(2024, 6, 30),
            output_path=ini_path,
        )
        content = Path(ini_path).read_text()
        assert "MyExpert" in content

    def test_generate_ini_contains_symbol(self, runner, portable_target, tmp_path):
        """INI file should reference the trading symbol."""
        ini_path = str(tmp_path / "backtest.ini")
        runner.generate_ini(
            target=portable_target,
            ea_name="TestEA",
            symbol="GBPUSD",
            timeframe="H1",
            date_from=datetime(2024, 1, 1),
            date_to=datetime(2024, 6, 30),
            output_path=ini_path,
        )
        content = Path(ini_path).read_text()
        assert "GBPUSD" in content

    def test_generate_ini_contains_timeframe(self, runner, portable_target, tmp_path):
        """INI file should contain the numeric period value for the timeframe."""
        ini_path = str(tmp_path / "backtest.ini")
        runner.generate_ini(
            target=portable_target,
            ea_name="TestEA",
            symbol="EURUSD",
            timeframe="M30",
            date_from=datetime(2024, 1, 1),
            date_to=datetime(2024, 6, 30),
            output_path=ini_path,
        )
        content = Path(ini_path).read_text()
        # MT5 INI uses numeric period (minutes): M30 = 30
        assert "Period=30" in content

    def test_generate_ini_contains_date_range(self, runner, portable_target, tmp_path):
        """INI file should contain the date range."""
        ini_path = str(tmp_path / "backtest.ini")
        runner.generate_ini(
            target=portable_target,
            ea_name="TestEA",
            symbol="EURUSD",
            timeframe="H1",
            date_from=datetime(2024, 1, 1),
            date_to=datetime(2024, 12, 31),
            output_path=ini_path,
        )
        content = Path(ini_path).read_text()
        assert "2024.01.01" in content
        assert "2024.12.31" in content

    def test_generate_ini_portable_mode_uses_install_path(
        self, runner, portable_target, tmp_path
    ):
        """Portable mode: INI should reference install_path for data folder."""
        ini_path = str(tmp_path / "backtest.ini")
        runner.generate_ini(
            target=portable_target,
            ea_name="TestEA",
            symbol="EURUSD",
            timeframe="H1",
            date_from=datetime(2024, 1, 1),
            date_to=datetime(2024, 6, 30),
            output_path=ini_path,
        )
        content = Path(ini_path).read_text()
        assert _to_posix("/fake/mt5_portable") in _to_posix(content)

    def test_generate_ini_normal_mode_uses_data_path(
        self, runner, normal_target, tmp_path
    ):
        """Normal mode: INI should reference data_path for data folder."""
        ini_path = str(tmp_path / "backtest.ini")
        runner.generate_ini(
            target=normal_target,
            ea_name="TestEA",
            symbol="EURUSD",
            timeframe="H1",
            date_from=datetime(2024, 1, 1),
            date_to=datetime(2024, 6, 30),
            output_path=ini_path,
        )
        content = Path(ini_path).read_text()
        assert _to_posix("/fake/mt5_data") in _to_posix(content)

    def test_generate_ini_creates_parent_dirs(self, runner, portable_target, tmp_path):
        """Should create parent directories if they don't exist."""
        ini_path = str(tmp_path / "subdir" / "deep" / "backtest.ini")
        result = runner.generate_ini(
            target=portable_target,
            ea_name="TestEA",
            symbol="EURUSD",
            timeframe="H1",
            date_from=datetime(2024, 1, 1),
            date_to=datetime(2024, 6, 30),
            output_path=ini_path,
        )
        assert os.path.isfile(result)


# ── Backtest Execution Tests ──────────────────────────────────────


class TestRunBacktest:
    """Tests for run_backtest() method with mocked subprocess."""

    def test_run_backtest_calls_terminal_with_config(
        self, runner, portable_target
    ):
        """Should launch terminal64.exe with /config:<ini_path>."""
        mock_process = MagicMock()
        mock_process.communicate = MagicMock(return_value=("", ""))
        mock_process.returncode = 0

        with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
            result = runner.run_backtest(
                target=portable_target,
                ea_name="TestEA",
                symbol="EURUSD",
                timeframe="H1",
                date_from=datetime(2024, 1, 1),
                date_to=datetime(2024, 6, 30),
            )

            mock_popen.assert_called_once()
            cmd = mock_popen.call_args[0][0]
            assert "/fake/terminal64.exe" in cmd
            assert any("/config:" in arg for arg in cmd)

    def test_run_backtest_success(self, runner, portable_target):
        """Successful backtest should return success=True."""
        mock_process = MagicMock()
        mock_process.communicate = MagicMock(return_value=("", ""))
        mock_process.returncode = 0

        with patch("subprocess.Popen", return_value=mock_process):
            result = runner.run_backtest(
                target=portable_target,
                ea_name="TestEA",
                symbol="EURUSD",
                timeframe="H1",
                date_from=datetime(2024, 1, 1),
                date_to=datetime(2024, 6, 30),
            )
            assert result.success is True
            assert result.error is None

    def test_run_backtest_nonzero_exit_code(
        self, runner, portable_target
    ):
        """Non-zero exit code should set success=False."""
        mock_process = MagicMock()
        mock_process.communicate = MagicMock(return_value=("Error output", ""))
        mock_process.returncode = 1

        with patch("subprocess.Popen", return_value=mock_process):
            result = runner.run_backtest(
                target=portable_target,
                ea_name="TestEA",
                symbol="EURUSD",
                timeframe="H1",
                date_from=datetime(2024, 1, 1),
                date_to=datetime(2024, 6, 30),
            )
            assert result.success is False
            assert result.error is not None

    def test_run_backtest_includes_log_output(
        self, runner, portable_target
    ):
        """Should capture and return subprocess output in log."""
        mock_process = MagicMock()
        mock_process.communicate = MagicMock(
            return_value=("Backtest complete", "stderr stuff")
        )
        mock_process.returncode = 0

        with patch("subprocess.Popen", return_value=mock_process):
            result = runner.run_backtest(
                target=portable_target,
                ea_name="TestEA",
                symbol="EURUSD",
                timeframe="H1",
                date_from=datetime(2024, 1, 1),
                date_to=datetime(2024, 6, 30),
            )
            assert "Backtest complete" in result.log
            assert "stderr stuff" in result.log

    def test_run_backtest_returns_report_path(
        self, runner, portable_target
    ):
        """Should resolve the HTML report path from tester directory."""
        mock_process = MagicMock()
        mock_process.communicate = MagicMock(return_value=("", ""))
        mock_process.returncode = 0

        with patch("subprocess.Popen", return_value=mock_process):
            result = runner.run_backtest(
                target=portable_target,
                ea_name="TestEA",
                symbol="EURUSD",
                timeframe="H1",
                date_from=datetime(2024, 1, 1),
                date_to=datetime(2024, 6, 30),
            )
            # Report path should be set (even if file doesn't exist in test)
            assert result.report_path is not None
            assert result.report_path.endswith(".htm")

    def test_run_backtest_handles_file_not_found(
        self, runner, portable_target
    ):
        """Missing terminal64.exe should raise RuntimeError."""
        with patch(
            "subprocess.Popen",
            side_effect=FileNotFoundError("terminal64.exe not found"),
        ):
            result = runner.run_backtest(
                target=portable_target,
                ea_name="TestEA",
                symbol="EURUSD",
                timeframe="H1",
                date_from=datetime(2024, 1, 1),
                date_to=datetime(2024, 6, 30),
            )
            assert result.success is False
            assert "not found" in result.error.lower()


# ── Timeout Handling Tests ────────────────────────────────────────


class TestTimeoutHandling:
    """Tests for timeout and process management."""

    def test_run_backtest_timeout_kills_process(
        self, runner, portable_target
    ):
        """Should kill process on timeout and return error."""
        mock_process = MagicMock()
        mock_process.communicate.side_effect = subprocess.TimeoutExpired(
            cmd="terminal64.exe", timeout=300
        )
        mock_process.kill = MagicMock()

        with patch("subprocess.Popen", return_value=mock_process):
            result = runner.run_backtest(
                target=portable_target,
                ea_name="TestEA",
                symbol="EURUSD",
                timeframe="H1",
                date_from=datetime(2024, 1, 1),
                date_to=datetime(2024, 6, 30),
            )
            assert result.success is False
            assert "timed out" in result.error.lower()
            mock_process.kill.assert_called_once()

    def test_custom_timeout_is_respected(self):
        """Custom timeout should be passed to communicate()."""
        r = BacktestRunner(timeout=60)
        mock_process = MagicMock()
        mock_process.communicate = MagicMock(return_value=("", ""))
        mock_process.returncode = 0

        target = MT5Target(
            name="Test",
            install_path="/fake",
            data_path=None,
            is_portable=True,
        )

        with patch("subprocess.Popen", return_value=mock_process):
            r.run_backtest(
                target=target,
                ea_name="TestEA",
                symbol="EURUSD",
                timeframe="H1",
                date_from=datetime(2024, 1, 1),
                date_to=datetime(2024, 6, 30),
            )
            mock_process.communicate.assert_called_once_with(timeout=60)

    def test_timeout_error_message_includes_seconds(
        self, runner, portable_target
    ):
        """Timeout error message should mention the timeout duration."""
        mock_process = MagicMock()
        mock_process.communicate.side_effect = subprocess.TimeoutExpired(
            cmd="terminal64.exe", timeout=300
        )
        mock_process.kill = MagicMock()

        with patch("subprocess.Popen", return_value=mock_process):
            result = runner.run_backtest(
                target=portable_target,
                ea_name="TestEA",
                symbol="EURUSD",
                timeframe="H1",
                date_from=datetime(2024, 1, 1),
                date_to=datetime(2024, 6, 30),
            )
            assert "300" in result.error



# ── Report Path Resolution Tests ──────────────────────────────────


class TestReportPath:
    """Tests for report path resolution from tester directory."""

    def test_report_path_includes_ea_name(self, runner, portable_target):
        """Report path should contain the EA name."""
        mock_process = MagicMock()
        mock_process.communicate = MagicMock(return_value=("", ""))
        mock_process.returncode = 0

        with patch("subprocess.Popen", return_value=mock_process):
            result = runner.run_backtest(
                target=portable_target,
                ea_name="MyExpert",
                symbol="EURUSD",
                timeframe="H1",
                date_from=datetime(2024, 1, 1),
                date_to=datetime(2024, 6, 30),
            )
            assert "MyExpert" in result.report_path

    def test_report_path_includes_tester_dir(self, runner, portable_target):
        """Report path should be under the tester directory."""
        mock_process = MagicMock()
        mock_process.communicate = MagicMock(return_value=("", ""))
        mock_process.returncode = 0

        with patch("subprocess.Popen", return_value=mock_process):
            result = runner.run_backtest(
                target=portable_target,
                ea_name="TestEA",
                symbol="EURUSD",
                timeframe="H1",
                date_from=datetime(2024, 1, 1),
                date_to=datetime(2024, 6, 30),
            )
            assert "tester" in result.report_path.lower()

    def test_report_path_portable_uses_install_path(
        self, runner, portable_target
    ):
        """Portable mode: report path should be under install_path."""
        mock_process = MagicMock()
        mock_process.communicate = MagicMock(return_value=("", ""))
        mock_process.returncode = 0

        with patch("subprocess.Popen", return_value=mock_process):
            result = runner.run_backtest(
                target=portable_target,
                ea_name="TestEA",
                symbol="EURUSD",
                timeframe="H1",
                date_from=datetime(2024, 1, 1),
                date_to=datetime(2024, 6, 30),
            )
            assert _to_posix("/fake/mt5_portable") in _to_posix(result.report_path)

    def test_report_path_normal_uses_data_path(
        self, runner, normal_target
    ):
        """Normal mode: report path should be under data_path."""
        mock_process = MagicMock()
        mock_process.communicate = MagicMock(return_value=("", ""))
        mock_process.returncode = 0

        with patch("subprocess.Popen", return_value=mock_process):
            result = runner.run_backtest(
                target=normal_target,
                ea_name="TestEA",
                symbol="EURUSD",
                timeframe="H1",
                date_from=datetime(2024, 1, 1),
                date_to=datetime(2024, 6, 30),
            )
            assert _to_posix("/fake/mt5_data") in _to_posix(result.report_path)
