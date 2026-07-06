"""Mid-term memory compression using LLM-based summarization.

When conversation tokens exceed the compression threshold (default 92%),
older messages are summarized by the LLM instead of being truncated.

This preserves technical context, decisions, and user preferences
that would otherwise be lost.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

from mahe.core.message import Message, MessageRole
from mahe.llm.adapter import LLMAdapter

logger = logging.getLogger("mahe.compression")

# Default compression threshold (percentage of max_tokens)
COMPRESSION_THRESHOLD = 0.92

# Minimum number of messages before compression is attempted
MIN_MESSAGES_TO_COMPRESS = 6

# Number of recent messages to always keep uncompressed
KEEP_RECENT_COUNT = 4

# Compression system prompt
COMPRESSION_PROMPT = """Summarize the following conversation segment concisely.
Preserve ALL of the following:
1. Technical decisions made and their rationale
2. Code changes discussed and their purpose
3. User preferences, conventions, and constraints mentioned
4. Key facts about the project architecture
5. Any errors encountered and how they were resolved
6. Important file paths referenced

Format your summary as bullet points. Be specific — include function names,
file paths, and exact parameters. Do NOT include trivial pleasantries.

Conversation to summarize:
{conversation}

Summary (preserving all technical context):"""


@dataclass
class CompressionStats:
    """Statistics about compression activity."""
    total_compressions: int = 0
    total_tokens_saved: int = 0
    last_compression_time: Optional[datetime] = None
    compressed_segments: List[str] = field(default_factory=list)  # Summary texts


class ContextCompressor:
    """Compresses older conversation messages into concise summaries.

    Uses the LLM to summarize old messages, replacing them with
    a summary message that preserves key technical context.

    Compression is triggered when:
    - Token count exceeds `threshold * max_tokens`
    - There are at least MIN_MESSAGES_TO_COMPRESS non-system messages
    - The most recent messages are preserved uncompressed
    """

    def __init__(
        self,
        llm: LLMAdapter,
        max_tokens: int = 100_000,
        threshold: float = COMPRESSION_THRESHOLD,
        keep_recent: int = KEEP_RECENT_COUNT,
    ):
        self.llm = llm
        self.max_tokens = max_tokens
        self.threshold = threshold
        self.keep_recent = keep_recent
        self.stats = CompressionStats()
        self._compressing = False  # Prevent concurrent compressions

    @property
    def trigger_threshold(self) -> int:
        """Token count that triggers compression."""
        return int(self.max_tokens * self.threshold)

    def should_compress(self, message_count: int, estimated_tokens: int) -> bool:
        """Check if compression should be triggered.

        Args:
            message_count: Number of non-system messages
            estimated_tokens: Current estimated token count

        Returns:
            True if compression is needed
        """
        if self._compressing:
            return False
        if message_count < MIN_MESSAGES_TO_COMPRESS:
            return False
        return estimated_tokens >= self.trigger_threshold

    async def compress(
        self,
        messages: List[Message],
    ) -> Tuple[List[Message], int]:
        """Compress old messages into a summary.

        Preserves:
        - System messages
        - Most recent `keep_recent` messages
        - Compresses everything else into a summary

        Args:
            messages: All current messages

        Returns:
            Tuple of (new_message_list, tokens_saved)
        """
        self._compressing = True
        try:
            # Separate system messages
            system_msgs = [m for m in messages if m.role == MessageRole.SYSTEM]
            non_system = [m for m in messages if m.role != MessageRole.SYSTEM]

            if len(non_system) <= self.keep_recent:
                return messages, 0

            # Messages to compress (old) vs keep (recent)
            to_compress = non_system[:-self.keep_recent]
            to_keep = non_system[-self.keep_recent:]

            # Build compression text
            conversation = self._format_for_compression(to_compress)
            old_tokens = sum(len(m.content or "") // 4 for m in to_compress)

            # Get summary from LLM (use a small, cheap model if possible)
            summary = await self._generate_summary(conversation)
            summary_tokens = len(summary) // 4

            # Create summary message
            summary_msg = Message(
                role=MessageRole.SYSTEM,
                content=f"<compressed-history>\n{summary}\n</compressed-history>",
            )

            # Rebuild message list
            new_messages = system_msgs + [summary_msg] + to_keep
            tokens_saved = old_tokens - summary_tokens

            # Update stats
            self.stats.total_compressions += 1
            self.stats.total_tokens_saved += tokens_saved
            self.stats.last_compression_time = datetime.now()
            self.stats.compressed_segments.append(summary[:200])

            logger.info(
                "Compressed %d messages → summary (%d tokens saved). "
                "New total: %d messages.",
                len(to_compress), tokens_saved, len(new_messages),
            )

            return new_messages, tokens_saved

        except Exception as e:
            logger.error("Compression failed: %s", e)
            # On failure, return original messages unchanged
            return messages, 0
        finally:
            self._compressing = False

    def _format_for_compression(self, messages: List[Message]) -> str:
        """Format messages into a string for the compression LLM call."""
        parts = []
        for msg in messages:
            role = msg.role.value
            content = msg.content or ""

            # Truncate very long messages
            if len(content) > 3000:
                content = content[:3000] + "\n...[truncated]"

            if msg.tool_calls:
                tool_names = [tc.get("function", {}).get("name", "?") for tc in msg.tool_calls]
                parts.append(f"[{role}] Called tool(s): {', '.join(tool_names)}")
                if content:
                    parts.append(f"[{role}] {content}")
            elif msg.tool_call_id:
                # Tool result — truncate long results
                if len(content) > 1000:
                    content = content[:1000] + "\n...[result truncated]"
                parts.append(f"[tool_result] {content}")
            else:
                parts.append(f"[{role}] {content}")

        return "\n\n".join(parts)

    async def _generate_summary(self, conversation: str) -> str:
        """Use the LLM to generate a summary.

        Uses a small/cheap model call with no tools.
        """
        prompt = COMPRESSION_PROMPT.format(conversation=conversation)

        try:
            # Use simple completion (no tools, no streaming)
            response = await self.llm.chat(
                messages=[
                    {"role": "user", "content": prompt},
                ],
                stream=False,
            )
            return response.content or "(compression failed)"
        except Exception as e:
            logger.error("Summary generation failed: %s", e)
            # Fallback: simple truncation-based "summary"
            return self._fallback_summary(conversation)

    def _fallback_summary(self, conversation: str) -> str:
        """Fallback: extract first sentences of each message as summary."""
        lines = conversation.split("\n")
        key_lines = [l for l in lines if l and not l.startswith("[tool_result]")]
        # Take first 20 key lines
        return "Partial summary (LLM unavailable):\n" + "\n".join(key_lines[:20])

    def load_compressed(self, messages: List[Message]) -> List[Message]:
        """Load already-compressed messages (no new compression).

        Used when loading a persisted session that already has summaries.
        """
        return messages

    def clear_stats(self) -> None:
        """Reset compression statistics."""
        self.stats = CompressionStats()
