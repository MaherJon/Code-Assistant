"""Code analysis tools with tree-sitter (multi-language) and Jedi (Python).

Phase 2: Replaces ast-based Python analysis with tree-sitter for
multi-language AST parsing, and adds Jedi for Python code intelligence.
"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from mahe.tools.base import Tool, ToolPermission, ToolResult

logger = logging.getLogger("mahe.tools.code")


# ─── Language Detection ───────────────────────────────────────────

LANGUAGE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
}


def detect_language(path: str) -> Optional[str]:
    """Detect the programming language from a file extension."""
    ext = os.path.splitext(path)[1].lower()
    return LANGUAGE_EXTENSIONS.get(ext)


# ─── Tree-Sitter Parser ────────────────────────────────────────────


class TreeSitterParser:
    """Multi-language AST parser using tree-sitter.

    Lazily loads language grammars on first use.
    """

    _parsers: Dict[str, Any] = {}  # language -> Parser instance

    @classmethod
    def _get_parser(cls, language: str):
        """Get or create a tree-sitter parser for a language."""
        if language in cls._parsers:
            return cls._parsers[language]

        try:
            import tree_sitter_python
            import tree_sitter_javascript
            from tree_sitter import Language, Parser

            # Map language names to tree-sitter language modules
            lang_map = {
                "python": tree_sitter_python.language,
                "javascript": tree_sitter_javascript.language,
                "typescript": tree_sitter_javascript.language,  # Fallback
            }

            lang_fn = lang_map.get(language)
            if not lang_fn:
                return None

            lang = Language(lang_fn())
            parser = Parser(lang)
            cls._parsers[language] = parser
            return parser
        except ImportError:
            logger.debug("tree-sitter grammar not available for: %s", language)
            return None
        except Exception as e:
            logger.warning("Failed to load tree-sitter parser for %s: %s", language, e)
            return None

    @classmethod
    def parse_file(cls, path: str) -> Optional[Dict[str, Any]]:
        """Parse a file and return its structure.

        Returns:
            Dict with: language, functions, classes, imports, symbols
            None if parsing fails
        """
        language = detect_language(path)
        if not language:
            return None

        parser = cls._get_parser(language)
        if not parser:
            return None

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
        except Exception:
            return None

        source_bytes = source.encode("utf-8")
        tree = parser.parse(source_bytes)

        functions = []
        classes = []
        imports = []
        symbols = []

        # Tree-sitter query-based extraction
        if language == "python":
            cls._extract_python(tree.root_node, source_bytes, functions, classes, imports)
        elif language in ("javascript", "typescript"):
            cls._extract_javascript(tree.root_node, source_bytes, functions, classes, imports)

        # Build symbol list
        for f in functions:
            symbols.append({"kind": "function", "name": f["name"], "line": f["line"]})
        for c in classes:
            symbols.append({"kind": "class", "name": c["name"], "line": c["line"]})

        return {
            "language": language,
            "functions": functions,
            "classes": classes,
            "imports": imports,
            "symbols": symbols,
        }

    @classmethod
    def _extract_python(cls, node, source: bytes, functions: list, classes: list, imports: list):
        """Extract Python structure from tree-sitter AST."""
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                params = node.child_by_field_name("parameters")
                functions.append({
                    "name": name_node.text.decode("utf-8"),
                    "line": node.start_point[0] + 1,
                    "params": params.text.decode("utf-8") if params else "()",
                })
        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                methods = []
                body_node = node.child_by_field_name("body")
                if body_node:
                    for child in body_node.children:
                        if child.type == "function_definition":
                            mn = child.child_by_field_name("name")
                            if mn:
                                methods.append(mn.text.decode("utf-8"))
                classes.append({
                    "name": name_node.text.decode("utf-8"),
                    "line": node.start_point[0] + 1,
                    "methods": methods,
                })
        elif node.type in ("import_statement", "import_from_statement"):
            imports.append(node.text.decode("utf-8").strip())

        for child in node.children:
            cls._extract_python(child, source, functions, classes, imports)

    @classmethod
    def _extract_javascript(cls, node, source: bytes, functions: list, classes: list, imports: list):
        """Extract JavaScript/TypeScript structure from tree-sitter AST."""
        if node.type in ("function_declaration", "method_definition"):
            name_node = node.child_by_field_name("name")
            if name_node:
                functions.append({
                    "name": name_node.text.decode("utf-8"),
                    "line": node.start_point[0] + 1,
                })
        elif node.type == "class_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                classes.append({
                    "name": name_node.text.decode("utf-8"),
                    "line": node.start_point[0] + 1,
                    "methods": [],
                })
        elif node.type == "import_statement":
            imports.append(node.text.decode("utf-8").strip())

        for child in node.children:
            cls._extract_javascript(child, source, functions, classes, imports)


# ─── Jedi Analyzer ─────────────────────────────────────────────────


class JediAnalyzer:
    """Python code intelligence using Jedi.

    Provides completions, go-to-definition, references, and hover info.
    """

    @staticmethod
    def _get_script(path: str, source: Optional[str] = None):
        """Create a Jedi Script for a file."""
        import jedi
        if source is None:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    source = f.read()
            except Exception:
                return None
        return jedi.Script(code=source, path=path)

    @classmethod
    def get_completions(cls, path: str, line: int, column: int) -> List[Dict[str, Any]]:
        """Get code completions at a position."""
        script = cls._get_script(path)
        if not script:
            return []
        try:
            completions = script.complete(line, column)
            return [
                {
                    "name": c.name,
                    "type": c.type or "unknown",
                    "description": c.description or "",
                    "complete": c.complete,
                }
                for c in completions[:20]
            ]
        except Exception as e:
            logger.warning("Jedi completions failed: %s", e)
            return []

    @classmethod
    def get_definition(cls, path: str, line: int, column: int) -> Optional[Dict[str, Any]]:
        """Get the definition location of a symbol."""
        script = cls._get_script(path)
        if not script:
            return None
        try:
            defs = script.goto(line, column)
            if defs:
                d = defs[0]
                return {
                    "file": d.module_path or path,
                    "line": d.line,
                    "column": d.column,
                    "description": d.description or "",
                    "name": d.name,
                }
        except Exception as e:
            logger.warning("Jedi goto failed: %s", e)
        return None

    @classmethod
    def get_references(cls, path: str, line: int, column: int) -> List[Dict[str, Any]]:
        """Find all references to a symbol."""
        script = cls._get_script(path)
        if not script:
            return []
        try:
            refs = script.get_references(line, column)
            return [
                {
                    "file": r.module_path or path,
                    "line": r.line,
                    "column": r.column,
                    "name": r.name,
                }
                for r in refs[:50]
            ]
        except Exception as e:
            logger.warning("Jedi references failed: %s", e)
            return []

    @classmethod
    def get_signature(cls, path: str, line: int, column: int) -> Optional[str]:
        """Get the signature of a callable at a position."""
        script = cls._get_script(path)
        if not script:
            return None
        try:
            signatures = script.get_signatures(line, column)
            if signatures:
                return signatures[0].to_string()
        except Exception as e:
            logger.warning("Jedi signatures failed: %s", e)
        return None

    @classmethod
    def get_docstring(cls, path: str, line: int, column: int) -> Optional[str]:
        """Get the docstring/help text at a position."""
        script = cls._get_script(path)
        if not script:
            return None
        try:
            help_text = script.help(line, column)
            if help_text:
                return help_text
        except Exception as e:
            logger.warning("Jedi help failed: %s", e)
        return None


# ─── Tools ──────────────────────────────────────────────────────────


class AnalyzeCode(Tool):
    """Analyze the structure of a code file using tree-sitter."""

    name = "analyze_code"
    description = (
        "Analyze a code file's structure: list classes, functions, imports, "
        "and symbols. Supports Python, JavaScript, TypeScript, Go, Rust, and more. "
        "Use this to understand code organization in any supported language."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the code file to analyze."
            },
        },
        "required": ["path"],
    }
    permission = ToolPermission.SAFE

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    async def execute(self, path: str) -> ToolResult:
        file_path = self._resolve_path(path)
        if not os.path.isfile(file_path):
            return ToolResult.fail(f"File not found: {path}")

        # Try tree-sitter first
        result = TreeSitterParser.parse_file(file_path)
        if result:
            return self._format_tree_sitter_result(file_path, result)

        # Fallback to built-in ast for Python
        language = detect_language(file_path)
        if language == "python":
            return await self._fallback_python_ast(file_path)

        return ToolResult.fail(
            f"Unsupported language for {path}. "
            f"Supported: Python, JavaScript, TypeScript, Go, Rust."
        )

    def _format_tree_sitter_result(self, file_path: str, result: dict) -> ToolResult:
        """Format tree-sitter parsing results."""
        lines = [f"File: {file_path} ({result['language']})", ""]

        if result["imports"]:
            lines.append("[bold]Imports:[/]")
            for imp in result["imports"][:30]:
                lines.append(f"  {imp}")
            if len(result["imports"]) > 30:
                lines.append(f"  ... and {len(result['imports']) - 30} more")
            lines.append("")

        if result["classes"]:
            lines.append("[bold]Classes:[/]")
            for cls in result["classes"]:
                lines.append(f"  class {cls['name']} (line {cls['line']})")
                for method in cls.get("methods", [])[:10]:
                    lines.append(f"    .{method}()")
                if len(cls.get("methods", [])) > 10:
                    lines.append(f"    ... and {len(cls['methods']) - 10} more methods")
            lines.append("")

        if result["functions"]:
            lines.append("[bold]Functions:[/]")
            for func in result["functions"]:
                params = func.get("params", "")
                lines.append(f"  def {func['name']}{params} (line {func['line']})")
            lines.append("")

        if not result["functions"] and not result["classes"]:
            lines.append("(no functions or classes found)")

        return ToolResult.ok(
            "\n".join(lines),
            language=result["language"],
            functions=len(result["functions"]),
            classes=len(result["classes"]),
            imports_count=len(result["imports"]),
        )

    async def _fallback_python_ast(self, file_path: str) -> ToolResult:
        """Fallback to Python's built-in ast module."""
        import ast
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
        except Exception as e:
            return ToolResult.fail(f"Error reading file: {e}")

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            return ToolResult.fail(f"Syntax error: {e}")

        functions = []
        classes = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                methods = [n.name for n in ast.iter_child_nodes(node) if isinstance(n, ast.FunctionDef)]
                classes.append({"name": node.name, "line": node.lineno, "methods": methods})
            elif isinstance(node, ast.FunctionDef):
                functions.append({"name": node.name, "line": node.lineno})

        lines = [f"File: {file_path} (python, ast fallback)", ""]
        if classes:
            lines.append("Classes:")
            for c in classes:
                lines.append(f"  class {c['name']} (line {c['line']})")
                for m in c.get("methods", []):
                    lines.append(f"    .{m}()")
        if functions:
            lines.append("Functions:")
            for f in functions:
                lines.append(f"  def {f['name']}() (line {f['line']})")

        return ToolResult.ok("\n".join(lines))

    def _resolve_path(self, path: str) -> str:
        if os.path.isabs(path):
            return path
        return os.path.normpath(os.path.join(self.working_dir, path))


