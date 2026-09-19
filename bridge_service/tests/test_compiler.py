"""Tests for Compiler: metaeditor64.exe wrapper for MQL5 compilation."""

import os
import sys

import pytest
from unittest.mock import MagicMock, patch

# Adjust import path for tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.compiler import Compiler, CompileResult, CompileError


# ── CompileResult Model Tests ─────────────────────────────────────


class TestCompileResult:
    """Tests for CompileResult data model."""

    def test_successful_compilation(self):
        result = CompileResult(success=True)
        assert result.success is True
        assert result.errors == []
        assert result.warnings == []
        assert result.log == ""

    def test_successful_compilation_with_warnings(self):
        result = CompileResult(
            success=True,
            warnings=["warning: unused variable x"],
        )
        assert result.success is True
        assert len(result.warnings) == 1

    def test_failed_compilation_with_errors(self):
        errors = [
            CompileError(file="test.mq5", line=10, severity="error", message="undeclared identifier 'x'"),
            CompileError(file="test.mq5", line=15, severity="error", message="';' expected"),
        ]
        result = CompileResult(success=False, errors=errors)
        assert result.success is False
        assert len(result.errors) == 2
        assert result.errors[0].message == "undeclared identifier 'x'"

    def test_compile_result_with_log(self):
        result = CompileResult(
            success=True,
            log="Compilation time: 0.5s",
        )
        assert result.log == "Compilation time: 0.5s"

    def test_compile_error_attributes(self):
        error = CompileError(
            file="my_strategy.mq5",
            line=42,
            severity="error",
            message="type mismatch",
        )
        assert error.file == "my_strategy.mq5"
        assert error.line == 42
        assert error.severity == "error"
        assert error.message == "type mismatch"

    def test_compile_error_warning_severity(self):
        error = CompileError(
            file="test.mq5",
            line=5,
            severity="warning",
            message="implicit conversion",
        )
        assert error.severity == "warning"


# ── Compiler Initialization Tests ─────────────────────────────────


class TestCompilerInit:
    """Tests for Compiler class initialization."""

    def test_create_with_default_metaeditor_path(self):
        compiler = Compiler()
        assert compiler.metaeditor_path is not None
        assert "metaeditor" in compiler.metaeditor_path.lower()

    def test_create_with_custom_metaeditor_path(self):
        compiler = Compiler(metaeditor_path="/custom/path/metaeditor64.exe")
        assert compiler.metaeditor_path == "/custom/path/metaeditor64.exe"

    def test_create_with_empty_string_uses_default(self):
        compiler = Compiler(metaeditor_path="")
        assert compiler.metaeditor_path is not None

    def test_default_include_paths_empty(self):
        compiler = Compiler()
        assert compiler.include_paths == []

    def test_custom_include_paths(self):
        compiler = Compiler(include_paths=["/includes", "/libraries"])
        assert len(compiler.include_paths) == 2


# ── Error Parser Tests ────────────────────────────────────────────


class TestErrorParser:
    """Tests for parsing metaeditor64.exe compilation output."""

    def test_parse_single_error(self):
        compiler = Compiler()
        output = 'test.mq5(10) : error : undeclared identifier \'x\''
        errors = compiler.parse_output(output)
        assert len(errors) == 1
        assert errors[0].file == "test.mq5"
        assert errors[0].line == 10
        assert errors[0].severity == "error"
        assert "undeclared identifier" in errors[0].message

    def test_parse_multiple_errors(self):
        compiler = Compiler()
        output = (
            'test.mq5(10) : error : undeclared identifier \'x\'\n'
            'test.mq5(15) : error : \';\' expected\n'
            'test.mq5(20) : warning : unused variable \'y\''
        )
        errors = compiler.parse_output(output)
        assert len(errors) == 3
        assert errors[0].severity == "error"
        assert errors[1].severity == "error"
        assert errors[2].severity == "warning"

    def test_parse_empty_output(self):
        compiler = Compiler()
        errors = compiler.parse_output("")
        assert errors == []

    def test_parse_no_errors(self):
        compiler = Compiler()
        output = "Compilation time: 0.5s\n0 error(s), 0 warning(s)"
        errors = compiler.parse_output(output)
        assert errors == []

    def test_parse_with_zero_errors_line(self):
        compiler = Compiler()
        output = "0 error(s), 2 warning(s)\n"
        errors = compiler.parse_output(output)
        assert errors == []

    def test_parse_compilation_time_line_ignored(self):
        compiler = Compiler()
        output = "Compilation time: 0.5s\n0 error(s), 0 warning(s)"
        errors = compiler.parse_output(output)
        assert errors == []

    def test_parse_error_with_path_in_filename(self):
        compiler = Compiler()
        output = 'C:/MQL5/Experts/test.mq5(42) : error : syntax error'
        errors = compiler.parse_output(output)
        assert len(errors) == 1
        assert errors[0].line == 42

    def test_parse_warnings_not_errors(self):
        compiler = Compiler()
        output = 'test.mq5(5) : warning : implicit conversion from \'int\' to \'bool\''
        errors = compiler.parse_output(output)
        assert len(errors) == 1
        assert errors[0].severity == "warning"

    def test_parse_multiline_error_message(self):
        compiler = Compiler()
        output = (
            'test.mq5(10) : error : too many parameters\n'
            'for function call\n'
            'test.mq5(15) : error : \'x\' - undeclared identifier'
        )
        errors = compiler.parse_output(output)
        # Should parse the lines that match the pattern
        assert len(errors) >= 2


