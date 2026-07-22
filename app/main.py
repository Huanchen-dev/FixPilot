"""AgentCenter 的 FastAPI 应用入口。"""

from fastapi import FastAPI
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app.graph import agent_graph

# 创建整个后端服务的应用对象；Uvicorn 启动时会加载它。
app = FastAPI(
    title="AgentCenter",
    description="多智能体协同中台",
    version="0.1.0",
)


class ChatRequest(BaseModel):
    """第一个聊天接口接收的最小请求体。"""

    message: str = Field(min_length=1, description="用户本次输入")
    thread_id: str = Field(min_length=1, description="会话标识，同一标识共享会话记忆")


@app.get("/health", summary="服务健康检查")
def health_check() -> dict[str, str]:
    """返回最小健康状态，用于确认FastAPI服务已经正常启动。"""

    return {
        "status": "ok",
        "service": "AgentCenter",
    }


@app.post("/chat", summary="执行路由工作流")
def chat(request: ChatRequest) -> dict[str, str]:
    """把请求交给LangGraph，并返回路由结果和占位回答。"""

    final_state = agent_graph.invoke(
        {"messages": [HumanMessage(content=request.message)]},
        config={"configurable": {"thread_id": request.thread_id}},
    )
    return {
        "intent": final_state["intent"],
        "response": final_state["response"],
        "thread_id": request.thread_id,
    }
