"""Click commands for CodeAssistant CLI."""

import asyncio
import os
import sys

import click
from rich.console import Console

console = Console()


@click.command()
@click.option("--model", "-m", help="Model name override")
@click.option("--working-dir", "-d", default=".", help="Working directory")
@click.argument("query", nargs=-1)
@click.pass_context
def ask(ctx, model, working_dir, query):
    """One-shot: ask a question and print the response.

    Example: codeassistant ask "what does git status do?"
    """
    query_str = " ".join(query)
    if not query_str:
        console.print("[red]Error:[/] Please provide a query. Usage: codeassistant ask <query>")
        sys.exit(1)

    from codeassistant.core.config import CodeAssistantConfig
    from codeassistant.core.engine import Engine

    settings = ctx.obj.get("settings", {})
    config_obj = CodeAssistantConfig.from_cli(
        model=model or settings.get("model"),
        api_key=settings.get("api_key"),
        api_base=settings.get("api_base"),
        provider=settings.get("provider", "openai"),
    )

    wd = os.path.abspath(working_dir)
    engine = Engine(config_obj, wd)

    try:
        result = asyncio.run(engine.process_query(query_str))
        console.print(result)
    except Exception as e:
        console.print(f"[red]Error:[/] {e}")
        sys.exit(1)


@click.command()
@click.option("--model", "-m", help="Model name override")
@click.option("--working-dir", "-d", default=".", help="Working directory")
@click.pass_context
def chat(ctx, model, working_dir):
    """Launch interactive chat REPL.

    Example: codeassistant chat
    """
    from codeassistant.core.config import CodeAssistantConfig
    from codeassistant.cli.repl import REPL

    settings = ctx.obj.get("settings", {})
    config_obj = CodeAssistantConfig.from_cli(
        model=model or settings.get("model"),
        api_key=settings.get("api_key"),
        api_base=settings.get("api_base"),
        provider=settings.get("provider", "openai"),
    )

    wd = os.path.abspath(working_dir)
    repl = REPL(config_obj, wd)
    try:
        asyncio.run(repl.run())
    except KeyboardInterrupt:
        console.print("\n[dim]Goodbye![/]")
    except EOFError:
        console.print("\n[dim]Goodbye![/]")


@click.command()
@click.option("--list", "list_config", is_flag=True, help="Show current configuration")
@click.option("--set", "set_key", nargs=2, multiple=True, help="Set a config key=value")
@click.pass_context
def config(ctx, list_config, set_key):
    """View and manage CodeAssistant configuration.

    Example: codeassistant config --list
             codeassistant config --set model gpt-4o
    """
    from codeassistant.core.config import CodeAssistantConfig

    if list_config:
        cfg = CodeAssistantConfig.from_cli()
        console.print("[bold]CodeAssistant Configuration:[/]")
        console.print(f"  Provider: {cfg.provider}")
        console.print(f"  Model: {cfg.model}")
        console.print(f"  API Base: {cfg.api_base or '(default)'}")
        console.print(f"  API Key: {'[green]set[/]' if cfg.api_key else '[red]not set[/]'}")
        console.print(f"  Permission Mode: {cfg.permission_mode}")
        console.print(f"  Data Dir: {cfg.data_dir}")
    elif set_key:
        # Save to config file
        import yaml
        config_path = os.path.expanduser("~/.codeassistant/config.yaml")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)

        existing = {}
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                existing = yaml.safe_load(f) or {}

        for key, value in set_key:
            existing[key] = value
            console.print(f"[green]Set[/] {key} = {value}")

        with open(config_path, "w") as f:
            yaml.dump(existing, f, default_flow_style=False)
        console.print(f"[dim]Saved to {config_path}[/]")
    else:
        console.print("Usage: codeassistant config --list | codeassistant config --set <key> <value>")


