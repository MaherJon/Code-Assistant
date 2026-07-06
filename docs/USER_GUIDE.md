# MAHE 用户指南 / MAHE User Guide

> AI-Powered Terminal Programming Assistant / AI 驱动的终端编程助手

---

## 目录 / Table of Contents

1. [快速开始 / Quick Start](#1-快速开始--quick-start)
2. [安装配置 / Installation](#2-安装配置--installation)
3. [基础用法 / Basic Usage](#3-基础用法--basic-usage)
4. [REPL 交互 / REPL Interaction](#4-repl-交互--repl-interaction)
5. [工具系统 / Tool System](#5-工具系统--tool-system)
6. [高级功能 / Advanced Features](#6-高级功能--advanced-features)
7. [配置参考 / Configuration](#7-配置参考--configuration)
8. [常见问题 / FAQ](#8-常见问题--faq)

---

## 1. 快速开始 / Quick Start

```bash
# 设置 API Key / Set API Key
export OPENAI_API_KEY="sk-..."

# 启动 REPL / Launch REPL
mahe

# 指定模型 / With specific model
mahe --model claude-sonnet-5 --provider anthropic
mahe --model deepseek-chat --provider deepseek

# 单次问答 / One-shot question
mahe ask "这段代码是做什么的？"              # What does this code do?
mahe ask "帮我写一个快速排序函数"             # Write a quicksort function

# 索引项目 / Index project for semantic search
mahe index

# 定时任务 / Scheduled task
mahe loop start 5m "检查构建状态"           # Check build status every 5 min
mahe loop once 10m "提醒我提交代码"          # Remind me to commit in 10 min

# MCP 服务器管理 / MCP server management
mahe mcp list
mahe mcp serve
```

---

## 2. 安装配置 / Installation

### 2.1 环境要求 / Prerequisites

- Python 3.11+
- 至少一个 LLM 提供商的 API Key / At least one LLM provider API key

### 2.2 安装步骤 / Install Steps

```bash
# 克隆项目 / Clone
cd /path/to/MAHE-AI-Assistant

# 安装 (开发模式) / Install (dev mode)
pip install -e .

# 可选：安装语义搜索支持 / Optional: semantic search
pip install chromadb
```

### 2.3 设置 API Key / Set API Key

支持以下方式设置（优先级从高到低）：

| 方式 Method | 示例 Example |
|---|---|
| 环境变量 Env Var | `export OPENAI_API_KEY="sk-..."` |
| 统一变量 Unified | `export MAHE_API_KEY="sk-..."` |
| 配置文件 Config | `mahe config --set api_key sk-...` |
| CLI 参数 CLI Flag | `mahe --api-key sk-...` |

支持的提供商 / Supported providers:

```bash
export OPENAI_API_KEY="sk-..."          # OpenAI (GPT-4o, GPT-4o-mini)
export ANTHROPIC_API_KEY="sk-ant-..."   # Anthropic Claude
export DEEPSEEK_API_KEY="sk-..."        # DeepSeek
# 或使用自定义 API Base / Or custom API base
export MAHE_API_BASE="https://your-api.com/v1"
```

### 2.4 项目配置 / Project Config

在项目根目录创建 `.aiassist.md` 文件，MAHE 启动时会自动加载作为上下文：

Create `.aiassist.md` in your project root, MAHE loads it as context:

```markdown
# 项目名称 / My Project
技术栈 / Tech Stack: Python 3.12, FastAPI, PostgreSQL

## 架构 / Architecture
- src/api/ - API 路由 / Route handlers
- src/models/ - 数据模型 / Data models
- src/services/ - 业务逻辑 / Business logic

## 约定 / Conventions
- 使用类型注解 / Use type hints
- 测试框架 / Test framework: pytest + async
```

---

## 3. 基础用法 / Basic Usage

### 3.1 命令行模式 / CLI Modes

```bash
# 交互式 REPL（推荐）/ Interactive REPL (recommended)
mahe

# 单次问答 / One-shot
mahe ask "查看 git 状态"                    # Show git status
mahe ask "src/auth.py 里有什么函数？"        # What functions are in auth.py?

# 查看配置 / View config
mahe config --list

# 修改配置 / Change config
mahe config --set model gpt-4o-mini
mahe config --set provider deepseek

# 索引项目（语义搜索）/ Index project (semantic search)
mahe index
mahe index --update                          # 增量更新 / Incremental update

# 定时任务 / Scheduled tasks
mahe loop start 5m "检查 CI 状态"           # Every 5 minutes
mahe loop start 1h "拉取最新代码并测试"      # Every hour
mahe loop list                               # 查看运行中的任务
mahe loop once 30m "提醒我休息"              # One-shot after 30 min

# MCP 管理 / MCP management
mahe mcp list                                # 列出配置的服务器
mahe mcp serve                               # 启动 MCP 服务器
```

### 3.2 常用交互示例 / Common Interactions

```
mahe> 帮我看看这个项目是什么结构
mahe> What's the structure of this project?

mahe> 在 src/api/users.py 里添加一个 GET /users/:id 接口
mahe> Add a GET /users/:id endpoint in src/api/users.py

mahe> 这个函数有 bug，帮我修复：def divide(a, b): return a/b
mahe> Fix this buggy function: def divide(a, b): return a/b

mahe> 运行测试，把失败的都修好
mahe> Run the tests and fix all failures

mahe> 帮我在整个项目中找到所有使用旧 API 的地方
mahe> Find all places using the deprecated API across the project

mahe> 提交这些改动，写一个规范的 commit message
mahe> Commit these changes with a proper commit message
```

---

## 4. REPL 交互 / REPL Interaction

### 4.1 REPL 命令 / REPL Commands

| 命令 Command | 说明 Description |
|---|---|
| `/help` | 显示帮助 / Show help |
| `/clear` | 清除对话历史 / Clear conversation |
| `/config` | 查看当前配置 / Show config |
| `/model <name>` | 切换模型 / Switch model |
| `/provider <name>` | 切换提供商 / Switch provider |
| `/mode` | 切换权限模式 / Toggle permission mode |
| `/loop start <间隔> <任务>` | 启动定时任务 / Start scheduled loop |
| `/loop list` | 查看定时任务 / List loops |
| `/loop stop <id>` | 停止定时任务 / Stop loop |
| `/exit` | 退出 / Exit |

### 4.2 键盘快捷键 / Keyboard Shortcuts

| 按键 Key | 功能 Function |
|---|---|
| `Enter` | 提交当前行 / Submit |
| `Alt+Enter` | 多行输入 / Multi-line input |
| `Ctrl+C` | 取消当前操作 / Cancel current action |
| `Ctrl+D` | 退出 / Exit |

### 4.3 权限模式 / Permission Modes

| 模式 Mode | 行为 Behavior |
|---|---|
| `prompt` (默认) | 写文件和危险命令需确认 / Confirm writes & dangerous commands |
| `auto_safe` | 安全操作自动放行 / Auto-allow safe operations |

切换方式 / Toggle: 命令行 `--permission-mode auto_safe` 或 REPL 内 `/mode`

---

## 5. 工具系统 / Tool System

MAHE 配备了 22 个内置工具，分类如下：

### 5.1 文件工具 / File Tools

| 工具 Tool | 功能 Function | 权限 Permission |
|---|---|---|
| `read_file` | 读取文件 / Read file | 安全 |
| `write_file` | 写入/创建文件 / Write/create file | 需确认 |
| `edit_file` | 精确字符串替换编辑 / Exact string replacement | 需确认 |
| `glob_files` | 文件名模式匹配 / Glob pattern search | 安全 |
| `search_code` | 正则代码搜索 / Regex code search | 安全 |

### 5.2 代码智能工具 / Code Intelligence

| 工具 Tool | 功能 Function |
|---|---|
| `analyze_code` | 多语言 AST 分析 (Python/JS/TS/Go/Rust) / Multi-language AST analysis |
| `python_definition` | 跳转到定义 / Go to definition |
| `python_references` | 查找所有引用 / Find all references |
| `python_hover` | 查看文档和签名 / View docstring & signature |

### 5.3 Shell & Git 工具

| 工具 Tool | 功能 Function | 权限 Permission |
|---|---|---|
| `run_shell` | 执行 Shell 命令 / Execute shell | 需确认 |
| `git_status` | 查看状态 / Show status | 安全 |
| `git_diff` | 查看差异 / Show diff | 安全 |
| `git_log` | 查看日志 / Show log | 安全 |
| `git_branch` | 查看分支 / List branches | 安全 |
| `git_add` | 暂存文件 / Stage files | 需确认 |
| `git_commit` | 提交 / Commit | 需确认 |

### 5.4 测试 & 委托工具 / Test & Delegation

| 工具 Tool | 功能 Function |
|---|---|
| `run_tests` | 运行 pytest 并分析失败 / Run tests & analyze failures |
| `delegate_task` | 派发任务给并行 SubAgent / Delegate to parallel sub-agents |

### 5.5 记忆工具 / Memory Tools

| 工具 Tool | 功能 Function |
|---|---|
| `save_memory` | 保存到项目记忆 / Save to project memory |
| `recall_memory` | 搜索项目记忆 / Search memories |
| `list_memories` | 列出所有记忆 / List all memories |

---

## 6. 高级功能 / Advanced Features

### 6.1 SubAgent 并行协作 / Parallel SubAgent Collaboration

MAHE 可将复杂任务拆分给多个并行子 Agent：

```
mahe> 从正确性、安全性和性能三个角度审查 src/auth.py
mahe> Review src/auth.py from correctness, security, and performance angles
```

MAHE 会同时启动 3 个专业 SubAgent：
- `code-reviewer`：检查逻辑错误和代码风格
- `security-auditor`：扫描安全漏洞
- `code-explorer`：分析完整性和依赖关系

预定义的 SubAgent 类型：

| 类型 Type | 用途 Purpose | 工具 Tools |
|---|---|---|
| `code-reviewer` | 代码审查 / Code review | read, search, glob, analyze |
| `test-fixer` | 测试修复 / Test fixing | read, write, edit, shell, test |
| `code-explorer` | 代码探索 / Code exploration | read, search, glob, analyze |
| `refactorer` | 大规模重构 / Refactoring | read, write, edit, shell |
| `security-auditor` | 安全审计 / Security audit | read, search, shell |

### 6.2 语义代码搜索 / Semantic Code Search

```bash
# 1. 先索引项目
mahe index

# 2. 在 REPL 中用自然语言搜索
mahe> 找到处理用户认证的代码在哪里
mahe> Find where authentication logic is implemented
```

索引文件存储在 `.mahe/vectors/` 目录，使用 Chroma 向量数据库。

### 6.3 上下文压缩 / Context Compression

当对话超过 92% 上下文窗口时，MAHE 会自动用 LLM 压缩旧消息为摘要，保留关键技术细节。你无需任何操作。

### 6.4 持久记忆 / Persistent Memory

```bash
# MAHE 会记住项目相关的知识
mahe> 记住：这个项目使用 PostgreSQL，不要用 SQLite
mahe> Remember: this project uses PostgreSQL, never use SQLite

# 下次会话 MAHE 会自动加载这些记忆
mahe> 数据库用什么？  # MAHE: PostgreSQL（从记忆读取）
```

记忆存储在 `.mahe/memory/` 目录，可手动编辑。

### 6.5 定时任务 (Loop) / Scheduled Tasks

```bash
# 每 5 分钟检查构建状态
mahe loop start 5m "运行 pytest 并报告结果"

# 每天拉取最新代码并测试
mahe loop start 1h "git pull && pytest"

# 30 分钟后提醒
mahe loop once 30m "记得提交代码"

# 查看运行中的任务
mahe loop list

# REPL 中也可以管理
/loop start 10m 检查服务器状态
/loop list
/loop stop loop-a1b2c3d4
```

### 6.6 MCP 协议 / MCP Protocol

连接外部工具（数据库、文件系统、API 等）：

```yaml
# ~/.mahe/mcp_servers.yaml
servers:
  - name: database
    command: python
    args: ["mcp_postgres.py"]
    env:
      DATABASE_URL: "postgresql://localhost/mydb"
```

```bash
mahe mcp list     # 查看配置的服务器
mahe mcp serve    # 启动 MCP 服务器，工具自动注册到 MAHE
```

### 6.7 工作流引擎 / Workflow Engine

开发者可通过 Python API 组合工作流：

```python
from mahe.core.workflow import WorkflowEngine, WorkflowStage

engine = WorkflowEngine()

# 流水线：分析 → 修改 → 验证
result = await engine.pipeline([
    WorkflowStage("analyze", handler=analyze),
    WorkflowStage("fix", handler=fix),
    WorkflowStage("verify", handler=verify),
])

# 并行处理多个文件
results = await engine.fanout(
    items=["file1.py", "file2.py", "file3.py"],
    handler=process_file,
)
```

---

## 7. 配置参考 / Configuration

### 7.1 环境变量 / Environment Variables

| 变量 Variable | 说明 Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI API 密钥 |
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 |
| `MAHE_API_KEY` | 通用 API 密钥（最高优先级） |
| `MAHE_API_BASE` | 自定义 API 基础 URL |
| `MAHE_MODEL` | 默认模型名称 |
| `MAHE_PROVIDER` | 默认提供商 |
| `MAHE_PERMISSION_MODE` | 权限模式 (prompt / auto_safe) |

### 7.2 配置文件 / Config File

`~/.mahe/config.yaml`:

```yaml
provider: openai
model: gpt-4o
api_base: null
permission_mode: prompt
```

### 7.3 项目配置 / Project Config

`.aiassist.md` (项目根目录):

```markdown
# 项目名称
技术栈和架构说明...
```

`.mahe/memory/*.md` — 持久化记忆文件

`.mahe/vectors/` — 语义搜索索引

---

## 8. 常见问题 / FAQ

### Q: 如何切换模型？ / How to switch models?

```bash
# 命令行
mahe --model gpt-4o-mini
mahe --model claude-sonnet-5 --provider anthropic

# REPL 内
/model gpt-4o-mini
/provider deepseek
```

### Q: 支持本地模型吗？ / Does it support local models?

支持。通过 LiteLLM 可以连接 Ollama、vLLM 等本地模型服务：

```bash
export OPENAI_API_BASE="http://localhost:11434/v1"
export OPENAI_API_KEY="ollama"
mahe --model ollama/llama3
```

### Q: 如何让 MAHE 自动执行安全操作？ / How to auto-allow safe ops?

```bash
mahe --permission-mode auto_safe
# 或 REPL 内 /mode
```

### Q: 定时任务会在后台一直运行吗？ / Do loops run in the background?

Loop 在 REPL 进程内运行。关闭 REPL 后 Loop 也会停止。适合开发时持续监控的场景。

### Q: SubAgent 会消耗更多 Token 吗？ / Do sub-agents use more tokens?

是的。每个 SubAgent 在自己的上下文中运行，会产生额外的 Token 消耗。建议对大型任务使用 SubAgent，简单任务直接用主 Agent。

### Q: 语义搜索需要什么额外配置？ / What's needed for semantic search?

```bash
pip install chromadb
mahe index   # 索引当前项目
```

### Q: 如何贡献？ / How to contribute?

欢迎提交 Issue 和 PR！项目结构见 [ARCHITECTURE.md](./ARCHITECTURE.md)

---

> **MAHE** — 终端里的 Python 原生智能编程伙伴
>
> Python-native intelligent coding companion in your terminal
