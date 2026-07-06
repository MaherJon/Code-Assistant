"""Project-level configuration discovery (.aiassist.md, .mahe/)."""

import os
from typing import Optional


class ProjectConfig:
    """Loads and manages project-level configuration.

    Searches for .aiassist.md files that describe the project
    to provide context to the AI assistant.

    Search order:
    1. Working directory / .aiassist.md
    2. Parent directories (future Phase 3+)
    3. User home / .mahe/config.md (future Phase 3+)
    """

    def __init__(self, project_root: Optional[str] = None):
        self.project_root = project_root or os.getcwd()
        self.content: str = ""
        self.config_path: Optional[str] = None
        self._load()

    def _load(self) -> None:
        """Load .aiassist.md from the project root."""
        candidates = [
            os.path.join(self.project_root, ".aiassist.md"),
            os.path.join(self.project_root, ".mahe", "project.md"),
        ]
        for path in candidates:
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        self.content = f.read()
                    self.config_path = path
                    return
                except Exception:
                    pass

    def get_system_context(self) -> str:
        """Format project configuration as system context."""
        if not self.content:
            return ""
        return (
            "<project-context>\n"
            f"{self.content}\n"
            "</project-context>\n"
        )

    def is_loaded(self) -> bool:
        """Check if a project config file was found."""
        return self.config_path is not None and bool(self.content)

    def reload(self) -> None:
        """Reload the project configuration."""
        self.content = ""
        self.config_path = None
        self._load()
