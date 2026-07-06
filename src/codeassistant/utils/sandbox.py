"""Command sandbox for safe shell execution.

In MVP, this is a simple allowlist/blocklist approach.
Phase 3+ can add more sophisticated sandboxing.
"""

import re
from dataclasses import dataclass, field
from typing import List


# Default patterns for dangerous commands
DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+/",          # rm -rf /
    r"rm\s+-rf\s+~",          # rm -rf ~
    r"rm\s+-rf\s+\$HOME",     # rm -rf $HOME
    r"mkfs\.",                # Format filesystem
    r"dd\s+if=",              # Raw disk write
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;:",  # Fork bomb
    r">\s*/dev/sda",          # Write to block device
    r"chmod\s+777\s+/",       # chmod 777 on root
    r"curl.*\|\s*(ba)?sh",    # curl pipe to shell
    r"wget.*\|\s*(ba)?sh",    # wget pipe to shell
    r"git\s+push\s+--force.*origin\s+(main|master)",  # Force push to main
    r"shutdown",               # System shutdown
    r"reboot",                 # System reboot
    r"sudo\s+rm",             # Sudo rm
    r"sudo\s+dd",             # Sudo dd
]

# Patterns that are always safe
SAFE_PATTERNS = [
    r"^ls\b", r"^dir\b", r"^pwd\b", r"^echo\b",
    r"^cat\b", r"^head\b", r"^tail\b", r"^wc\b",
    r"^grep\b", r"^find\b", r"^which\b", r"^type\b",
    r"^git\s+status\b", r"^git\s+diff\b", r"^git\s+log\b",
    r"^git\s+branch\b", r"^git\s+show\b", r"^git\s+stash\s+list\b",
    r"^python\s+--version\b", r"^python\s+-c\b",
    r"^pip\s+list\b", r"^pip\s+show\b",
    r"^npm\s+list\b", r"^npm\s+view\b",
    r"^cargo\s+check\b", r"^cargo\s+build\b.*--check",
    r"^node\s+--version\b", r"^npm\s+--version\b",
    r"^docker\s+ps\b", r"^docker\s+images\b",
]


@dataclass
class Sandbox:
    """Validates shell commands for safety.

    Attributes:
        blocked_patterns: Regex patterns for commands that are always blocked
        safe_patterns: Regex patterns for commands that are always safe
    """

    blocked_patterns: List[str] = field(default_factory=lambda: DANGEROUS_PATTERNS.copy())
    safe_patterns: List[str] = field(default_factory=lambda: SAFE_PATTERNS.copy())

    def is_blocked(self, command: str) -> bool:
        """Check if a command matches any blocked pattern."""
        cmd_normalized = command.strip()
        for pattern in self.blocked_patterns:
            if re.search(pattern, cmd_normalized, re.IGNORECASE):
                return True
        return False

    def is_safe(self, command: str) -> bool:
        """Check if a command matches any safe pattern."""
        cmd_normalized = command.strip()
        for pattern in self.safe_patterns:
            if re.search(pattern, cmd_normalized, re.IGNORECASE):
                return True
        return False

    def validate(self, command: str) -> tuple[bool, str]:
        """Validate a command.

        Returns:
            Tuple of (is_allowed, reason)
        """
        if self.is_blocked(command):
            return False, "Command matches dangerous pattern and is blocked for safety."

        return True, ""

    def classify(self, command: str) -> str:
        """Classify a command as 'safe', 'blocked', or 'confirm'.

        Returns:
            One of 'safe', 'blocked', 'confirm'
        """
        if self.is_blocked(command):
            return "blocked"
        if self.is_safe(command):
            return "safe"
        return "confirm"

    def add_blocked_pattern(self, pattern: str) -> None:
        """Add a custom blocked pattern."""
        self.blocked_patterns.append(pattern)

    def add_safe_pattern(self, pattern: str) -> None:
        """Add a custom safe pattern."""
        self.safe_patterns.append(pattern)
