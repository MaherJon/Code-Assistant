"""File system tools: ReadFile, WriteFile, EditFile, Glob, Grep."""

import os
import re
from pathlib import Path
from typing import Optional

from mahe.tools.base import Tool, ToolPermission, ToolResult


class ReadFile(Tool):
    """Read contents of a file."""

    name = "read_file"
    description = (
        "Read the contents of a file. Use this to inspect code, configuration, "
        "or any text file. Returns the file contents with line numbers."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The path to the file to read (absolute or relative to working directory)."
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (1-indexed). Default: 1."
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read. Default: read entire file."
            },
        },
        "required": ["path"],
    }
    permission = ToolPermission.SAFE

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    async def execute(self, path: str, offset: int = 0, limit: Optional[int] = None) -> ToolResult:
        """Read a file and return its contents with line numbers."""
        file_path = self._resolve_path(path)

        if not os.path.isfile(file_path):
            return ToolResult.fail(f"File not found: {path}")

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except PermissionError as e:
            return ToolResult.fail(f"Permission denied: {e}")
        except Exception as e:
            return ToolResult.fail(f"Error reading file: {e}")

        total_lines = len(lines)

        # Apply offset and limit
        start = max(0, offset - 1) if offset > 0 else 0
        if limit is not None:
            end = min(start + limit, total_lines)
        else:
            end = total_lines

        selected_lines = lines[start:end]

        # Add line numbers
        numbered = []
        for i, line in enumerate(selected_lines, start=start + 1):
            numbered.append(f"{i:6}\t{line.rstrip()}")

        output = "\n".join(numbered)
        if not output:
            output = "(empty file)"

        # Truncate if too long (超过2000行截断)
        if len(numbered) > 2000:
            output = "\n".join(numbered[:2000])
            output += f"\n\n... (truncated, {total_lines - 2000} more lines)"

        header = f"File: {file_path} (lines {start + 1}-{end} of {total_lines})\n\n"
        return ToolResult.ok(header + output, path=file_path, total_lines=total_lines, shown_lines=len(selected_lines))

    def _resolve_path(self, path: str) -> str:
        """Resolve a file path relative to working directory."""
        if os.path.isabs(path):
            return path
        return os.path.normpath(os.path.join(self.working_dir, path))


class WriteFile(Tool):
    """Write or overwrite a file."""

    name = "write_file"
    description = (
        "Write or overwrite a file with the given content. "
        "Creates parent directories if they don't exist. "
        "Use this to create new files or update existing ones."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The path to the file to write (absolute or relative)."
            },
            "content": {
                "type": "string",
                "description": "The complete content to write to the file."
            },
        },
        "required": ["path", "content"],
    }
    permission = ToolPermission.NEEDS_CONFIRM

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    async def execute(self, path: str, content: str) -> ToolResult:
        """Write content to a file."""
        file_path = self._resolve_path(path)

        # Check if this is a new file or modification
        is_new = not os.path.exists(file_path)

        try:
            # Create parent directories
            parent = os.path.dirname(file_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

        except PermissionError as e:
            return ToolResult.fail(f"Permission denied: {e}")
        except Exception as e:
            return ToolResult.fail(f"Error writing file: {e}")

        action = "Created" if is_new else "Updated"
        lines = content.count("\n") + 1
        size = len(content)
        return ToolResult.ok(
            f"{action} file: {file_path} ({lines} lines, {size} chars)",
            path=file_path, action=action, lines=lines, size=size
        )

    def _resolve_path(self, path: str) -> str:
        """Resolve a file path relative to working directory."""
        if os.path.isabs(path):
            return path
        return os.path.normpath(os.path.join(self.working_dir, path))


class EditFile(Tool):
    """Edit a file by replacing exact string matches."""

    name = "edit_file"
    description = (
        "Edit a file by performing exact string replacements. "
        "Provide the exact text to find and its replacement. "
        "Use replace_all: true to replace all occurrences."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The path to the file to edit."
            },
            "old_string": {
                "type": "string",
                "description": "The exact text to find and replace."
            },
            "new_string": {
                "type": "string",
                "description": "The text to replace with."
            },
            "replace_all": {
                "type": "boolean",
                "description": "Replace all occurrences (default: false, replace first match only).",
                "default": False,
            },
        },
        "required": ["path", "old_string", "new_string"],
    }
    permission = ToolPermission.NEEDS_CONFIRM

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    async def execute(
        self, path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> ToolResult:
        """Edit a file by replacing exact string matches."""
        file_path = self._resolve_path(path)

        if not os.path.isfile(file_path):
            return ToolResult.fail(f"File not found: {path}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return ToolResult.fail(f"Error reading file: {e}")

        # Find the old string
        count = content.count(old_string)
        if count == 0:
            return ToolResult.fail(
                f"Could not find the specified text in {path}. "
                "The text must match exactly (including whitespace)."
            )

        if replace_all:
            new_content = content.replace(old_string, new_string)
        else:
            new_content = content.replace(old_string, new_string, 1)
            count = 1

        # Don't write if nothing changed
        if new_content == content:
            return ToolResult.ok("No changes made (old and new strings are identical).", path=file_path)

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except Exception as e:
            return ToolResult.fail(f"Error writing file: {e}")

        return ToolResult.ok(
            f"Edited {path}: {count} replacement(s) made.",
            path=file_path, replacements=count
        )

    def _resolve_path(self, path: str) -> str:
        if os.path.isabs(path):
            return path
        return os.path.normpath(os.path.join(self.working_dir, path))


class GlobTool(Tool):
    """Find files matching a glob pattern."""

    name = "glob_files"
    description = (
        "Find files matching a glob pattern (e.g., '**/*.py', 'src/**/*.ts'). "
        "Returns matching file paths sorted by modification time."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match files (e.g., '**/*.py', 'src/*.ts')."
            },
            "path": {
                "type": "string",
                "description": "Directory to search in. Defaults to working directory."
            },
        },
        "required": ["pattern"],
    }
    permission = ToolPermission.SAFE

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    async def execute(self, pattern: str, path: str = None) -> ToolResult:
        """Find files matching a glob pattern."""
        search_dir = path or self.working_dir
        if not os.path.isabs(search_dir):
            search_dir = os.path.join(self.working_dir, search_dir)
        search_dir = os.path.normpath(search_dir)

        try:
            matches = list(Path(search_dir).glob(pattern))
        except Exception as e:
            return ToolResult.fail(f"Glob error: {e}")

        # Filter to files only, sort by mtime
        files = []
        for m in matches:
            if m.is_file():
                try:
                    mtime = os.path.getmtime(m)
                    files.append((str(m), mtime))
                except OSError:
                    files.append((str(m), 0))

        files.sort(key=lambda x: x[1], reverse=True)

        if not files:
            return ToolResult.ok(f"No files matching '{pattern}' in {search_dir}")

        # Limit output to 200 results
        lines = [f"Found {len(files)} files matching '{pattern}':", ""]
        for filepath, _ in files[:200]:
            lines.append(f"  {filepath}")

        if len(files) > 200:
            lines.append(f"  ... and {len(files) - 200} more")

        return ToolResult.ok("\n".join(lines), count=len(files))


