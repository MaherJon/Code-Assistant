"""Tests for the ReAct agent loop."""

import pytest

from mahe.core.agent import ReActAgent, AgentState
from mahe.core.prompts import build_system_prompt
from mahe.llm.adapter import LLMResponse, ToolCall
from mahe.context.memory import SessionMemory
from mahe.context.manager import ContextBuilder
from mahe.context.project import ProjectConfig
from mahe.tools.base import ToolRegistry
from mahe.tools.file_tools import ReadFile, WriteFile
from mahe.utils.permissions import PermissionChecker, PermissionPolicy

from tests.helpers import MockLLMAdapter


@pytest.fixture
def agent_setup(temp_dir):
    """Set up all components needed for an agent."""
    # LLM
    mock_llm = MockLLMAdapter()

    # Memory
    memory = SessionMemory(
        system_prompt=build_system_prompt(temp_dir),
        max_tokens=100_000,
    )

    # Context builder
    project_config = ProjectConfig(project_root=temp_dir)
    context_builder = ContextBuilder(
        memory=memory,
        project_config=project_config,
        max_tokens=100_000,
    )

    # Tools
    tool_registry = ToolRegistry()
    tool_registry.register(ReadFile(working_dir=temp_dir))
    tool_registry.register(WriteFile(working_dir=temp_dir))

    # Permissions
    permission_checker = PermissionChecker(PermissionPolicy.auto())  # Auto-safe for testing

    # Agent
    agent = ReActAgent(
        llm=mock_llm,
        context_builder=context_builder,
        tool_registry=tool_registry,
        permission_checker=permission_checker,
    )

    return agent, mock_llm, temp_dir


class TestReActAgent:
    """Tests for the ReAct agent loop."""

    @pytest.mark.asyncio
    async def test_simple_chat_response(self, agent_setup):
        """Test that agent returns text response without tool calls."""
        agent, mock_llm, temp_dir = agent_setup

        # Set up mock to return a simple text response
        mock_llm.add_response(LLMResponse(
            content="Hello! How can I help you today?",
            finish_reason="stop",
        ))

        result = await agent.run("Hi!", temp_dir)
        assert "Hello!" in result
        assert agent.state == AgentState.COMPLETED
        assert len(mock_llm.call_history) == 1

    @pytest.mark.asyncio
    async def test_agent_uses_tool(self, agent_setup):
        """Test that agent can use a tool and continue."""
        agent, mock_llm, temp_dir = agent_setup

        # First response: tool call to read a file
        mock_llm.add_response(LLMResponse(
            content="Let me read the file.",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="read_file",
                    arguments={"path": "hello.py"},
                )
            ],
            finish_reason="tool_calls",
        ))

        # Second response: final answer after reading
        mock_llm.add_response(LLMResponse(
            content="I've read the file. It contains a hello function.",
            finish_reason="stop",
        ))

        # Create the file first
        import os
        with open(os.path.join(temp_dir, "hello.py"), "w") as f:
            f.write("def hello():\n    return 'Hello, World!'\n")

        result = await agent.run("Read hello.py", temp_dir)
        assert "hello function" in result
        assert agent.state == AgentState.COMPLETED
        assert len(mock_llm.call_history) == 2  # Two LLM calls

    @pytest.mark.asyncio
    async def test_agent_handles_tool_error(self, agent_setup):
        """Test agent gracefully handles tool errors."""
        agent, mock_llm, temp_dir = agent_setup

        # Tool call to a non-existent file
        mock_llm.add_response(LLMResponse(
            content="Let me check.",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="read_file",
                    arguments={"path": "nonexistent.py"},
                )
            ],
            finish_reason="tool_calls",
        ))

        # Second response after error
        mock_llm.add_response(LLMResponse(
            content="The file doesn't exist.",
            finish_reason="stop",
        ))

        result = await agent.run("Check nonexistent.py", temp_dir)
        assert agent.state == AgentState.COMPLETED

    @pytest.mark.asyncio
    async def test_agent_max_iterations(self, agent_setup):
        """Test that agent stops after max iterations."""
        agent, mock_llm, temp_dir = agent_setup

        # Keep returning tool calls to force max iterations
        for _ in range(ReActAgent.MAX_ITERATIONS + 5):
            mock_llm.add_response(LLMResponse(
                content="Let me keep reading...",
                tool_calls=[
                    ToolCall(
                        id="call_x",
                        name="read_file",
                        arguments={"path": "hello.py"},
                    )
                ],
                finish_reason="tool_calls",
            ))

        # Create a file to read
        import os
        with open(os.path.join(temp_dir, "hello.py"), "w") as f:
            f.write("test\n")

        result = await agent.run("Keep reading", temp_dir)
        assert "Maximum" in result or "tool iterations" in result

    @pytest.mark.asyncio
    async def test_unknown_tool(self, agent_setup):
        """Test handling of unknown tool calls."""
        agent, mock_llm, temp_dir = agent_setup

        mock_llm.add_response(LLMResponse(
            content="Trying unknown tool.",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="nonexistent_tool",
                    arguments={},
                )
            ],
            finish_reason="tool_calls",
        ))

        mock_llm.add_response(LLMResponse(
            content="The tool doesn't exist.",
            finish_reason="stop",
        ))

        result = await agent.run("Use bad tool", temp_dir)
        assert agent.state == AgentState.COMPLETED

    def test_agent_initial_state(self, agent_setup):
        agent, _, _ = agent_setup
        assert agent.state == AgentState.IDLE

    def test_cancel(self, agent_setup):
        agent, _, _ = agent_setup
        agent.cancel()
        assert agent.state == AgentState.CANCELLED
        assert agent._cancelled is True


class TestBuildSystemPrompt:
    """Tests for system prompt building."""

    def test_basic_prompt(self):
        prompt = build_system_prompt("/test/dir")
        assert "/test/dir" in prompt
        assert "MAHE" in prompt

    def test_with_project_context(self):
        prompt = build_system_prompt("/test/dir", "Project: My App")
        assert "Project: My App" in prompt
        assert "<project-context>" not in prompt  # should be stripped
