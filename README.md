# CodeAssistant - AI-Powered Terminal Programming Assistant

CodeAssistant is an AI-powered CLI programming assistant that runs in your terminal. It helps you write, understand, and improve code — inspired by Claude Code, built with Python.

## Features

- **Conversational AI**: Natural language interactions with your codebase
- **Code Editing**: Read, write, and edit files with exact string replacements
- **Shell Execution**: Run commands with smart sandboxing and safety checks
- **Git Integration**: Status, diff, log, branch, add, and commit directly
- **Code Search**: Regex search across your entire codebase
- **Multi-Model**: OpenAI, Anthropic Claude, DeepSeek, Qwen, Ollama, and more (via LiteLLM)
- **Permission System**: Three-tier safety (safe auto-run, confirm, blocked)
- **Streaming Output**: Real-time response display
- **Smart Context Compression**: Auto-summarize long conversations at 92% token threshold
- **Persistent Memory**: `.codeassistant/memory/` for project knowledge across sessions
- **Semantic Code Search**: Vector-based natural language search with Chroma DB
- **Code Intelligence**: Multi-language AST parsing (tree-sitter) + Python code intelligence (Jedi)
- **Test Automation**: Run tests and auto-analyze failures
- **MCP Protocol**: Connect external tools via Model Context Protocol

## Installation

### Prerequisites

- Python 3.11 or higher
- An API key for at least one LLM provider
- For semantic search: `pip install chromadb`

### Prerequisites

- Python 3.11 or higher
- An API key for at least one LLM provider

### Install from source

```bash
pip install -e .
```

### Set up API keys

```bash
# OpenAI
export OPENAI_API_KEY="sk-..."

# Anthropic Claude
export ANTHROPIC_API_KEY="sk-ant-..."

# Or use the unified CodeAssistant key
export CodeAssistant_API_KEY="sk-..."
```

## Quick Start

```bash
# Launch interactive REPL (default: gpt-4o via OpenAI)
codeassistant

# Launch with a specific model
codeassistant --model claude-sonnet-5 --provider anthropic

# Launch with a DeepSeek model
codeassistant --model deepseek-chat --provider deepseek

# Index project for semantic code search
codeassistant index

# One-shot question (no REPL)
codeassistant ask "what does git status do?"

# Manage MCP servers
codeassistant mcp list
codeassistant mcp serve

# View/change configuration
codeassistant config --list
codeassistant config --set model gpt-4o
```

## Usage

Once in the REPL, type your questions naturally. CodeAssistant can:

- **Read code**: "Show me the login function in auth.py"
- **Write code**: "Create a hello.py file with a hello world function"
- **Edit code**: "Add error handling to the parse_config function in config.py"
- **Search code**: "Find all places where we call the deprecated API"
- **Run commands**: "Run pytest and fix any failing tests"
- **Git operations**: "Show me the recent commits and create a new branch"

### REPL Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/clear` | Clear conversation history |
| `/config` | Show current configuration |
| `/model <name>` | Switch model (e.g., `/model gpt-4o`) |
| `/provider <name>` | Switch provider |
| `/mode` | Toggle permission mode (prompt/auto_safe) |
| `/exit` | Exit CodeAssistant |

## Project Configuration

Create a `.aiassist.md` file in your project root to give CodeAssistant context about your project:

```markdown
# My Awesome Project

Tech stack: Python 3.12, FastAPI, PostgreSQL

## Architecture
- `src/api/` - FastAPI route handlers
- `src/models/` - SQLAlchemy models
- `src/services/` - Business logic
- `tests/` - Pytest test suite

## Conventions
- Use type hints everywhere
- Follow PEP 8
- Tests use pytest with async support
```

## Architecture

```
src/codeassistant/
├── cli/          # CLI interface (Click, prompt_toolkit, Rich)
│   ├── commands.py
│   ├── repl.py       # Interactive REPL loop
│   └── renderer.py   # Rich-based output rendering
├── core/         # Core engine
│   ├── agent.py      # ReAct agent loop
│   ├── engine.py     # Top-level orchestrator
│   ├── message.py    # Message types and history
│   ├── prompts.py    # System prompt templates
│   └── config.py     # Configuration management
├── context/      # Context management
│   ├── manager.py    # Context builder
│   ├── memory.py     # Session memory
│   └── project.py    # .aiassist.md discovery
├── tools/        # Tool system
│   ├── base.py       # Tool ABC and registry
│   ├── file_tools.py # File read/write/edit/glob/grep
│   ├── shell_tools.py# Shell command execution
│   ├── git_tools.py  # Git operations
│   └── code_tools.py # Code analysis
├── llm/          # LLM integration
│   ├── adapter.py    # Abstract adapter
│   ├── litellm_adapter.py  # LiteLLM implementation
│   └── cache.py      # Prompt caching
└── utils/        # Utilities
    ├── permissions.py# Permission system
    ├── sandbox.py    # Command sandbox
    ├── errors.py     # Custom exceptions
    └── logging.py    # Logging setup
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with debug logging
CodeAssistant_LOG_LEVEL=DEBUG codeassistant
```

## License

MIT
