"""AgentCenter 各入口共享的请求、响应与路由数据结构。"""

from typing import Literal

from pydantic import BaseModel, Field


Intent = Literal["chat", "knowledge"]


class ChatRequest(BaseModel):
    """AgentCenter聊天入口接收的请求。"""

    message: str = Field(min_length=1, description="用户本次输入")
    thread_id: str = Field(min_length=1, description="同一标识共享会话状态")


class ChatResponse(BaseModel):
    """普通聊天接口的统一响应。"""

    intent: Intent
    response: str
    source: str
    thread_id: str


class RouterDecision(BaseModel):
    """Router模型必须返回的结构化意图。"""

    intent: Intent = Field(description="普通交流选chat，需要知识库资料选knowledge")


class KnowledgeResult(BaseModel):
    """Knowledge Agent、MCP工具和RAG服务之间的统一结果。"""

    answer: str
    source: str
