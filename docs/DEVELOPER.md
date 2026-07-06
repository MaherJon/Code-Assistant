# CodeAssistant Developer Documentation / CodeAssistant 开发者文档

> AI-Powered Terminal Programming Assistant — Internals, Architecture & Contribution Guide
>
> AI 驱动的终端编程助手 — 内部架构、设计模式与贡献指南

---

## 目录 / Table of Contents

1. [Architecture Overview / 架构总览](#1-architecture-overview--架构总览)
2. [Core Design Patterns / 核心设计模式](#2-core-design-patterns--核心设计模式)
3. [Project Structure / 项目结构](#3-project-structure--项目结构)
4. [Module Deep Dive / 模块详解](#4-module-deep-dive--模块详解)
   - [4.1 Engine & Agent Loop / 引擎与 Agent 循环](#41-engine--agent-loop)
   - [4.2 Tool System / 工具系统](#42-tool-system)
   - [4.3 LLM Adapter / LLM 适配器](#43-llm-adapter)
   - [4.4 Context Management / 上下文管理](#44-context-management)
   - [4.5 Permission System / 权限系统](#45-permission-system)
   - [4.6 SubAgent System / 子 Agent 系统](#46-subagent-system)
   - [4.7 Workflow Engine / 工作流引擎](#47-workflow-engine)
   - [4.8 Persistent Memory / 持久记忆](#48-persistent-memory)
   - [4.9 Semantic Search / 语义搜索](#49-semantic-search)
5. [Data Flow / 数据流](#5-data-flow--数据流)
6. [Adding Features / 添加功能](#6-adding-features--添加功能)
   - [6.1 Adding a New Tool / 添加新工具](#61-adding-a-new-tool)
   - [6.2 Adding a New SubAgent Type / 添加新 SubAgent 类型](#62-adding-a-new-subagent-type)
   - [6.3 Adding a New LLM Provider / 添加新 LLM 提供商](#63-adding-a-new-llm-provider)
   - [6.4 Creating a Workflow Template / 创建 Workflow 模板](#64-creating-a-workflow-template)
7. [Message Protocol / 消息协议](#7-message-protocol--消息协议)
8. [Configuration System / 配置系统](#8-configuration-system--配置系统)
9. [Testing / 测试](#9-testing--测试)
10. [Development Setup / 开发环境搭建](#10-development-setup--开发环境搭建)
11. [Roadmap & Contributing / 路线图与贡献](#11-roadmap--contributing)

---

## 1. Architecture Overview / 架构总览

CodeAssistant follows a **layered architecture** with a central **ReAct (Reasoning + Acting) agent loop** at its core. The system is designed around the principle of _composition over inheritance_: every subsystem is a swappable component behind a well-defined interface.

CodeAssistant 采用**分层架构**，核心是一个 **ReAct（推理+行动）Agent 循环**。系统围绕"组合优于继承"的原则设计：每个子系统都是可替换的组件，背后有定义清晰的接口。

```
┌──────────────────────────────────────────────────────┐
│                    CLI Layer                          │
│  ┌──────────┐  ┌──────────┐  ┌────────────────────┐ │
│  │   REPL   │  │ Commands │  │    Renderer (Rich)  │ │
│  │ (prompt_ │  │ (Click)  │  │                     │ │
│  │ toolkit) │  │          │  │                     │ │
│  └────┬─────┘  └────┬─────┘  └─────────┬──────────┘ │
├───────┼──────────────┼─────────────────┼────────────┤
│       │         Engine Orchestrator     │            │
│       └──────────────┬──────────────────┘            │
│                      │                               │
│  ┌───────────────────▼────────────────────────────┐  │
│  │              ReAct Agent Loop                   │  │
│  │  ┌─────────┐  ┌─────────┐  ┌────────────────┐  │  │
│  │  │Context  │→ │  LLM    │→ │ Tool Execution  │  │  │
│  │  │Builder  │  │Adapter  │  │ + Permission    │  │  │
│  │  └─────────┘  └─────────┘  └────────────────┘  │  │
│  └────────────────────────────────────────────────┘  │
│                      │                               │
│  ┌───────────────────┼────────────────────────────┐  │
│  │          Supporting Subsystems                  │  │
│  │  ┌──────────┐ ┌──────────┐ ┌────────────────┐  │  │
│  │  │ Session  │ │ Context  │ │  Permission    │  │  │
│  │  │ Memory   │ │Compressor│ │  Checker       │  │  │
│  │  └──────────┘ └──────────┘ └────────────────┘  │  │
│  │  ┌──────────┐ ┌──────────┐ ┌────────────────┐  │  │
│  │  │Persistent│ │ Vector   │ │  SubAgent      │  │  │
│  │  │ Memory   │ │ Store    │ │  Manager       │  │  │
│  │  └──────────┘ └──────────┘ └────────────────┘  │  │
│  └────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────┤
│                  Tool Layer                           │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌──────────────┐  │
│  │ File   │ │ Shell  │ │  Git   │ │ Code Intel    │  │
│  │ Tools  │ │ Tools  │ │ Tools  │ │ Tools         │  │
│  └────────┘ └────────┘ └────────┘ └──────────────┘  │
│  ┌────────┐ ┌────────┐ ┌──────────────────────────┐  │
│  │ Memory │ │  Test  │ │      MCP Client           │  │
│  │ Tools  │ │ Tools  │ │                           │  │
│  └────────┘ └────────┘ └──────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

### Key Design Decisions / 关键设计决策

| Decision / 决策 | Rationale / 理由 |
|---|---|
| **ReAct pattern** | Separates reasoning from tool execution; each LLM call gets fresh context including previous tool results |
| **LiteLLM as sole adapter** | Supports 100+ model providers through a single, unified code path |
| **OpenAI function-calling format** | Industry standard for tool definitions; all tools emit OpenAI-compatible schemas |
| **Async-first** | All tools and LLM calls are `async`; enables concurrent SubAgent execution |
| **Callback-based UI integration** | Engine/Agent are UI-agnostic; the CLI passes callbacks for streaming text, tool progress, and permission prompts |
| **File-based persistent memory** | `.codeassistant/memory/*.md` with YAML frontmatter — human-readable, git-trackable, no database dependency |

---

## 2. Core Design Patterns / 核心设计模式

### 2.1 ReAct Loop / ReAct 循环

The central algorithm. Every user query goes through this loop:

```
1. Build Context (system prompt + history + tool schemas + project config)
2. Call LLM with streaming → accumulate text + tool calls
3. If LLM returns text only → task complete, return to user
4. If LLM returns tool calls → execute each tool (with permission check)
5. Feed tool results back as tool-result messages
6. Goto 1 (repeat until completion, cancellation, or max iterations)
```

**Source:** `src/codeassistant/core/agent.py` — `ReActAgent.run()`

Key constraints:
- **Max iterations:** 50 (prevents infinite loops)
- **Sequential tool execution:** Tools execute one at a time within an iteration
- **Stopping conditions:** text-only response, user cancellation, max iterations, fatal error

### 2.2 Tool ABC / 工具抽象基类

Every tool inherits from `Tool` (`src/codeassistant/tools/base.py`):

```python
class Tool(ABC):
    name: str           # Unique identifier (e.g., "read_file")
    description: str    # Tells the LLM when/how to use this tool
    parameters: dict    # JSON Schema for parameters
    permission: ToolPermission  # SAFE | NEEDS_CONFIRM | BLOCKED

    @abstractmethod
    async def execute(self, **params) -> ToolResult:
        ...
```

The `ToolRegistry` holds all registered tools and can emit them as OpenAI function-calling schemas via `get_openai_schemas()`.

### 2.3 Callback Pattern / 回调模式

The Engine/Agent communicates with the UI purely through callbacks — no direct coupling to CLI code:

```python
await engine.process_query(
    query="Fix the bug in auth.py",
    on_stream=lambda chunk: print(chunk, end=""),       # Real-time text
    on_tool_start=lambda tool, params: show_spinner(),   # Tool started
    on_tool_result=lambda tool, params, result: ...,     # Tool completed
    on_confirm=lambda tool, params: ask_user(),          # Permission prompt
)
```

### 2.4 Composition over Inheritance / 组合优于继承

The `Engine` class (`src/codeassistant/core/engine.py`) is the composition root. It creates and wires together all subsystems:

```python
class Engine:
    def __init__(self, config, working_dir):
        self._permission_checker = PermissionChecker(policy)
        self._tool_registry = ToolRegistry()      # + register all tools
        self._subagent_manager = SubAgentManager(...)
        self._agent = ReActAgent(
            llm=LiteLLMAdapter(...),
            context_builder=ContextBuilder(...),
            tool_registry=self._tool_registry,
            permission_checker=self._permission_checker,
        )
```

Each subsystem can be swapped independently — e.g., replace `LiteLLMAdapter` with a mock for testing.

---

## 3. Project Structure / 项目结构

```
src/codeassistant/
├── __init__.py
├── main.py                  # CLI entry point (Click)
├── cli/
│   ├── commands.py          # Subcommands: ask, config, index, mcp, loop
│   ├── repl.py              # Interactive REPL (prompt_toolkit + Rich)
│   └── renderer.py          # Rich-based markdown/code/diff rendering
├── core/
│   ├── agent.py             # ReAct agent loop ★
│   ├── engine.py            # Top-level orchestrator ★
│   ├── subagent.py          # SubAgent manager + predefined agents ★
│   ├── workflow.py          # Workflow engine (pipeline/parallel/fanout/verify)
│   ├── loop.py              # Scheduled task loop (/loop command)
│   ├── config.py            # CodeAssistantConfig dataclass + hierarchical loading
│   ├── message.py           # Message, MessageRole, MessageHistory
│   └── prompts.py           # System prompt template
├── context/
│   ├── manager.py           # ContextBuilder — assembles context for each LLM call
│   ├── memory.py            # SessionMemory (wraps MessageHistory)
│   ├── compression.py       # ContextCompressor — LLM-based conversation summarization
│   ├── persistent.py        # PersistentMemory — .codeassistant/memory/*.md CRUD
│   ├── project.py           # ProjectConfig — .aiassist.md discovery & loading
│   └── vector_store.py      # VectorStore — ChromaDB semantic code search
├── tools/
│   ├── base.py              # Tool ABC, ToolRegistry, ToolResult, ToolPermission
│   ├── file_tools.py        # ReadFile, WriteFile, EditFile, GlobTool, GrepTool
│   ├── shell_tools.py       # BashTool (command execution with sandbox)
│   ├── git_tools.py         # GitStatus, GitDiff, GitLog, GitBranch, GitAdd, GitCommit
│   ├── code_tools.py        # AnalyzeCode, PythonDefinition, PythonReferences, PythonHover
│   ├── memory_tools.py      # SaveMemory, RecallMemory, ListMemories
│   ├── test_tools.py        # RunTests (pytest with failure analysis)
│   ├── subagent_tools.py    # DelegateTask (spawns parallel sub-agents)
│   └── mcp_client.py        # MCP protocol client
├── llm/
│   ├── adapter.py           # LLMAdapter ABC, LLMResponse, LLMStreamChunk, ToolCall
│   ├── litellm_adapter.py   # LiteLLM implementation (100+ providers)
│   └── cache.py             # Prompt caching utilities
└── utils/
    ├── permissions.py       # PermissionChecker + PermissionPolicy
    ├── sandbox.py           # Command sandbox (dangerous command detection)
    ├── errors.py            # Custom exceptions (ModelError, ConfigError, etc.)
    └── logging.py           # Logging configuration

tests/
├── conftest.py              # Pytest fixtures (mock LLM, test engine, temp dirs)
├── helpers.py               # Test helper utilities
├── test_agent.py            # ReActAgent tests
├── test_cli.py              # CLI command tests
├── test_messages.py         # Message/MessageHistory tests
└── test_tools.py            # Tool execution tests

docs/
├── USER_GUIDE.md            # End-user guide (bilingual)
└── DEVELOPER.md             # This document (bilingual)

examples/
└── .aiassist.md             # Example project configuration
```

---

## 4. Module Deep Dive / 模块详解

### 4.1 Engine & Agent Loop / 引擎与 Agent 循环

**Files:** `core/engine.py`, `core/agent.py`

#### Engine (`core/engine.py`)

The `Engine` is the **composition root**. It:
1. Creates all subsystems based on `CodeAssistantConfig`
2. Registers all 22 tools into the `ToolRegistry`
3. Creates the `SubAgentManager` with an `engine_factory` closure
4. Builds the system prompt from templates + project config + persistent memory
5. Wires everything into a `ReActAgent`
6. Exposes `process_query()` as the single entry point

**Lifecycle:**
```
Engine(config, working_dir) → process_query() × N → reset_session()
```

**SubAgent isolation:** `_create_subagent_engine()` creates a lightweight `Engine` clone with:
- Fresh `SessionMemory` (no shared conversation history)
- Custom system prompt (role-specialized)
- Restricted tool set (e.g., code-reviewer can't run shell commands)
- Shared `PermissionChecker` (same security policy)
- No recursive SubAgent spawning (sub-agents can't spawn sub-sub-agents)

#### ReActAgent (`core/agent.py`)

The core loop implementation:

```python
class ReActAgent:
    MAX_ITERATIONS = 50  # Safety limit

    async def run(self, user_input: str, working_dir: str) -> str:
        self.context.memory.add_user_message(user_input)

        while self._iteration < self.MAX_ITERATIONS and not self._cancelled:
            # 1. Build context (message history + tool schemas)
            ctx = await self.context.build(working_dir, tool_schemas)

            # 2. Call LLM with streaming
            response = await self._stream_llm_call(ctx)

            # 3. Text-only → done
            if not response.tool_calls:
                self.context.memory.add_assistant_message(response.content)
                return response.content

            # 4. Execute tools sequentially
            for tc in response.tool_calls:
                result = await self._execute_tool(tc)  # Includes permission check
                self.context.memory.add_tool_result(tc.id, result.output)

            # 5. Loop back (tool results are now in context)
```

**State machine:** `IDLE → THINKING → ACTING → WAITING_CONFIRMATION → COMPLETED / ERROR / CANCELLED`

**Streaming:** `_stream_llm_call()` processes SSE chunks from the LLM, yielding:
- `content_delta` → forwarded to UI via `on_stream` callback
- `tool_call_delta` → accumulated into a buffer, parsed as JSON when complete
- `finish_reason` → signals end of stream

---

### 4.2 Tool System / 工具系统

**Files:** `tools/base.py`, `tools/file_tools.py`, `tools/shell_tools.py`, `tools/git_tools.py`, `tools/code_tools.py`, `tools/memory_tools.py`, `tools/test_tools.py`

#### Tool Base Class

```python
class Tool(ABC):
    name: str = ""              # Unique ID for LLM function calling
    description: str = ""       # Natural language guide for the LLM
    parameters: dict = {}       # JSON Schema for arguments
    permission: ToolPermission = NEEDS_CONFIRM

    @abstractmethod
    async def execute(self, **params) -> ToolResult: ...

    def to_openai_schema(self) -> dict: ...  # OpenAI function-calling format
```

#### ToolResult

```python
@dataclass
class ToolResult:
    success: bool
    output: str           # Human-readable summary
    error: Optional[str]  # Set only on failure
    metadata: dict        # Arbitrary structured data
```

Tool results are added to the conversation as `role: "tool"` messages with the tool_call_id for correlation.

#### ToolRegistry

```python
class ToolRegistry:
    def register(self, tool: Tool): ...
    def get(self, name: str) -> Optional[Tool]: ...
    def get_openai_schemas(self) -> List[dict]: ...  # For LLM API
    async def execute(self, name: str, **params) -> ToolResult: ...
```

#### Permission Levels

| Level | Behavior | Example Tools |
|---|---|---|
| `SAFE` | Auto-execute, no prompt | `read_file`, `search_code`, `git_status`, `glob_files` |
| `NEEDS_CONFIRM` | Ask user before executing | `write_file`, `edit_file`, `run_shell`, `git_commit` |
| `BLOCKED` | Never execute (dangerous) | Any command matching `rm -rf /`, `mkfs`, fork bombs, etc. |

#### All 22 Built-in Tools

| Category | Tools |
|---|---|
| **File** | `read_file`, `write_file`, `edit_file`, `glob_files`, `search_code` |
| **Code Intelligence** | `analyze_code`, `python_definition`, `python_references`, `python_hover` |
| **Shell** | `run_shell` |
| **Git** | `git_status`, `git_diff`, `git_log`, `git_branch`, `git_add`, `git_commit` |
| **Memory** | `save_memory`, `recall_memory`, `list_memories` |
| **Test** | `run_tests` |
| **SubAgent** | `delegate_task` |

---

### 4.3 LLM Adapter / LLM 适配器

**Files:** `llm/adapter.py`, `llm/litellm_adapter.py`

#### Abstract Interface

```python
class LLMAdapter(ABC):
    @abstractmethod
    async def chat(self, messages, tools=None, stream=False) -> LLMResponse: ...

    @abstractmethod
    async def chat_stream(self, messages, tools=None) -> AsyncIterator[LLMStreamChunk]: ...

    @abstractmethod
    def count_tokens(self, text: str) -> int: ...

    async def embed(self, texts: List[str]) -> List[List[float]]: ...  # Optional
```

#### Data Types

```python
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict

@dataclass
class LLMResponse:
    content: Optional[str]
    tool_calls: List[ToolCall]
    finish_reason: Literal["stop", "tool_calls", "length", "error"]
    usage: Optional[dict]

@dataclass
class LLMStreamChunk:
    content_delta: Optional[str]       # Incremental text
    tool_call_delta: Optional[dict]    # {index, id, name, arguments}
    finish_reason: Optional[str]
```

#### LiteLLMAdapter Implementation

The sole production adapter. Uses [LiteLLM](https://github.com/BerriAI/litellm) to support 100+ model providers through a unified OpenAI-compatible interface:

```python
class LiteLLMAdapter(LLMAdapter):
    def __init__(self, model, api_key, api_base, temperature, max_tokens):
        # model can be: "gpt-4o", "claude-sonnet-5", "deepseek-chat",
        #               "anthropic/claude-sonnet-5", "ollama/llama3", etc.
```

**Error handling:** Wraps LiteLLM exceptions into `ModelError` subtypes:
- `APIConnectionError` → network issues
- `RateLimitError` → rate limiting
- `AuthenticationError` → bad API key
- `BadRequestError` → invalid model/parameters

**Embedding fallback:** If embedding API fails (e.g., wrong model), returns zero vectors — allows the semantic search system to operate in degraded mode.

---

### 4.4 Context Management / 上下文管理

**Files:** `context/manager.py`, `context/memory.py`, `context/compression.py`, `context/project.py`

#### ContextBuilder (`context/manager.py`)

Assembles the complete context for each LLM call:

```python
class ContextBuilder:
    async def build(self, working_dir, tool_schemas) -> AgentContext:
        # 1. Reload project config (.aiassist.md)
        # 2. Build/reuse system prompt
        # 3. Check if compression needed (tokens > 92% threshold)
        # 4. Trim history to fit token budget
        # 5. Return AgentContext(messages, tools, project_config, ...)
```

#### SessionMemory (`context/memory.py`)

Wraps `MessageHistory` with convenience methods for the agent loop:

```python
class SessionMemory:
    session_id: str          # UUID for this session
    history: MessageHistory  # Ordered list of Messages

    def add_user_message(content): ...
    def add_assistant_message(content, tool_calls): ...
    def add_tool_result(tool_call_id, result, tool_name): ...
    def get_messages_for_llm() -> list: ...  # OpenAI-compatible format
```

#### ContextCompressor (`context/compression.py`)

**Trigger:** When estimated tokens exceed **92%** of `max_context_tokens` and there are ≥6 non-system messages.

**Algorithm:**
1. Preserve system messages + most recent 4 messages
2. Format older messages as a conversation transcript
3. Call LLM (non-streaming, no tools) to generate a structured summary
4. Insert summary as a `<compressed-history>` system message
5. Preserved details: technical decisions, code changes, user preferences, file paths, errors resolved

**Fallback:** If summary generation fails, extracts first 20 key lines as a simple truncation-based summary.

#### Token Budget Management

The system maintains a token budget across three layers:
1. **Max context tokens** (config: default 100,000) — total budget
2. **Compression threshold** (92%) — triggers summarization before truncation
3. **Trim target** (max_tokens - 8000 reserve) — hard truncation if still over budget

---

### 4.5 Permission System / 权限系统

**File:** `utils/permissions.py`

Three-tier permission model:

```
Tool.permission:
  SAFE ──────────────→ auto-execute (no prompt)
  NEEDS_CONFIRM ─────→ check policy
                         ├─ blocked path/command → BLOCKED
                         ├─ auto_safe mode + safe command → SAFE
                         └─ otherwise → prompt user
  BLOCKED ───────────→ never execute
```

**Blocked commands** (always rejected):
- `rm -rf /`, `rm -rf ~`, `mkfs.*`, `dd if=`
- Fork bombs (`:(){ :|:& };:`)
- `curl`/`wget` piped to shell
- `shutdown`, `reboot`, `sudo rm`
- `chmod 777 /`

**Blocked paths** (never writable):
- `/etc/`, `/sys/`, `/proc/`, `/boot/`
- `C:\Windows\`, `C:\System32\`
- `~/.ssh/`, `~/.gnupg/`, `.git/config`

**Auto-safe commands** (in `auto_safe` mode):
- `ls`, `pwd`, `echo`, `cat`, `head`, `tail`, `grep`, `find`, `which`
- `git status/diff/log/branch/stash/show`
- `python --version`, `pip list`, `node --version`, `whoami`, `hostname`

---

### 4.6 SubAgent System / 子 Agent 系统

**File:** `core/subagent.py`

CodeAssistant can spawn multiple independent agents that run in parallel for complex tasks.

#### Architecture

```
User Request: "Review auth.py from correctness, security, and performance angles"
       │
       ▼
  Main Agent (ReActAgent)
       │ calls delegate_task tool
       ▼
  SubAgentManager
       │ run_parallel()
       ├──▶ SubAgent #1: code-reviewer → reads auth.py → reports bugs
       ├──▶ SubAgent #2: security-auditor → scans auth.py → reports vulns
       └──▶ SubAgent #3: code-explorer → analyzes structure → reports patterns
       │
       ▼
  Results aggregated → returned to main agent → user sees combined report
```

#### Predefined SubAgent Types

```python
PREDEFINED_AGENTS = {
    "code-reviewer": SubAgentConfig(
        tools=["read_file", "search_code", "glob_files", "analyze_code"],
        system_prompt="You are a thorough code reviewer...",
        max_iterations=15,
    ),
    "test-fixer": SubAgentConfig(
        tools=["read_file", "write_file", "edit_file", "search_code", "run_shell", "run_tests"],
        system_prompt="You are a test automation specialist...",
        max_iterations=25,
    ),
    "code-explorer": SubAgentConfig(...),
    "refactorer": SubAgentConfig(...),
    "security-auditor": SubAgentConfig(...),
}
```

#### Cross-Validation Mode

`SubAgentManager.run_with_cross_validation()` implements the **verify pattern**:
1. One primary agent performs the task
2. N validator agents independently review the output
3. Findings confirmed by ≥ consensus_threshold validators are returned

#### Isolation Guarantees

Each SubAgent gets:
- **Independent `SessionMemory`** — no shared conversation with parent or siblings
- **Custom system prompt** — specialized role instructions
- **Restricted tool set** — only the tools it needs (principle of least privilege)
- **Limited iterations** — separate `max_iterations` per agent type
- **No recursive spawning** — sub-agents cannot spawn sub-sub-agents (prevents explosion)

---

### 4.7 Workflow Engine / 工作流引擎

**File:** `core/workflow.py`

Programmatic composition of complex multi-step workflows via Python API:

#### Patterns

| Pattern | Method | Description |
|---|---|---|
| **Pipeline** | `engine.pipeline([stages])` | Sequential stages: A → B → C. Each stage's output feeds the next. |
| **Parallel** | `engine.parallel([tasks])` | Run N independent tasks concurrently. All complete before returning. |
| **Fan-out** | `engine.fanout(items, handler)` | Apply one handler to many items in parallel (map-reduce pattern). |
| **Verify** | `engine.verify(proposer, verifiers)` | Propose → N validators vote → consensus check. |

#### Concurrency Control

- `max_concurrency` (default: 10) — semaphore-based limiting
- All patterns built on `asyncio.gather()` — truly concurrent, not just scheduled

#### Built-in Templates

```python
# Multi-dimensional code review
make_review_workflow(dimensions=["correctness", "security", "style", "performance"])

# Auto-fix test failures (max 3 rounds)
make_fix_all_tests_workflow(test_runner=..., fixer=..., max_rounds=3)
```

---

### 4.8 Persistent Memory / 持久记忆

**File:** `context/persistent.py`

File-based knowledge persistence in `.codeassistant/memory/*.md`:

```markdown
---
name: project-uses-postgresql
description: Database choice for this project
metadata:
  type: project
---

This project uses PostgreSQL 16. Never use SQLite for production code.
Connection string format: postgresql://user:pass@localhost:5432/dbname
```

#### CRUD Operations

```python
memory = PersistentMemory(project_root=".")

# Create/Update
memory.add(MemoryEntry(name="key", description="...", content="..."))

# Read
entry = memory.get("key")
results = memory.search("postgresql", top_k=5)

# List
all_entries = memory.list_all()

# Delete
memory.delete("key")
```

#### System Prompt Injection

On engine startup, `PersistentMemory.get_all_content()` returns formatted markdown wrapped in `<project-memory>` tags, injected directly into the system prompt. This means the agent "remembers" project facts across sessions without consuming conversation history tokens.

#### Search

Currently keyword-based scoring (name > description > content). For semantic search over memories, use `VectorStore` instead.

---

### 4.9 Semantic Search / 语义搜索

**File:** `context/vector_store.py`

ChromaDB-based code indexing for natural language queries:

```bash
codeassistant index                    # Full project index
codeassistant index --update           # Incremental update
```

```
User query: "Where is authentication logic?"
       │
       ▼
  VectorStore.search(query)
       │
       ├─ Embed query with LLM embedding API
       ├─ Query ChromaDB collection (cosine similarity)
       └─ Return top-K SearchResult(path, content, score)
```

**Supported languages:** 20+ extensions (`.py`, `.js`, `.ts`, `.go`, `.rs`, `.java`, `.rb`, `.php`, `.swift`, `.kt`, etc.)

**Indexing:**
- Files > 4000 chars are truncated to first 4000 chars (representative sample)
- Skips hidden dirs, `node_modules`, `__pycache__`, `venv`, `.git`, `dist`, `build`
- Batch size: 20 files per embedding API call

**Storage:** `.codeassistant/vectors/` — ChromaDB persistent client, cosine distance metric

---

## 5. Data Flow / 数据流

### Complete Request Lifecycle / 完整请求生命周期

```
User types: "Fix the bug in src/auth.py line 42"
       │
       ▼
┌── CLI Layer ──────────────────────────────────────────────┐
│  REPL.run() receives input via prompt_toolkit              │
│  → engine.process_query(query, callbacks...)               │
└──────────────────────┬────────────────────────────────────┘
                       │
┌── Engine ─────────────────────────────────────────────────┐
│  process_query() → agent.run(query, working_dir)           │
└──────────────────────┬────────────────────────────────────┘
                       │
┌── ReActAgent.run() ───────────────────────────────────────┐
│                                                            │
│  Iteration 1:                                              │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ ContextBuilder.build():                               │ │
│  │  1. Load .aiassist.md project config                  │ │
│  │  2. Build system prompt (env + project + memory)      │ │
│  │  3. Check token count → compress if >92%              │ │
│  │  4. Trim to fit budget                                │ │
│  │  5. Return messages + tool schemas                    │ │
│  └──────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ LLM Call: LiteLLMAdapter.chat_stream()                │ │
│  │  → Sends: system + history + tool definitions         │ │
│  │  ← Streams: text chunks + tool_call deltas            │ │
│  │  → on_stream("Let me read the file...")  [UI update]  │ │
│  │  → tool_call: read_file(path="src/auth.py")           │ │
│  └──────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ Tool Execution:                                        │ │
│  │  1. tool_registry.get("read_file")                    │ │
│  │  2. permission_checker.check(tool, params) → SAFE     │ │
│  │  3. tool.execute(path="src/auth.py")                  │ │
│  │  4. → ToolResult(success=True, output="42: def...")   │ │
│  │  5. memory.add_tool_result(...)                       │ │
│  │  6. on_tool_result(tool, params, result)  [UI]        │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  Iteration 2: [Context now includes file contents]         │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ LLM Call: "I see the bug on line 42. Editing..."      │ │
│  │  → on_stream("The bug is...")                        │ │
│  │  → tool_call: edit_file(path="src/auth.py",           │ │
│  │      old_string="if user = None",                     │ │
│  │      new_string="if user is None")                    │ │
│  └──────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ Tool Execution:                                        │ │
│  │  1. permission: NEEDS_CONFIRM                         │ │
│  │  2. on_confirm(tool, params) → user clicks "Allow"    │ │
│  │  3. tool.execute(...)                                 │ │
│  │  4. → ToolResult(success=True, "1 replacement made")  │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  Iteration 3:                                              │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ LLM Call: text-only response                          │ │
│  │  → "Fixed! Changed `=` to `is` for None comparison."  │ │
│  │  → No tool calls → COMPLETED                         │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  Return: "Fixed! Changed `=` to `is` for None comparison." │
└────────────────────────────────────────────────────────────┘
```

---

## 6. Adding Features / 添加功能

### 6.1 Adding a New Tool / 添加新工具

**Step 1:** Create your tool class inheriting from `Tool`:

```python
# src/codeassistant/tools/my_tools.py

from codeassistant.tools.base import Tool, ToolPermission, ToolResult

class FormatCode(Tool):
    name = "format_code"
    description = "Format code using the project's configured formatter."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File or directory to format."
            },
            "formatter": {
                "type": "string",
                "description": "Formatter to use (black, prettier, rustfmt, etc.)",
                "enum": ["black", "prettier", "rustfmt", "gofmt"]
            },
        },
        "required": ["path"],
    }
    permission = ToolPermission.NEEDS_CONFIRM  # Modifies files

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir

    async def execute(self, path: str, formatter: str = "black") -> ToolResult:
        import subprocess
        try:
            result = subprocess.run(
                [formatter, path],
                capture_output=True, text=True, timeout=30,
                cwd=self.working_dir,
            )
            if result.returncode == 0:
                return ToolResult.ok(
                    f"Formatted {path} with {formatter}.",
                    path=path, formatter=formatter,
                )
            else:
                return ToolResult.fail(result.stderr)
        except Exception as e:
            return ToolResult.fail(str(e))
```

**Step 2:** Register it in the engine:

```python
# In src/codeassistant/core/engine.py, add to _init_subsystems():

from codeassistant.tools.my_tools import FormatCode
self._tool_registry.register(FormatCode(working_dir=wd))
```

**Step 3:** (Optional) Add permission rules in `PermissionChecker.check()` if needed.

**That's it.** The tool is now available to the LLM — no other code changes needed.

### 6.2 Adding a New SubAgent Type / 添加新 SubAgent 类型

```python
# In src/codeassistant/core/subagent.py, add to PREDEFINED_AGENTS:

"doc-writer": SubAgentConfig(
    name="doc-writer",
    description="Generates documentation for code",
    system_prompt=(
        "You are a technical writer. Generate clear, concise documentation. "
        "Include function signatures, parameter descriptions, return values, "
        "and usage examples. Use the project's existing doc style."
    ),
    tools=["read_file", "search_code", "glob_files", "analyze_code"],
    max_iterations=10,
),
```

Available immediately via:

```python
await engine.spawn_subagents([
    SubAgentTask(agent_type="doc-writer", prompt="Document src/auth.py"),
])
```

Or naturally via the LLM: `"Generate documentation for all modules using a doc-writer sub-agent."`

### 6.3 Adding a New LLM Provider / 添加新 LLM 提供商

Since CodeAssistant uses LiteLLM, most providers work out of the box. Any provider LiteLLM supports (100+) is already available:

```bash
codeassistant --model ollama/llama3
codeassistant --model together_ai/mistral-7b
codeassistant --model replicate/meta/llama-3-70b
```

To add a provider NOT supported by LiteLLM:

1. Create a new adapter implementing `LLMAdapter` in `src/codeassistant/llm/`
2. Follow the interface: `chat()`, `chat_stream()`, `count_tokens()`, `embed()`
3. Add a factory or detection method to `Engine._build_llm()`

### 6.4 Creating a Workflow Template / 创建 Workflow 模板

```python
# In src/codeassistant/core/workflow.py or your own code:

def make_migrate_workflow(
    finder: Callable[[], Awaitable[List[str]]],
    migrator: Callable[[str], Awaitable[str]],
    verifier: Callable[[str], Awaitable[bool]],
) -> WorkflowTemplate:
    """Migrate each file found by finder and verify."""
    return WorkflowTemplate(
        name="migrate",
        description="Find → Migrate each file → Verify",
        stages=[
            WorkflowStage(name="find", description="Find files to migrate", handler=finder),
            WorkflowStage(name="migrate", handler=lambda files: engine.fanout(files, migrator)),
            WorkflowStage(name="verify", handler=lambda files: engine.fanout(files, verifier)),
            WorkflowStage(name="report", handler=lambda results: summarize_migration(results)),
        ],
        category="refactoring",
    )
```

---

## 7. Message Protocol / 消息协议

CodeAssistant uses OpenAI's message format internally for LLM compatibility:

```python
# System message
{"role": "system", "content": "You are CodeAssistant..."}

# User message
{"role": "user", "content": "Fix the bug in auth.py"}

# Assistant message with tool calls
{
    "role": "assistant",
    "content": "Let me read the file first.",
    "tool_calls": [
        {
            "id": "call_abc123",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": "{\"path\": \"src/auth.py\"}"
            }
        }
    ]
}

# Tool result message
{
    "role": "tool",
    "tool_call_id": "call_abc123",
    "name": "read_file",
    "content": "1: def authenticate(user, password):\n2:     ..."
}
```

The `Message` dataclass (`core/message.py`) wraps this format with:
- Type-safe `MessageRole` enum
- Timestamp for each message
- Cached `token_count` estimate
- Factory methods: `Message.system()`, `.user()`, `.assistant()`, `.tool_result()`

---

## 8. Configuration System / 配置系统

**File:** `core/config.py`

### Priority (highest to lowest) / 优先级（从高到低）

```
CLI flags  >  Environment variables  >  Config file (~/.codeassistant/config.yaml)  >  Defaults
```

### Configurable Fields / 可配置字段

| Field | Default | Description |
|---|---|---|
| `provider` | `"openai"` | Model provider name |
| `model` | `"gpt-4o"` | Model identifier |
| `api_key` | `None` | API key (not persisted to file) |
| `api_base` | `None` | Custom API base URL |
| `max_iterations` | `50` | Max ReAct loop iterations |
| `max_context_tokens` | `100_000` | Token budget |
| `permission_mode` | `"prompt"` | `"prompt"` or `"auto_safe"` |
| `temperature` | `0.1` | LLM temperature |
| `max_tokens` | `8192` | Max tokens per LLM response |
| `stream` | `True` | Enable streaming output |

### Environment Variables / 环境变量

```bash
CodeAssistant_API_KEY="sk-..."         # Unified key (highest priority)
CodeAssistant_PROVIDER="anthropic"     # Default provider
CodeAssistant_MODEL="claude-sonnet-5"  # Default model
CodeAssistant_API_BASE="https://..."   # Custom endpoint
CodeAssistant_PERMISSION_MODE="auto_safe"
OPENAI_API_KEY="sk-..."       # Provider-specific fallback
ANTHROPIC_API_KEY="sk-ant-..." # Provider-specific fallback
```

---

## 9. Testing / 测试

**Directory:** `tests/`

### Test Structure

```
tests/
├── conftest.py          # Shared fixtures
├── helpers.py           # Test utilities
├── test_agent.py        # ReActAgent loop tests
├── test_cli.py          # CLI command tests
├── test_messages.py     # MessageHistory tests
└── test_tools.py        # Tool execution tests
```

### Key Fixtures (`conftest.py`)

- `mock_llm` — Returns controlled responses, no API calls
- `temp_workspace` — Temporary directory with test files
- `test_engine` — Fully wired Engine with mock LLM

### Running Tests / 运行测试

```bash
# All tests
pytest

# Specific file
pytest tests/test_tools.py

# With coverage
pytest --cov=src/codeassistant --cov-report=html

# Debug mode
pytest -s --log-cli-level=DEBUG
```

### Writing Tests / 编写测试

```python
import pytest
from codeassistant.tools.file_tools import ReadFile

@pytest.mark.asyncio
async def test_read_file(temp_workspace):
    tool = ReadFile(working_dir=str(temp_workspace))
    result = await tool.execute(path="test.py")
    assert result.success
    assert "hello world" in result.output

@pytest.mark.asyncio
async def test_agent_single_tool_call(mock_llm, test_engine):
    # Setup: LLM returns one tool call then text
    mock_llm.set_responses([
        LLMResponse(tool_calls=[ToolCall(id="1", name="read_file", arguments={"path": "x.py"})]),
        LLMResponse(content="Done!"),
    ])
    result = await test_engine.process_query("Read x.py")
    assert "Done!" in result
```

---

## 10. Development Setup / 开发环境搭建

### Prerequisites / 前提条件

- Python 3.11+
- Git
- An API key for at least one LLM provider (for manual testing)
- Optional: `chromadb` for semantic search features

### Setup / 环境搭建

```bash
# Clone
git clone <repo-url>
cd CodeAssistant-AI-Assistant

# Create virtual environment
python -m venv Development
source Development/Scripts/activate  # Windows Git Bash
# or: Development\Scripts\activate   # Windows CMD
# or: source Development/bin/activate  # Linux/macOS

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Verify installation
codeassistant --help
pytest  # Should pass with all green
```

### Project Config / 项目配置

Create `.aiassist.md` in the project root (already exists for CodeAssistant itself). This file is auto-loaded as context.

### Debugging / 调试

```bash
# Enable debug logging
CodeAssistant_LOG_LEVEL=DEBUG codeassistant

# Run with a specific test model (cheaper)
codeassistant --model gpt-4o-mini

# Use a local model (no API costs)
codeassistant --model ollama/llama3
```

### Code Style / 代码风格

- **Type hints:** All public functions and methods must have type annotations
- **Docstrings:** All public classes and methods must have docstrings (Google style preferred)
- **Async by default:** All I/O operations should be async
- **Tool ABC:** New tools must extend `Tool` and follow the established patterns
- **Message format:** Stick to OpenAI-compatible format for LLM interoperability

---

## 11. Roadmap & Contributing / 路线图与贡献

### Architecture Principles / 架构原则

1. **Separation of concerns** — CLI rendering, agent logic, tool execution, and LLM calls are independent
2. **Composition over inheritance** — Systems are wired together, not inherited
3. **Async-first** — All I/O is async; concurrency is the default
4. **Least privilege** — Tools and SubAgents get only the permissions they need
5. **Graceful degradation** — Features like vector search and compression fall back instead of crashing

### How to Contribute / 如何贡献

1. **Fork** the repository
2. **Create a branch:** `feature/your-feature` or `fix/your-bugfix`
3. **Add tests** for new functionality
4. **Run `pytest`** to confirm everything passes
5. **Update docs** if adding new tools, SubAgent types, or configuration options
6. **Submit a PR** with a clear description

### What to Contribute / 可贡献方向

| Area | Ideas |
|---|---|
| **Tools** | LSP integration, database query tool, Docker tool, AWS/GCP CLI tools |
| **Code Intelligence** | Support for more languages (Rust, Go, Java AST), call graph analysis |
| **SubAgents** | Specialized agents for specific frameworks (Django, React, Spring Boot) |
| **UI** | VS Code extension, web dashboard, Slack bot integration |
| **Memory** | Vector-based memory search, automatic memory extraction from conversations |
| **MCP** | More MCP server implementations, MCP tool discovery improvements |
| **Performance** | Prompt caching improvements, streaming optimizations, parallel tool execution |

### Key Files Reference / 核心文件速查

| File | What It Does |
|---|---|
| `core/agent.py` | **The ReAct loop** — where the magic happens |
| `core/engine.py` | **Composition root** — wires everything together |
| `core/subagent.py` | **Parallel agents** — multi-agent orchestration |
| `core/workflow.py` | **Workflow engine** — composable async patterns |
| `tools/base.py` | **Tool ABC** — the contract all tools follow |
| `tools/file_tools.py` | **File operations** — read, write, edit, search |
| `llm/litellm_adapter.py` | **LLM integration** — 100+ providers via LiteLLM |
| `context/compression.py` | **Auto-summarization** — keeps context manageable |
| `context/persistent.py` | **Long-term memory** — file-based knowledge store |
| `utils/permissions.py` | **Security** — three-tier permission system |

---

> **CodeAssistant** — A Python-native, composable AI coding agent. Hackable, extensible, open source.
>
> **CodeAssistant** — 一个 Python 原生的、可组合的 AI 编程 Agent。可定制、可扩展、开源。

---

*Document version: 1.0 — Last updated: 2026-07-06*