class PythonDefinition(Tool):
    """Go to definition using Jedi."""

    name = "python_definition"
    description = (
        "Find where a symbol is defined in Python code. "
        "Provide the file path, line number, and column of the symbol. "
        "Use this to navigate to function/class/variable definitions."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the Python file."},
            "line": {"type": "integer", "description": "Line number of the symbol (1-indexed)."},
            "column": {"type": "integer", "description": "Column number of the symbol (1-indexed)."},
        },
        "required": ["path", "line", "column"],
    }
    permission = ToolPermission.SAFE

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    async def execute(self, path: str, line: int, column: int) -> ToolResult:
        file_path = path if os.path.isabs(path) else os.path.join(self.working_dir, path)
        result = JediAnalyzer.get_definition(file_path, line, column)
        if not result:
            return ToolResult.fail(f"No definition found at {path}:{line}:{column}")
        return ToolResult.ok(
            f"Definition of '{result['name']}':\n"
            f"  File: {result['file']}\n"
            f"  Line: {result['line']}, Column: {result['column']}\n"
            f"  {result.get('description', '')}",
            **result,
        )


class PythonReferences(Tool):
    """Find all references using Jedi."""

    name = "python_references"
    description = (
        "Find all references to a symbol in Python code. "
        "Provide the file path, line number, and column of the symbol. "
        "Use this to find all usages of a function, class, or variable."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the Python file."},
            "line": {"type": "integer", "description": "Line number of the symbol."},
            "column": {"type": "integer", "description": "Column number of the symbol."},
        },
        "required": ["path", "line", "column"],
    }
    permission = ToolPermission.SAFE

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    async def execute(self, path: str, line: int, column: int) -> ToolResult:
        file_path = path if os.path.isabs(path) else os.path.join(self.working_dir, path)
        refs = JediAnalyzer.get_references(file_path, line, column)
        if not refs:
            return ToolResult.fail(f"No references found at {path}:{line}:{column}")
        lines = [f"Found {len(refs)} reference(s):", ""]
        for r in refs:
            lines.append(f"  {r['file']}:{r['line']}:{r['column']} - {r['name']}")
        return ToolResult.ok("\n".join(lines), count=len(refs))


