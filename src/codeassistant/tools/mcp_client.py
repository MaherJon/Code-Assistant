"""MCP (Model Context Protocol) client for external tool integration.

Connects to MCP servers via stdio transport, discovers their tools,
and registers them into the existing ToolRegistry.

MCP servers are configured in ~/.codeassistant/mcp_servers.yaml:
```yaml
servers:
  - name: filesystem
    command: npx
    args: ["-y", "@anthropic/mcp-filesystem", "/path/to/dir"]
  - name: database
    command: python
    args: ["mcp_server.py"]
    env:
      DATABASE_URL: postgresql://...
```
"""

import asyncio
import json
import logging
import os
import signal
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from codeassistant.tools.base import Tool, ToolResult, ToolPermission

logger = logging.getLogger("codeassistant.mcp")


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)


class MCPToolWrapper(Tool):
    """Wraps an MCP tool as a CodeAssistant Tool.

    MCP tools are discovered from connected servers and wrapped
    so the agent can use them transparently.
    """

    def __init__(self, mcp_name: str, server_name: str, tool_def: Dict, client: "MCPClient"):
        self.name = mcp_name
        self._server_name = server_name
        self._client = client
        self.description = tool_def.get("description", f"MCP tool: {mcp_name}")
        self.parameters = tool_def.get("inputSchema", {
            "type": "object",
            "properties": {},
            "required": [],
        })
        self.permission = ToolPermission.NEEDS_CONFIRM  # MCP tools always need confirmation

    async def execute(self, **params) -> ToolResult:
        """Execute the MCP tool via the client."""
        try:
            result = await self._client.call_tool(self._server_name, self.name, params)
            return result
        except Exception as e:
            return ToolResult.fail(f"MCP tool '{self.name}' failed: {e}")


class MCPClient:
    """MCP (Model Context Protocol) client using stdio transport.

    Manages connections to MCP servers, discovers their tools,
    and provides a unified interface for tool execution.
    """

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or os.path.expanduser("~/.codeassistant/mcp_servers.yaml")
        self._servers: Dict[str, Dict] = {}  # name -> {process, reader, writer}
        self._tools: Dict[str, MCPToolWrapper] = {}
        self._request_id = 0

    def load_config(self) -> List[MCPServerConfig]:
        """Load MCP server configurations from file."""
        if not os.path.exists(self.config_path):
            return []

        try:
            with open(self.config_path, "r") as f:
                import yaml
                config = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("Failed to load MCP config: %s", e)
            return []

        servers = []
        for server_data in config.get("servers", []):
            servers.append(MCPServerConfig(
                name=server_data.get("name", "unknown"),
                command=server_data.get("command", ""),
                args=server_data.get("args", []),
                env=server_data.get("env", {}),
            ))

        return servers

    async def connect_all(self) -> Dict[str, List[str]]:
        """Connect to all configured MCP servers and discover their tools.

        Returns:
            Dict mapping server_name -> list of tool names
        """
        configs = self.load_config()
        results = {}

        for config in configs:
            try:
                tools = await self._connect_server(config)
                if tools:
                    results[config.name] = tools
                    logger.info("MCP server '%s': %d tools discovered", config.name, len(tools))
            except Exception as e:
                logger.error("Failed to connect to MCP server '%s': %s", config.name, e)
                results[config.name] = []

        return results

    async def _connect_server(self, config: MCPServerConfig) -> List[str]:
        """Connect to a single MCP server and discover tools.

        Uses MCP's JSON-RPC over stdio protocol.
        """
        env = {**os.environ, **config.env}

        try:
            proc = await asyncio.create_subprocess_exec(
                config.command, *config.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError:
            logger.warning("MCP server command not found: %s", config.command)
            return []
        except Exception as e:
            logger.error("Failed to start MCP server '%s': %s", config.name, e)
            return []

        # Store process reference
        self._servers[config.name] = {
            "process": proc,
            "config": config,
        }

        # Initialize MCP session
        try:
            init_result = await self._send_request(
                config.name,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "codeassistant",
                        "version": "0.2.0",
                    },
                },
            )

            if not init_result:
                logger.warning("MCP server '%s' initialization failed", config.name)
                return []

            # Send initialized notification
            await self._send_notification(config.name, "notifications/initialized", {})

            # Discover tools
            tools_result = await self._send_request(
                config.name,
                "tools/list",
                {},
            )

            if not tools_result or "tools" not in tools_result:
                return []

            # Wrap each tool
            tool_names = []
            for tool_def in tools_result["tools"]:
                tool_name = tool_def.get("name", "")
                if tool_name:
                    mcp_name = f"mcp__{config.name}__{tool_name}"
                    wrapper = MCPToolWrapper(
                        mcp_name=mcp_name,
                        server_name=config.name,
                        tool_def=tool_def,
                        client=self,
                    )
                    self._tools[mcp_name] = wrapper
                    tool_names.append(mcp_name)

            return tool_names

        except Exception as e:
            logger.error("MCP protocol error for '%s': %s", config.name, e)
            return []

    async def _send_request(self, server_name: str, method: str, params: Dict) -> Optional[Dict]:
        """Send a JSON-RPC request to an MCP server."""
        server = self._servers.get(server_name)
        if not server:
            return None

        proc = server["process"]
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        try:
            request_bytes = (json.dumps(request) + "\n").encode("utf-8")
            proc.stdin.write(request_bytes)
            await proc.stdin.drain()

            # Read response
            response_line = await asyncio.wait_for(
                proc.stdout.readline(),
                timeout=30,
            )
            response = json.loads(response_line.decode("utf-8"))

            if "error" in response:
                logger.warning("MCP error [%s/%s]: %s", server_name, method, response["error"])
                return None

            return response.get("result")

        except asyncio.TimeoutError:
            logger.warning("MCP request timeout [%s/%s]", server_name, method)
            return None
        except Exception as e:
            logger.error("MCP request failed [%s/%s]: %s", server_name, method, e)
            return None

    async def _send_notification(self, server_name: str, method: str, params: Dict) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        server = self._servers.get(server_name)
        if not server:
            return

        proc = server["process"]
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        try:
            request_bytes = (json.dumps(notification) + "\n").encode("utf-8")
            proc.stdin.write(request_bytes)
            await proc.stdin.drain()
        except Exception as e:
            logger.debug("MCP notification failed [%s/%s]: %s", server_name, method, e)

    async def call_tool(self, server_name: str, tool_name: str, params: Dict) -> ToolResult:
        """Call an MCP tool and return the result."""
        result = await self._send_request(
            server_name,
            "tools/call",
            {
                "name": tool_name,
                "arguments": params,
            },
        )

        if result is None:
            return ToolResult.fail(f"MCP tool '{tool_name}' returned no result.")

        # MCP results can be text or structured content
        content = result.get("content", [])
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            output = "\n".join(text_parts)
        elif isinstance(content, str):
            output = content
        else:
            output = json.dumps(content)

        return ToolResult.ok(output)

    def get_all_tools(self) -> List[MCPToolWrapper]:
        """Get all discovered MCP tools."""
        return list(self._tools.values())

    def get_tool(self, name: str) -> Optional[MCPToolWrapper]:
        """Get a specific MCP tool by name."""
        return self._tools.get(name)

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers."""
        for name, server in self._servers.items():
            proc = server.get("process")
            if proc:
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                logger.info("Disconnected MCP server: %s", name)

        self._servers.clear()
        self._tools.clear()

    async def __aenter__(self):
        await self.connect_all()
        return self

    async def __aexit__(self, *args):
        await self.disconnect_all()
