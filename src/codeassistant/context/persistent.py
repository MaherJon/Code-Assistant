"""Persistent project memory stored in .codeassistant/memory/ directory.

Each memory is a markdown file with YAML frontmatter:
---
name: <kebab-slug>
description: <one-line summary>
metadata:
  type: user | feedback | project | reference
---
<content>
"""

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("codeassistant.persistent")

# Frontmatter pattern: ---\n<yaml>\n---
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class MemoryEntry:
    """A single persistent memory entry."""
    name: str
    description: str
    content: str
    metadata: Dict[str, str] = field(default_factory=dict)
    file_path: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @property
    def id(self) -> str:
        return self.name

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "content": self.content,
            "metadata": self.metadata,
        }

    @classmethod
    def from_file(cls, file_path: str) -> Optional["MemoryEntry"]:
        """Load a memory entry from a markdown file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw = f.read()
        except Exception:
            return None

        # Parse frontmatter
        match = FRONTMATTER_RE.match(raw)
        if not match:
            return None

        try:
            import yaml
            fm = yaml.safe_load(match.group(1)) or {}
        except Exception:
            # Try JSON fallback
            try:
                fm = json.loads(match.group(1))
            except Exception:
                fm = {}

        content = raw[match.end():].strip()
        name = fm.get("name", os.path.splitext(os.path.basename(file_path))[0])
        metadata = fm.get("metadata", {})

        stat = os.stat(file_path)
        return cls(
            name=name,
            description=fm.get("description", ""),
            content=content,
            metadata=metadata,
            file_path=file_path,
            created_at=datetime.fromtimestamp(stat.st_ctime).isoformat(),
            updated_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
        )

    def to_markdown(self) -> str:
        """Serialize to markdown with frontmatter."""
        import yaml
        fm = {
            "name": self.name,
            "description": self.description,
            "metadata": self.metadata,
        }
        yaml_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True)
        return f"---\n{yaml_str}---\n\n{self.content}"


class PersistentMemory:
    """Manages persistent project memory in .codeassistant/memory/.

    Provides CRUD operations and relevance-based search.
    Memory is stored as markdown files with YAML frontmatter.
    """

    MEMORY_DIR = ".codeassistant/memory"

    def __init__(self, project_root: str):
        self.project_root = project_root
        self.memory_dir = os.path.join(project_root, self.MEMORY_DIR)
        self._index: Dict[str, MemoryEntry] = {}
        self._ensure_dir()
        self._load_all()

    def _ensure_dir(self) -> None:
        """Create the memory directory if it doesn't exist."""
        os.makedirs(self.memory_dir, exist_ok=True)
        # Also create .codeassistant/ dir
        os.makedirs(os.path.join(self.project_root, ".codeassistant"), exist_ok=True)

    def _load_all(self) -> None:
        """Load all memory entries from disk."""
        self._index.clear()
        if not os.path.isdir(self.memory_dir):
            return

        for fname in os.listdir(self.memory_dir):
            if fname.endswith(".md"):
                fpath = os.path.join(self.memory_dir, fname)
                entry = MemoryEntry.from_file(fpath)
                if entry:
                    self._index[entry.name] = entry

        logger.debug("Loaded %d persistent memories", len(self._index))

    def list_all(self) -> List[MemoryEntry]:
        """List all memory entries."""
        return sorted(self._index.values(), key=lambda e: e.name)

    def get(self, name: str) -> Optional[MemoryEntry]:
        """Get a memory entry by name."""
        return self._index.get(name)

    def search(self, query: str, top_k: int = 5) -> List[MemoryEntry]:
        """Simple keyword-based search across memory entries.

        For semantic search, use VectorStore instead.
        """
        query_lower = query.lower()
        scored = []
        for entry in self._index.values():
            score = 0
            # Score by name match
            if query_lower in entry.name.lower():
                score += 10
            # Score by description match
            if query_lower in entry.description.lower():
                score += 5
            # Score by content match
            score += entry.content.lower().count(query_lower)
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:top_k]]

    def add(self, entry: MemoryEntry) -> None:
        """Add or update a memory entry."""
        # Sanitize the filename
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "-", entry.name).strip("-") or str(uuid.uuid4())[:8]
        fpath = os.path.join(self.memory_dir, f"{safe_name}.md")
        entry.file_path = fpath
        entry.updated_at = datetime.now().isoformat()
        if not entry.created_at:
            entry.created_at = entry.updated_at

        # Write to disk
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(entry.to_markdown())

        self._index[entry.name] = entry
        logger.info("Saved memory: %s → %s", entry.name, fpath)

    def update(self, name: str, content: str = None, description: str = None) -> bool:
        """Update an existing memory entry."""
        entry = self._index.get(name)
        if not entry:
            return False
        if content is not None:
            entry.content = content
        if description is not None:
            entry.description = description
        self.add(entry)
        return True

    def delete(self, name: str) -> bool:
        """Delete a memory entry."""
        entry = self._index.pop(name, None)
        if entry and entry.file_path and os.path.exists(entry.file_path):
            os.remove(entry.file_path)
            logger.info("Deleted memory: %s", name)
            return True
        return False

    def get_all_content(self, top_k: int = 10) -> str:
        """Get all memory content formatted for system prompt injection."""
        entries = self.list_all()
        if not entries:
            return ""

        lines = ["<project-memory>"]
        for entry in entries[:top_k]:
            lines.append(f"## {entry.description or entry.name}")
            # Truncate very long entries
            content = entry.content
            if len(content) > 2000:
                content = content[:2000] + "\n...(truncated)"
            lines.append(content)
            lines.append("")
        lines.append("</project-memory>")

        return "\n".join(lines)

    def reload(self) -> None:
        """Reload all memories from disk."""
        self._load_all()