@click.command()
@click.option("--update", is_flag=True, help="Re-index only changed files")
@click.option("--force", is_flag=True, help="Force full re-index")
@click.option("--working-dir", "-d", default=".", help="Project directory to index")
@click.pass_context
def index_cmd(ctx, update, force, working_dir):
    """Index the project for semantic code search.

    Creates a vector index of all code files, enabling natural language
    code search in the REPL.
    """
    wd = os.path.abspath(working_dir)
    console.print(f"[bold]Indexing project:[/] {wd}")

    try:
        from codeassistant.core.config import CodeAssistantConfig
        from codeassistant.llm.litellm_adapter import LiteLLMAdapter
        from codeassistant.context.vector_store import VectorStore

        settings = ctx.obj.get("settings", {})
        config_obj = CodeAssistantConfig.from_cli(
            model=settings.get("model"),
            api_key=settings.get("api_key"),
            api_base=settings.get("api_base"),
            provider=settings.get("provider", "openai"),
        )

        # Create embed function using LiteLLM
        llm = LiteLLMAdapter(
            model=config_obj.effective_model_name(),
            api_key=config_obj.api_key,
            api_base=config_obj.api_base,
        )

        async def _embed(texts):
            return await llm.embed(texts)

        import asyncio

        # Initialize vector store
        store = VectorStore(
            persist_dir=os.path.join(wd, ".codeassistant", "vectors"),
            embedding_fn=None,  # Will be set below
        )

        if not store.enabled:
            console.print("[red]Vector store not available.[/] Install chromadb: pip install chromadb")
            return

        # Set the embedding function
        store.embedding_fn = lambda texts: asyncio.run(_embed(texts))

        # Index
        with console.status("[cyan]Indexing files...[/]"):
            count = store.index_project(wd)

        console.print(f"[green]✓[/] Indexed [bold]{count}[/] files.")
        stats = store.get_stats()
        console.print(f"[dim]Vector store: {stats['count']} documents at {stats['dir']}[/]")

    except ImportError:
        console.print("[red]chromadb not installed.[/] Run: pip install chromadb")
    except Exception as e:
        console.print(f"[red]Error:[/] {e}")


@click.group()
def mcp():
    """Manage MCP (Model Context Protocol) servers."""
    pass


@mcp.command("list")
def mcp_list():
    """List configured MCP servers."""
    import yaml
    config_path = os.path.expanduser("~/.codeassistant/mcp_servers.yaml")

    if not os.path.exists(config_path):
        console.print("[dim]No MCP servers configured.[/]")
        console.print(f"Create {config_path} to add MCP servers.")
        return

    with open(config_path, "r") as f:
        config = yaml.safe_load(f) or {}

    servers = config.get("servers", [])
    if not servers:
        console.print("[dim]No MCP servers configured.[/]")
        return

    console.print("[bold]Configured MCP Servers:[/]")
    for s in servers:
        status = "[green]enabled[/]" if s.get("enabled", True) else "[dim]disabled[/]"
        console.print(f"  {status} [bold]{s.get('name', '?')}[/]: {s.get('command', '?')} {' '.join(s.get('args', []))}")


@mcp.command("serve")
@click.pass_context
def mcp_serve(ctx):
    """Start MCP servers and register their tools.

    MCP servers run as subprocesses. Tools discovered from MCP servers
    are available in the REPL alongside built-in tools.
    """
    from codeassistant.tools.mcp_client import MCPClient

    client = MCPClient()
    console.print("[bold]Starting MCP servers...[/]")

    try:
        import asyncio
        results = asyncio.run(client.connect_all())

        for server, tools in results.items():
            if tools:
                console.print(f"  [green]✓[/] {server}: [bold]{len(tools)}[/] tools")
                for tool in tools[:5]:
                    console.print(f"      - {tool}")
                if len(tools) > 5:
                    console.print(f"      ... and {len(tools) - 5} more")
            else:
                console.print(f"  [red]✗[/] {server}: no tools discovered")

    except Exception as e:
        console.print(f"[red]Error:[/] {e}")

    console.print("[dim]MCP servers running. Press Ctrl+C to stop.[/]")
    try:
        import asyncio
        asyncio.run(asyncio.Event().wait())  # Wait forever
    except KeyboardInterrupt:
        console.print("\n[dim]Stopping MCP servers...[/]")
        import asyncio
        asyncio.run(client.disconnect_all())


