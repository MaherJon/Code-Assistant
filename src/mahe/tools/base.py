"""Tool base class, ToolResult, and ToolRegistry."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Callable


class ToolPermission(Enum):
    """Permission level for a tool call."""
    SAFE = "safe"               # Always auto-execute
    NEEDS_CONFIRM = "confirm"   # Ask user before executing
    BLOCKED = "blocked"         # Never allow


@dataclass
class ToolResult:
    """Result from executing a tool."""
    success: bool
    output: str
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, output: str, **metadata) -> "ToolResult":
        """Create a successful result."""
        return cls(success=True, output=output, metadata=metadata)

    @classmethod
    def fail(cls, error: str, output: str = "") -> "ToolResult":
        """Create a failed result."""
        return cls(success=False, output=output, error=error)


class Tool(ABC):
    """Abstract base class for all tools.

    Each tool has:
    - A unique name (used for LLM function calling)
    - A description (tells the LLM when/how to use it)
    - A JSON Schema for parameters
    - A permission level
    - An execute method

    Example:
        class ReadFile(Tool):
            name = "read_file"
            description = "Read a file from the filesystem"
            parameters = {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"}
                },
                "required": ["path"]
            }
            permission = ToolPermission.SAFE

            async def execute(self, path: str) -> ToolResult:
                ...
    """

    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}
    permission: ToolPermission = ToolPermission.NEEDS_CONFIRM

    @abstractmethod
    async def execute(self, **params) -> ToolResult:
        """Execute the tool with the given parameters."""
        ...

    def to_openai_schema(self) -> Dict[str, Any]:
        """Convert to OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }

    def render_input(self, **params) -> str:
        """Human-readable representation of the tool call.

        Used in permission confirmation prompts and status display.
        """
        # Show first few params for readability
        parts = []
        for key, value in params.items():
            val_str = str(value)
            if len(val_str) > 80:
                val_str = val_str[:77] + "..."
            parts.append(f"{key}={val_str}")
        return f"{self.name}({', '.join(parts)})"


class ToolRegistry:
    """Central registry for all available tools.

    Tools are registered with their name and can be looked up
    or listed in OpenAI function-calling format.
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._on_tool_start: Optional[Callable] = None
        self._on_tool_complete: Optional[Callable] = None

    def register(self, tool: Tool) -> None:
        """Register a tool instance."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        """Look up a tool by name."""
        return self._tools.get(name)

    def list_all(self) -> List[Tool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_openai_schemas(self) -> List[Dict[str, Any]]:
        """Get all tools as OpenAI function schemas."""
        return [t.to_openai_schema() for t in self._tools.values()]

    def get_tool_names(self) -> List[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    async def execute(self, name: str, **params) -> ToolResult:
        """Execute a tool by name.

        Fires on_tool_start/on_tool_complete callbacks for UI updates.
        """
        tool = self._tools.get(name)
        if not tool:
            return ToolResult.fail(f"Unknown tool: {name}")

        if self._on_tool_start:
            self._on_tool_start(tool, params)

        try:
            result = await tool.execute(**params)
        except Exception as e:
            result = ToolResult.fail(str(e))

        if self._on_tool_complete:
            self._on_tool_complete(tool, params, result)

        return result

    def set_callbacks(
        self,
        on_start: Optional[Callable] = None,
        on_complete: Optional[Callable] = None,
    ) -> None:
        """Set callbacks for tool execution monitoring."""
        self._on_tool_start = on_start
        self._on_tool_complete = on_complete
