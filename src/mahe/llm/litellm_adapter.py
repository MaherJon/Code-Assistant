"""LiteLLM-based LLM adapter supporting 100+ model providers.

Supports: OpenAI, Anthropic, DeepSeek, Qwen, Ollama, and any OpenAI-compatible API.
"""

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import litellm

from mahe.llm.adapter import LLMAdapter, LLMResponse, LLMStreamChunk, ToolCall
from mahe.utils.errors import ModelError

logger = logging.getLogger("mahe.llm")

# Enable LiteLLM debug logging only at DEBUG level
litellm.set_verbose = False


class LiteLLMAdapter(LLMAdapter):
    """LLM adapter using LiteLLM for multi-provider support.

    LiteLLM provides a single interface (OpenAI-compatible) for 100+ models.
    This adapter handles the translation and error handling.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 8192,
    ):
        self.model = self._resolve_model(model)
        self.api_key = api_key
        self.api_base = api_base
        self.temperature = temperature
        self.max_tokens = max_tokens

        # Configure LiteLLM
        if api_key:
            # LiteLLM picks up keys automatically, but we can be explicit
            pass
        if api_base:
            litellm.api_base = api_base

        logger.info("LiteLLM adapter initialized: model=%s", self.model)

    def _resolve_model(self, model: str) -> str:
        """Resolve the model name for LiteLLM.

        LiteLLM expects model names like 'gpt-4o', 'claude-sonnet-5',
        or 'provider/model_name' for explicit routing.
        """
        # If already in provider/model format, return as-is
        if "/" in model:
            return model
        return model

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
    ) -> LLMResponse:
        """Send a non-streaming chat completion."""
        try:
            kwargs = self._build_request_kwargs(messages, tools, stream=False)

            # litellm.acompletion is the async version
            response = await litellm.acompletion(**kwargs)

            return self._parse_response(response)

        except litellm.exceptions.APIConnectionError as e:
            raise ModelError(f"API connection failed: {e}") from e
        except litellm.exceptions.RateLimitError as e:
            raise ModelError(f"Rate limit exceeded. Please wait and try again: {e}") from e
        except litellm.exceptions.AuthenticationError as e:
            raise ModelError(f"Authentication failed. Check your API key: {e}") from e
        except litellm.exceptions.BadRequestError as e:
            raise ModelError(f"Bad request - check model name and parameters: {e}") from e
        except Exception as e:
            logger.error("Unexpected error in LLM call: %s", e)
            raise ModelError(f"LLM call failed: {e}") from e

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Streaming chat completion."""
        try:
            kwargs = self._build_request_kwargs(messages, tools, stream=True)

            response = await litellm.acompletion(**kwargs)

            # Process streaming response
            tool_call_buffer: Dict[int, Dict] = {}  # index -> {id, name, arguments_str}

            async for chunk in response:
                # Sometimes LiteLLM returns the chunk directly, sometimes wrapped
                if hasattr(chunk, "choices") and chunk.choices:
                    choice = chunk.choices[0]
                    delta = choice.delta if hasattr(choice, "delta") else None

                    if delta is None:
                        continue

                    # Text content delta
                    content = getattr(delta, "content", None) or ""
                    if content:
                        yield LLMStreamChunk(content_delta=content)

                    # Tool call deltas
                    if hasattr(delta, "tool_calls") and delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = getattr(tc_delta, "index", 0)

                            if idx not in tool_call_buffer:
                                tool_call_buffer[idx] = {
                                    "id": "",
                                    "name": "",
                                    "arguments_str": "",
                                }

                            if hasattr(tc_delta, "id") and tc_delta.id:
                                tool_call_buffer[idx]["id"] = tc_delta.id
                            if hasattr(tc_delta, "function"):
                                func = tc_delta.function
                                if hasattr(func, "name") and func.name:
                                    tool_call_buffer[idx]["name"] = func.name
                                if hasattr(func, "arguments") and func.arguments:
                                    tool_call_buffer[idx]["arguments_str"] += func.arguments

                            yield LLMStreamChunk(
                                tool_call_delta={
                                    "index": idx,
                                    "id": tool_call_buffer[idx]["id"],
                                    "name": tool_call_buffer[idx]["name"],
                                    "arguments": tool_call_buffer[idx]["arguments_str"],
                                }
                            )

                    # Finish reason
                    finish = getattr(choice, "finish_reason", None)
                    if finish:
                        yield LLMStreamChunk(finish_reason=finish)

        except litellm.exceptions.APIConnectionError as e:
            raise ModelError(f"API connection failed: {e}") from e
        except litellm.exceptions.RateLimitError as e:
            raise ModelError(f"Rate limit exceeded: {e}") from e
        except Exception as e:
            logger.error("Unexpected error in streaming: %s", e)
            raise ModelError(f"Streaming failed: {e}") from e

    def count_tokens(self, text: str) -> int:
        """Estimate token count using tiktoken."""
        try:
            return litellm.token_counter(model=self.model, text=text)
        except Exception:
            # Fallback: rough estimate (4 chars ≈ 1 token for English)
            return len(text) // 4

    def count_message_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Estimate token count for a list of messages."""
        total = 0
        for msg in messages:
            content = msg.get("content", "") or ""
            total += self.count_tokens(content)
            # Add overhead for tool calls
            if "tool_calls" in msg:
                total += self.count_tokens(json.dumps(msg["tool_calls"]))
        return total

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts using LiteLLM.

        Uses the model configured for embeddings (default: text-embedding-3-small).
        Falls back gracefully if the current model doesn't support embeddings.
        """
        try:
            # Use a dedicated embedding model
            embedding_model = "text-embedding-3-small"
            if self.api_key:
                # Try with provided key
                pass

            response = await litellm.aembedding(
                model=embedding_model,
                input=texts,
                api_key=self.api_key,
                api_base=self.api_base,
            )

            # Extract embedding vectors
            embeddings = []
            if hasattr(response, "data"):
                for item in response.data:
                    embeddings.append(item.embedding)
            return embeddings

        except Exception as e:
            logger.warning("Embedding failed: %s. Falling back to dummy embeddings.", e)
            # Fallback: return zero vectors (allows vector store to work in degraded mode)
            return [[0.0] * 128 for _ in texts]

    def _build_request_kwargs(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """Build the kwargs for litellm.acompletion."""
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": stream,
        }

        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base

        # Only include tools if provided
        if tools:
            kwargs["tools"] = tools
            # LiteLLM handles tool_choice automatically

        return kwargs

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse a non-streaming LiteLLM response into LLMResponse."""
        try:
            choice = response.choices[0]
            message = choice.message if hasattr(choice, "message") else None

            if message is None:
                return LLMResponse(content="", finish_reason="stop")

            content = getattr(message, "content", None) or ""

            tool_calls = []
            if hasattr(message, "tool_calls") and message.tool_calls:
                for tc in message.tool_calls:
                    func = tc.function if hasattr(tc, "function") else None
                    if func:
                        try:
                            arguments = json.loads(func.arguments)
                        except json.JSONDecodeError:
                            arguments = {}
                        tool_calls.append(ToolCall(
                            id=getattr(tc, "id", ""),
                            name=func.name,
                            arguments=arguments,
                        ))

            finish = getattr(choice, "finish_reason", "stop") or "stop"
            usage = None
            if hasattr(response, "usage"):
                u = response.usage
                usage = {
                    "prompt_tokens": getattr(u, "prompt_tokens", 0),
                    "completion_tokens": getattr(u, "completion_tokens", 0),
                    "total_tokens": getattr(u, "total_tokens", 0),
                }

            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                finish_reason=finish,
                usage=usage,
            )

        except Exception as e:
            logger.error("Failed to parse LLM response: %s", e)
            return LLMResponse(content="", finish_reason="error")
