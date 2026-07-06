"""Custom exception hierarchy for MAHE."""


class MaheError(Exception):
    """Base exception for all MAHE errors."""
    pass


class ConfigError(MaheError):
    """Configuration-related errors."""
    pass


class ModelError(MaheError):
    """LLM model-related errors (API errors, rate limits, etc.)."""
    pass


class ToolError(MaheError):
    """Tool execution errors."""
    pass


class PermissionError(MaheError):
    """Permission-related errors (user denied, blocked operation)."""
    pass


class ContextError(MaheError):
    """Context management errors (token overflow, etc.)."""
    pass
