"""SubAgent spawning tools for the main agent.

The delegate_task tool allows the main ReActAgent to spawn
parallel sub-agents for complex, parallelizable work.
"""

import asyncio
import logging
from typing import TYPE_CHECKING, List

from mahe.tools.base import Tool, ToolPermission, ToolResult

if TYPE_CHECKING:
    from mahe.core.subagent import SubAgentManager, SubAgentTask

logger = logging.getLogger("mahe.tools.subagent")


class DelegateTask(Tool):
    """Spawn parallel sub-agents to handle complex subtasks.

    The main agent can use this to:
    - Review code across multiple dimensions simultaneously
    - Explore multiple parts of a codebase in parallel
    - Fix multiple test failures concurrently
    - Audit code for different types of issues
    """

    name = "delegate_task"
    description = (
        "Delegate work to parallel sub-agents. Each sub-agent works independently "
        "with its own context and tools. Use this for complex tasks that can be "
        "parallelized: code review, security audit, multi-file exploration, "
        "or any task where multiple independent perspectives are valuable. "
        "Available agent types: code-reviewer, test-fixer, code-explorer, "
        "refactorer, security-auditor."
    )
    parameters = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "description": "List of subtasks to delegate. Each subtask has agent_type, prompt, and optional context.",
                "items": {
                    "type": "object",
                    "properties": {
                        "agent_type": {
                            "type": "string",
                            "description": "Type of agent: code-reviewer, test-fixer, code-explorer, refactorer, security-auditor.",
                            "enum": ["code-reviewer", "test-fixer", "code-explorer", "refactorer", "security-auditor"],
                        },
                        "prompt": {
                            "type": "string",
                            "description": "The task for this sub-agent to execute."
                        },
                        "context": {
                            "type": "string",
                            "description": "Optional additional context (file contents, error messages, etc.)."
                        },
                    },
                    "required": ["agent_type", "prompt"],
                },
            },
            "parallel": {
                "type": "boolean",
                "description": "Run sub-agents in parallel (true) or sequentially (false). Default: true.",
                "default": True,
            },
        },
        "required": ["tasks"],
    }
    permission = ToolPermission.SAFE  # Sub-agents have their own permission checks

    def __init__(self, manager: "SubAgentManager" = None):
        self._manager = manager

    def set_manager(self, manager: "SubAgentManager") -> None:
        """Set the sub-agent manager (called after engine init)."""
        self._manager = manager

    async def execute(self, tasks: List[dict], parallel: bool = True) -> ToolResult:
        """Execute delegated tasks via sub-agents."""
        if not self._manager:
            return ToolResult.fail("SubAgent manager not initialized.")

        from mahe.core.subagent import SubAgentTask

        subagent_tasks = []
        for i, task_data in enumerate(tasks):
            agent_type = task_data.get("agent_type", "code-explorer")
            prompt = task_data.get("prompt", "")
            context = task_data.get("context", "")

            if not prompt:
                return ToolResult.fail(f"Task {i} is missing a prompt.")

            subagent_tasks.append(SubAgentTask(
                agent_type=agent_type,
                prompt=prompt,
                context=context,
            ))

        # Run sub-agents
        if parallel and len(subagent_tasks) > 1:
            results = await self._manager.run_parallel(subagent_tasks)
        else:
            results = await self._manager.run_sequential(subagent_tasks)

        # Format results
        lines = [f"SubAgent Results ({len(results)} tasks):", ""]
        success_count = 0
        fail_count = 0

        for result in results:
            status = "✓" if result.success else "✗"
            duration = f" ({result.duration_seconds:.1f}s)" if result.duration_seconds > 0 else ""
            lines.append(f"  {status} [{result.agent_type}] {result.agent_id}{duration}")
            if result.success:
                success_count += 1
                # Show output preview
                preview = result.output[:300]
                if len(result.output) > 300:
                    preview += "..."
                for line in preview.split("\n")[:5]:
                    lines.append(f"      {line}")
            else:
                fail_count += 1
                lines.append(f"      Error: {result.error}")
            lines.append("")

        summary = f"{success_count} succeeded, {fail_count} failed"
        lines.insert(1, summary)

        return ToolResult(
            success=fail_count == 0,
            output="\n".join(lines),
            metadata={
                "total": len(results),
                "success": success_count,
                "failed": fail_count,
            }
        )
