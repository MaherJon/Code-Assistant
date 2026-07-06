"""Shell command execution tool with sandboxing."""

import asyncio
import os
import subprocess
from typing import Optional

from codeassistant.tools.base import Tool, ToolPermission, ToolResult
from codeassistant.utils.sandbox import Sandbox


class BashTool(Tool):
    """Execute a shell command and return its output."""

    name = "run_shell"
    description = (
        "Execute a shell command and return its output (stdout and stderr). "
        "Use this for building, testing, git operations, installing packages, etc. "
        "Commands run in the working directory with a configurable timeout. "
        "IMPORTANT: Always explain what command you're running and why."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute."
            },
            "working_dir": {
                "type": "string",
                "description": "Working directory for the command. Defaults to the project working directory."
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum execution time in seconds. Default: 120, Max: 600.",
                "default": 120,
            },
        },
        "required": ["command"],
    }
    permission = ToolPermission.NEEDS_CONFIRM

    def __init__(self, working_dir: str = ".", sandbox: Optional[Sandbox] = None):
        self.working_dir = working_dir
        self.sandbox = sandbox or Sandbox()

    async def execute(
        self,
        command: str,
        working_dir: Optional[str] = None,
        timeout: int = 120,
    ) -> ToolResult:
        """Execute a shell command."""
        # Validate command
        is_allowed, reason = self.sandbox.validate(command)
        if not is_allowed:
            return ToolResult.fail(f"Command blocked: {reason}")

        # Resolve working directory
        cwd = working_dir or self.working_dir
        if not os.path.isabs(cwd):
            cwd = os.path.join(self.working_dir, cwd)
        cwd = os.path.normpath(cwd)

        if not os.path.isdir(cwd):
            return ToolResult.fail(f"Directory not found: {cwd}")

        # Clamp timeout
        timeout = max(1, min(timeout, 600))

        try:
            # Run asynchronously with timeout
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                ),
                timeout=10,  # Process creation timeout
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )

            stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
            stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""

            output_parts = []
            if stdout_str:
                # Truncate stdout if too long
                if len(stdout_str) > 50000:
                    stdout_str = stdout_str[:50000] + "\n... (output truncated)"
                output_parts.append(stdout_str)

            if stderr_str:
                if len(stderr_str) > 10000:
                    stderr_str = stderr_str[:10000] + "\n... (stderr truncated)"
                output_parts.append(f"[stderr]\n{stderr_str}")

            output = "\n".join(output_parts) if output_parts else "(no output)"

            # Add exit code info
            status = f"Exit code: {proc.returncode}"
            if proc.returncode != 0:
                status += " (error)"

            return ToolResult(
                success=proc.returncode == 0,
                output=f"{status}\n\n{output}",
                metadata={
                    "exit_code": proc.returncode,
                    "cwd": cwd,
                }
            )

        except asyncio.TimeoutError:
            return ToolResult.fail(
                f"Command timed out after {timeout}s: {command[:100]}"
            )
        except FileNotFoundError:
            return ToolResult.fail(
                f"Shell not found or command not available: {command[:100]}"
            )
        except Exception as e:
            return ToolResult.fail(f"Error executing command: {e}")

    def render_input(self, command: str, **kwargs) -> str:
        """Show command in a readable format."""
        display = command if len(command) <= 80 else command[:77] + "..."
        return f"$ {display}"
