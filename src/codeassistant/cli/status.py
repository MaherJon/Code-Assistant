"""Live status display for the CodeAssistant terminal interface.

Manages the "what's happening now" area using Rich's Live context manager,
showing thinking spinners, tool execution progress, and transient messages.
"""

import time
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from codeassistant.cli.theme import ThemeConfig, DARK_THEME


class StatusDisplay:
    """Manages a live-updating status area in the terminal.

    Wraps Rich's `Live` context manager to show transient status info:
    - Thinking spinner during LLM generation
    - Tool execution in-progress cards
    - Progress messages

    Usage:
        status = StatusDisplay(console)
        with status:
            status.thinking("Analyzing codebase...")
            # ... work ...
            status.tool_running("read_file", "src/auth.py")
            # ... work ...
    """

    def __init__(self, console: Console, theme: ThemeConfig = None):
        self.console = console
        self.theme = theme or DARK_THEME
        self._live: Optional[Live] = None
        self._content: str = ""
        self._tool_timers: dict = {}  # tool_name -> start_time

    def __enter__(self):
        """Start the live display context."""
        self._live = Live(
            self._render(""),
            console=self.console,
            refresh_per_second=12,
            transient=False,
            auto_refresh=True,
        )
        self._live.__enter__()
        return self

    def __exit__(self, *args):
        """Stop the live display context."""
        if self._live:
            self._live.__exit__(*args)
            self._live = None

    def _render(self, content: str) -> Panel:
        """Render the current content as a styled panel."""
        if not content.strip():
            return Panel("", border_style=self.theme.dim, padding=(0, 2))
        return Panel(
            content,
            border_style=self.theme.dim,
            padding=(0, 2),
        )

    def update(self, content: str) -> None:
        """Update the live display content.

        Args:
            content: Rich-markup string to display
        """
        self._content = content
        if self._live:
            self._live.update(self._render(content))

    def clear(self) -> None:
        """Clear the status display."""
        self._content = ""
        if self._live:
            self._live.update(self._render(""))

    def thinking(self, message: str = "Thinking") -> None:
        """Show a thinking spinner with a message.

        Args:
            message: Context message (e.g., "Analyzing project structure...")
        """
        spinner = Spinner(
            name="dots",
            text=f"[{self.theme.thinking}]{message}...[/]",
            style=self.theme.thinking,
        )
        text = Text()
        text.append(f"  {self.theme.icon_thinking} ", style=self.theme.thinking)
        text.append(message, style=self.theme.thinking)
        text.append("...", style=self.theme.dim)
        self._content = text
        if self._live:
            self._live.update(Panel(text, border_style=self.theme.dim, padding=(0, 2)))

    def tool_running(self, tool_name: str, detail: str = "") -> None:
        """Show a tool as currently executing.

        Args:
            tool_name: Name of the tool being run
            detail: Parameters or description
        """
        self._tool_timers[tool_name] = time.time()
        text = Text()
        text.append(f"  {self.theme.icon_running} ", style=self.theme.warning)
        text.append(f"{tool_name}", style=f"bold {self.theme.tool_name}")
        if detail:
            text.append(f"  {detail}", style=self.theme.dim)
        self._content = text
        if self._live:
            self._live.update(Panel(text, border_style=self.theme.warning, padding=(0, 2)))

    def tool_done(self, tool_name: str, success: bool = True, detail: str = "") -> str:
        """Show a tool as completed and return the duration string.

        Args:
            tool_name: Name of the completed tool
            success: Whether the tool succeeded
            detail: Result summary

        Returns:
            Duration string like "120ms"
        """
        duration_ms = 0
        if tool_name in self._tool_timers:
            duration_ms = int((time.time() - self._tool_timers[tool_name]) * 1000)
            del self._tool_timers[tool_name]

        if duration_ms > 0:
            duration_str = f"({duration_ms}ms)" if duration_ms < 1000 else f"({duration_ms / 1000:.1f}s)"
        else:
            duration_str = ""

        icon = self.theme.icon_success if success else self.theme.icon_error
        color = self.theme.success if success else self.theme.error

        text = Text()
        text.append(f"  {icon} ", style=color)
        text.append(f"{tool_name}", style=f"bold {color}")
        if detail:
            text.append(f"  {detail}", style=self.theme.dim)
        if duration_str:
            text.append(f"  [{self.theme.dim}]{duration_str}[/]")

        self._content = text
        if self._live:
            self._live.update(Panel(
                text,
                border_style=color,
                padding=(0, 2),
            ))

        return duration_str


class NoOpStatus:
    """A no-op status display for non-interactive modes (--ask, loop scheduler)."""

    def __enter__(self): return self
    def __exit__(self, *args): pass
    def update(self, content: str): pass
    def clear(self): pass
    def thinking(self, message: str = ""): pass
    def tool_running(self, tool_name: str, detail: str = ""): pass
    def tool_done(self, tool_name: str, success: bool = True, detail: str = "") -> str: return ""
