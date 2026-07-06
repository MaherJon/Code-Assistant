"""Tests for the tool system."""

import os
import pytest

from mahe.tools.base import ToolPermission, ToolResult
from mahe.tools.file_tools import ReadFile, WriteFile, EditFile, GlobTool, GrepTool


class TestReadFile:
    """Tests for ReadFile tool."""

    @pytest.mark.asyncio
    async def test_read_existing_file(self, read_file_tool, working_dir):
        result = await read_file_tool.execute(path="hello.py")
        assert result.success
        assert "def hello()" in result.output
        assert "def goodbye()" in result.output

    @pytest.mark.asyncio
    async def test_read_with_offset(self, read_file_tool, working_dir):
        result = await read_file_tool.execute(path="hello.py", offset=3)
        assert result.success
        assert "def goodbye()" in result.output
        assert "def hello()" not in result.output

    @pytest.mark.asyncio
    async def test_read_with_limit(self, read_file_tool, working_dir):
        result = await read_file_tool.execute(path="hello.py", limit=2)
        assert result.success
        lines = result.output.split("\n")
        # Should have header + 2 lines
        assert len([l for l in lines if l.strip().startswith(tuple("0123456789"))]) <= 2

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, read_file_tool):
        result = await read_file_tool.execute(path="nonexistent.py")
        assert not result.success
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_permission_is_safe(self, read_file_tool):
        assert read_file_tool.permission == ToolPermission.SAFE


class TestWriteFile:
    """Tests for WriteFile tool."""

    @pytest.mark.asyncio
    async def test_create_new_file(self, write_file_tool, temp_dir):
        result = await write_file_tool.execute(
            path=os.path.join(temp_dir, "new_file.py"),
            content="print('hello')"
        )
        assert result.success
        assert "Created" in result.output
        assert os.path.exists(os.path.join(temp_dir, "new_file.py"))

        # Verify content
        with open(os.path.join(temp_dir, "new_file.py")) as f:
            assert f.read() == "print('hello')"

    @pytest.mark.asyncio
    async def test_overwrite_existing_file(self, write_file_tool, working_dir):
        result = await write_file_tool.execute(
            path="hello.py",
            content="# New content"
        )
        assert result.success
        assert "Updated" in result.output

        with open(os.path.join(working_dir, "hello.py")) as f:
            assert f.read() == "# New content"

    @pytest.mark.asyncio
    async def test_creates_parent_directories(self, write_file_tool, temp_dir):
        result = await write_file_tool.execute(
            path=os.path.join(temp_dir, "deep/nested/file.txt"),
            content="nested content"
        )
        assert result.success
        assert os.path.exists(os.path.join(temp_dir, "deep/nested/file.txt"))

    @pytest.mark.asyncio
    async def test_permission_needs_confirm(self, write_file_tool):
        assert write_file_tool.permission == ToolPermission.NEEDS_CONFIRM


class TestEditFile:
    """Tests for EditFile tool."""

    @pytest.mark.asyncio
    async def test_single_replacement(self, edit_file_tool, working_dir):
        result = await edit_file_tool.execute(
            path="hello.py",
            old_string="return 'Hello, World!'",
            new_string="return 'Hi!'"
        )
        assert result.success
        assert "1 replacement" in result.output

        with open(os.path.join(working_dir, "hello.py")) as f:
            content = f.read()
            assert "return 'Hi!'" in content
            assert "return 'Hello, World!'" not in content

    @pytest.mark.asyncio
    async def test_replace_all(self, edit_file_tool, working_dir):
        result = await edit_file_tool.execute(
            path="hello.py",
            old_string="return",
            new_string="yield",
            replace_all=True
        )
        assert result.success
        with open(os.path.join(working_dir, "hello.py")) as f:
            content = f.read()
            assert "return" not in content
            assert content.count("yield") == 2

    @pytest.mark.asyncio
    async def test_string_not_found(self, edit_file_tool, working_dir):
        result = await edit_file_tool.execute(
            path="hello.py",
            old_string="this text does not exist",
            new_string="replacement"
        )
        assert not result.success
        assert "Could not find" in result.error

    @pytest.mark.asyncio
    async def test_nonexistent_file(self, edit_file_tool):
        result = await edit_file_tool.execute(
            path="nonexistent.py",
            old_string="x",
            new_string="y"
        )
        assert not result.success
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_permission_needs_confirm(self, edit_file_tool):
        assert edit_file_tool.permission == ToolPermission.NEEDS_CONFIRM


class TestGlobTool:
    """Tests for GlobTool."""

    @pytest.mark.asyncio
    async def test_find_python_files(self, glob_tool, working_dir):
        result = await glob_tool.execute(pattern="**/*.py")
        assert result.success
        assert "hello.py" in result.output
        assert "main.py" in result.output

    @pytest.mark.asyncio
    async def test_find_yaml_files(self, glob_tool, working_dir):
        result = await glob_tool.execute(pattern="**/*.yaml")
        assert result.success
        assert "config.yaml" in result.output

    @pytest.mark.asyncio
    async def test_no_matches(self, glob_tool, working_dir):
        result = await glob_tool.execute(pattern="**/*.rs")
        assert result.success
        assert "No files matching" in result.output


class TestGrepTool:
    """Tests for GrepTool."""

    @pytest.mark.asyncio
    async def test_search_function_def(self, grep_tool, working_dir):
        result = await grep_tool.execute(pattern=r"def \w+")
        assert result.success
        assert "def hello" in result.output
        assert "def goodbye" in result.output
        assert "def main" in result.output

    @pytest.mark.asyncio
    async def test_search_with_glob_filter(self, grep_tool, working_dir):
        result = await grep_tool.execute(pattern=r"def", glob="*.yaml")
        assert result.success
        assert "No matches" in result.output

    @pytest.mark.asyncio
    async def test_invalid_regex(self, grep_tool, working_dir):
        result = await grep_tool.execute(pattern=r"[invalid")
        assert not result.success
        assert "Invalid regex" in result.error
