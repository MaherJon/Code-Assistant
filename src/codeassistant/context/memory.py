"""Session memory wrapping MessageHistory with session-scoped concerns."""

import logging
import uuid
from typing import List, Tuple, TYPE_CHECKING

from codeassistant.core.message import Message, MessageHistory

if TYPE_CHECKING:
    from codeassistant.context.compression import ContextCompressor

logger = logging.getLogger("codeassistant.memory")


class SessionMemory:
    """Session-scoped conversation memory.

    Wraps MessageHistory with session identification and
    convenience methods for the ReAct agent loop.

    In Phase 3, this will add compression and vector storage.
    """

    def __init__(self, session_id: str = None, system_prompt: str = "", max_tokens: int = 100_000):
        self.session_id = session_id or str(uuid.uuid4())
        self.history = MessageHistory(max_tokens=max_tokens)

        # Always add system message first
        if system_prompt:
            self.history.add(Message.system(system_prompt))

    def add_user_message(self, content: str) -> None:
        """Add a user message."""
        self.history.add(Message.user(content))

    def add_assistant_message(self, content: str = "", tool_calls: List[dict] = None) -> None:
        """Add an assistant message."""
        self.history.add(Message.assistant(content, tool_calls))

    def add_tool_result(self, tool_call_id: str, result: str, tool_name: str = None) -> None:
        """Add a tool execution result."""
        self.history.add(Message.tool_result(tool_call_id, result, tool_name))

    def get_messages_for_llm(self) -> list:
        """Get messages formatted for the LLM API."""
        return self.history.to_dict_list()

    def total_tokens(self) -> int:
        """Estimated total token count."""
        return self.history.total_tokens()

    def trim(self, target_tokens: int) -> None:
        """Trim history to fit token budget."""
        self.history.trim_to_fit(target_tokens)

    def clear(self) -> None:
        """Clear all messages except system prompt."""
        self.history.clear(keep_system=True)

    def reset(self, new_system_prompt: str = None) -> None:
        """Full reset with optional new system prompt."""
        self.history.clear(keep_system=False)
        if new_system_prompt:
            self.history.add(Message.system(new_system_prompt))

    async def _compress_with(self, compressor: "ContextCompressor") -> Tuple[int, int]:
        """Run compression on the message history.

        Args:
            compressor: The ContextCompressor instance to use

        Returns:
            Tuple of (tokens_saved, new_message_count)
        """
        messages = self.history.get_all()
        new_messages, tokens_saved = await compressor.compress(messages)

        if tokens_saved > 0:
            self.history._messages = new_messages
            # Recalculate total tokens
            self.history._total_tokens = sum(
                len(m.content or "") // 4 + 10 for m in new_messages
            )
            logger.info(
                "Memory compressed: %d tokens saved, now %d messages",
                tokens_saved, len(new_messages),
            )

        return tokens_saved, len(new_messages)