class GrepTool(Tool):
    """Search file contents using regex."""

    name = "search_code"
    description = (
        "Search file contents using a regular expression pattern. "
        "Returns matching file paths and line numbers. "
        "Use this to find function definitions, imports, usage of APIs, etc."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regular expression pattern to search for."
            },
            "path": {
                "type": "string",
                "description": "Directory or file to search in. Defaults to working directory."
            },
            "glob": {
                "type": "string",
                "description": "File glob filter (e.g., '*.py', '*.{js,ts}')."
            },
        },
        "required": ["pattern"],
    }
    permission = ToolPermission.SAFE

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    async def execute(self, pattern: str, path: str = None, glob: str = None) -> ToolResult:
        """Search for a regex pattern in files."""
        search_dir = path or self.working_dir
        if not os.path.isabs(search_dir):
            search_dir = os.path.join(self.working_dir, search_dir)
        search_dir = os.path.normpath(search_dir)

        try:
            regex = re.compile(pattern, re.MULTILINE)
        except re.error as e:
            return ToolResult.fail(f"Invalid regex pattern: {e}")

        results = []
        files_searched = 0

        # Determine file filter
        if glob:
            import fnmatch
            def file_filter(fname):
                return fnmatch.fnmatch(fname, glob)
        else:
            def file_filter(fname):
                # Default: common code file extensions
                code_exts = {'.py', '.js', '.ts', '.jsx', '.tsx', '.go', '.rs', '.java',
                            '.c', '.cpp', '.h', '.hpp', '.rb', '.php', '.swift', '.kt',
                            '.vue', '.svelte', '.yml', '.yaml', '.json', '.toml', '.md',
                            '.sql', '.sh', '.bash', '.zsh', '.ps1', '.txt', '.cfg', '.ini'}
                ext = os.path.splitext(fname)[1].lower()
                return ext in code_exts

        # Walk the directory
        try:
            for root, dirs, files in os.walk(search_dir):
                # Skip hidden directories and common non-code dirs
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in
                          ('node_modules', '__pycache__', 'venv', '.git', 'dist', 'build',
                           'target', '.next', '.nuxt', 'coverage', '.pytest_cache')]

                for fname in files:
                    if not file_filter(fname):
                        continue
                    files_searched += 1
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                            for i, line in enumerate(f, 1):
                                if regex.search(line):
                                    rel_path = os.path.relpath(fpath, self.working_dir)
                                    results.append((rel_path, i, line.rstrip()[:200]))
                    except Exception:
                        continue
        except Exception as e:
            return ToolResult.fail(f"Search error: {e}")

        # Limit results
        if len(results) > 100:
            results = results[:100]
            truncated = True
        else:
            truncated = False

        if not results:
            return ToolResult.ok(
                f"No matches for '{pattern}' in {files_searched} files.",
                files_searched=files_searched
            )

        lines = [f"Found {len(results)} matches for '{pattern}':", ""]
        for filepath, lineno, text in results:
            lines.append(f"  {filepath}:{lineno}: {text}")

        if truncated:
            lines.append(f"  ... (truncated, showing first 100 matches)")

        return ToolResult.ok("\n".join(lines), matches=len(results), files_searched=files_searched)
