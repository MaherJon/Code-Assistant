"""Tests for the CLI interface."""

import os
import pytest
from click.testing import CliRunner

from mahe.main import main
from mahe.cli.commands import ask, chat, config


@pytest.fixture
def runner():
    """Create a Click CLI test runner."""
    return CliRunner()


class TestMainCLI:
    """Tests for the main CLI entry point."""

    def test_help(self, runner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "MAHE" in result.output
        assert "chat" in result.output
        assert "ask" in result.output
        assert "config" in result.output

    def test_version(self, runner):
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_invalid_option(self, runner):
        result = runner.invoke(main, ["--invalid-option"])
        assert result.exit_code != 0


class TestConfigCommand:
    """Tests for the config command."""

    def test_config_list(self, runner):
        result = runner.invoke(config, ["--list"])
        assert result.exit_code == 0
        assert "MAHE Configuration" in result.output
        assert "Provider" in result.output
        assert "Model" in result.output

    def test_config_set(self, runner):
        result = runner.invoke(config, ["--set", "model", "gpt-4o-mini"])
        assert result.exit_code == 0
        assert "gpt-4o-mini" in result.output


class TestAskCommand:
    """Tests for the one-shot ask command."""

    def test_ask_no_query(self, runner):
        result = runner.invoke(ask, [])
        assert result.exit_code == 1
        assert "Error" in result.output or "Please provide" in result.output

    def test_ask_with_query_no_api_key(self, runner):
        # Should fail gracefully without API key
        result = runner.invoke(ask, ["what is python?"])
        # Will error when trying to create engine without API key
        # But should not crash
        assert result.exit_code == 1


class TestChatCommand:
    """Tests for the chat command."""

    def test_chat_help(self, runner):
        result = runner.invoke(chat, ["--help"])
        assert result.exit_code == 0
        assert "interactive" in result.output.lower() or "chat" in result.output.lower()