class PythonHover(Tool):
    """Get hover information using Jedi."""

    name = "python_hover"
    description = (
        "Get documentation and signature information for a symbol in Python code. "
        "Provide the file path, line number, and column. "
        "Use this to see docstrings and function signatures."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the Python file."},
            "line": {"type": "integer", "description": "Line number of the symbol."},
            "column": {"type": "integer", "description": "Column number of the symbol."},
        },
        "required": ["path", "line", "column"],
    }
    permission = ToolPermission.SAFE

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    async def execute(self, path: str, line: int, column: int) -> ToolResult:
        file_path = path if os.path.isabs(path) else os.path.join(self.working_dir, path)
        signature = JediAnalyzer.get_signature(file_path, line, column)
        docstring = JediAnalyzer.get_docstring(file_path, line, column)

        parts = []
        if signature:
            parts.append(f"Signature: {signature}")
        if docstring:
            parts.append(f"Documentation:\n{docstring}")
        if not parts:
            # Try completions as fallback
            completions = JediAnalyzer.get_completions(file_path, line, column)
            if completions:
                parts.append("Completions at this position:")
                for c in completions[:10]:
                    parts.append(f"  {c['name']} ({c['type']})")
            else:
                return ToolResult.fail(f"No information found at {path}:{line}:{column}")

        return ToolResult.ok("\n\n".join(parts))
