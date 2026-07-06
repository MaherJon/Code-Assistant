"""Message types and conversation history management."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class MessageRole(Enum):
    """Message sender roles."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class Message:
    """A single message in the conversation.

    Follows OpenAI's message format for compatibility.
    """
    role: MessageRole
    content: str
    tool_call_id: Optional[str] = None       # For tool result messages
    tool_calls: Optional[List[Dict]] = None   # For assistant messages with tool calls
    name: Optional[str] = None               # Optional tool name for tool messages
    timestamp: datetime = field(default_factory=datetime.now)
    token_count: int = 0                     # Cached token estimate

    def to_dict(self) -> Dict[str, Any]:
        """Convert to OpenAI-compatible message dict."""
        msg: Dict[str, Any] = {
            "role": self.role.value,
            "content": self.content or "",
        }
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        if self.name:
            msg["name"] = self.name
        return msg

    @classmethod
    def system(cls, content: str) -> "Message":
        """Create a system message."""
        return cls(role=MessageRole.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> "Message":
        """Create a user message."""
        return cls(role=MessageRole.USER, content=content)

    @classmethod
    def assistant(cls, content: str = "", tool_calls: List[Dict] = None) -> "Message":
        """Create an assistant message."""
        return cls(role=MessageRole.ASSISTANT, content=content, tool_calls=tool_calls)

    @classmethod
    def tool_result(cls, tool_call_id: str, content: str, tool_name: str = None) -> "Message":
        """Create a tool result message."""
        return cls(role=MessageRole.TOOL, content=content, tool_call_id=tool_call_id, name=tool_name)


class MessageHistory:
    """Stores and manages conversation history with token-aware trimming.

    Provides methods to add messages, retrieve recent history,
    and trim to fit within a token budget.
    """

    def __init__(self, max_tokens: int = 100_000):
        self._messages: List[Message] = []
        self.max_tokens = max_tokens
        self._total_tokens = 0

    def add(self, message: Message) -> None:
        """Add a message to the history."""
        self._messages.append(message)
        # Rough estimate: 4 chars ≈ 1 token
        self._total_tokens += len(message.content) // 4 + 10  # +10 for overhead

    def get_all(self) -> List[Message]:
        """Get all messages."""
        return list(self._messages)

    def get_recent(self, n: int) -> List[Message]:
        """Get the n most recent messages."""
        return self._messages[-n:] if n > 0 else []

    def total_tokens(self) -> int:
        """Estimated total token count."""
        return self._total_tokens

    def to_dict_list(self) -> List[Dict[str, Any]]:
        """Convert all messages to OpenAI-compatible format."""
        return [m.to_dict() for m in self._messages]

    def trim_to_fit(self, target_tokens: int) -> List[Message]:
        """Trim messages to fit within target token budget.

        Always preserves the system message and at least the
        last user-assistant-tool exchange.

        Args:
            target_tokens: Maximum tokens to target

        Returns:
            List of kept messages
        """
        if self._total_tokens <= target_tokens:
            return self._messages

        # Find system messages (always keep)
        system_msgs = [m for m in self._messages if m.role == MessageRole.SYSTEM]
        system_tokens = sum(len(m.content) // 4 for m in system_msgs)

        # Work backwards from the end, keeping recent messages
        available = target_tokens - system_tokens - 1000  # Reserve 1k for safety
        kept = list(system_msgs)
        current_tokens = 0

        for msg in reversed(self._messages):
            if msg.role == MessageRole.SYSTEM:
                continue
            msg_tokens = len(msg.content) // 4 + 10
            if current_tokens + msg_tokens > available:
                break
            current_tokens += msg_tokens
            kept.insert(len(system_msgs), msg)

        # Ensure we have at least the last exchange
        last_exchange = []
        for msg in reversed(self._messages):
            if msg.role != MessageRole.SYSTEM:
                last_exchange.insert(0, msg)
                if msg.role == MessageRole.USER:
                    break

        for msg in last_exchange:
            if msg not in kept:
                kept.append(msg)

        self._messages = kept
        return kept

    def clear(self, keep_system: bool = True) -> None:
        """Clear all messages, optionally keeping system messages."""
        if keep_system:
            self._messages = [m for m in self._messages if m.role == MessageRole.SYSTEM]
        else:
            self._messages = []
        self._total_tokens = 0
