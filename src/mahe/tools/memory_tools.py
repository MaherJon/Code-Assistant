"""Memory management tools for persistent project memory.

Tools: save_memory, recall_memory, list_memories
"""

import logging
from typing import Optional

from mahe.tools.base import Tool, ToolPermission, ToolResult
from mahe.context.persistent import PersistentMemory, MemoryEntry

logger = logging.getLogger("mahe.tools.memory")


class SaveMemory(Tool):
    """Save a fact to persistent project memory."""

    name = "save_memory"
    description = (
        "Save a fact, preference, or decision to persistent project memory. "
        "This memory will be available in future sessions. "
        "Use this when the user explicitly asks to remember something, "
        "or when you discover important project conventions worth preserving. "
        "Each memory needs a unique kebab-case name (e.g., 'api-conventions', 'db-schema')."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Unique kebab-case name for this memory (e.g., 'coding-conventions')."
            },
            "description": {
                "type": "string",
                "description": "One-line summary used for relevance matching in future searches."
            },
            "content": {
                "type": "string",
                "description": "The full content of the memory (markdown). Include all details."
            },
            "mem_type": {
                "type": "string",
                "enum": ["project", "user", "feedback", "reference"],
                "description": "Memory type: project (architecture), user (preferences), feedback (corrections), reference (pointers).",
                "default": "project",
            },
        },
        "required": ["name", "description", "content"],
    }
    permission = ToolPermission.SAFE

    def __init__(self, project_root: str = "."):
        self.project_root = project_root

    async def execute(
        self, name: str, description: str, content: str, mem_type: str = "project"
    ) -> ToolResult:
        persistent = PersistentMemory(self.project_root)
        entry = MemoryEntry(
            name=name,
            description=description,
            content=content,
            metadata={"type": mem_type},
        )
        persistent.add(entry)
        return ToolResult.ok(
            f"Memory saved: '{name}'\nDescription: {description}\nType: {mem_type}",
            name=name, mem_type=mem_type,
        )


class RecallMemory(Tool):
    """Search and retrieve persistent memories."""

    name = "recall_memory"
    description = (
        "Search and retrieve facts from persistent project memory. "
        "Returns matching memories based on keyword search. "
        "Use this to recall project conventions, architecture decisions, "
        "or user preferences saved from previous sessions."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query to find relevant memories."
            },
        },
        "required": ["query"],
    }
    permission = ToolPermission.SAFE

    def __init__(self, project_root: str = "."):
        self.project_root = project_root

    async def execute(self, query: str) -> ToolResult:
        persistent = PersistentMemory(self.project_root)
        results = persistent.search(query)

        if not results:
            return ToolResult.ok("No matching memories found.", count=0)

        lines = [f"Found {len(results)} matching memories:", ""]
        for entry in results:
            # Truncate long content for display
            content_preview = entry.content[:300]
            if len(entry.content) > 300:
                content_preview += "..."
            lines.append(f"### {entry.description or entry.name}")
            lines.append(f"Name: `{entry.name}` | Type: {entry.metadata.get('type', 'project')}")
            lines.append(f"Updated: {entry.updated_at or 'unknown'}")
            lines.append("")
            lines.append(content_preview)
            lines.append("")

        return ToolResult.ok("\n".join(lines), count=len(results))


class ListMemories(Tool):
    """List all persistent memories."""

    name = "list_memories"
    description = (
        "List all stored persistent project memories. "
        "Returns name, description, and type for each memory."
    )
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    permission = ToolPermission.SAFE

    def __init__(self, project_root: str = "."):
        self.project_root = project_root

    async def execute(self) -> ToolResult:
        persistent = PersistentMemory(self.project_root)
        entries = persistent.list_all()

        if not entries:
            return ToolResult.ok("No persistent memories stored yet.")

        lines = [f"Found {len(entries)} memories:", ""]
        for entry in entries:
            mem_type = entry.metadata.get("type", "project")
            lines.append(
                f"- **{entry.name}**: {entry.description} "
                f"[{mem_type}] ({entry.updated_at or 'unknown'})"
            )

        return ToolResult.ok("\n".join(lines), count=len(entries))
