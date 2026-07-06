"""CLI entry point for MAHE."""

import asyncio
import os
import sys

import click

from mahe.cli.commands import chat, ask, config, index_cmd, mcp, loop
from mahe.cli.repl import REPL


@click.group(invoke_without_command=True)
@click.option("--model", "-m", help="Model name (e.g., gpt-4o, claude-sonnet-5, deepseek-chat)")
@click.option("--api-key", help="API key (or set MAHE_API_KEY / OPENAI_API_KEY env var)")
@click.option("--api-base", help="API base URL for OpenAI-compatible endpoints")
@click.option("--provider", "-p", default="openai", help="Model provider (openai, anthropic, deepseek, etc.)")
@click.option("--working-dir", "-d", default=".", help="Working directory")
@click.option("--permission-mode", default="prompt", type=click.Choice(["prompt", "auto_safe"]),
              help="Permission mode: prompt (ask before writes) or auto_safe (auto-allow safe ops)")
@click.version_option(version="0.1.0", prog_name="mahe")
@click.pass_context
def main(ctx, model, api_key, api_base, provider, working_dir, permission_mode):
    """MAHE - AI-powered terminal CLI programming assistant.

    An intelligent coding companion that runs in your terminal.
    """
    ctx.ensure_object(dict)

    # Store settings for subcommands
    ctx.obj["settings"] = {
        "model": model,
        "api_key": api_key,
        "api_base": api_base,
        "provider": provider,
        "working_dir": os.path.abspath(working_dir),
        "permission_mode": permission_mode,
    }

    if ctx.invoked_subcommand is None:
        # No subcommand: launch interactive REPL
        from mahe.core.config import MaheConfig
        config_obj = MaheConfig.from_cli(
            model=model,
            api_key=api_key,
            api_base=api_base,
            provider=provider,
            permission_mode=permission_mode,
        )
        repl = REPL(config_obj, os.path.abspath(working_dir))
        try:
            asyncio.run(repl.run())
        except KeyboardInterrupt:
            print("\nGoodbye!")
        except EOFError:
            print("\nGoodbye!")


# Register subcommands
main.add_command(chat)
main.add_command(ask)
main.add_command(config)
main.add_command(index_cmd, name="index")
main.add_command(mcp)
main.add_command(loop)

if __name__ == "__main__":
    main()
