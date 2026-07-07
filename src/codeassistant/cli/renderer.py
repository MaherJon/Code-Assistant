"""Rich-based terminal rendering engine for CodeAssistant.

Provides a polished, Claude Code-like visual experience with:
- Streaming markdown output
- Tool execution cards with timing and icons
- Interactive permission prompts
- Progress bars, spinners, and status indicators
- Color-coded messages by role
- Formatted help and config panels
- Syntax-highlighted code blocks and diffs
"""

import shutil
import textwrap
from typing import Optional

from rich.box import Box, ROUNDED
from rich.console import Console
from rich.columns import Columns
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.rule import Rule
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from codeassistant.cli.theme import ThemeConfig, DARK_THEME, get_icon_for_tool


# ─── Constants ───────────────────────────────────────────────────

TERMINAL_WIDTH = shutil.get_terminal_size().columns


# ─── Renderer ────────────────────────────────────────────────────

class Renderer:
    """Handles all terminal output rendering using Rich.

    Provides a comprehensive set of rendering methods for every
    interaction type in the agent loop. All visual styling is
    driven by a ThemeConfig for easy customization.

    Usage:
        renderer = Renderer(theme=load_theme("dark"))
        renderer.welcome(config)
        renderer.user_message("Fix the bug in auth.py")
        renderer.streaming_start()
        renderer.stream_chunk("Let me read the file...")
        renderer.streaming_end()
        renderer.tool_card("read_file", {"path": "src/auth.py"}, duration="120ms")
        renderer.assistant_message("The bug is on line 42...")
    """

    def __init__(self, console: Optional[Console] = None, theme: ThemeConfig = None):
        self.console = console or Console(highlight=False)
        self.theme = theme or DARK_THEME
        self._streaming_live: Optional[Live] = None
        self._streaming_buffer: str = ""

    # ── Welcome & Headers ───────────────────────────────────────

    def welcome(self, config=None) -> None:
        """Display the welcome banner with project and model info.

        Args:
            config: Optional CodeAssistantConfig for model/provider display
        """
        width = min(TERMINAL_WIDTH - 4, 80)

        # Title panel
        title = Text()
        title.append(self.theme.icon_star + " ", style=self.theme.warning)
        title.append("CodeAssistant", style=f"bold {self.theme.primary}")
        title.append("  v0.2.0", style=self.theme.dim)

        subtitle = Text.assemble(
            "AI-Powered Terminal Programming Assistant  ",
            "Type ",
            ("/help", f"bold {self.theme.primary}"),
            " for commands, ",
            ("/exit", f"bold {self.theme.primary}"),
            " to quit",
        )

        self.console.print()
        self.console.print(Panel(
            Text.assemble(title, "\n", subtitle),
            border_style=self.theme.panel_border,
            box=ROUNDED,
            width=width,
        ))

        # Config summary table
        if config:
            self.console.print()
            info_table = Table(show_header=False, box=None, padding=(0, 4, 0, 0))
            info_table.add_column(style=self.theme.dim, width=14)
            info_table.add_column(style="bold")
            info_table.add_column(style=self.theme.dim, width=14)
            info_table.add_column(style="bold")
            info_table.add_row(
                f"{self.theme.icon_gear} Model", f"{config.provider}/{config.model}",
                f"{self.theme.icon_clock} Permission", config.permission_mode,
            )
            self.console.print(info_table)

        self.console.print(Rule(style=self.theme.dim))

    # ── Message Display ──────────────────────────────────────────

    def user_message(self, text: str) -> None:
        """Display user's input with visual styling.

        Args:
            text: The user's query text
        """
        prefix = Text()
        prefix.append("▸ ", style=f"bold {self.theme.user}")
        prefix.append("You", style=f"bold {self.theme.user}")
        self.console.print(prefix)

        # Wrap long messages
        wrapped = textwrap.fill(text, width=TERMINAL_WIDTH - 4)
        self.console.print(f"  [{self.theme.user}]{wrapped}[/]")
        self.console.print()

    def assistant_header(self, model: str = "") -> None:
        """Show a subtle model badge before the assistant response.

        Args:
            model: The model name (e.g., "openai/gpt-4o")
        """
        if model:
            short_model = model.split("/")[-1] if "/" in model else model
            self.console.print(f"  [{self.theme.dim}]{self.theme.icon_star} {short_model}[/]")

    def assistant_message(self, text: str) -> None:
        """Render the assistant's response as markdown.

        Args:
            text: Markdown-formatted response text
        """
        if not text.strip():
            return
        md = Markdown(
            text,
            code_theme="monokai",
            inline_code_theme="monokai",
        )
        self.console.print(md)
        self.console.print()

    # ── Streaming Output ─────────────────────────────────────────

    def streaming_start(self) -> None:
        """Begin a live-updating streaming text area."""
        self._streaming_buffer = ""
        self._streaming_live = Live(
            Markdown(""),
            console=self.console,
            refresh_per_second=15,
            transient=False,
            auto_refresh=True,
        )
        self._streaming_live.__enter__()

    def streaming_chunk(self, chunk: str) -> None:
        """Append a text chunk to the streaming output.

        Args:
            chunk: Text delta from the LLM stream
        """
        if self._streaming_live is None:
            # Streaming not started; just print directly
            self.console.print(chunk, end="")
            return

        self._streaming_buffer += chunk
        try:
            md = Markdown(self._streaming_buffer, code_theme="monokai")
            self._streaming_live.update(md)
        except Exception:
            # If markdown parsing fails, show raw text
            self._streaming_live.update(Text(self._streaming_buffer))

    def streaming_end(self) -> None:
        """End the streaming output and finalize the display."""
        if self._streaming_live:
            self._streaming_live.__exit__(None, None, None)
            self._streaming_live = None
            self._streaming_buffer = ""

    def streaming_raw(self, text: str) -> None:
        """Write text directly (for use outside Live context).

        Args:
            text: Text to output immediately
        """
        self.console.print(text, end="")

    # ── Tool Execution Cards ─────────────────────────────────────

    _tool_start_times: dict = {}

    def tool_card_start(self, tool_name: str, params: dict, tool=None) -> None:
        """Display a tool execution start card.

        Shows as a bordered panel with spinner icon and parameter summary.

        Args:
            tool_name: Name of the tool
            params: Tool parameters (shown in summary)
            tool: Optional Tool instance for rich parameter rendering
        """
        import time
        self._tool_start_times[tool_name] = time.time()

        icon = get_icon_for_tool(tool_name, self.theme)
        summary = self._format_tool_params(tool_name, params)

        content = Text()
        content.append(f" {icon}  ", style=self.theme.tool_name)
        content.append(f"{tool_name}", style=f"bold {self.theme.tool_name}")
        if summary:
            content.append(f"\n     {summary}", style=self.theme.dim)

        self.console.print(Panel(
            content,
            border_style=self.theme.warning,
            box=ROUNDED,
            padding=(0, 2),
        ))

    def tool_card_end(self, tool_name: str, success: bool, result_text: str = "") -> str:
        """Display a tool execution completion card with timing.

        Args:
            tool_name: Name of the tool
            success: Whether execution succeeded
            result_text: Result summary (truncated if long)

        Returns:
            Duration string (e.g., "120ms")
        """
        import time
        duration_ms = 0
        if tool_name in self._tool_start_times:
            duration_ms = int((time.time() - self._tool_start_times[tool_name]) * 1000)
            del self._tool_start_times[tool_name]

        if duration_ms > 0:
            duration_str = f"{duration_ms}ms" if duration_ms < 1000 else f"{duration_ms / 1000:.1f}s"
        else:
            duration_str = ""

        icon = get_icon_for_tool(tool_name, self.theme)
        status_icon = self.theme.icon_success if success else self.theme.icon_error
        color = self.theme.success if success else self.theme.error

        content = Text()
        content.append(f" {status_icon} ", style=color)
        content.append(f"{tool_name}", style=f"bold {color}")
        if duration_str:
            content.append(f"  [{self.theme.muted}]{duration_str}[/]")
        if result_text:
            truncated = result_text[:200].replace("\n", " ")
            if len(result_text) > 200:
                truncated += "..."
            content.append(f"\n     [{self.theme.dim}]{truncated}[/]")

        self.console.print(Panel(
            content,
            border_style=color,
            box=ROUNDED,
            padding=(0, 2),
        ))
        return duration_str

    def tool_error(self, tool_name: str, error: str) -> None:
        """Display a tool error card.

        Args:
            tool_name: Name of the tool
            error: Error message
        """
        content = Text()
        content.append(f" {self.theme.icon_error} ", style=self.theme.error)
        content.append(f"{tool_name}", style=f"bold {self.theme.error}")
        content.append(f"\n     [{self.theme.error}]{error[:300]}[/]")

        self.console.print(Panel(
            content,
            border_style=self.theme.error,
            box=ROUNDED,
            padding=(0, 2),
        ))

    def _format_tool_params(self, tool_name: str, params: dict) -> str:
        """Format tool parameters for display.

        Args:
            tool_name: The tool name
            params: Parameter dictionary

        Returns:
            Formatted string showing key parameters
        """
        if not params:
            return ""

        # Tool-specific formatting
        if tool_name in ("read_file", "write_file", "edit_file"):
            path = params.get("path", params.get("file_path", ""))
            return path if path else str(params)

        if tool_name == "run_shell":
            cmd = params.get("command", "")
            return cmd[:100] if cmd else str(params)

        if tool_name == "search_code":
            pattern = params.get("pattern", "")
            return f"pattern: {pattern[:80]}" if pattern else str(params)

        if tool_name == "glob_files":
            pattern = params.get("pattern", "")
            return f"pattern: {pattern[:80]}" if pattern else str(params)

        if tool_name.startswith("git_"):
            return " ".join(f"{k}={v}" for k, v in list(params.items())[:2])

        # Generic: show first significant param
        skip_keys = {"working_dir", "cwd", "timeout", "encoding"}
        show_params = {k: v for k, v in params.items() if k not in skip_keys}
        if show_params:
            first_key = list(show_params.keys())[0]
            val = str(show_params[first_key])
            return f"{first_key}: {val[:80]}"

        return ""

    # ── Permission Prompts ───────────────────────────────────────

    def confirm_panel(self, tool_name: str, description: str) -> None:
        """Display a permission confirmation prompt.

        Args:
            tool_name: Name of the tool needing confirmation
            description: Human-readable description of the action
        """
        self.console.print()
        width = min(TERMINAL_WIDTH - 4, 70)

        content = Text()
        # Header
        content.append(" ═══ ", style=self.theme.dim)
        content.append("⚠", style=f"bold {self.theme.warning}")
        content.append(" Confirm Action ", style=f"bold {self.theme.warning}")
        content.append("═" * (width - 22), style=self.theme.dim)
        content.append("\n\n")

        # Tool name
        content.append("   Tool:   ", style=f"bold {self.theme.dim}")
        content.append(f"{tool_name}\n", style=f"bold {self.theme.primary}")

        # Action description
        content.append("   Action: ", style=f"bold {self.theme.dim}")
        # Wrap description
        wrapped_desc = textwrap.fill(description, width=width - 14)
        content.append(f"{wrapped_desc}\n\n", style="white")

        # Separator
        content.append("   " + "─" * (width - 6) + "\n\n", style=self.theme.muted)

        # Options - prominent and color-coded
        content.append("   ", style="")
        # Y - Approve (green, default)
        content.append("[Y]", style=f"bold {self.theme.success} reverse")
        content.append(" Approve     ", style=f"bold {self.theme.success}")
        # N - Deny (red)
        content.append("[N]", style=f"bold {self.theme.error} reverse")
        content.append(" Deny       ", style=f"bold {self.theme.error}")
        # A - Approve All (yellow)
        content.append("[A]", style=f"bold {self.theme.warning} reverse")
        content.append(" Approve All", style=f"bold {self.theme.warning}")
        content.append("\n\n")
        # Keyboard hints
        content.append("   ", style="")
        content.append("← →", style=f"bold {self.theme.primary}")
        content.append(" to choose", style=self.theme.muted)
        content.append("  ·  ", style=self.theme.muted)
        content.append("Enter", style=f"bold {self.theme.primary}")
        content.append(" to confirm", style=self.theme.muted)
        content.append("  ·  ", style=self.theme.muted)
        content.append("Y/N/A", style=f"bold {self.theme.primary}")
        content.append(" quick-select", style=self.theme.muted)
        content.append("  ·  ", style=self.theme.muted)
        content.append("Ctrl+C", style=f"bold {self.theme.primary}")
        content.append(" to cancel", style=self.theme.muted)

        self.console.print(Panel(
            content,
            border_style=self.theme.warning,
            box=ROUNDED,
            padding=(1, 2),
        ))

    # ── Progress & Spinner ───────────────────────────────────────

    def thinking_start(self, message: str = "Thinking") -> None:
        """Show a thinking indicator.

        Uses a Live context with a spinner.

        Args:
            message: Status message to show beside spinner
        """
        spinner = Spinner(
            name="dots",
            text=f"[{self.theme.thinking}]{message}...[/]",
            style=self.theme.thinking,
        )
        self.console.print(spinner)

    def progress_bar(self, description: str = "Processing", total: float = 100) -> Progress:
        """Create and return a progress bar.

        The caller should use it as a context manager and update it.

        Args:
            description: Label for the progress bar
            total: Maximum value

        Returns:
            Rich Progress instance (use as context manager)

        Usage:
            with renderer.progress_bar("Indexing files", len(files)) as progress:
                task = progress.add_task("indexing", total=len(files))
                for f in files:
                    process(f)
                    progress.update(task, advance=1)
        """
        return Progress(
            SpinnerColumn(),
            TextColumn(f"[{self.theme.primary}]{{task.description}}"),
            BarColumn(bar_width=40),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=self.console,
        )

    # ── Help & Config ────────────────────────────────────────────

    def help_panel(self, commands: dict) -> None:
        """Display a formatted help panel with categorized commands.

        Args:
            commands: Dict of command_name -> description
        """
        self.console.print(Rule(f"[{self.theme.heading}]Commands[/]", style=self.theme.dim))

        table = Table(
            show_header=False,
            box=None,
            padding=(0, 2, 0, 4),
            expand=False,
        )
        table.add_column(style=f"bold {self.theme.primary}", width=22)
        table.add_column(style=self.theme.dim)

        for cmd_name, cmd_desc in commands.items():
            table.add_row(cmd_name, cmd_desc)

        self.console.print(table)
        self.console.print()

        # Tips section
        tips = Text()
        tips.append(f" {self.theme.icon_info} ", style=self.theme.primary)
        tips.append("Tips:", style=f"bold {self.theme.heading}")
        tips.append("\n   • Type your question directly for AI assistance")
        tips.append("\n   • Use ")
        tips.append("Ctrl+O", style=f"bold {self.theme.primary}")
        tips.append(" to toggle multi-line mode ")
        tips.append("[M]", style=self.theme.warning)
        tips.append("\n   • Use ")
        tips.append("Ctrl+R", style=f"bold {self.theme.primary}")
        tips.append(" to search command history")
        tips.append("\n   • Use ")
        tips.append("Ctrl+C", style=f"bold {self.theme.primary}")
        tips.append(" to cancel the current action")

        self.console.print(Panel(tips, border_style=self.theme.dim, box=ROUNDED))
        self.console.print()

    def config_panel(self, config) -> None:
        """Display the current configuration in a formatted panel.

        Args:
            config: CodeAssistantConfig instance
        """
        self.console.print(Rule(f"[{self.theme.heading}]Configuration[/]", style=self.theme.dim))

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style=f"bold {self.theme.dim}", width=16)
        table.add_column(style="white")
        table.add_column(style=f"bold {self.theme.dim}", width=16)
        table.add_column(style="white")

        table.add_row(
            "Provider", f"[{self.theme.primary}]{config.provider}[/]",
            "Model", f"[{self.theme.primary}]{config.model}[/]",
        )
        table.add_row(
            "API Base", config.api_base or "(default)",
            "API Key", "[green]set[/]" if config.api_key else "[red]not set[/]",
        )
        table.add_row(
            "Permission Mode", f"[{self.theme.warning}]{config.permission_mode}[/]",
            "Data Dir", config.data_dir,
        )
        table.add_row(
            "Max Iterations", str(config.max_iterations),
            "Max Tokens", str(config.max_tokens),
        )

        self.console.print(table)
        self.console.print()

    # ── Simple Messages ───────────────────────────────────────────

    def error(self, message: str) -> None:
        """Display an error message."""
        self.console.print(f"  {self.theme.icon_error} [{self.theme.error}]Error:[/] {message}")

    def warning(self, message: str) -> None:
        """Display a warning message."""
        self.console.print(f"  {self.theme.icon_warning} [{self.theme.warning}]Warning:[/] {message}")

    def success(self, message: str) -> None:
        """Display a success message."""
        self.console.print(f"  {self.theme.icon_success} [{self.theme.success}]{message}[/]")

    def info(self, message: str) -> None:
        """Display an informational message."""
        self.console.print(f"  [{self.theme.dim}]{message}[/]")

    # ── Content Rendering ─────────────────────────────────────────

    def render_markdown(self, text: str) -> None:
        """Render markdown text with syntax highlighting.

        Args:
            text: Markdown-formatted text
        """
        md = Markdown(text, code_theme="monokai")
        self.console.print(md)

    def render_code(self, code: str, language: str = "python") -> None:
        """Render syntax-highlighted code block.

        Args:
            code: Source code string
            language: Programming language for syntax highlighting
        """
        syntax = Syntax(
            code, language,
            theme="monokai",
            line_numbers=True,
            word_wrap=True,
        )
        self.console.print(Panel(
            syntax,
            border_style=self.theme.code_border,
            box=ROUNDED,
            padding=(0, 1),
        ))

    def render_diff(self, old_text: str, new_text: str, title: str = "Diff") -> None:
        """Render a colorized unified diff.

        Args:
            old_text: Original text
            new_text: Modified text
            title: Panel title
        """
        import difflib
        diff_lines = list(difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile="a/before",
            tofile="b/after",
        ))
        diff_text = "".join(diff_lines)

        if not diff_text:
            self.console.print(f"  [{self.theme.dim}](no changes)[/]")
            return

        syntax = Syntax(diff_text, "diff", theme="monokai", line_numbers=False)
        self.console.print(Panel(
            syntax,
            title=title,
            title_align="left",
            border_style=self.theme.diff_border,
            box=ROUNDED,
            padding=(0, 1),
        ))

    def render_table(self, headers: list, rows: list, title: str = "") -> None:
        """Render a formatted table.

        Args:
            headers: List of column header strings
            rows: List of tuples (one per row)
            title: Optional table title
        """
        table = Table(
            title=title,
            title_style=f"bold {self.theme.heading}",
            border_style=self.theme.dim,
            box=ROUNDED,
        )
        for h in headers:
            table.add_column(h, style=f"bold {self.theme.primary}")
        for row in rows:
            table.add_row(*[str(c) for c in row])
        self.console.print(table)

    def render_tree(self, data: dict, title: str = "") -> None:
        """Render hierarchical data as a tree.

        Args:
            data: Dict where keys are parent nodes and values are lists of children
            title: Root node label
        """
        tree = Tree(f"[bold {self.theme.primary}]{title}[/]")
        for key, children in data.items():
            branch = tree.add(f"[{self.theme.primary}]{key}[/]")
            if isinstance(children, list):
                for child in children:
                    branch.add(str(child))
            elif isinstance(children, dict):
                for ck, cv in children.items():
                    branch.add(f"[{self.theme.dim}]{ck}:[/] {cv}")
        self.console.print(tree)

    # ── Token Usage ───────────────────────────────────────────────

    def usage_stats(self, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        """Display token usage statistics after a response.

        Args:
            prompt_tokens: Tokens used in the prompt
            completion_tokens: Tokens used in the completion
        """
        if prompt_tokens == 0 and completion_tokens == 0:
            return
        total = prompt_tokens + completion_tokens
        text = Text()
        text.append(f"  {self.theme.icon_info} ", style=self.theme.dim)
        text.append(f"Tokens: ", style=self.theme.dim)
        text.append(f"{total:,}", style="bold")
        text.append(f" (prompt: {prompt_tokens:,}, completion: {completion_tokens:,})", style=self.theme.muted)
        self.console.print(text)

    # ── Rules & Separators ───────────────────────────────────────

    def rule(self, title: str = "") -> None:
        """Display a horizontal rule with optional title.

        Args:
            title: Optional section title
        """
        if title:
            self.console.print(Rule(title, style=self.theme.dim))
        else:
            self.console.print(Rule(style=self.theme.dim))

    def separator(self) -> None:
        """A subtle visual separator between sections."""
        self.console.print(f"[{self.theme.muted}]" + "─" * min(40, TERMINAL_WIDTH - 4) + "[/]")

    def blank_line(self) -> None:
        """Print a blank line for spacing."""
        self.console.print()
