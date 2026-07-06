"""Permission system for tool execution control.

Controls which tool calls are auto-executed vs require user confirmation.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from codeassistant.tools.base import Tool, ToolPermission


# Dangerous file paths that should never be written
BLOCKED_PATHS = [
    "/etc/", "/sys/", "/proc/", "/boot/",
    "C:\\Windows\\", "C:\\System32\\",
    "/System/", "/Library/",
    "~/.ssh/", "~/.gnupg/",
    ".git/config",
]


@dataclass
class PermissionPolicy:
    """Policy defining which operations require confirmation."""

    # Mode: "prompt" (ask for everything) or "auto_safe" (auto-allow safe ops)
    mode: str = "prompt"

    # Additional blocked paths
    blocked_paths: List[str] = field(default_factory=list)

    # Always-blocked patterns
    blocked_commands: List[str] = field(default_factory=list)

    # Always-safe patterns (for auto_safe mode)
    safe_commands: List[str] = field(default_factory=list)

    @classmethod
    def default(cls) -> "PermissionPolicy":
        return cls(mode="prompt")

    @classmethod
    def auto(cls) -> "PermissionPolicy":
        """Auto-safe mode: auto-allow known-safe operations."""
        return cls(mode="auto_safe")


class PermissionChecker:
    """Evaluates whether a tool call is allowed."""

    def __init__(self, policy: PermissionPolicy = None):
        self.policy = policy or PermissionPolicy.default()

    def check(self, tool: Tool, params: Dict) -> ToolPermission:
        """Determine the permission for a tool call.

        Order of precedence:
        1. If the tool itself is BLOCKED → blocked
        2. If the tool is SAFE → safe
        3. For NEEDS_CONFIRM tools:
           a. Check if any params match blocked patterns → blocked
           b. Check auto_safe mode for shell commands → safe if known-safe
           c. Otherwise → needs confirmation

        Returns:
            The most restrictive applicable permission
        """
        # Tool-level block
        if tool.permission == ToolPermission.BLOCKED:
            return ToolPermission.BLOCKED

        # Tool-level safe
        if tool.permission == ToolPermission.SAFE:
            return ToolPermission.SAFE

        # For NEEDS_CONFIRM tools, check detailed policies
        if tool.name in ("write_file", "edit_file"):
            path = params.get("path", "")
            if self._is_blocked_path(path):
                return ToolPermission.BLOCKED

        elif tool.name == "run_shell":
            command = params.get("command", "")
            if self._is_blocked_command(command):
                return ToolPermission.BLOCKED
            if self.policy.mode == "auto_safe" and self._is_safe_command(command):
                return ToolPermission.SAFE

        elif tool.name == "git_commit":
            # Always confirm commits
            return ToolPermission.NEEDS_CONFIRM

        elif tool.name == "git_add":
            # Check if adding to root
            files = params.get("files", "")
            if "." == files.strip() or "*" == files.strip():
                # Git add all needs extra care
                return ToolPermission.NEEDS_CONFIRM

        return tool.permission

    def _is_blocked_path(self, path: str) -> bool:
        """Check if a file path is blocked from modification."""
        path_lower = path.lower().replace("\\", "/")
        expanded = os.path.expanduser(path_lower)

        for blocked in BLOCKED_PATHS + self.policy.blocked_paths:
            blocked_lower = blocked.lower().replace("\\", "/")
            if expanded.startswith(blocked_lower) or blocked_lower in expanded:
                return True
        return False

    def _is_blocked_command(self, command: str) -> bool:
        """Check if a shell command is blocked."""
        cmd_lower = command.strip().lower()

        # Dangerous patterns
        dangerous = [
            ("rm -rf /", "Attempting to delete root filesystem"),
            ("rm -rf ~", "Attempting to delete home directory"),
            ("rm -rf $home", "Attempting to delete home directory"),
            ("mkfs.", "Filesystem format command"),
            ("dd if=", "Raw disk write operation"),
            (":(){ :|:& };:", "Fork bomb detected"),
            ("chmod 777 /", "Dangerous permission change on root"),
            ("curl", "curl piped to shell"),
            ("wget", "wget piped to shell"),
            ("shutdown", "System shutdown"),
            ("reboot", "System reboot"),
            ("sudo rm", "Sudo remove command"),
        ]

        # Check curl/wget pipe to shell specifically
        if ("curl" in cmd_lower or "wget" in cmd_lower) and ("|" in command):
            if "sh" in cmd_lower or "bash" in cmd_lower:
                return True

        for pattern, _ in dangerous:
            if pattern in cmd_lower:
                return True

        return False

    def _is_safe_command(self, command: str) -> bool:
        """Check if a shell command is known-safe for auto-approval."""
        cmd = command.strip()

        safe_prefixes = [
            "ls ", "dir ", "pwd", "echo ",
            "cat ", "head ", "tail ", "wc ",
            "grep ", "find ", "which ", "type ",
            "git status", "git diff", "git log", "git branch",
            "git stash list", "git show ",
            "python --version", "python -c ",
            "pip list", "pip show ",
            "node --version", "npm --version",
            "cargo --version", "rustc --version",
            "go version",
            "docker ps", "docker images",
            "whoami", "hostname", "uname",
            "env", "printenv",
        ]

        cmd_lower = cmd.lower()
        for prefix in safe_prefixes:
            if cmd_lower.startswith(prefix):
                return True
        return False

    def update_policy(self, policy: PermissionPolicy) -> None:
        """Update the permission policy."""
        self.policy = policy
