"""Rich-based terminal output rendering."""

from typing import Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.live import Live
from rich.spinner import Spinner
from rich.progress import Progress, SpinnerColumn, TextColumn


class Renderer:
    """Handles all terminal output rendering using Rich."""

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()

    def welcome(self) -> None:
        """Display welcome banner."""
        self.console.print()
        self.console.print(
            Panel.fit(
                "[bold cyan]MAHE[/] - AI-Powered Terminal Programming Assistant\n"
                "[dim]Type /help for commands, /exit to quit[/]",
                border_style="cyan",
            )
        )
        self.console.print()

    def prompt(self) -> str:
        """Return the prompt string."""
        return "[bold cyan]mahe>[/] "

    def render_markdown(self, text: str) -> None:
        """Render markdown text with syntax highlighting."""
        md = Markdown(text)
        self.console.print(md)

    def render_code(self, code: str, language: str = "python") -> None:
        """Render syntax-highlighted code block."""
        syntax = Syntax(code, language, theme="monokai", line_numbers=True)
        self.console.print(syntax)

    def render_diff(self, old_text: str, new_text: str, title: str = "Diff") -> None:
        """Render a unified diff."""
        import difflib
        diff = difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile="before",
            tofile="after",
        )
        diff_text = "".join(diff)
        if diff_text:
            syntax = Syntax(diff_text, "diff", theme="monokai")
            self.console.print(Panel(syntax, title=title, border_style="yellow"))
        else:
            self.console.print("[dim](no changes)[/]")

    def tool_status(self, tool_name: str, status: str, detail: str = "") -> None:
        """Display tool execution status.

        Args:
            tool_name: Name of the tool being executed
            status: One of 'running', 'success', 'error', 'blocked'
            detail: Additional detail (file path, error message, etc.)
        """
        icons = {
            "running": "[yellow]⏳[/]",
            "success": "[green]✓[/]",
            "error": "[red]✗[/]",
            "blocked": "[red]🚫[/]",
        }
        icon = icons.get(status, "  ")
        label = {
            "running": "Running",
            "success": "Done",
            "error": "Error",
            "blocked": "Blocked",
        }.get(status, status)

        if detail:
            self.console.print(f"  {icon} [bold]{label}[/] {tool_name}: [dim]{detail}[/]")
        else:
            self.console.print(f"  {icon} [bold]{label}[/] {tool_name}")

    def confirmation(self, tool_name: str, description: str) -> None:
        """Display a confirmation prompt for tool execution."""
        self.console.print()
        self.console.print(
            Panel(
                f"[bold yellow]⚠ Confirm Action[/]\n"
                f"[bold]{tool_name}[/]\n"
                f"[dim]{description}[/]",
                border_style="yellow",
            )
        )

    def error(self, message: str) -> None:
        """Display an error message."""
        self.console.print(f"[red]Error:[/] {message}")

    def warning(self, message: str) -> None:
        """Display a warning message."""
        self.console.print(f"[yellow]Warning:[/] {message}")

    def info(self, message: str) -> None:
        """Display an informational message."""
        self.console.print(f"[dim]{message}[/]")

    def success(self, message: str) -> None:
        """Display a success message."""
        self.console.print(f"[green]✓[/] {message}")

    def stream(self, text: str) -> None:
        """Write text directly (for streaming output)."""
        self.console.print(text, end="")

    def rule(self, title: str = "") -> None:
        """Display a horizontal rule."""
        self.console.rule(title)