# ── Compiler Compile Method Tests ─────────────────────────────────


class TestCompilerCompile:
    """Tests for Compiler.compile() method with mocked subprocess."""

    def test_compile_calls_metaeditor_with_file_path(self):
        compiler = Compiler(metaeditor_path="/fake/metaeditor64.exe")

        mock_process = MagicMock()
        mock_process.communicate = MagicMock(return_value=("0 error(s), 0 warning(s)", ""))
        mock_process.returncode = 0

        with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
            result = compiler.compile("/fake/strategy.mq5")

            # Verify Popen was called
            mock_popen.assert_called_once()
            call_args = mock_popen.call_args
            # First arg is the command list
            cmd = call_args[0][0]
            assert "/fake/metaeditor64.exe" in cmd
            assert "/fake/strategy.mq5" in cmd

    def test_compile_success_returns_true(self):
        compiler = Compiler(metaeditor_path="/fake/metaeditor64.exe")

        mock_process = MagicMock()
        mock_process.communicate = MagicMock(return_value=("0 error(s), 0 warning(s)", ""))
        mock_process.returncode = 0

        with patch("subprocess.Popen", return_value=mock_process):
            result = compiler.compile("/fake/strategy.mq5")
            assert result.success is True
            assert result.errors == []

    def test_compile_failure_returns_false_with_errors(self):
        compiler = Compiler(metaeditor_path="/fake/metaeditor64.exe")

        error_output = "test.mq5(10) : error : undeclared identifier 'x'\n1 error(s), 0 warning(s)"
        mock_process = MagicMock()
        mock_process.communicate = MagicMock(return_value=(error_output, ""))
        mock_process.returncode = 1

        with patch("subprocess.Popen", return_value=mock_process):
            result = compiler.compile("/fake/strategy.mq5")
            assert result.success is False
            assert len(result.errors) == 1
            assert "undeclared identifier" in result.errors[0].message

    def test_compile_includes_include_paths(self):
        compiler = Compiler(
            metaeditor_path="/fake/metaeditor64.exe",
            include_paths=["/includes", "/libraries"],
        )

        mock_process = MagicMock()
        mock_process.communicate = MagicMock(return_value=("0 error(s), 0 warning(s)", ""))
        mock_process.returncode = 0

        with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
            compiler.compile("/fake/strategy.mq5")
            cmd = mock_popen.call_args[0][0]
            # Include paths should be passed as /include: flags
            assert any("/includes" in arg for arg in cmd)
            assert any("/libraries" in arg for arg in cmd)

    def test_compile_strips_log_output(self):
        compiler = Compiler(metaeditor_path="/fake/metaeditor64.exe")

        log_output = "0 error(s), 0 warning(s)\nCompilation time: 0.5s"
        mock_process = MagicMock()
        mock_process.communicate = MagicMock(return_value=(log_output, ""))
        mock_process.returncode = 0

        with patch("subprocess.Popen", return_value=mock_process):
            result = compiler.compile("/fake/strategy.mq5")
            assert result.log == "0 error(s), 0 warning(s)\nCompilation time: 0.5s"

    def test_compile_populates_warnings(self):
        compiler = Compiler(metaeditor_path="/fake/metaeditor64.exe")

        output = "test.mq5(5) : warning : implicit conversion\n0 error(s), 1 warning(s)"
        mock_process = MagicMock()
        mock_process.communicate = MagicMock(return_value=(output, ""))
        mock_process.returncode = 0

        with patch("subprocess.Popen", return_value=mock_process):
            result = compiler.compile("/fake/strategy.mq5")
            assert len(result.warnings) == 1
            assert "implicit conversion" in result.warnings[0]

    def test_compile_handles_subprocess_error(self):
        compiler = Compiler(metaeditor_path="/fake/metaeditor64.exe")

        with patch("subprocess.Popen", side_effect=FileNotFoundError("metaeditor not found")):
            with pytest.raises(RuntimeError, match="metaeditor64.exe not found"):
                compiler.compile("/fake/strategy.mq5")


