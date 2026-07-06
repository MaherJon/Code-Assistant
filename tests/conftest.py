"""Shared test fixtures for MAHE."""

import os
import tempfile
from pathlib import Path

import pytest

from mahe.tools.base import ToolRegistry
from mahe.tools.file_tools import ReadFile, WriteFile, EditFile, GlobTool, GrepTool
from mahe.utils.sandbox import Sandbox
from mahe.utils.permissions import PermissionChecker, PermissionPolicy
from tests.helpers import MockLLMAdapter


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


@pytest.fixture
def working_dir(temp_dir):
    """Create a temporary directory with some test files."""
    # Create test files
    (Path(temp_dir) / "hello.py").write_text(
        "def hello():\n    return 'Hello, World!'\n\n"
        "def goodbye():\n    return 'Goodbye!'\n"
    )
    (Path(temp_dir) / "config.yaml").write_text(
        "name: test\nversion: 1.0\n"
    )
    (Path(temp_dir) / "src").mkdir(exist_ok=True)
    (Path(temp_dir) / "src" / "main.py").write_text(
        "import hello\n\n"
        "def main():\n"
        "    print(hello.hello())\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    return temp_dir


@pytest.fixture
def sandbox():
    """Create a sandbox instance."""
    return Sandbox()


@pytest.fixture
def read_file_tool(working_dir):
    """Create a ReadFile tool instance."""
    return ReadFile(working_dir=working_dir)


@pytest.fixture
def write_file_tool(working_dir):
    """Create a WriteFile tool instance."""
    return WriteFile(working_dir=working_dir)


@pytest.fixture
def edit_file_tool(working_dir):
    """Create an EditFile tool instance."""
    return EditFile(working_dir=working_dir)


@pytest.fixture
def glob_tool(working_dir):
    """Create a GlobTool instance."""
    return GlobTool(working_dir=working_dir)


@pytest.fixture
def grep_tool(working_dir):
    """Create a GrepTool instance."""
    return GrepTool(working_dir=working_dir)


@pytest.fixture
def tool_registry(working_dir, sandbox):
    """Create a fully populated ToolRegistry."""
    registry = ToolRegistry()
    registry.register(ReadFile(working_dir=working_dir))
    registry.register(WriteFile(working_dir=working_dir))
    registry.register(EditFile(working_dir=working_dir))
    registry.register(GlobTool(working_dir=working_dir))
    registry.register(GrepTool(working_dir=working_dir))
    return registry


@pytest.fixture
def permission_checker():
    """Create a PermissionChecker with default policy."""
    return PermissionChecker(PermissionPolicy.default())


@pytest.fixture
def mock_llm():
    """Create a MockLLMAdapter."""
    return MockLLMAdapter()
