"""MQL5 Compiler Wrapper: wraps metaeditor64.exe for compiling MQL5 files.

Provides CompileResult with parsed errors and warnings from metaeditor output.
"""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


# ── Data Models ───────────────────────────────────────────────────


@dataclass
class CompileError:
    """A single compilation error or warning parsed from metaeditor output."""

    file: str
    line: int
    severity: str  # "error" or "warning"
    message: str


@dataclass
class CompileResult:
    """Result of an MQL5 compilation attempt."""

    success: bool
    errors: list[CompileError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    log: str = ""


# ── Compiler Class ────────────────────────────────────────────────


# Pattern:  filename(line) : severity : message
# Examples:
#   test.mq5(10) : error : undeclared identifier 'x'
#   C:/MQL5/Experts/test.mq5(42) : warning : implicit conversion
_ERROR_PATTERN = re.compile(
    r"^(.+?)\((\d+)\)\s*:\s*(error|warning)\s*:\s*(.+)$"
)

# Pattern:  N error(s), M warning(s)
_SUMMARY_PATTERN = re.compile(r"(\d+)\s*error\(s\),\s*(\d+)\s*warning\(s\)")


class Compiler:
    """Wrapper around metaeditor64.exe for compiling MQL5 source files.

    Args:
        metaeditor_path: Path to the metaeditor64.exe binary.
            Defaults to the config setting.
        include_paths: Additional include directories for compilation.
    """

    def __init__(
        self,
        metaeditor_path: str = "",
        include_paths: list[str] | None = None,
    ) -> None:
        if metaeditor_path:
            self.metaeditor_path = metaeditor_path
        else:
            from config import settings
            self.metaeditor_path = settings.metaeditor_path
        self.include_paths = include_paths or []

    def compile(
        self,
        file_path: str,
        include_paths: list[str] | None = None,
    ) -> CompileResult:
        """Compile an MQL5 file using metaeditor64.exe.

        Args:
            file_path: Path to the .mq5 file to compile.
            include_paths: Optional override for include directories.

        Returns:
            CompileResult with success status, parsed errors/warnings, and log.
        """
        cmd = self._build_command(file_path, include_paths)
        stdout, stderr = self._run_subprocess(cmd)
        full_output = stdout + stderr
        errors = self.parse_output(full_output)
        warnings = [e.message for e in errors if e.severity == "warning"]
        non_warning_errors = [e for e in errors if e.severity == "error"]

        success = len(non_warning_errors) == 0 and self._check_zero_errors_line(full_output)
        return CompileResult(
            success=success,
            errors=non_warning_errors,
            warnings=warnings,
            log=full_output,
        )

    def parse_output(self, output: str) -> list[CompileError]:
        """Parse metaeditor64.exe stdout/stderr for errors and warnings.

        Args:
            output: The raw output string from metaeditor.

        Returns:
            List of CompileError objects, one per error/warning line.
        """
        errors: list[CompileError] = []
        for line in output.splitlines():
            line = line.strip()
            match = _ERROR_PATTERN.match(line)
            if match:
                file_name = match.group(1)
                line_num = int(match.group(2))
                severity = match.group(3)
                message = match.group(4).strip()
                errors.append(CompileError(
                    file=file_name,
                    line=line_num,
                    severity=severity,
                    message=message,
                ))
        return errors

    # ── Private helpers ───────────────────────────────────────────

    def _build_command(
        self,
        file_path: str,
        include_paths: list[str] | None = None,
    ) -> list[str]:
        """Build the metaeditor64.exe command line."""
        cmd = [self.metaeditor_path, file_path]
        paths = include_paths or self.include_paths
        for p in paths:
            cmd.append(f"/include:{p}")
        return cmd

    def _run_subprocess(self, cmd: list[str]) -> tuple[str, str]:
        """Run metaeditor64.exe and return (stdout, stderr)."""
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = process.communicate(timeout=120)
        except FileNotFoundError:
            raise RuntimeError(
                f"metaeditor64.exe not found at: {self.metaeditor_path}"
            )
        except subprocess.TimeoutExpired:
            process.kill()
            raise RuntimeError("Compilation timed out after 120 seconds")
        return stdout, stderr

    def _check_zero_errors_line(self, output: str) -> bool:
        """Check if output contains a '0 error(s)' summary line."""
        match = _SUMMARY_PATTERN.search(output)
        if match:
            return int(match.group(1)) == 0
        # No summary line found — check if any error-pattern lines exist
        return not any(_ERROR_PATTERN.match(line.strip()) for line in output.splitlines())
