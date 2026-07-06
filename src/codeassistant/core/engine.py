"""Engine orchestrator - wires together all CodeAssistant subsystems.

This is the central integration point. The CLI creates an Engine instance,
which owns and coordinates all subsystems: LLM, tools, permissions,
context, and agent.
"""

import asyncio
import logging
from typing import Optional

from codeassistant.core.config import CodeAssistantConfig
from codeassistant.core.agent import ReActAgent
from codeassistant.core.prompts import build_system_prompt
from codeassistant.context.memory import SessionMemory
from codeassistant.context.manager import ContextBuilder
from codeassistant.context.project import ProjectConfig
from codeassistant.llm.litellm_adapter import LiteLLMAdapter
from codeassistant.tools.base import ToolRegistry
from codeassistant.tools.file_tools import ReadFile, WriteFile, EditFile, GlobTool, GrepTool
from codeassistant.tools.shell_tools import BashTool
from codeassistant.tools.git_tools import GitStatus, GitDiff, GitLog, GitBranch, GitAdd, GitCommit
from codeassistant.tools.code_tools import AnalyzeCode, PythonDefinition, PythonReferences, PythonHover
from codeassistant.tools.memory_tools import SaveMemory, RecallMemory, ListMemories
from codeassistant.tools.test_tools import RunTests
from codeassistant.tools.subagent_tools import DelegateTask
from codeassistant.context.compression import ContextCompressor
from codeassistant.context.persistent import PersistentMemory
from codeassistant.core.subagent import SubAgentManager, SubAgentConfig
from codeassistant.utils.permissions import PermissionChecker, PermissionPolicy
from codeassistant.utils.sandbox import Sandbox

logger = logging.getLogger("codeassistant.engine")


