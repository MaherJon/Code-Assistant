"""ReAct Agent loop - the central reasoning engine.

Implements the ReAct (Reasoning + Acting) pattern:
1. Build context → 2. LLM thinks → 3. Execute tools → 4. Feed back → Repeat
"""

import json
import logging
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

from codeassistant.core.message import Message
from codeassistant.llm.adapter import LLMAdapter, LLMResponse, ToolCall
from codeassistant.tools.base import Tool, ToolPermission, ToolRegistry, ToolResult
from codeassistant.context.manager import ContextBuilder
from codeassistant.utils.permissions import PermissionChecker

logger = logging.getLogger("codeassistant.agent")


class AgentState(Enum):
    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


class ReActAgent:
    """Core agent implementing the ReAct loop.

    The agent receives a user query, then iteratively:
    1. Builds context (system prompt + history + tools + project config)
    2. Calls the LLM with streaming for real-time text output
    3. If the LLM returns tool calls, executes them (with permission checks)
    4. Feeds tool results back into the conversation
    5. Repeats until the LLM returns a text-only response

    Stopping conditions:
    - LLM returns text without tool calls (task complete)
    - User cancels (via confirmation callback)
    - Max iterations reached (prevents infinite loops)
    - Fatal error occurs
    """

    MAX_ITERATIONS = 50

    def __init__(
        self,
        llm: LLMAdapter,
        context_builder: ContextBuilder,
        tool_registry: ToolRegistry,
        permission_checker: PermissionChecker,
    ):
        self.llm = llm
        self.context = context_builder
        self.tools = tool_registry
        self.permissions = permission_checker
        self.state = AgentState.IDLE
        self._iteration = 0
        self._cancelled = False

        # Callbacks
        self._on_stream: Optional[Callable[[str], None]] = None
        self._on_tool_start: Optional[Callable[[Tool, Dict], None]] = None
        self._on_tool_result: Optional[Callable[[Tool, Dict, ToolResult], None]] = None
        self._on_confirm: Optional[Callable[[Tool, Dict], Awaitable[bool]]] = None

    def set_callbacks(
        self,
        on_stream: Optional[Callable[[str], None]] = None,
        on_tool_start: Optional[Callable[[Tool, Dict], None]] = None,
        on_tool_result: Optional[Callable[[Tool, Dict, ToolResult], None]] = None,
        on_confirm: Optional[Callable[[Tool, Dict], Awaitable[bool]]] = None,
    ) -> None:
        """Configure callbacks for UI integration."""
        self._on_stream = on_stream
        self._on_tool_start = on_tool_start
        self._on_tool_result = on_tool_result
        self._on_confirm = on_confirm

    async def run(self, user_input: str, working_dir: str) -> str:
        """Execute the ReAct loop for a user request.

        Args:
            user_input: Natural language request from the user
            working_dir: Current working directory

        Returns:
            Final textual response from the agent
        """
        self.state = AgentState.THINKING
        self._iteration = 0
        self._cancelled = False

        # Add user message to memory
        self.context.memory.add_user_message(user_input)

        accumulated_response = ""

        while self._iteration < self.MAX_ITERATIONS and not self._cancelled:
            self._iteration += 1
            logger.debug("Agent iteration %d", self._iteration)

            try:
                # 1. Build context
                ctx = await self.context.build(
                    working_dir=working_dir,
                    tool_schemas=self.tools.get_openai_schemas(),
                )

                # 2. Call LLM with streaming
                self.state = AgentState.THINKING
                response = await self._stream_llm_call(ctx)

                if self._cancelled:
                    break

                # 3. Process response
                if response.tool_calls:
                    # Tools were requested
                    self.state = AgentState.ACTING

                    # Save assistant message with tool calls
                    tc_dicts = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            }
                        }
                        for tc in response.tool_calls
                    ]
                    self.context.memory.add_assistant_message(
                        content=response.content or "",
                        tool_calls=tc_dicts,
                    )

                    # Execute each tool call sequentially
                    for tc in response.tool_calls:
                        if self._cancelled:
                            break
                        result = await self._execute_tool(tc)
                        # Add tool result to memory
                        self.context.memory.add_tool_result(
                            tool_call_id=tc.id,
                            result=result.output if result.success else f"Error: {result.error}",
                            tool_name=tc.name,
                        )

                    # Loop back for another iteration
                    continue

                else:
                    # Text-only response: task is complete
                    self.state = AgentState.COMPLETED
                    self.context.memory.add_assistant_message(content=response.content or "")
                    accumulated_response = response.content or ""
                    break

            except Exception as e:
                logger.error("Agent iteration %d failed: %s", self._iteration, e, exc_info=True)
                self.state = AgentState.ERROR
                accumulated_response = f"Error: {e}"
                break

        if self._iteration >= self.MAX_ITERATIONS:
            accumulated_response = (
                "Maximum number of tool iterations reached. "
                "The task may be too complex. Try breaking it into smaller steps."
            )

        return accumulated_response

    async def _stream_llm_call(self, ctx) -> LLMResponse:
        """Call the LLM with streaming, aggregating the response."""
        full_content = ""
        tool_call_buffer: Dict[int, Dict] = {}  # index -> {id, name, arguments_str}
        finish_reason = "stop"

        try:
            async for chunk in self.llm.chat_stream(
                messages=ctx.messages,
                tools=ctx.available_tools if ctx.available_tools else None,
            ):
                # Text delta
                if chunk.content_delta:
                    full_content += chunk.content_delta
                    if self._on_stream:
                        self._on_stream(chunk.content_delta)

                # Tool call delta
                if chunk.tool_call_delta:
                    tc = chunk.tool_call_delta
                    idx = tc.get("index", 0)
                    if idx not in tool_call_buffer:
                        tool_call_buffer[idx] = {
                            "id": "", "name": "", "arguments_str": ""
                        }
                    buf = tool_call_buffer[idx]
                    if tc.get("id"):
                        buf["id"] = tc["id"]
                    if tc.get("name"):
                        buf["name"] = tc["name"]
                    if tc.get("arguments"):
                        buf["arguments_str"] = tc["arguments"]

                # Finish
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason

        except Exception as e:
            logger.error("Stream error: %s", e)
            return LLMResponse(content=full_content or f"Error: {e}", finish_reason="error")

        # Build tool calls from buffer
        tool_calls = []
        for idx in sorted(tool_call_buffer.keys()):
            buf = tool_call_buffer[idx]
            if buf["name"]:
                try:
                    arguments = json.loads(buf["arguments_str"])
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
                tool_calls.append(ToolCall(
                    id=buf["id"] or f"call_{idx}",
                    name=buf["name"],
                    arguments=arguments,
                ))

        return LLMResponse(
            content=full_content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )

    async def _execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """Execute a single tool call with permission checks.

        Args:
            tool_call: The tool call to execute

        Returns:
            ToolResult from execution
        """
        tool = self.tools.get(tool_call.name)
        if not tool:
            return ToolResult.fail(f"Unknown tool: {tool_call.name}")

        params = tool_call.arguments

        # Notify UI
        if self._on_tool_start:
            self._on_tool_start(tool, params)

        # Check permissions
        permission = self.permissions.check(tool, params)

        if permission == ToolPermission.BLOCKED:
            result = ToolResult.fail(
                "Operation blocked by security policy. "
                "This command could be dangerous."
            )
            if self._on_tool_result:
                self._on_tool_result(tool, params, result)
            return result

        if permission == ToolPermission.NEEDS_CONFIRM:
            if self._on_confirm:
                self.state = AgentState.WAITING_CONFIRMATION
                approved = await self._on_confirm(tool, params)
                if not approved:
                    result = ToolResult.fail("User denied permission.")
                    if self._on_tool_result:
                        self._on_tool_result(tool, params, result)
                    return result
            else:
                result = ToolResult.fail(
                    "This operation requires confirmation. "
                    "Use interactive mode to approve tool calls."
                )
                if self._on_tool_result:
                    self._on_tool_result(tool, params, result)
                return result

        # Execute
        self.state = AgentState.ACTING
        try:
            result = await tool.execute(**params)
        except Exception as e:
            result = ToolResult.fail(str(e))

        if self._on_tool_result:
            self._on_tool_result(tool, params, result)

        return result

    def cancel(self) -> None:
        """Cancel the current agent run."""
        self._cancelled = True
        self.state = AgentState.CANCELLED
