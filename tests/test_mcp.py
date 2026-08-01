import asyncio

from app.config import PROJECT_ROOT
from app.mcp_client import McpInspectorClient, REQUIRED_TOOLS


def test_mcp_tool_discovery_and_read_only_calls():
    async def run():
        client = McpInspectorClient()
        try:
            await client.start()
            tools = await client._session.list_tools()
            listing = await client.call_tool(
                "list_project_files",
                {"repository_path": str(PROJECT_ROOT)},
            )
            search = await client.call_tool(
                "search_code",
                {
                    "repository_path": str(PROJECT_ROOT),
                    "queries": ["DiagnosisRequest", "FixPilot"],
                    "max_results": 8,
                },
            )
            return listing, search, {tool.name for tool in tools.tools}
        finally:
            await client.close()

    listing, search, tool_names = asyncio.run(run())
    assert tool_names == REQUIRED_TOOLS
    assert listing["files_scanned"] > 0
    assert search["matches"]
