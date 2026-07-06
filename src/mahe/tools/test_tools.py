"""Test automation tools: run tests, analyze failures, fix-and-rerun."""

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import List, Optional

from mahe.tools.base import Tool, ToolPermission, ToolResult

logger = logging.getLogger("mahe.tools.test")


class RunTests(Tool):
    """Run project tests and report results."""

    name = "run_tests"
    description = (
        "Run project tests using pytest (or the detected test runner). "
        "Returns test results with any failures, including file paths and line numbers. "
        "Use this to check if code changes work correctly. "
        "To fix failures, use this first to identify issues, then edit the source."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Specific test file or directory to run. Default: entire test suite."
            },
            "test_name": {
                "type": "string",
                "description": "Specific test function or class name to run."
            },
            "verbose": {
                "type": "boolean",
                "description": "Show verbose output including test names. Default: false.",
                "default": False,
            },
            "max_failures": {
                "type": "integer",
                "description": "Stop after N failures. Default: no limit.",
            },
        },
        "required": [],
    }
    permission = ToolPermission.SAFE

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    async def execute(
        self,
        path: Optional[str] = None,
        test_name: Optional[str] = None,
        verbose: bool = False,
        max_failures: Optional[int] = None,
    ) -> ToolResult:
        """Run tests and parse results."""
        # Detect test runner
        test_runner = self._detect_runner()

        # Build command
        if test_runner == "pytest":
            cmd_parts = ["python", "-m", "pytest"]
            if verbose:
                cmd_parts.append("-v")
            if max_failures:
                cmd_parts.extend(["--maxfail", str(max_failures)])
            if path:
                cmd_parts.append(path)
            if test_name:
                cmd_parts.extend(["-k", test_name])
        else:
            # Generic: try pytest first
            cmd_parts = ["python", "-m", "pytest", "-v" if verbose else ""]
            if path:
                cmd_parts.append(path)

        cmd = " ".join(filter(None, cmd_parts))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd.split(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_dir,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=300  # 5 min max
            )
        except asyncio.TimeoutError:
            return ToolResult.fail("Tests timed out after 5 minutes.")
        except FileNotFoundError:
            return ToolResult.fail("pytest not found. Install with: pip install pytest")
        except Exception as e:
            return ToolResult.fail(f"Error running tests: {e}")

        stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""

        # Parse failures
        failures = self._parse_pytest_failures(stdout_str + "\n" + stderr_str)

        # Build summary
        exit_code = proc.returncode
        summary_parts = []
        summary_parts.append(f"Exit code: {exit_code} {'✓ Passed' if exit_code == 0 else '✗ Failed'}")

        # Try to extract test counts
        passed_match = re.search(r"(\d+) passed", stdout_str)
        failed_match = re.search(r"(\d+) failed", stdout_str)
        error_match = re.search(r"(\d+) error", stdout_str)

        if passed_match or failed_match:
            counts = []
            if passed_match:
                counts.append(f"{passed_match.group(1)} passed")
            if failed_match:
                counts.append(f"{failed_match.group(1)} failed")
            if error_match:
                counts.append(f"{error_match.group(1)} errors")
            summary_parts.append(", ".join(counts))

        if failures:
            summary_parts.append(f"\n[bold]Failures ({len(failures)}):[/]")
            for f in failures[:10]:
                summary_parts.append(
                    f"\n  {f['path']}:{f['line']} - {f['test_name']}\n"
                    f"  {f['message'][:200]}"
                )
            if len(failures) > 10:
                summary_parts.append(f"\n  ... and {len(failures) - 10} more failures")

        # Truncate full output
        output = stdout_str
        if len(output) > 8000:
            summary_part = output[:4000] + "\n...\n" + output[-4000:]
        else:
            summary_part = output

        return ToolResult(
            success=exit_code == 0,
            output="\n".join(summary_parts) + "\n\n" + summary_part,
            metadata={
                "exit_code": exit_code,
                "failures": len(failures),
            }
        )

    def _detect_runner(self) -> str:
        """Detect the project's test runner."""
        root = Path(self.working_dir)

        # Check for pytest config
        for config in ["pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"]:
            if (root / config).exists():
                # Check if it has pytest config
                try:
                    content = (root / config).read_text()
                    if "pytest" in content or "[tool.pytest" in content:
                        return "pytest"
                except Exception:
                    pass

        # Check for test directory
        if (root / "tests").is_dir() or (root / "test").is_dir():
            return "pytest"

        return "pytest"  # Default

    def _parse_pytest_failures(self, output: str) -> List[dict]:
        """Parse pytest output to extract failure details."""
        failures = []

        # Pattern: FAILED tests/test_file.py::TestClass::test_name - AssertionError: message
        # Pattern: E   AssertionError: ...
        # Pattern: >   actual code line

        failure_pattern = re.compile(
            r"FAILED\s+(\S+?)(?:::\S+)?\s*-\s*(.*)",
            re.MULTILINE,
        )

        for match in failure_pattern.finditer(output):
            test_id = match.group(1)
            error_msg = match.group(2).strip()

            # Parse file path and test name
            parts = test_id.split("::")
            path = parts[0] if parts else test_id
            test_name = "::".join(parts[1:]) if len(parts) > 1 else path

            # Try to find line number from the error context
            line = 0
            line_match = re.search(rf"{re.escape(path)}:(\d+)", output)
            if line_match:
                line = int(line_match.group(1))

            failures.append({
                "path": path,
                "line": line,
                "test_name": test_name,
                "message": error_msg[:300],
            })

        return failures
