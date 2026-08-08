"""MCP 服务白名单。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class McpServiceConfig:
    """单个远程 MCP 的连接配置；密钥仅通过环境变量注入。"""

    name: str
    transport: str
    endpoint: str
    timeout_seconds: int = 20


ALLOWED_MCP_SERVICES = {"akshare-one-mcp", "cn-financial-mcp"}
