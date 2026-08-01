"""Repository Inspector Agent内部使用的持久stdio MCP Client。"""

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from app.config import PROJECT_ROOT
REQUIRED_TOOLS = {
    "list_project_files",
    "read_source_file",
    "search_code",
    "read_dependency_manifest",
    "get_python_environment",
}


class McpInspectorClient:
    """维护stdio会话，只负责发现和执行MCP工具。"""

    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._start_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._session is not None:
            return
        async with self._start_lock:
            if self._session is not None:
                return
            stack = AsyncExitStack()
            try:
                read_stream, write_stream = await stack.enter_async_context(
                    stdio_client(
                        StdioServerParameters(
                            command=sys.executable,
                            args=["-m", "app.mcp_server"],
                            cwd=PROJECT_ROOT,
                            env=os.environ.copy(),
                        )
                    )
                )
                session = await stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )
                await session.initialize()
                tools = await session.list_tools()
                available = {tool.name for tool in tools.tools}
                missing = sorted(REQUIRED_TOOLS - available)
                if missing:
                    raise RuntimeError(f"MCP Server缺少工具：{', '.join(missing)}")
            except Exception:
                await stack.aclose()
                raise
            self._stack = stack
            self._session = session

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        await self.start()
        if self._session is None:
            raise RuntimeError("MCP Client尚未建立连接。")
        result = await self._session.call_tool(name, arguments)
        payload = self._extract_payload(result.structuredContent, result.content)
        if getattr(result, "isError", False):
            raise RuntimeError(str(payload))
        return payload

    async def close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None

    @staticmethod
    def _extract_payload(
        structured_content: dict[str, Any] | None,
        content: list[Any],
    ) -> dict[str, Any]:
        if structured_content:
            if "result" in structured_content and isinstance(
                structured_content["result"], dict
            ):
                return structured_content["result"]
            return structured_content
        text = "\n".join(
            item.text for item in content if isinstance(item, TextContent)
        )
        if not text:
            raise ValueError("MCP工具没有返回可解析内容。")
        payload = json.loads(text)
        if isinstance(payload, dict) and "result" in payload:
            payload = payload["result"]
        if not isinstance(payload, dict):
            raise ValueError("MCP工具返回格式不是对象。")
        return payload
