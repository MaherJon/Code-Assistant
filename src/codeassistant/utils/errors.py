"""Custom exception hierarchy for CodeAssistant."""


class CodeAssistantError(Exception):
    """Base exception for all CodeAssistant errors."""
    pass


class ConfigError(CodeAssistantError):
    """Configuration-related errors."""
    pass


class ModelError(CodeAssistantError):
    """LLM model-related errors (API errors, rate limits, etc.)."""
    pass


class ToolError(CodeAssistantError):
    """Tool execution errors."""
    pass


class PermissionError(CodeAssistantError):
    """Permission-related errors (user denied, blocked operation)."""
    pass


class ContextError(CodeAssistantError):
    """Context management errors (token overflow, etc.)."""
    pass
