"""Workflow Engine for composing complex multi-step operations.

Implements composable workflow patterns:
- pipeline: Chain stages sequentially (each stage's output → next stage's input)
- parallel: Fan-out N independent tasks concurrently
- fanout: Apply one handler to many items in parallel
- verify: Propose → validate with N verifiers → consensus

These patterns can be nested to build complex workflows.
This is the proposal's Phase 4 "动态工作流" capability (Section 3.2.5).
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar

logger = logging.getLogger("mahe.workflow")

T = TypeVar("T")


@dataclass
class WorkflowStage:
    """A single stage in a pipeline workflow."""
    name: str
    description: str = ""
    handler: Optional[Callable[[Any], Awaitable[Any]]] = None


@dataclass
class WorkflowTask:
    """A task to run in a parallel/fanout workflow."""
    name: str
    fn: Callable[[], Awaitable[Any]]
    description: str = ""


@dataclass
class WorkflowResult:
    """Result from a workflow execution."""
    name: str
    success: bool
    output: Any = None
    error: Optional[str] = None
    duration_ms: float = 0
    stages_completed: int = 0


@dataclass
class WorkflowTemplate:
    """A reusable workflow template."""
    name: str
    description: str
    stages: List[WorkflowStage] = field(default_factory=list)
    category: str = "general"


class WorkflowEngine:
    """Orchestrates complex multi-step workflows.

    Supports composable patterns that can be nested arbitrarily.

    Usage:
        engine = WorkflowEngine()

        # Pipeline: A → B → C
        result = await engine.pipeline([
            WorkflowStage("analyze", handler=analyze_fn),
            WorkflowStage("transform", handler=transform_fn),
            WorkflowStage("verify", handler=verify_fn),
        ])

        # Fan-out: apply handler to each item
        results = await engine.fanout(
            items=["file1.py", "file2.py", "file3.py"],
            handler=process_file,
            max_concurrency=5,
        )
    """

    def __init__(self, max_concurrency: int = 10):
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def pipeline(
        self,
        stages: List[WorkflowStage],
        input_data: Any = None,
    ) -> WorkflowResult:
        """Execute stages sequentially, each feeding into the next.

        Args:
            stages: Ordered list of workflow stages
            input_data: Initial input for the first stage

        Returns:
            WorkflowResult with final output
        """
        if not stages:
            return WorkflowResult(
                name="empty-pipeline",
                success=True,
                output=input_data,
            )

        import time
        start = time.time()
        data = input_data
        completed = 0

        for stage in stages:
            if not stage.handler:
                logger.warning("Stage '%s' has no handler, skipping", stage.name)
                continue

            try:
                logger.debug("Pipeline stage: %s", stage.name)
                data = await stage.handler(data)
                completed += 1
            except Exception as e:
                logger.error("Pipeline stage '%s' failed: %s", stage.name, e)
                return WorkflowResult(
                    name=stage.name,
                    success=False,
                    output=data,
                    error=str(e),
                    duration_ms=(time.time() - start) * 1000,
                    stages_completed=completed,
                )

        return WorkflowResult(
            name="pipeline",
            success=True,
            output=data,
            duration_ms=(time.time() - start) * 1000,
            stages_completed=completed,
        )

    async def parallel(
        self,
        tasks: List[WorkflowTask],
    ) -> List[WorkflowResult]:
        """Run multiple tasks in parallel and collect all results.

        Args:
            tasks: List of independent tasks to run

        Returns:
            List of WorkflowResult, one per task
        """
        if not tasks:
            return []

        async def _run_one(task: WorkflowTask) -> WorkflowResult:
            import time
            start = time.time()
            async with self._semaphore:
                try:
                    output = await task.fn()
                    return WorkflowResult(
                        name=task.name,
                        success=True,
                        output=output,
                        duration_ms=(time.time() - start) * 1000,
                    )
                except Exception as e:
                    return WorkflowResult(
                        name=task.name,
                        success=False,
                        error=str(e),
                        duration_ms=(time.time() - start) * 1000,
                    )

        coros = [_run_one(t) for t in tasks]
        return await asyncio.gather(*coros, return_exceptions=False)

    async def fanout(
        self,
        items: List[Any],
        handler: Callable[[Any], Awaitable[Any]],
        description: str = "",
    ) -> List[WorkflowResult]:
        """Apply a handler to each item in parallel.

        This is the core pattern for "do X to each file/function/class".

        Args:
            items: List of items to process
            handler: Async function that takes one item and returns result
            description: Human-readable description

        Returns:
            List of WorkflowResult
        """
        tasks = [
            WorkflowTask(
                name=f"{description or 'fanout'}-{i}",
                fn=lambda item=item: handler(item),  # Capture item by value
            )
            for i, item in enumerate(items)
        ]
        return await self.parallel(tasks)

    async def verify(
        self,
        proposer: Callable[[], Awaitable[Any]],
        verifiers: List[Callable[[Any], Awaitable[bool]]],
        agree_threshold: int = 2,
    ) -> Dict[str, Any]:
        """Propose a solution then verify with multiple verifiers.

        The proposer generates output, then each verifier independently
        checks it. If >= agree_threshold verifiers approve, the result is
        accepted.

        Args:
            proposer: Function that generates proposed output
            verifiers: List of functions that take proposed output → return True/False
            agree_threshold: Minimum number of verifiers that must agree

        Returns:
            Dict with 'proposal', 'votes', 'accepted', 'agree_count'
        """
        # 1. Generate proposal
        proposal = await proposer()

        # 2. Verify with all verifiers in parallel
        async def _verify(verifier):
            try:
                return await verifier(proposal)
            except Exception:
                return False

        vote_results = await asyncio.gather(*[asyncio.ensure_future(_verify(v)) for v in verifiers])
        agree_count = sum(1 for v in vote_results if v)

        return {
            "proposal": proposal,
            "votes": vote_results,
            "accepted": agree_count >= agree_threshold,
            "agree_count": agree_count,
            "total_verifiers": len(verifiers),
        }


# ─── Built-in Workflow Templates ──────────────────────────────────

def make_review_workflow(
    reviewer_factory: Callable[[str], Callable[[], Awaitable[str]]],
    dimensions: List[str] = None,
) -> WorkflowTemplate:
    """Create a code-review workflow that checks multiple dimensions.

    Example:
        wf = make_review_workflow(
            reviewer_factory=lambda dim: lambda: review_dimension(dim),
            dimensions=["correctness", "security", "performance"],
        )
    """
    if dimensions is None:
        dimensions = ["correctness", "security", "style", "performance"]

    stages = [
        WorkflowStage(
            name=f"review-{dim}",
            description=f"Review code for {dim}",
            handler=reviewer_factory(dim),
        )
        for dim in dimensions
    ]

    return WorkflowTemplate(
        name="code-review",
        description="Multi-dimensional code review",
        stages=stages,
        category="quality",
    )


def make_fix_all_tests_workflow(
    test_runner: Callable[[], Awaitable[Dict]],
    fixer: Callable[[Dict], Awaitable[str]],
    max_rounds: int = 3,
) -> WorkflowTemplate:
    """Create a test-fix-rerun loop workflow.

    Runs tests → fixes failures → reruns → repeats until all pass or max_rounds.

    Args:
        test_runner: Async function returning {'passed': int, 'failed': int, 'failures': list}
        fixer: Async function taking failure info → fixing them → returning summary
        max_rounds: Maximum fix-rerun rounds
    """
    stages = []
    for round_num in range(1, max_rounds + 1):
        stages.append(WorkflowStage(
            name=f"round-{round_num}-test",
            description=f"Run tests (round {round_num})",
            handler=lambda _: test_runner(),
        ))
        stages.append(WorkflowStage(
            name=f"round-{round_num}-fix",
            description=f"Fix failures (round {round_num})",
            handler=lambda result: fixer(result) if result.get("failed", 0) > 0 else result,
        ))

    return WorkflowTemplate(
        name="fix-all-tests",
        description=f"Auto-fix test failures (max {max_rounds} rounds)",
        stages=stages,
        category="testing",
    )
