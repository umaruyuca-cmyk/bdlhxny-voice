"""远程 MCP Client：支持 SSE 与 Streamable HTTP 两种传输。

两个金融 MCP 服务的传输协议不同（见 2026-08-06 实测）：
- cn-financial-mcp 用 SSE（:8000/sse）
- akshare-one-mcp 用 Streamable HTTP（:8083/mcp）

两者的 mcp 客户端 async with 都返回 2 元组 (read, write)——这是实测确认的，
不是 3 元组。本模块对上层屏蔽传输差异，统一暴露 McpClient 接口。

连接生命周期：每次 call_tool 内部建立连接、调用、关闭。MCP SDK 的
streamable_http_client / sse_client 是 async context manager，不能跨
调用复用连接（SSE 尤其如此）。如需连接池化，后续在 Gateway 层做。
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger("stockwise_analysis.mcp.client")


class McpClient(Protocol):
    """单个 MCP 服务连接的统一接口。

    Gateway 不得绕过 Adapter 直接持有 McpClient；Adapter 通过本接口调用
    原始工具，标准化由 observations/normalizer 负责。
    """

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调用 MCP 原始工具并返回原始响应。

        返回 dict 包含 content（工具输出文本列表）和 isError（协议层错误
        标志）。注意：cn-financial 的部分工具会把数据源失败包成正常响应
        （{"error": true, ...}），此时 isError=False——这种"服务端吞错"
        由 normalizer 解析响应体识别，不在这里处理。
        """
        ...


class SseMcpClient:
    """SSE 传输的 MCP 客户端（用于 cn-financial-mcp）。

    每次 call_tool 建立 SSE 连接 → initialize 握手 → 调用工具 → 关闭。
    SSE 是长连接，不能在调用间复用同一个 context manager。
    """

    def __init__(self, endpoint: str, timeout_seconds: float = 20.0):
        self._endpoint = endpoint
        self._timeout = timeout_seconds

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        import asyncio

        from mcp.client.session import ClientSession
        from mcp.client.sse import sse_client

        async with sse_client(url=self._endpoint) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=self._timeout)
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments), timeout=self._timeout
                )
                return _extract_result(result)


class StreamableHttpMcpClient:
    """Streamable HTTP 传输的 MCP 客户端（用于 akshare-one-mcp）。

    与 SseMcpClient 接口一致，但底层用 streamable_http_client。两者返回
    都是 2 元组 (read, write)，但握手协议不同，不能混用。
    """

    def __init__(self, endpoint: str, timeout_seconds: float = 20.0):
        self._endpoint = endpoint
        self._timeout = timeout_seconds

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        import asyncio

        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        # 注意：streamable_http_client 返回 2 元组 (read, write)，不是 3 元组
        async with streamable_http_client(url=self._endpoint) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=self._timeout)
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments), timeout=self._timeout
                )
                return _extract_result(result)


def _extract_result(result: Any) -> dict[str, Any]:
    """从 MCP SDK 的 CallToolResult 提取为纯 dict。

    MCP 返回的 content 是 TextContent 列表，这里拼接成文本。isError 是
    协议层错误标志（True=工具抛异常），但服务端吞错（{"error":true}）
    不影响 isError，由 normalizer 处理。
    """
    contents = []
    if hasattr(result, "content"):
        for item in result.content:
            text = getattr(item, "text", None)
            if text is not None:
                contents.append(text)
    return {
        "text": "\n".join(contents),
        "is_error": bool(getattr(result, "isError", False)),
        "raw_content_count": len(getattr(result, "content", [])),
    }


def create_mcp_client(transport: str, endpoint: str, timeout_seconds: float = 20.0) -> McpClient:
    """工厂函数：按传输类型创建对应客户端。

    传输类型来自 Settings.mcp_*.transport，必须在配置里显式指定——
    不能假设两个 MCP 用同一种传输（实测就是不同的）。
    """
    if transport == "sse":
        return SseMcpClient(endpoint, timeout_seconds)
    if transport == "streamable_http":
        return StreamableHttpMcpClient(endpoint, timeout_seconds)
    raise ValueError(f"不支持的 MCP 传输类型: {transport}（仅支持 sse / streamable_http）")
