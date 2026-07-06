"""Prompt caching support for repeated system prompts.

In MVP, this is a simple in-memory cache for system prompts.
Phase 3+ can add persistent caching with TTL.
"""

import hashlib
from typing import Optional


class PromptCache:
    """Simple in-memory cache for prompt content.

    Cache key is a hash of the prompt content. Useful for:
    - System prompts (rarely change within a session)
    - Tool definitions (change only when tools are added/removed)
    """

    def __init__(self):
        self._cache: dict[str, str] = {}

    def get(self, content: str) -> Optional[str]:
        """Get cached content if available."""
        key = self._make_key(content)
        return self._cache.get(key)

    def set(self, content: str) -> None:
        """Cache content."""
        key = self._make_key(content)
        self._cache[key] = content

    def invalidate(self, content: str) -> None:
        """Remove content from cache."""
        key = self._make_key(content)
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cached content."""
        self._cache.clear()

    @staticmethod
    def _make_key(content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()
