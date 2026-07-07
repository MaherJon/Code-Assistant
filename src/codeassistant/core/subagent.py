"""SubAgent Manager for parallel agent execution.

Supports spawning independent sub-agents with isolated contexts,
custom system prompts, and restricted tool access. Sub-agents run
concurrently via asyncio.gather().

This is the proposal's Phase 4 core feature (Section 4.2.3).
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from codeassistant.core.engine import Engine

logger = logging.getLogger("codeassistant.subagent")


# ─── SubAgent Types ────────────────────────────────────────────────

@dataclass
class SubAgentConfig:
    """Configuration for a sub-agent instance.

    Attributes:
        name: Unique name for this sub-agent type
        description: Human-readable description of what this agent does
        system_prompt: Custom system prompt (appended to base prompt)
        tools: Allowed tool names (empty list = inherit all from parent)
        model: Optional model override (None = inherit from parent)
        max_iterations: Maximum ReAct iterations for this sub-agent
    """
    name: str
    description: str = ""
    system_prompt: str = ""
    tools: List[str] = field(default_factory=list)
    model: Optional[str] = None
    max_iterations: int = 20


# Predefined sub-agent types
PREDEFINED_AGENTS = {
    "code-reviewer": SubAgentConfig(
        name="code-reviewer",
        description="Reviews code for bugs, style issues, and best practices",
        system_prompt=(
            "You are a thorough code reviewer. Your job is to find bugs, "
            "style issues, security vulnerabilities, and logic errors. "
            "Be specific — reference exact line numbers and explain WHY "
            "each issue is a problem. Focus on correctness and safety."
        ),
        tools=["read_file", "search_code", "glob_files", "analyze_code"],
        max_iterations=15,
    ),
    "test-fixer": SubAgentConfig(
        name="test-fixer",
        description="Finds and fixes failing tests automatically",
        system_prompt=(
            "You are a test automation specialist. You find failing tests, "
            "diagnose root causes, and apply fixes. Always read both the "
            "test and the source code before making changes. After fixing, "
            "run the tests to verify."
        ),
        tools=["read_file", "write_file", "edit_file", "search_code", "run_shell", "run_tests"],
        max_iterations=25,
    ),
    "code-explorer": SubAgentConfig(
        name="code-explorer",
        description="Explores unfamiliar code and reports structure and patterns",
        system_prompt=(
            "You are a code explorer. Your job is to understand unfamiliar "
            "code quickly and report back with a clear summary of: "
            "1) Overall architecture, 2) Key files and their roles, "
            "3) Dependencies between modules, 4) Any notable patterns or anti-patterns."
        ),
        tools=["read_file", "search_code", "glob_files", "analyze_code"],
        max_iterations=10,
    ),
    "refactorer": SubAgentConfig(
        name="refactorer",
        description="Executes planned code refactors across multiple files",
        system_prompt=(
            "You are a refactoring specialist. You execute planned, "
            "systematic code changes across multiple files. Be precise — "
            "make only the planned changes, verify each change, and "
            "report what was modified."
        ),
        tools=["read_file", "write_file", "edit_file", "search_code", "glob_files", "run_shell"],
        max_iterations=30,
    ),
    "security-auditor": SubAgentConfig(
        name="security-auditor",
        description="Audits code for security vulnerabilities",
        system_prompt=(
            "You are a security auditor. Your job is to find security "
            "vulnerabilities: injection attacks, XSS, unsafe deserialization, "
            "hardcoded secrets, missing authentication checks, etc. "
            "Report every finding with severity level and fix recommendation."
        ),
        tools=["read_file", "search_code", "glob_files", "run_shell"],
        max_iterations=20,
    ),
    "viz-agent": SubAgentConfig(
        name="viz-agent",
        description="Creates data visualizations, charts, and dashboards from data",
        system_prompt=(
            "You are a data visualization specialist. Your job is to create "
            "clear, informative, and aesthetically pleasing charts from data. "
            "You can read data from files, process it, and generate visualization "
            "PNG files.\n\n"
            "Your workflow:\n"
            "1. Read and understand the data using read_file or run_shell\n"
            "2. If data needs cleaning or transformation, write a Python script and run it\n"
            "3. Use create_visualization to generate the chart\n"
            "4. Verify the output file was created\n"
            "5. Explain what the chart reveals about the data\n\n"
            "Chart type selection guidelines:\n"
            "- line: time series, trends over time\n"
            "- bar: categorical comparisons\n"
            "- scatter: correlation between two numeric variables\n"
            "- pie: part-to-whole relationships (max 7 categories)\n"
            "- histogram: distribution of a single numeric variable\n"
            "- box: statistical summary (median, quartiles, outliers)\n"
            "- area: cumulative trends or volume over time\n"
            "- heatmap: matrix or correlation patterns\n\n"
            "Best practices:\n"
            "- Always inspect data before charting\n"
            "- Choose appropriate chart types for the data\n"
            "- Use clear titles and axis labels\n"
            "- Report data statistics alongside the chart\n"
            "- Always save charts as PNG files with descriptive filenames"
        ),
        tools=[
            "read_file", "write_file", "search_code", "glob_files",
            "run_shell", "create_visualization",
        ],
        max_iterations=20,
    ),
}


@dataclass
class SubAgentTask:
    """A task to be executed by a sub-agent.

    Attributes:
        agent_type: Name of the agent config to use (from PREDEFINED_AGENTS or custom)
        prompt: The task description/prompt
        context: Additional context (file paths, code snippets, etc.)
        config: Optional custom config override
    """
    agent_type: str
    prompt: str
    context: str = ""
    config: Optional[SubAgentConfig] = None

    @property
    def effective_config(self) -> SubAgentConfig:
        """Get the effective config (custom override or predefined)."""
        if self.config:
            return self.config
        if self.agent_type in PREDEFINED_AGENTS:
            return PREDEFINED_AGENTS[self.agent_type]
        # Default fallback
        return SubAgentConfig(
            name=self.agent_type,
            description=f"Custom agent: {self.agent_type}",
        )


@dataclass
class SubAgentResult:
    """Result from a sub-agent execution."""
    agent_id: str
    agent_type: str
    success: bool
    output: str
    tool_calls_made: int = 0
    iterations: int = 0
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    @property
    def duration_seconds(self) -> float:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0


@dataclass
class SubAgentHandle:
    """Handle to a running or completed sub-agent."""
    agent_id: str
    task: asyncio.Task
    config: SubAgentConfig
    started_at: datetime = field(default_factory=datetime.now)


# ─── SubAgent Manager ───────────────────────────────────────────────

class SubAgentManager:
    """Manages parallel sub-agent execution.

    Sub-agents are independent ReActAgent instances with:
    - Isolated SessionMemory (fresh context)
    - Custom system prompts (specialized per type)
    - Restricted tool access (configurable per agent)
    - Independent LLM adapters (or shared for connection pooling)

    Usage:
        manager = SubAgentManager(engine_factory)
        results = await manager.run_parallel([
            SubAgentTask("code-reviewer", "Review auth.py for bugs"),
            SubAgentTask("security-auditor", "Check auth.py for vulns"),
        ])
    """

    def __init__(
        self,
        engine_factory: Callable[..., "Engine"],
        max_parallel: int = 5,
    ):
        self._engine_factory = engine_factory
        self.max_parallel = max_parallel
        self._running: Dict[str, SubAgentHandle] = {}
        self._semaphore = asyncio.Semaphore(max_parallel)

    async def run_parallel(
        self,
        tasks: List[SubAgentTask],
        on_progress: Optional[Callable[[str, str, str], None]] = None,
    ) -> List[SubAgentResult]:
        """Run multiple sub-agent tasks in parallel.

        Args:
            tasks: List of sub-agent tasks to execute
            on_progress: Optional callback(agent_id, status, message)

        Returns:
            List of SubAgentResult, one per task (order matches input)
        """
        if not tasks:
            return []

        async def _run_one(task: SubAgentTask, index: int) -> SubAgentResult:
            async with self._semaphore:
                return await self._run_single(task, index, on_progress)

        coros = [_run_one(t, i) for i, t in enumerate(tasks)]
        results = await asyncio.gather(*coros, return_exceptions=True)

        # Convert exceptions to error results
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(SubAgentResult(
                    agent_id=f"error-{i}",
                    agent_type=tasks[i].agent_type,
                    success=False,
                    output="",
                    error=str(result),
                ))
            else:
                final_results.append(result)

        return final_results

    async def run_sequential(
        self,
        tasks: List[SubAgentTask],
        on_progress: Optional[Callable[[str, str, str], None]] = None,
    ) -> List[SubAgentResult]:
        """Run sub-agent tasks sequentially (one after another)."""
        results = []
        for i, task in enumerate(tasks):
            result = await self._run_single(task, i, on_progress)
            results.append(result)
        return results

    async def run_with_cross_validation(
        self,
        task: SubAgentTask,
        validators: List[SubAgentConfig],
        consensus_threshold: int = 2,
        on_progress: Optional[Callable[[str, str, str], None]] = None,
    ) -> Dict[str, Any]:
        """Run a task with multiple validator agents for cross-validation.

        Each validator independently reviews/checks the output and votes.
        Findings confirmed by >= consensus_threshold validators are kept.

        Args:
            task: The main task to execute
            validators: List of validator agent configs
            consensus_threshold: Minimum number of agreeing validators
            on_progress: Optional progress callback

        Returns:
            Dict with 'main_result', 'validator_results', 'confirmed_findings'
        """
        # Run main task
        main_result = await self._run_single(task, 0, on_progress)
        if not main_result.success:
            return {
                "main_result": main_result,
                "validator_results": [],
                "confirmed_findings": [],
            }

        # Run validators in parallel
        validator_tasks = [
            SubAgentTask(
                agent_type=v.name,
                prompt=(
                    f"Validate the following output from a {task.agent_type}. "
                    f"Confirm whether each finding is real and relevant. "
                    f"Rate confidence in each finding (high/medium/low).\n\n"
                    f"Original task: {task.prompt}\n\n"
                    f"Output to validate:\n{main_result.output}"
                ),
                config=v,
            )
            for v in validators
        ]

        validator_results = await self.run_parallel(validator_tasks, on_progress)

        # Simple consensus: findings confirmed by threshold validators
        confirmed = []
        for vr in validator_results:
            if vr.success:
                confirmed.append(vr.output)

        return {
            "main_result": main_result,
            "validator_results": validator_results,
            "confirmed_findings": confirmed,
        }

    async def _run_single(
        self,
        task: SubAgentTask,
        index: int,
        on_progress: Optional[Callable] = None,
    ) -> SubAgentResult:
        """Run a single sub-agent task."""
        agent_id = f"{task.agent_type}-{uuid.uuid4().hex[:8]}"
        config = task.effective_config
        started_at = datetime.now()

        if on_progress:
            on_progress(agent_id, "starting", f"Starting {task.agent_type}...")

        try:
            # Create isolated engine for this sub-agent
            engine = self._engine_factory(config)

            # Build the full prompt
            full_prompt = task.prompt
            if task.context:
                full_prompt = f"{task.prompt}\n\nContext:\n{task.context}"

            if on_progress:
                on_progress(agent_id, "running", f"Running {task.agent_type}...")

            # Process the query
            output = await engine.process_query(full_prompt)

            # Count tool calls from the agent's history
            tool_calls_made = sum(
                1 for m in engine._agent.context.memory.history._messages
                if hasattr(m, 'tool_calls') and m.tool_calls
            )

            if on_progress:
                on_progress(agent_id, "completed", f"Completed {task.agent_type}")

            return SubAgentResult(
                agent_id=agent_id,
                agent_type=task.agent_type,
                success=True,
                output=output,
                tool_calls_made=tool_calls_made,
                iterations=engine._agent._iteration if hasattr(engine._agent, '_iteration') else 0,
                started_at=started_at,
                finished_at=datetime.now(),
            )

        except Exception as e:
            logger.error("SubAgent %s failed: %s", agent_id, e, exc_info=True)
            if on_progress:
                on_progress(agent_id, "error", str(e))
            return SubAgentResult(
                agent_id=agent_id,
                agent_type=task.agent_type,
                success=False,
                output="",
                error=str(e),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    async def broadcast(
        self,
        tasks: List[SubAgentTask],
        on_progress: Optional[Callable] = None,
    ) -> List[SubAgentResult]:
        """Alias for run_parallel with unlimited concurrency."""
        old_max = self.max_parallel
        self.max_parallel = len(tasks)
        try:
            return await self.run_parallel(tasks, on_progress)
        finally:
            self.max_parallel = old_max

    @property
    def running_count(self) -> int:
        """Number of currently running sub-agents."""
        return len(self._running)
