"""Shared test helper classes that can be imported directly."""

from typing import Any, AsyncIterator, Dict, List, Optional

from codeassistant.llm.adapter import LLMAdapter, LLMResponse, LLMStreamChunk


class MockLLMAdapter(LLMAdapter):
    """Mock LLM adapter for testing.

    Returns predetermined responses for testing the agent loop.
    """

    def __init__(self, responses: List[LLMResponse] = None):
        self.responses = responses or []
        self.call_history: List[Dict] = []
        self._response_index = 0

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
    ) -> LLMResponse:
        self.call_history.append({
            "messages": messages,
            "tools": tools,
            "stream": stream,
        })
        if self._response_index < len(self.responses):
            resp = self.responses[self._response_index]
            self._response_index += 1
            return resp
        return LLMResponse(content="Done.", finish_reason="stop")

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        self.call_history.append({
            "messages": messages,
            "tools": tools,
        })

        if self._response_index < len(self.responses):
            resp = self.responses[self._response_index]
            self._response_index += 1

            # Stream the content character by character
            if resp.content:
                for char in resp.content:
                    yield LLMStreamChunk(content_delta=char)

            # Yield tool calls
            if resp.tool_calls:
                for tc in resp.tool_calls:
                    import json
                    yield LLMStreamChunk(
                        tool_call_delta={
                            "index": 0,
                            "id": tc.id,
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        }
                    )

            yield LLMStreamChunk(finish_reason=resp.finish_reason)
        else:
            yield LLMStreamChunk(content_delta="Done.")
            yield LLMStreamChunk(finish_reason="stop")

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    def count_message_tokens(self, messages: List[Dict[str, Any]]) -> int:
        total = 0
        for msg in messages:
            total += self.count_tokens(msg.get("content", ""))
        return total

    def add_response(self, response: LLMResponse) -> None:
        """Add a response to the queue."""
        self.responses.append(response)

    def reset(self) -> None:
        """Reset call history."""
        self.call_history = []
        self._response_index = 0
