"""Interactive REPL loop for CodeAssistant — Claude Code-like terminal experience.

Features:
- Real-time streaming markdown output during LLM generation
- Tool execution cards with spinners, icons, and timing
- Interactive permission prompts (Y/N/A inline)
- Enhanced autocomplete (slash commands, model names, file paths)
- Multi-line input mode (Ctrl+O to toggle)
- Command history with search (Ctrl+R)
- User input echo with visual separation
- Graceful Ctrl+C cancellation of agent actions
- Status bar with model/cwd info (Ctrl+T)
"""

import asyncio
import os
import time
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import (
    NestedCompleter,
    PathCompleter,
    WordCompleter,
    merge_completers,
)
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style

from codeassistant.cli.renderer import Renderer
from codeassistant.cli.theme import load_theme, get_icon_for_tool
from codeassistant.core.config import CodeAssistantConfig


# ─── Multi-line Input Helpers ────────────────────────────────────

def _create_multiline_bindings() -> KeyBindings:
    """Create key bindings for multi-line input mode.

    In this mode, Enter inserts a newline, and Alt+Enter submits.
    """
    kb = KeyBindings()

    @kb.add(Keys.Enter)
    def _(event):
        """Insert a newline instead of submitting."""
        event.current_buffer.insert_text("\n")

    @kb.add(Keys.Escape, Keys.ControlM)
    def _(event):
        """Alt+Enter: submit the buffer."""
        event.current_buffer.validate_and_handle()

    return kb


def _create_singleline_bindings() -> KeyBindings:
    """Create key bindings for single-line input mode.

    Standard behavior: Enter submits.
    """
    kb = KeyBindings()

    @kb.add(Keys.Escape, Keys.ControlM)
    def _(event):
        """Alt+Enter: insert a newline (for quick multi-line in single-line mode)."""
        event.current_buffer.insert_text("\n")

    return kb


# ─── Prompt Style ────────────────────────────────────────────────

PROMPT_STYLE = Style.from_dict({
    "prompt": "bold cyan",
    "separator": "dim",
    "multiline": "bold yellow",
    "info": "dim",
})


# ─── Completer ───────────────────────────────────────────────────

def _build_completer() -> NestedCompleter:
    """Build the enhanced auto-completer.

    Supports:
    - Slash commands with sub-completions
    - Model names for /model
    - Provider names for /provider
    - File paths via PathCompleter (merged)
    """
    slash_commands = {
        "/help": None,
        "/clear": None,
        "/config": None,
        "/exit": None,
        "/quit": None,
        "/q": None,
        "/model": {
            "gpt-4o": None,
            "gpt-4o-mini": None,
            "gpt-3.5-turbo": None,
            "o1": None,
            "o1-mini": None,
            "claude-sonnet-5": None,
            "claude-opus-4-8": None,
            "claude-haiku-4-5": None,
            "deepseek-chat": None,
            "deepseek-reasoner": None,
            "qwen-max": None,
            "qwen-plus": None,
            "ollama/llama3": None,
            "ollama/codellama": None,
        },
        "/provider": {
            "openai": None,
            "anthropic": None,
            "deepseek": None,
            "qwen": None,
            "ollama": None,
            "together_ai": None,
            "replicate": None,
        },
        "/mode": None,
        "/loop": {
            "start": None,
            "stop": None,
            "list": None,
        },
    }
    return NestedCompleter.from_nested_dict(slash_commands)


# ─── REPL ────────────────────────────────────────────────────────

