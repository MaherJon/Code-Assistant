"""Loop Scheduler for recurring and delayed agent tasks.

Supports:
- Fixed interval loops: "every 5 minutes, check the deploy"
- One-shot delayed: "in 10 minutes, remind me to commit"
- Conditional loops: "keep running until tests pass"

Loops run as background asyncio tasks within the REPL process.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Awaitable

logger = logging.getLogger("mahe.loop")


class LoopStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass
class LoopConfig:
    """Configuration for a scheduled loop."""
    prompt: str                         # Task to execute each iteration
    name: str = ""                      # Human-readable name
    interval_seconds: int = 0           # 0 = run once (delayed)
    max_iterations: int = 0             # 0 = unlimited
    stop_condition: Optional[str] = None  # Natural language stop condition
    delay_start_seconds: int = 0        # Delay before first execution


@dataclass
class LoopStatusInfo:
    """Current status of a running loop."""
    loop_id: str
    name: str
    status: LoopStatus
    prompt: str
    interval_seconds: int
    iterations_completed: int = 0
    max_iterations: int = 0
    last_result: Optional[str] = None
    last_error: Optional[str] = None
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)


class LoopScheduler:
    """Schedules recurring or delayed agent tasks.

    Loops run as background asyncio tasks. The scheduler manages
    lifecycle: start, stop, pause, resume, list.

    Usage:
        scheduler = LoopScheduler(engine.process_query)

        # Run every 5 minutes
        loop_id = await scheduler.start(LoopConfig(
            prompt="Check the build status",
            interval_seconds=300,
            name="Build Monitor",
        ))

        # One-shot delayed (run in 10 min)
        await scheduler.run_once("Remind me to push", delay=600)

        # Stop a loop
        await scheduler.stop(loop_id)
    """

    def __init__(
        self,
        query_fn: Callable[[str], Awaitable[str]],
        max_loops: int = 10,
    ):
        self._query_fn = query_fn
        self._max_loops = max_loops
        self._loops: Dict[str, Dict[str, Any]] = {}  # loop_id → {config, task, status_info}
        self._running = False

    async def start(self, config: LoopConfig) -> str:
        """Start a new loop.

        Args:
            config: Loop configuration

        Returns:
            loop_id for management

        Raises:
            RuntimeError: If max loops reached
        """
        if len(self._loops) >= self._max_loops:
            raise RuntimeError(f"Maximum {self._max_loops} loops reached")

        loop_id = f"loop-{uuid.uuid4().hex[:8]}"
        status_info = LoopStatusInfo(
            loop_id=loop_id,
            name=config.name or config.prompt[:50],
            status=LoopStatus.PENDING,
            prompt=config.prompt,
            interval_seconds=config.interval_seconds,
            max_iterations=config.max_iterations,
        )

        task = asyncio.ensure_future(self._run_loop(loop_id, config, status_info))
        self._loops[loop_id] = {
            "config": config,
            "task": task,
            "status_info": status_info,
        }

        logger.info("Loop started: %s (every %ds)", loop_id, config.interval_seconds)
        return loop_id

    async def run_once(self, prompt: str, delay: int = 0) -> str:
        """Schedule a one-shot delayed execution.

        Args:
            prompt: Task to execute
            delay: Seconds to wait before execution

        Returns:
            loop_id (completes after one iteration)
        """
        config = LoopConfig(
            prompt=prompt,
            name=f"one-shot: {prompt[:40]}",
            interval_seconds=0,
            max_iterations=1,
            delay_start_seconds=delay,
        )
        return await self.start(config)

    async def stop(self, loop_id: str) -> bool:
        """Stop a running loop.

        Args:
            loop_id: The loop to stop

        Returns:
            True if stopped, False if not found
        """
        entry = self._loops.get(loop_id)
        if not entry:
            return False

        entry["status_info"].status = LoopStatus.CANCELLED
        task = entry["task"]
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        logger.info("Loop stopped: %s", loop_id)
        return True

    async def stop_all(self) -> int:
        """Stop all running loops.

        Returns:
            Number of loops stopped
        """
        count = 0
        for loop_id in list(self._loops.keys()):
            if await self.stop(loop_id):
                count += 1
        return count

    def list_loops(self) -> List[LoopStatusInfo]:
        """List all loops with their status."""
        active = []
        for entry in self._loops.values():
            info = entry["status_info"]
            if info.status in (LoopStatus.PENDING, LoopStatus.RUNNING):
                active.append(info)
        return sorted(active, key=lambda x: x.created_at)

    def get_loop(self, loop_id: str) -> Optional[LoopStatusInfo]:
        """Get status info for a specific loop."""
        entry = self._loops.get(loop_id)
        return entry["status_info"] if entry else None

    async def _run_loop(
        self,
        loop_id: str,
        config: LoopConfig,
        status_info: LoopStatusInfo,
    ) -> None:
        """Internal loop runner."""
        # Delay start
        if config.delay_start_seconds > 0:
            await asyncio.sleep(config.delay_start_seconds)

        status_info.status = LoopStatus.RUNNING
        iteration = 0

        try:
            while True:
                # Check max iterations
                if config.max_iterations > 0 and iteration >= config.max_iterations:
                    status_info.status = LoopStatus.COMPLETED
                    logger.info("Loop %s completed (max iterations)", loop_id)
                    break

                iteration += 1
                status_info.iterations_completed = iteration
                status_info.last_run_at = datetime.now()

                # Calculate next run time
                if config.interval_seconds > 0:
                    status_info.next_run_at = (
                        datetime.now() + timedelta(seconds=config.interval_seconds)
                    )

                # Execute
                try:
                    logger.debug("Loop %s iteration %d: %s", loop_id, iteration, config.prompt[:50])
                    result = await self._query_fn(config.prompt)
                    status_info.last_result = result
                    status_info.last_error = None
                except Exception as e:
                    logger.error("Loop %s iteration %d failed: %s", loop_id, iteration, e)
                    status_info.last_error = str(e)
                    status_info.status = LoopStatus.ERROR
                    break

                # Check stop condition
                if config.stop_condition:
                    # Simple check: if the result contains certain text
                    if config.stop_condition.lower() in (status_info.last_result or "").lower():
                        status_info.status = LoopStatus.COMPLETED
                        logger.info("Loop %s completed (stop condition met)", loop_id)
                        break

                # Check if cancelled
                if status_info.status == LoopStatus.CANCELLED:
                    break

                # One-shot: exit after first iteration
                if config.interval_seconds <= 0:
                    status_info.status = LoopStatus.COMPLETED
                    break

                # Wait for next interval
                await asyncio.sleep(config.interval_seconds)

        except asyncio.CancelledError:
            status_info.status = LoopStatus.CANCELLED
            logger.info("Loop %s cancelled", loop_id)
        except Exception as e:
            status_info.status = LoopStatus.ERROR
            status_info.last_error = str(e)
            logger.error("Loop %s crashed: %s", loop_id, e)

    async def cleanup(self) -> None:
        """Stop all loops and clean up."""
        await self.stop_all()
        self._loops.clear()

    def parse_interval(self, interval_str: str) -> int:
        """Parse a human-readable interval string to seconds.

        Supports: "30s", "5m", "1h", "2d"
        """
        interval_str = interval_str.strip().lower()
        if interval_str.endswith("s"):
            return int(interval_str[:-1])
        elif interval_str.endswith("m"):
            return int(interval_str[:-1]) * 60
        elif interval_str.endswith("h"):
            return int(interval_str[:-1]) * 3600
        elif interval_str.endswith("d"):
            return int(interval_str[:-1]) * 86400
        else:
            # Assume seconds
            try:
                return int(interval_str)
            except ValueError:
                return 300  # Default 5 minutes
