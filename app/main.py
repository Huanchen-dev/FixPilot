"""AgentCenter的FastAPI统一入口。"""

import json
from collections.abc import AsyncIterator

from fastapi import FastAPI
from langchain_core.messages import HumanMessage
from starlette.responses import StreamingResponse

from app.graph import agent_graph
from app.schemas import ChatRequest, ChatResponse


app = FastAPI(
    title="AgentCenter",
    description="基于LangGraph、A2A与MCP的智能路由协同服务",
    version="1.0.0",
)


@app.get("/health", summary="服务健康检查")
def health_check() -> dict[str, str]:
    """返回最小健康状态，用于确认FastAPI服务已经正常启动。"""

    return {
        "status": "ok",
        "service": "AgentCenter",
    }


@app.post("/chat", response_model=ChatResponse, summary="执行路由工作流")
async def chat(request: ChatRequest) -> ChatResponse:
    """把请求交给LangGraph，并返回统一结果。"""

    final_state = await agent_graph.ainvoke(
        {
            "messages": [HumanMessage(content=request.message)],
            "thread_id": request.thread_id,
        },
        config={"configurable": {"thread_id": request.thread_id}},
    )
    return ChatResponse(
        intent=final_state["intent"],
        response=final_state["response"],
        source=final_state["source"],
        thread_id=request.thread_id,
    )


def sse_event(event: str, data: dict[str, object]) -> str:
    """把一个事件编码成SSE要求的文本格式。"""

    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


async def stream_chat_events(request: ChatRequest) -> AsyncIterator[str]:
    """把LangGraph事件转换成稳定的SSE事件契约。"""

    config = {"configurable": {"thread_id": request.thread_id}}
    yield sse_event("start", {"thread_id": request.thread_id})
    emitted_token = False
    emitted_message = False
    intent = "chat"
    source = "CHAT"

    try:
        async for event in agent_graph.astream_events(
            {
                "messages": [HumanMessage(content=request.message)],
                "thread_id": request.thread_id,
            },
            config=config,
            version="v2",
        ):
            metadata = event.get("metadata", {})
            node = metadata.get("langgraph_node") or event.get("name")

            if event["event"] == "on_chain_end" and node == "router":
                output = event["data"].get("output", {})
                if isinstance(output, dict) and output.get("intent"):
                    intent = str(output["intent"])
                    yield sse_event("route", {"intent": intent})

            elif (
                event["event"] == "on_chat_model_stream"
                and node == "chat_agent"
            ):
                content = event["data"]["chunk"].content
                if isinstance(content, str) and content:
                    emitted_token = True
                    source = "CHAT"
                    yield sse_event(
                        "token",
                        {"content": content, "source": source},
                    )

            elif event["event"] == "on_chain_end" and node in {
                "chat_agent",
                "knowledge_agent",
            }:
                output = event["data"].get("output", {})
                if not isinstance(output, dict):
                    continue
                response = output.get("response")
                source = str(output.get("source", source))
                should_emit_message = node == "knowledge_agent" or not emitted_token
                if response and should_emit_message and not emitted_message:
                    emitted_message = True
                    yield sse_event(
                        "message",
                        {
                            "content": response,
                            "source": output.get("source", "RAG"),
                        },
                    )

        yield sse_event(
            "done",
            {
                "intent": intent,
                "source": source,
                "streamed": emitted_token,
            },
        )
    except Exception:
        yield sse_event(
            "error",
            {"message": "AgentCenter处理失败，请检查服务状态后重试。"},
        )


@app.post("/chat/stream", summary="以SSE流式执行路由工作流")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """返回持续发送SSE事件的响应，而不是等待完整答案。"""

    return StreamingResponse(
        stream_chat_events(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
