"""Abstract LLM adapter interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Literal, Optional


@dataclass
class ToolCall:
    """Represents a tool call from the LLM."""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    """Response from an LLM chat completion."""
    content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: Literal["stop", "tool_calls", "length", "error"] = "stop"
    usage: Optional[Dict[str, int]] = None  # {"prompt_tokens": N, "completion_tokens": M}


@dataclass
class LLMStreamChunk:
    """A single chunk from a streaming LLM response."""
    content_delta: Optional[str] = None
    tool_call_delta: Optional[Dict] = None
    finish_reason: Optional[str] = None


class LLMAdapter(ABC):
    """Abstract interface for all LLM providers.

    Implementations handle the specifics of each provider's API
    while presenting a unified interface to the rest of CodeAssistant.
    """

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
    ) -> LLMResponse:
        """Send a chat completion request.

        Args:
            messages: List of message dicts in OpenAI format
            tools: Optional list of tool definitions in OpenAI function-calling format
            stream: Whether to use streaming (streaming is handled via chat_stream)

        Returns:
            LLMResponse with content and/or tool calls
        """
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Streaming version of chat().

        Yields chunks as they arrive from the API.
        """
        ...

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Estimate the number of tokens in a text string."""
        ...

    @abstractmethod
    def count_message_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Estimate token count for a list of messages."""
        ...

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts.

        Default implementation raises NotImplementedError.
        Override in providers that support embeddings.
        """
        raise NotImplementedError("Embeddings not supported by this adapter")