class REPL:
    """Interactive Read-Eval-Print Loop for CodeAssistant.

    Provides a Claude Code-like terminal experience with:
    - Streaming markdown output
    - Tool execution visualization
    - Interactive permission prompts
    - Multi-line input support
    - Enhanced autocomplete
    - Command history search

    Usage:
        repl = REPL(config, working_dir)
        await repl.run()
    """

    COMMANDS = {
        "/help": "Show this help message",
        "/clear": "Clear conversation history",
        "/config": "Show current configuration",
        "/model <name>": "Switch the AI model (e.g., /model gpt-4o)",
        "/provider <name>": "Switch the model provider",
        "/mode": "Toggle permission mode (prompt ↔ auto_safe)",
        "/loop start <int> <prompt>": "Start a scheduled task",
        "/loop stop <id>": "Stop a scheduled task",
        "/loop list": "List active scheduled tasks",
        "/exit": "Exit CodeAssistant (/quit, /q, Ctrl+D)",
    }

    def __init__(self, config: CodeAssistantConfig, working_dir: str):
        self.config = config
        self.working_dir = os.path.abspath(working_dir)
        self.renderer = Renderer(theme=load_theme("dark"))
        self._engine = None
        self._running = False
        self._loop_scheduler = None
        self._multiline_mode = False
        self._current_agent_task: Optional[asyncio.Task] = None
        self._cancel_requested = False

        # Setup prompt history directory
        history_dir = os.path.expanduser("~/.codeassistant")
        os.makedirs(history_dir, exist_ok=True)
        history_file = os.path.join(history_dir, "history")

        # Build completions
        completer = _build_completer()

        # Initial key bindings (single-line mode)
        self._singleline_bindings = _create_singleline_bindings()
        self._multiline_bindings = _create_multiline_bindings()

        # Create prompt session
        self.session = PromptSession(
            history=FileHistory(history_file),
            completer=completer,
            style=PROMPT_STYLE,
            key_bindings=self._singleline_bindings,
            auto_suggest=AutoSuggestFromHistory(),
            multiline=False,
            wrap_lines=True,
        )

    # ── Lazy Properties ──────────────────────────────────────────

    @property
    def engine(self):
        """Lazy-init: the Engine orchestrator."""
        if self._engine is None:
            from codeassistant.core.engine import Engine
            self._engine = Engine(self.config, self.working_dir)
        return self._engine

    @property
    def loop_scheduler(self):
        """Lazy-init: the loop scheduler."""
        if self._loop_scheduler is None:
            from codeassistant.core.loop import LoopScheduler
            self._loop_scheduler = LoopScheduler(
                query_fn=self._scheduled_query,
                max_loops=5,
            )
        return self._loop_scheduler

    async def _scheduled_query(self, prompt: str) -> str:
        """Execute a query for the loop scheduler (no streaming, no UI)."""
        try:
            return await self.engine.process_query(prompt)
        except Exception as e:
            return f"Error: {e}"

    # ── Prompt Construction ──────────────────────────────────────

    def _get_prompt_tokens(self):
        """Build the prompt_toolkit prompt tokens with multi-line indicator."""
        tokens = [("class:prompt", "\n"), ("class:prompt", "codeassistant")]
        if self._multiline_mode:
            tokens.append(("class:multiline", " [M]"))
        tokens.append(("class:separator", "> "))
        return tokens

    # ── Main Loop ────────────────────────────────────────────────

    async def run(self) -> None:
        """Main REPL loop — entry point for interactive mode."""
        self._running = True
        self.renderer.welcome(self.config)
        self._check_api_key()

        while self._running:
            try:
                user_input = await self.session.prompt_async(
                    self._get_prompt_tokens(),
                )
            except KeyboardInterrupt:
                # Ctrl+C during input: if agent is running, cancel it
                if self._current_agent_task and not self._current_agent_task.done():
                    self._cancel_requested = True
                    self.renderer.info("[dim]Cancelling current operation... Press Ctrl+C again to force[/]")
                else:
                    self.renderer.info("Interrupted. Press /exit or Ctrl+D to quit.")
                continue
            except EOFError:
                # Ctrl+D: exit
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            # Slash commands
            if user_input.startswith("/"):
                self._handle_command(user_input)
                continue

            # Process as a natural language query
            await self._process_query(user_input)

        self.renderer.info("Goodbye!")

    # ── Query Processing ─────────────────────────────────────────

    async def _process_query(self, query: str) -> None:
        """Process a user query with full callback wiring.

        Wires all four engine callbacks for a real-time,
        Claude Code-like interactive experience.

        Args:
            query: User's natural language query
        """
        # Echo user input
        self.renderer.user_message(query)

        # Track tool results during this turn
        tool_results: list = []
        stream_started = False

        # ── Callback: Streaming text ──────────────────────────
        def _on_stream(chunk: str):
            nonlocal stream_started
            if not stream_started:
                stream_started = True
                self.renderer.streaming_start()
            self.renderer.streaming_chunk(chunk)

        # ── Callback: Tool execution started ──────────────────
        def _on_tool_start(tool, params: dict):
            nonlocal stream_started
            # End the current thinking stream so the next iteration
            # starts fresh — prevents text stacking across tool calls
            if stream_started:
                self.renderer.streaming_end()
                stream_started = False
            self.renderer.tool_card_start(tool.name, params, tool)

        # ── Callback: Tool execution completed ────────────────
        def _on_tool_result(tool, params: dict, result):
            duration = self.renderer.tool_card_end(
                tool.name,
                result.success,
                result.output if result.success else result.error,
            )
            tool_results.append({
                "tool": tool.name,
                "success": result.success,
                "duration": duration,
            })

        # ── Callback: Permission confirmation ─────────────────
        async def _on_confirm(tool, params: dict) -> bool:
            description = tool.render_input(**params)
            self.renderer.confirm_panel(tool.name, description)

            # Arrow-key navigable confirmation (Claude Code style)
            OPTIONS = [
                ("Y", "Approve", "ansigreen"),
                ("N", "Deny", "ansired"),
                ("A", "Approve All", "ansiyellow"),
            ]
            selection = {"idx": 0}  # mutable so toolbar sees updates

            confirm_bindings = KeyBindings()

            @confirm_bindings.add("left")
            def _(event):
                """Left arrow: move selection left."""
                selection["idx"] = (selection["idx"] - 1) % len(OPTIONS)

            @confirm_bindings.add("right")
            def _(event):
                """Right arrow: move selection right."""
                selection["idx"] = (selection["idx"] + 1) % len(OPTIONS)

            @confirm_bindings.add("y")
            @confirm_bindings.add("Y")
            def _(event):
                """Press Y: approve immediately."""
                event.current_buffer.insert_text("y")
                event.current_buffer.validate_and_handle()

            @confirm_bindings.add("n")
            @confirm_bindings.add("N")
            def _(event):
                """Press N: deny immediately."""
                event.current_buffer.insert_text("n")
                event.current_buffer.validate_and_handle()

            @confirm_bindings.add("a")
            @confirm_bindings.add("A")
            def _(event):
                """Press A: approve all immediately."""
                event.current_buffer.insert_text("a")
                event.current_buffer.validate_and_handle()

            @confirm_bindings.add("enter")
            def _(event):
                """Enter: confirm currently selected option."""
                labels = ["y", "n", "a"]
                event.current_buffer.insert_text(labels[selection["idx"]])
                event.current_buffer.validate_and_handle()

            @confirm_bindings.add("c-c")
            def _(event):
                """Ctrl+C: cancel / deny."""
                event.current_buffer.insert_text("n")
                event.current_buffer.validate_and_handle()

            # Dynamic bottom toolbar using prompt_toolkit styles
            # (NOT Rich markup — prompt_toolkit needs its own style tuples)
            def _confirm_toolbar():
                parts = []
                for i, (key, label, _color) in enumerate(OPTIONS):
                    if i == selection["idx"]:
                        # Selected: reverse-video highlight for clear visibility
                        parts.append(("class:confirm.selected", f" [{key}] {label} "))
                    else:
                        # Not selected: dimmed
                        parts.append(("class:confirm.dimmed", f"  {key}   {label}  "))
                    if i < len(OPTIONS) - 1:
                        parts.append(("", "  "))
                parts.append(("", "    "))
                parts.append(("class:confirm.hint", "← → to choose  ·  Enter to confirm  ·  Y/N/A quick-select"))
                return FormattedText(parts)

            # Style for the confirmation prompt toolbar
            confirm_style = Style.from_dict({
                "confirm.selected": "bold reverse ansigreen",
                "confirm.dimmed": "ansibrightblack",
                "confirm.hint": "italic ansibrightblack",
            })

            # Use an isolated PromptSession so the bottom_toolbar from
            # this confirm prompt does not leak into the main REPL prompt.
            confirm_session = PromptSession(
                style=confirm_style,
                key_bindings=confirm_bindings,
            )
            try:
                answer = await confirm_session.prompt_async(
                    [("class:info", "")],
                    bottom_toolbar=_confirm_toolbar,
                )
                answer = answer.strip().lower()
                if answer == "a":
                    # "Approve all" for this session: toggle to auto_safe
                    self.config.permission_mode = "auto_safe"
                    if self._engine:
                        self._engine.update_config(self.config)
                    self.renderer.success(
                        "All future operations will be auto-approved this session."
                    )
                    return True
                if answer == "n" or answer == "no":
                    return False
                # Default: yes
                return True
            except (KeyboardInterrupt, EOFError):
                return False

        # ── Execute ───────────────────────────────────────────
        try:
            # Create cancellable task
            self._cancel_requested = False
            start_time = time.time()

            response = await self.engine.process_query(
                query,
                on_stream=_on_stream,
                on_tool_start=_on_tool_start,
                on_tool_result=_on_tool_result,
                on_confirm=_on_confirm,
            )

            elapsed = time.time() - start_time

            # End streaming if it was started
            if stream_started:
                self.renderer.streaming_end()

            # Show tool summary if tools were used
            if tool_results:
                self._show_tool_summary(tool_results, elapsed)

            # Show response (if not already shown via streaming)
            if not stream_started and response:
                self.renderer.assistant_message(response)

        except Exception as e:
            if stream_started:
                self.renderer.streaming_end()
            self.renderer.error(str(e))

    def _show_tool_summary(self, tool_results: list, total_elapsed: float) -> None:
        """Show a compact summary of all tools used in this turn.

        Args:
            tool_results: List of dicts with tool, success, duration
            total_elapsed: Total wall-clock time for this turn
        """
        parts = []
        for tr in tool_results:
            icon = "✓" if tr["success"] else "✗"
            color = "green" if tr["success"] else "red"
            dur = tr.get("duration", "")
            dur_str = f" [{dur}]" if dur else ""
            parts.append(f"[{color}]{icon} {tr['tool']}{dur_str}[/]")

        summary = "  ".join(parts)
        elapsed_str = f"{total_elapsed:.1f}s" if total_elapsed < 60 else f"{total_elapsed / 60:.1f}m"
        self.renderer.info(f"{summary}    [dim]Total: {elapsed_str}[/]")

    # ── Command Handling ─────────────────────────────────────────

    def _handle_command(self, cmd: str) -> None:
        """Handle REPL slash commands.

        Args:
            cmd: Full command string including leading '/'
        """
        parts = cmd.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if command in ("/exit", "/quit", "/q"):
            self._running = False

        elif command == "/help":
            self.renderer.help_panel(self.COMMANDS)

        elif command == "/clear":
            if self._engine:
                self._engine.reset_session()
            self.renderer.success("Conversation history cleared.")
            self.renderer.rule()

        elif command == "/config":
            self.renderer.config_panel(self.config)

        elif command == "/model":
            self._cmd_model(args)

        elif command == "/provider":
            self._cmd_provider(args)

        elif command == "/mode":
            self._cmd_mode()

        elif command == "/loop":
            self._handle_loop_command(args)

        else:
            self.renderer.warning(f"Unknown command: {command}. Type /help for available commands.")

    def _cmd_model(self, args: str) -> None:
        """Handle /model command."""
        if args:
            new_model = args.strip()
            old_model = self.config.model
            self.config.model = new_model
            if self._engine:
                self._engine.update_config(self.config)
            self.renderer.success(f"Model: [{self.renderer.theme.primary}]{old_model}[/] → [{self.renderer.theme.primary}]{new_model}[/]")
        else:
            self.renderer.info(f"Current model: [{self.renderer.theme.primary}]{self.config.model}[/]")
            self.renderer.info("Usage: /model <model-name>")
            self.renderer.info("Examples: /model gpt-4o, /model claude-sonnet-5, /model deepseek-chat")

    def _cmd_provider(self, args: str) -> None:
        """Handle /provider command."""
        if args:
            new_provider = args.strip()
            old_provider = self.config.provider
            self.config.provider = new_provider
            if self._engine:
                self._engine.update_config(self.config)
            self.renderer.success(f"Provider: [{self.renderer.theme.primary}]{old_provider}[/] → [{self.renderer.theme.primary}]{new_provider}[/]")
        else:
            self.renderer.info(f"Current provider: [{self.renderer.theme.primary}]{self.config.provider}[/]")
            self.renderer.info("Usage: /provider <provider-name>")
            self.renderer.info("Supported: openai, anthropic, deepseek, qwen, ollama")

    def _cmd_mode(self) -> None:
        """Handle /mode command — toggle permission mode."""
        new_mode = "auto_safe" if self.config.permission_mode == "prompt" else "prompt"
        self.config.permission_mode = new_mode
        if self._engine:
            self._engine.update_config(self.config)

        if new_mode == "auto_safe":
            self.renderer.success(f"Permission mode: [{self.renderer.theme.warning}]auto_safe[/] — safe operations auto-approved")
        else:
            self.renderer.success(f"Permission mode: [{self.renderer.theme.primary}]prompt[/] — confirm before writes")

    # ── Loop Command ──────────────────────────────────────────────

    def _handle_loop_command(self, args: str) -> None:
        """Handle /loop subcommands: start, stop, list."""
        parts = args.split(maxsplit=1)
        subcmd = parts[0].lower() if parts else ""
        subargs = parts[1] if len(parts) > 1 else ""

        if subcmd == "start":
            interval_parts = subargs.split(maxsplit=1)
            if len(interval_parts) < 2:
                self.renderer.info("Usage: /loop start <interval> <prompt>")
                self.renderer.info("  e.g., /loop start 5m check the build status")
                self.renderer.info("  Intervals: 30s, 5m, 1h, 2d")
                return

            interval_str = interval_parts[0]
            prompt = interval_parts[1]

            from codeassistant.core.loop import LoopConfig
            scheduler = self.loop_scheduler
            try:
                interval = scheduler.parse_interval(interval_str)
            except ValueError:
                self.renderer.error(f"Invalid interval: {interval_str}. Use format like 30s, 5m, 1h.")
                return

            config = LoopConfig(
                prompt=prompt,
                name=prompt[:40],
                interval_seconds=interval,
            )

            async def _start_loop():
                return await scheduler.start(config)

            loop_id = asyncio.run(_start_loop())
            self.renderer.success(
                f"Loop [{self.renderer.theme.primary}]{loop_id}[/] started "
                f"(every {interval_str}, prompt: '{prompt[:50]}{'...' if len(prompt) > 50 else ''}')"
            )

        elif subcmd == "stop":
            if not subargs:
                self.renderer.info("Usage: /loop stop <loop-id>")
                return
            scheduler = self.loop_scheduler

            async def _stop_loop():
                return await scheduler.stop(subargs)

            if asyncio.run(_stop_loop()):
                self.renderer.success(f"Loop [{self.renderer.theme.primary}]{subargs}[/] stopped.")
            else:
                self.renderer.warning(f"Loop not found: {subargs}")

        elif subcmd == "list":
            scheduler = self.loop_scheduler
            loops = scheduler.list_loops()
            if loops:
                self.renderer.info(f"[bold]Active loops ({len(loops)}):[/]")
                for lp in loops:
                    status_icon = "▶" if lp.status.value == "running" else "⏸"
                    self.renderer.info(
                        f"  {status_icon} [{self.renderer.theme.primary}]{lp.loop_id}[/] "
                        f"{lp.name} (every {lp.interval_seconds}s, "
                        f"{lp.iterations_completed} done)"
                    )
            else:
                self.renderer.info("No active loops.")

        else:
            self.renderer.info("[bold]Loop commands:[/]")
            self.renderer.info("  /loop start <interval> <prompt>  Start a scheduled loop")
            self.renderer.info("  /loop stop <loop-id>            Stop a loop")
            self.renderer.info("  /loop list                      List active loops")
            self.renderer.info("[dim]Intervals: 30s, 5m, 1h, 2d[/]")

    # ── API Key Check ────────────────────────────────────────────

    def _check_api_key(self) -> None:
        """Check if API key is configured and warn if not."""
        if self.config.api_key:
            return

        env_keys = ["CODEASSISTANT_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
        for key in env_keys:
            if os.getenv(key):
                return

        self.renderer.warning("No API key configured!")
        self.renderer.info("Set one of these environment variables:")
        self.renderer.info("  CODEASSISTANT_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY")
        self.renderer.info("Or use: codeassistant config --set api_key <your-key>")
        self.renderer.blank_line()
