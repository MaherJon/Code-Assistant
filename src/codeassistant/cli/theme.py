"""Centralized theme system for CodeAssistant terminal UI.

Provides configurable color palettes, icon sets, and visual constants
used throughout the CLI layer. Supports dark, light, and high-contrast themes.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ThemeConfig:
    """Visual theme configuration for the terminal UI.

    All colors use Rich style names (e.g., "cyan", "bold green", "bright_yellow").
    All icons are single Unicode characters or short strings.
    """

    name: str = "dark"

    # ── Color Palette ──────────────────────────────────────────
    primary: str = "cyan"            # Brand color, borders, highlights
    success: str = "green"           # Checkmarks, success states
    warning: str = "yellow"          # Warnings, confirmations
    error: str = "red"               # Errors, blocked actions, failures
    dim: str = "dim"                 # Secondary / muted information
    user: str = "bright_cyan"        # User input echo
    assistant: str = "white"         # Assistant output text
    tool_name: str = "bright_yellow" # Tool names in status cards
    thinking: str = "dim cyan"       # Thinking/spinner indicator
    heading: str = "bold cyan"       # Section headings
    code_border: str = "blue"        # Code block borders
    diff_border: str = "yellow"      # Diff panel borders
    panel_border: str = "cyan"       # Default panel border
    muted: str = "rgb(128,128,128)"  # Very subtle text

    # ── Icons ──────────────────────────────────────────────────
    icon_success: str = "✓"
    icon_error: str = "✗"
    icon_warning: str = "⚠"
    icon_blocked: str = "🚫"
    icon_info: str = "ℹ"
    icon_thinking: str = "⠋"
    icon_running: str = "⏳"
    icon_file: str = "📄"
    icon_folder: str = "📁"
    icon_shell: str = ">_"
    icon_git: str = "⎇"
    icon_search: str = "🔍"
    icon_test: str = "🧪"
    icon_code: str = "💻"
    icon_memory: str = "🧠"
    icon_gear: str = "⚙"
    icon_clock: str = "🕐"
    icon_star: str = "★"

    # ── Layout ─────────────────────────────────────────────────
    indent: str = "  "               # Indentation for nested content
    max_width: int = 100             # Max panel width (chars)
    code_max_height: int = 30        # Max code block height (lines)

    # ── Animations ─────────────────────────────────────────────
    spinner_frames: tuple = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    spinner_speed: float = 0.08      # Seconds per frame

    # ── Prompt ─────────────────────────────────────────────────
    prompt_style: str = "bold cyan"
    prompt_text: str = "codeassistant"
    prompt_separator: str = "> "
    multiline_indicator: str = "[M]"


# ─── Pre-built Theme Variants ─────────────────────────────────

DARK_THEME = ThemeConfig(name="dark")

LIGHT_THEME = ThemeConfig(
    name="light",
    primary="blue",
    success="dark_green",
    warning="dark_yellow",
    error="dark_red",
    dim="rgb(100,100,100)",
    user="bold blue",
    assistant="black",
    tool_name="bold yellow",
    thinking="dim blue",
    heading="bold blue",
    panel_border="blue",
    code_border="dark_blue",
    diff_border="dark_yellow",
    muted="rgb(150,150,150)",
    prompt_style="bold blue",
)

HIGH_CONTRAST = ThemeConfig(
    name="high_contrast",
    primary="bold bright_cyan",
    success="bold bright_green",
    warning="bold bright_yellow",
    error="bold bright_red",
    dim="bright_black",
    user="bold bright_cyan",
    assistant="bright_white",
    tool_name="bold bright_yellow",
    thinking="bright_cyan",
    heading="bold bright_cyan",
    panel_border="bright_cyan",
    prompt_style="bold bright_cyan",
)

THEMES: Dict[str, ThemeConfig] = {
    "dark": DARK_THEME,
    "light": LIGHT_THEME,
    "high_contrast": HIGH_CONTRAST,
}


def load_theme(name: str = "dark") -> ThemeConfig:
    """Load a theme by name.

    Args:
        name: One of "dark", "light", "high_contrast"

    Returns:
        ThemeConfig for the requested theme (falls back to dark)
    """
    return THEMES.get(name, DARK_THEME)


def get_icon_for_tool(tool_name: str, theme: ThemeConfig = None) -> str:
    """Get the appropriate icon for a tool category.

    Args:
        tool_name: The tool's name string
        theme: Theme config (uses default if None)

    Returns:
        Unicode icon character
    """
    t = theme or DARK_THEME
    name = tool_name.lower()
    if "file" in name or "read" in name or "write" in name or "edit" in name or "glob" in name:
        return t.icon_file
    if "shell" in name or "bash" in name or "run_shell" in name:
        return t.icon_shell
    if "git" in name:
        return t.icon_git
    if "search" in name or "grep" in name or "find" in name:
        return t.icon_search
    if "test" in name:
        return t.icon_test
    if "code" in name or "analyze" in name or "python" in name:
        return t.icon_code
    if "memory" in name:
        return t.icon_memory
    return t.icon_gear
