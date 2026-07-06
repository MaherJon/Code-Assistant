"""Interactive REPL loop for CodeAssistant."""

import asyncio
import os
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

from codeassistant.cli.renderer import Renderer
from codeassistant.core.config import CodeAssistantConfig


# Custom style for the prompt
PROMPT_STYLE = Style.from_dict({
    "prompt": "bold cyan",
    "separator": "dim",
})


class REPL:
    """Interactive Read-Eval-Print Loop for CodeAssistant.

    Features:
    - Multi-line input (Alt+Enter for newline)
    - Command history persisted to ~/.codeassistant/history
    - Rich Markdown rendering for responses
    - Slash commands: /help, /clear, /exit, /config, /model
    - Ctrl+C interrupts current agent action
    - Streaming output display during LLM generation
    """

    # Slash commands available in the REPL
    COMMANDS = {
        "/help": "Show this help message",
        "/clear": "Clear conversation history",
        "/exit": "Exit CodeAssistant (also /quit, Ctrl+D)",
        "/config": "Show current configuration",
        "/model <name>": "Switch the current model",
        "/provider <name>": "Switch the model provider",
        "/mode": "Toggle permission mode (prompt/auto_safe)",
        "/loop": "Manage scheduled loops (start/stop/list)",
    }

    def __init__(self, config: CodeAssistantConfig, working_dir: str):
        self.config = config
        self.working_dir = working_dir
        self.renderer = Renderer()
        self._engine = None  # Lazy init
        self._running = False
        self._loop_scheduler = None  # Lazy init

        # Setup prompt_toolkit session
        history_dir = os.path.expanduser("~/.codeassistant")
        os.makedirs(history_dir, exist_ok=True)
        history_file = os.path.join(history_dir, "history")

        self.session = PromptSession(
            history=FileHistory(history_file),
            completer=WordCompleter(
                list(self.COMMANDS.keys()),
                ignore_case=True,
                sentence=True,
            ),
            style=PROMPT_STYLE,
            multiline=False,  # Single line by default; Alt+Enter for multi-line
        )

    @property
    def engine(self):
        """Lazy initialization of the engine."""
        if self._engine is None:
            from codeassistant.core.engine import Engine
            self._engine = Engine(self.config, self.working_dir)
        return self._engine

    @property
    def loop_scheduler(self):
        """Lazy initialization of the loop scheduler."""
        if self._loop_scheduler is None:
            from codeassistant.core.loop import LoopScheduler
            self._loop_scheduler = LoopScheduler(
                query_fn=self._scheduled_query,
                max_loops=5,
            )
        return self._loop_scheduler

    async def _scheduled_query(self, prompt: str) -> str:
        """Execute a query for the loop scheduler (no streaming)."""
        try:
            return await self.engine.process_query(prompt)
        except Exception as e:
            return f"Error: {e}"

    def _handle_loop_command(self, args: str) -> None:
        """Handle /loop subcommands: start, stop, list."""
        parts = args.split(maxsplit=1)
        subcmd = parts[0].lower() if parts else ""
        subargs = parts[1] if len(parts) > 1 else ""

        if subcmd == "start":
            # Parse: /loop start 5m <prompt>
            interval_parts = subargs.split(maxsplit=1)
            if len(interval_parts) < 2:
                self.renderer.info("Usage: /loop start <interval> <prompt>")
                self.renderer.info("  e.g., /loop start 5m check the build")
                return

            interval_str = interval_parts[0]
            prompt = interval_parts[1]

            from codeassistant.core.loop import LoopConfig
            scheduler = self.loop_scheduler
            interval = scheduler.parse_interval(interval_str)
            config = LoopConfig(
                prompt=prompt,
                name=prompt[:40],
                interval_seconds=interval,
            )

            loop_id = asyncio.run(scheduler.start(config))
            self.renderer.success(
                f"Loop started: {loop_id} (every {interval_str}, prompt: '{prompt[:50]}...')"
            )

        elif subcmd == "stop":
            if not subargs:
                self.renderer.info("Usage: /loop stop <loop-id>")
                return
            scheduler = self.loop_scheduler
            if asyncio.run(scheduler.stop(subargs)):
                self.renderer.success(f"Loop stopped: {subargs}")
            else:
                self.renderer.warning(f"Loop not found: {subargs}")

        elif subcmd == "list":
            scheduler = self.loop_scheduler
            loops = scheduler.list_loops()
            if loops:
                self.renderer.info(f"[bold]Active loops ({len(loops)}):[/]")
                for loop in loops:
                    status_icon = "▶" if loop.status.value == "running" else "⏸"
                    self.renderer.info(
                        f"  {status_icon} [{loop.loop_id}] {loop.name} "
                        f"(every {loop.interval_seconds}s, {loop.iterations_completed} done)"
                    )
            else:
                self.renderer.info("No active loops.")

        else:
            self.renderer.info("Loop commands:")
            self.renderer.info("  /loop start <interval> <prompt>  Start a scheduled loop")
            self.renderer.info("  /loop stop <loop-id>              Stop a loop")
            self.renderer.info("  /loop list                        List active loops")
            self.renderer.info("Intervals: 30s, 5m, 1h, 2d")

    async def run(self) -> None:
        """Main REPL loop."""
        self._running = True
        self.renderer.welcome()
        self._check_api_key()

        while self._running:
            try:
                user_input = await self.session.prompt_async(
                    [("class:prompt", "codeassistant"), ("class:separator", "> ")],
                )
            except KeyboardInterrupt:
                # Ctrl+C: cancel current action or clear line
                self.renderer.info("Interrupted. Press Ctrl+D or /exit to quit.")
                continue
            except EOFError:
                # Ctrl+D: exit
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            # Handle slash commands
            if user_input.startswith("/"):
                self._handle_command(user_input)
                continue

            # Process query through the agent
            await self._process_query(user_input)

        self.renderer.info("Goodbye!")

    async def _process_query(self, query: str) -> None:
        """Process a user query through the agent engine."""
        try:
            response = await self.engine.process_query(query)
            self.renderer.render_markdown(response)
        except Exception as e:
            self.renderer.error(str(e))

    def _handle_command(self, cmd: str) -> None:
        """Handle REPL slash commands."""
        parts = cmd.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if command in ("/exit", "/quit", "/q"):
            self._running = False

        elif command == "/help":
            self.renderer.info("Available commands:")
            for cmd_name, cmd_desc in self.COMMANDS.items():
                self.renderer.info(f"  [bold]{cmd_name}[/] - {cmd_desc}")
            self.renderer.info("")
            self.renderer.info("Tips:")
            self.renderer.info("  - Type your question directly for AI assistance")
            self.renderer.info("  - Use Alt+Enter for multi-line input")
            self.renderer.info("  - Ctrl+C to cancel current action")

        elif command == "/clear":
            if self._engine:
                self._engine.reset_session()
            self.renderer.success("Conversation history cleared.")

        elif command == "/config":
            self.renderer.info("[bold]Current Configuration:[/]")
            self.renderer.info(f"  Provider: [cyan]{self.config.provider}[/]")
            self.renderer.info(f"  Model: [cyan]{self.config.model}[/]")
            self.renderer.info(f"  API Base: [cyan]{self.config.api_base or '(default)'}[/]")
            self.renderer.info(f"  API Key: [green]set[/]")
            self.renderer.info(f"  Permission Mode: [cyan]{self.config.permission_mode}[/]")

        elif command == "/model":
            if args:
                self.config.model = args.strip()
                if self._engine:
                    self._engine.update_config(self.config)
                self.renderer.success(f"Model switched to: {self.config.model}")
            else:
                self.renderer.info(f"Current model: [cyan]{self.config.model}[/]")
                self.renderer.info("Usage: /model <model-name>")

        elif command == "/provider":
            if args:
                self.config.provider = args.strip()
                if self._engine:
                    self._engine.update_config(self.config)
                self.renderer.success(f"Provider switched to: {self.config.provider}")
            else:
                self.renderer.info(f"Current provider: [cyan]{self.config.provider}[/]")
                self.renderer.info("Usage: /provider <provider-name>")

        elif command == "/mode":
            new_mode = "auto_safe" if self.config.permission_mode == "prompt" else "prompt"
            self.config.permission_mode = new_mode
            if self._engine:
                self._engine.update_config(self.config)
            self.renderer.success(f"Permission mode: [bold]{new_mode}[/]")

        elif command == "/loop":
            self._handle_loop_command(args)

        else:
            self.renderer.warning(f"Unknown command: {command}. Type /help for available commands.")

    def _check_api_key(self) -> None:
        """Check if API key is configured and warn if not."""
        if not self.config.api_key:
            # Check environment variables
            env_keys = ["CODEASSISTANT_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
            for key in env_keys:
                if os.getenv(key):
                    return

            self.renderer.warning("No API key configured!")
            self.renderer.info("Set one of these environment variables:")
            self.renderer.info("  CODEASSISTANT_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY")
            self.renderer.info("Or use: codeassistant config --set api_key <your-key>")
            self.renderer.info("")
