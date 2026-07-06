"""Git operation tools for version control automation."""

import asyncio
import os
from typing import Optional

from mahe.tools.base import Tool, ToolPermission, ToolResult


class GitStatus(Tool):
    """Show the working tree status."""

    name = "git_status"
    description = "Show the git working tree status (modified, staged, untracked files)."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Repository path. Defaults to working directory."
            },
        },
        "required": [],
    }
    permission = ToolPermission.SAFE

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    async def execute(self, path: str = None) -> ToolResult:
        cwd = path or self.working_dir
        return await self._run_git(["status", "--short", "--branch"], cwd)


class GitDiff(Tool):
    """Show changes in the working tree."""

    name = "git_diff"
    description = "Show git diff of changes (unstaged, staged, or between commits)."
    parameters = {
        "type": "object",
        "properties": {
            "staged": {
                "type": "boolean",
                "description": "Show staged changes (--staged). Default: false (unstaged)."
            },
            "path": {
                "type": "string",
                "description": "Repository path. Defaults to working directory."
            },
        },
        "required": [],
    }
    permission = ToolPermission.SAFE

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    async def execute(self, staged: bool = False, path: str = None) -> ToolResult:
        cwd = path or self.working_dir
        args = ["diff"]
        if staged:
            args.append("--staged")
        return await self._run_git(args, cwd)


class GitLog(Tool):
    """Show commit history."""

    name = "git_log"
    description = "Show git commit history with a configurable number of entries."
    parameters = {
        "type": "object",
        "properties": {
            "count": {
                "type": "integer",
                "description": "Number of recent commits to show. Default: 10.",
                "default": 10,
            },
            "path": {
                "type": "string",
                "description": "Repository path. Defaults to working directory."
            },
        },
        "required": [],
    }
    permission = ToolPermission.SAFE

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    async def execute(self, count: int = 10, path: str = None) -> ToolResult:
        cwd = path or self.working_dir
        return await self._run_git(
            ["log", f"-{min(count, 100)}", "--oneline", "--decorate"],
            cwd
        )


class GitBranch(Tool):
    """List, create, or switch branches."""

    name = "git_branch"
    description = "List git branches. Use run_shell for creating/switching branches."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Repository path. Defaults to working directory."
            },
        },
        "required": [],
    }
    permission = ToolPermission.SAFE

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    async def execute(self, path: str = None) -> ToolResult:
        cwd = path or self.working_dir
        return await self._run_git(["branch", "--list"], cwd)


class GitAdd(Tool):
    """Stage files for commit."""

    name = "git_add"
    description = "Stage files for git commit. Use with specific file paths to be safe."
    parameters = {
        "type": "object",
        "properties": {
            "files": {
                "type": "string",
                "description": "Files to stage (space-separated paths, or '.' for all)."
            },
            "path": {
                "type": "string",
                "description": "Repository path. Defaults to working directory."
            },
        },
        "required": ["files"],
    }
    permission = ToolPermission.NEEDS_CONFIRM

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    async def execute(self, files: str, path: str = None) -> ToolResult:
        cwd = path or self.working_dir
        # Split files and add each
        file_list = files.split()
        return await self._run_git(["add"] + file_list, cwd)


class GitCommit(Tool):
    """Create a commit with staged changes."""

    name = "git_commit"
    description = "Create a git commit with staged changes. Use git_add first to stage files."
    parameters = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Commit message."
            },
            "path": {
                "type": "string",
                "description": "Repository path. Defaults to working directory."
            },
        },
        "required": ["message"],
    }
    permission = ToolPermission.NEEDS_CONFIRM

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    async def execute(self, message: str, path: str = None) -> ToolResult:
        cwd = path or self.working_dir
        return await self._run_git(["commit", "-m", message], cwd)


# Helper for all git tools
async def _run_git(args: list, cwd: str) -> ToolResult:
    """Run a git command and return the result."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=60
        )
    except asyncio.TimeoutError:
        return ToolResult.fail("Git command timed out")
    except FileNotFoundError:
        return ToolResult.fail("Git not found. Is git installed and in PATH?")
    except Exception as e:
        return ToolResult.fail(f"Error running git: {e}")

    stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
    stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""

    output = stdout_str or stderr_str or "(no output)"

    return ToolResult(
        success=proc.returncode == 0,
        output=output if proc.returncode == 0 else f"[Error]\n{stderr_str or stdout_str}",
        metadata={"exit_code": proc.returncode},
    )


# Patch git tool classes to use the helper
GitStatus._run_git = staticmethod(_run_git)
GitDiff._run_git = staticmethod(_run_git)
GitLog._run_git = staticmethod(_run_git)
GitBranch._run_git = staticmethod(_run_git)
GitAdd._run_git = staticmethod(_run_git)
GitCommit._run_git = staticmethod(_run_git)