class Engine:
    """Top-level orchestrator for CodeAssistant.

    Creates and wires together all subsystems based on configuration.
    Provides a single `process_query()` entry point for the CLI/REPL.

    Lifecycle:
    1. Created with a CodeAssistantConfig and working directory
    2. process_query() is called for each user input
    3. reset_session() clears conversation history
    """

    def __init__(self, config: CodeAssistantConfig, working_dir: str):
        self.config = config
        self.working_dir = working_dir
        self._agent: Optional[ReActAgent] = None
        self._tool_registry: Optional[ToolRegistry] = None
        self._permission_checker: Optional[PermissionChecker] = None

        self._init_subsystems()

    def _init_subsystems(self) -> None:
        """Initialize all subsystems."""
        # 1. Permission system
        policy = (
            PermissionPolicy.auto()
            if self.config.permission_mode == "auto_safe"
            else PermissionPolicy.default()
        )
        self._permission_checker = PermissionChecker(policy)

        # 2. Sandbox
        sandbox = Sandbox()

        # 3. Tool registry
        self._tool_registry = ToolRegistry()
        wd = self.working_dir
        self._tool_registry.register(ReadFile(working_dir=wd))
        self._tool_registry.register(WriteFile(working_dir=wd))
        self._tool_registry.register(EditFile(working_dir=wd))
        self._tool_registry.register(GlobTool(working_dir=wd))
        self._tool_registry.register(GrepTool(working_dir=wd))
        self._tool_registry.register(BashTool(working_dir=wd, sandbox=sandbox))
        self._tool_registry.register(GitStatus(working_dir=wd))
        self._tool_registry.register(GitDiff(working_dir=wd))
        self._tool_registry.register(GitLog(working_dir=wd))
        self._tool_registry.register(GitBranch(working_dir=wd))
        self._tool_registry.register(GitAdd(working_dir=wd))
        self._tool_registry.register(GitCommit(working_dir=wd))
        # Code intelligence tools
        self._tool_registry.register(AnalyzeCode(working_dir=wd))
        self._tool_registry.register(PythonDefinition(working_dir=wd))
        self._tool_registry.register(PythonReferences(working_dir=wd))
        self._tool_registry.register(PythonHover(working_dir=wd))
        # Memory tools
        self._tool_registry.register(SaveMemory(project_root=wd))
        self._tool_registry.register(RecallMemory(project_root=wd))
        self._tool_registry.register(ListMemories(project_root=wd))
        # Test tools
        self._tool_registry.register(RunTests(working_dir=wd))
        # SubAgent delegation tool (registered without manager, set later)
        self._delegate_tool = DelegateTask()
        self._tool_registry.register(self._delegate_tool)

        logger.info(
            "Engine initialized with %d tools: %s",
            len(self._tool_registry.list_all()),
            self._tool_registry.get_tool_names(),
        )

        # 4. LLM adapter (extracted for reuse by sub-agents)
        llm = self._build_llm()

        # 4b. SubAgent Manager
        self._subagent_manager = SubAgentManager(
            engine_factory=self._create_subagent_engine,
            max_parallel=4,
        )
        # Wire the delegate tool to the manager
        self._delegate_tool.set_manager(self._subagent_manager)

        # 5. Context management + compressor
        project_config = ProjectConfig(project_root=wd)

        # Load persistent memories for system prompt
        persistent_memory = PersistentMemory(project_root=wd)
        memory_context = persistent_memory.get_all_content()

        system_prompt = build_system_prompt(
            working_dir=wd,
            project_context=project_config.get_system_context() + "\n" + memory_context,
        )
        session_memory = SessionMemory(
            system_prompt=system_prompt,
            max_tokens=self.config.max_context_tokens,
        )
        # Create compressor for long conversations
        compressor = ContextCompressor(
            llm=llm,
            max_tokens=self.config.max_context_tokens,
        )
        context_builder = ContextBuilder(
            memory=session_memory,
            project_config=project_config,
            max_tokens=self.config.max_context_tokens,
            compressor=compressor,
        )

        # 6. Agent
        self._agent = ReActAgent(
            llm=llm,
            context_builder=context_builder,
            tool_registry=self._tool_registry,
            permission_checker=self._permission_checker,
        )

    async def process_query(
        self,
        query: str,
        on_stream: callable = None,
        on_tool_start: callable = None,
        on_tool_result: callable = None,
        on_confirm: callable = None,
    ) -> str:
        """Process a user query through the agent.

        Args:
            query: Natural language user query
            on_stream: Callback(str) for streaming text chunks
            on_tool_start: Callback(tool, params) when a tool starts executing
            on_tool_result: Callback(tool, params, result) when a tool completes
            on_confirm: Async callback(tool, params) -> bool for permission

        Returns:
            Final agent response text

        Raises:
            RuntimeError: If engine is not properly initialized
        """
        if not self._agent:
            raise RuntimeError("Engine not initialized")

        self._agent.set_callbacks(
            on_stream=on_stream,
            on_tool_start=on_tool_start,
            on_tool_result=on_tool_result,
            on_confirm=on_confirm,
        )

        return await self._agent.run(query, self.working_dir)

    def _build_llm(self, model: str = None) -> LiteLLMAdapter:
        """Build an LLM adapter instance (reusable for sub-agents).

        Args:
            model: Optional model override (uses config default if None)

        Returns:
            Configured LiteLLMAdapter
        """
        return LiteLLMAdapter(
            model=model or self.config.effective_model_name(),
            api_key=self.config.api_key,
            api_base=self.config.api_base,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

    def _create_subagent_engine(self, config: SubAgentConfig) -> "Engine":
        """Create an isolated engine for a sub-agent.

        The sub-agent gets:
        - Fresh SessionMemory with custom system prompt
        - Restricted tool set (only allowed tools)
        - Its own LLM adapter (or inherited model)
        - Independent context (no shared memory with parent)

        Args:
            config: SubAgent configuration

        Returns:
            New Engine instance for the sub-agent
        """
        wd = self.working_dir

        # Build restricted tool registry
        sub_registry = ToolRegistry()
        if config.tools:
            # Only register allowed tools
            for tool_name in config.tools:
                tool = self._tool_registry.get(tool_name)
                if tool:
                    sub_registry.register(tool)
        else:
            # Inherit all tools from parent
            for tool in self._tool_registry.list_all():
                sub_registry.register(tool)

        # Use sub-agent specific model or inherit from parent
        sub_llm = self._build_llm(config.model) if config.model else self._build_llm()

        # Fresh context with custom system prompt
        base_prompt = build_system_prompt(wd, "")
        full_prompt = f"{base_prompt}\n\n## Your Role\n{config.system_prompt}"
        sub_memory = SessionMemory(
            system_prompt=full_prompt,
            max_tokens=self.config.max_context_tokens,
        )
        sub_project = ProjectConfig(project_root=wd)
        sub_compressor = ContextCompressor(
            llm=sub_llm,
            max_tokens=self.config.max_context_tokens,
        )
        sub_context = ContextBuilder(
            memory=sub_memory,
            project_config=sub_project,
            max_tokens=self.config.max_context_tokens,
            compressor=sub_compressor,
        )

        # Build sub-agent
        sub_agent = ReActAgent(
            llm=sub_llm,
            context_builder=sub_context,
            tool_registry=sub_registry,
            permission_checker=self._permission_checker,
        )
        sub_agent.MAX_ITERATIONS = config.max_iterations

        # Create a lightweight engine wrapper
        sub_engine = Engine.__new__(Engine)
        sub_engine.config = self.config
        sub_engine.working_dir = wd
        sub_engine._agent = sub_agent
        sub_engine._tool_registry = sub_registry
        sub_engine._permission_checker = self._permission_checker
        sub_engine._subagent_manager = None  # Sub-agents can't spawn sub-sub-agents
        sub_engine._delegate_tool = None

        return sub_engine

    def reset_session(self) -> None:
        """Reset the conversation session (clear history, keep config)."""
        if self._agent and self._agent.context:
            self._agent.context.memory.clear()

    def update_config(self, config: CodeAssistantConfig) -> None:
        """Update configuration and rebuild subsystems as needed.

        Args:
            config: New configuration
        """
        old_model = self.config.effective_model_name()
        self.config = config
        new_model = self.config.effective_model_name()

        # Update permission mode
        if self._permission_checker:
            policy = (
                PermissionPolicy.auto()
                if self.config.permission_mode == "auto_safe"
                else PermissionPolicy.default()
            )
            self._permission_checker.update_policy(policy)

        # Rebuild LLM if model changed
        if old_model != new_model and self._agent:
            self._agent.llm = LiteLLMAdapter(
                model=new_model,
                api_key=self.config.api_key,
                api_base=self.config.api_base,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
            logger.info("Switched LLM to: %s", new_model)

    async def spawn_subagents(
        self,
        tasks: list,
        parallel: bool = True,
    ) -> list:
        """Convenience method to spawn sub-agents directly.

        Args:
            tasks: List of SubAgentTask objects
            parallel: Run in parallel or sequentially

        Returns:
            List of SubAgentResult
        """
        if not self._subagent_manager:
            raise RuntimeError("SubAgent manager not initialized")
        if parallel:
            return await self._subagent_manager.run_parallel(tasks)
        return await self._subagent_manager.run_sequential(tasks)

    @property
    def tool_registry(self) -> Optional[ToolRegistry]:
        """Access the tool registry (for debugging/inspection)."""
        return self._tool_registry
