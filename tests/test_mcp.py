import asyncio

from app.mcp_client import McpKnowledgeClient


def test_mcp_tool_discovery_and_call():
    async def run():
        client = McpKnowledgeClient()
        try:
            return await client.query("协议连通性测试", "mcp-test")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result.source
    assert result.answer
