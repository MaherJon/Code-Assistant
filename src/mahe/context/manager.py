"""Context builder: assembles full context for each LLM call."""

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from mahe.context.memory import SessionMemory
from mahe.context.project import ProjectConfig
from mahe.context.compression import ContextCompressor
from mahe.core.prompts import build_system_prompt

logger = logging.getLogger("mahe.context")


@dataclass
class AgentContext:
    """All context assembled for an LLM invocation."""
    messages: List[Dict[str, Any]]    # Formatted for API
    working_dir: str                   # Current working directory
    available_tools: List[Dict]        # Tool schemas
    project_config: str = ""           # .aiassist.md content


class ContextBuilder:
    """Assembles the full context for each LLM invocation.

    Responsibilities:
    - Pull recent messages from SessionMemory
    - Add working directory info as system context
    - Include .aiassist.md project configuration
    - Ensure total context fits within model's token limit
    - Inject tool definitions into the system prompt
    """

    def __init__(
        self,
        memory: SessionMemory,
        project_config: ProjectConfig,
        max_tokens: int = 100_000,
        compressor: Optional[ContextCompressor] = None,
    ):
        self.memory = memory
        self.project_config = project_config
        self.max_tokens = max_tokens
        self._system_prompt_base = ""
        self.compressor = compressor

    async def build(
        self,
        working_dir: str,
        tool_schemas: Optional[List[Dict[str, Any]]] = None,
        force_rebuild: bool = False,
    ) -> AgentContext:
        """Build the full context for the next LLM call.

        Args:
            working_dir: Current working directory
            tool_schemas: Available tool definitions (OpenAI format)
            force_rebuild: Force rebuilding the system prompt

        Returns:
            AgentContext with formatted messages and metadata
        """
        # Reload project config (may have changed)
        self.project_config.reload()
        project_ctx = self.project_config.get_system_context()

        # Build system prompt if needed
        if not self._system_prompt_base or force_rebuild:
            self._system_prompt_base = build_system_prompt(
                working_dir=working_dir,
                project_context=project_ctx,
            )

            # Update the session memory's system message
            self._reset_system_message()

        # Check if compression is needed before trimming
        reserve = 8000  # Reserve for LLM response
        target = self.max_tokens - reserve
        non_system_count = sum(1 for m in self.memory.history._messages
                               if hasattr(m, 'role') and m.role.value != "system")

        if self.compressor and self.compressor.should_compress(
            non_system_count, self.memory.total_tokens()
        ):
            # Run compression (replaces old messages with summary)
            new_messages, saved = await self.memory._compress_with(self.compressor)
            if saved > 0:
                logger.info("Compression saved %d tokens", saved)

        # Trim history to fit within token budget
        self.memory.trim(target)

        # Get formatted messages
        messages = self.memory.get_messages_for_llm()

        return AgentContext(
            messages=messages,
            working_dir=working_dir,
            available_tools=tool_schemas or [],
            project_config=self.project_config.content,
        )

    def _reset_system_message(self) -> None:
        """Replace the system message in the session memory."""
        from mahe.core.message import Message, MessageRole

        # Remove old system messages
        old_messages = self.memory.history._messages
        non_system = [m for m in old_messages if m.role != MessageRole.SYSTEM]
        self.memory.history._messages = [Message.system(self._system_prompt_base)] + non_system

    async def update_working_dir(self, working_dir: str) -> None:
        """Update the working directory (rebuilds system prompt)."""
        await self.build(working_dir, force_rebuild=True)
