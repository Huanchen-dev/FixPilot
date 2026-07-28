"""把项目一RAG能力暴露为标准MCP工具。"""

from mcp.server.fastmcp import FastMCP

from app.rag_client import query_rag_service


mcp = FastMCP(
    "AgentCenter Knowledge Tools",
    instructions="提供项目一编程面试知识库问答工具。",
)


@mcp.tool()
async def query_knowledge_base(
    question: str,
    session_id: str = "mcp-default",
) -> dict[str, str]:
    """调用项目一RAG问答接口，并返回结构化答案与来源。"""

    result = await query_rag_service(question, session_id)
    return result.model_dump()


if __name__ == "__main__":
    mcp.run("stdio")
