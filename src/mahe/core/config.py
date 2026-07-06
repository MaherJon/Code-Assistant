"""Configuration management for MAHE.

Hierarchical config: defaults → config file → env vars → CLI flags.
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MaheConfig:
    """Global configuration for MAHE.

    Priority: CLI flags > environment variables > config file > defaults
    """

    # Model settings
    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: Optional[str] = None
    api_base: Optional[str] = None

    # Behavior
    max_iterations: int = 50
    max_context_tokens: int = 100_000
    permission_mode: str = "prompt"  # "prompt" or "auto_safe"
    temperature: float = 0.1
    max_tokens: int = 8192

    # Paths
    data_dir: str = "~/.mahe"

    # Streaming
    stream: bool = True

    def __post_init__(self):
        """Expand paths after init."""
        self.data_dir = os.path.expanduser(self.data_dir)

    @classmethod
    def from_cli(
        cls,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        provider: Optional[str] = None,
        permission_mode: Optional[str] = None,
        **kwargs,
    ) -> "MaheConfig":
        """Build configuration from CLI flags + environment + defaults.

        Priority: explicit CLI arg > env var > config file > default
        """
        config = cls()

        # Load from config file first (lowest priority)
        config._load_from_file()

        # Override with environment variables
        config.provider = (
            provider
            or os.getenv("MAHE_PROVIDER")
            or config.provider
        )
        config.model = (
            model
            or os.getenv("MAHE_MODEL")
            or config.model
        )
        config.api_key = (
            api_key
            or os.getenv("MAHE_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
            or config.api_key
        )
        config.api_base = (
            api_base
            or os.getenv("MAHE_API_BASE")
            or os.getenv("OPENAI_API_BASE")
            or config.api_base
        )
        config.permission_mode = (
            permission_mode
            or os.getenv("MAHE_PERMISSION_MODE")
            or config.permission_mode
        )

        return config

    def _load_from_file(self) -> None:
        """Load configuration from ~/.mahe/config.yaml."""
        import yaml
        config_path = os.path.expanduser("~/.mahe/config.yaml")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    data = yaml.safe_load(f) or {}
                for key, value in data.items():
                    if hasattr(self, key):
                        setattr(self, key, value)
            except Exception:
                pass  # Silently ignore config file errors

    def save_to_file(self) -> None:
        """Save current configuration to ~/.mahe/config.yaml."""
        import yaml
        config_path = os.path.expanduser("~/.mahe/config.yaml")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        data = {
            "provider": self.provider,
            "model": self.model,
            "api_base": self.api_base,
            "permission_mode": self.permission_mode,
        }
        # Don't save api_key to config file for security
        with open(config_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

    def effective_model_name(self) -> str:
        """Get the full model name for LiteLLM (provider/model format)."""
        # If model already includes provider prefix, use as-is
        if "/" in self.model:
            return self.model
        # LiteLLM uses provider/model format for non-OpenAI models
        if self.provider and self.provider != "openai":
            return f"{self.provider}/{self.model}"
        return self.model