@click.group()
def loop():
    """Manage scheduled and recurring tasks."""
    pass


@loop.command("start")
@click.argument("interval")
@click.argument("prompt", nargs=-1)
@click.pass_context
def loop_start(ctx, interval, prompt):
    """Start a recurring loop.

    INTERVAL: e.g., 30s, 5m, 1h
    PROMPT: The task to execute each iteration
    """
    prompt_str = " ".join(prompt)
    if not prompt_str:
        console.print("[red]Error:[/] No prompt provided.")
        return

    from codeassistant.core.config import CodeAssistantConfig
    from codeassistant.core.engine import Engine
    from codeassistant.core.loop import LoopConfig, LoopScheduler

    settings = ctx.obj.get("settings", {})
    config_obj = CodeAssistantConfig.from_cli(
        model=settings.get("model"),
        api_key=settings.get("api_key"),
        api_base=settings.get("api_base"),
        provider=settings.get("provider", "openai"),
    )
    wd = os.path.abspath(settings.get("working_dir", "."))

    engine = Engine(config_obj, wd)

    async def _run_loop():
        scheduler = LoopScheduler(query_fn=engine.process_query)
        parsed = scheduler.parse_interval(interval)
        loop_config = LoopConfig(
            prompt=prompt_str,
            name=prompt_str[:40],
            interval_seconds=parsed,
        )
        loop_id = await scheduler.start(loop_config)
        console.print(f"[green]Loop started:[/] {loop_id} (every {interval})")

        # Keep running until Ctrl+C
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await scheduler.cleanup()
            console.print("\n[dim]All loops stopped.[/]")

    asyncio.run(_run_loop())


@loop.command("list")
@click.pass_context
def loop_list(ctx):
    """List active loops (REPL-only, informational)."""
    console.print("[dim]Active loops are managed within the REPL session.[/]")
    console.print("Use [bold]codeassistant chat[/] and then [bold]/loop list[/] to see active loops.")


@loop.command("once")
@click.argument("delay")
@click.argument("prompt", nargs=-1)
@click.pass_context
def loop_once(ctx, delay, prompt):
    """Run a task once after a delay.

    DELAY: e.g., 10m, 1h
    PROMPT: The task to execute
    """
    prompt_str = " ".join(prompt)
    if not prompt_str:
        console.print("[red]Error:[/] No prompt provided.")
        return

    from codeassistant.core.config import CodeAssistantConfig
    from codeassistant.core.engine import Engine
    from codeassistant.core.loop import LoopScheduler

    settings = ctx.obj.get("settings", {})
    config_obj = CodeAssistantConfig.from_cli(
        model=settings.get("model"),
        api_key=settings.get("api_key"),
        api_base=settings.get("api_base"),
        provider=settings.get("provider", "openai"),
    )
    wd = os.path.abspath(settings.get("working_dir", "."))

    engine = Engine(config_obj, wd)

    async def _run_once():
        scheduler = LoopScheduler(query_fn=engine.process_query)
        parsed = scheduler.parse_interval(delay)
        console.print(f"[dim]Scheduled to run in {delay}...[/]")
        loop_id = await scheduler.run_once(prompt_str, delay=parsed)

        # Wait for completion
        for _ in range(parsed + 10):
            loops = scheduler.list_loops()
            if not loops:
                break
            await asyncio.sleep(1)

        console.print("[green]✓[/] Task completed.")

    asyncio.run(_run_once())
