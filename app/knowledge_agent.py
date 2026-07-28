"""通过A2A协议提供知识库问答能力的独立Agent服务。"""

import json
from contextlib import asynccontextmanager
from typing import AsyncIterator

from a2a.helpers.proto_helpers import new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
)
from a2a.utils.constants import PROTOCOL_VERSION_1_0, TransportProtocol
from fastapi import FastAPI

from app.config import KNOWLEDGE_AGENT_BASE_URL
from app.mcp_client import McpKnowledgeClient


mcp_knowledge_client = McpKnowledgeClient()


class KnowledgeAgentExecutor(AgentExecutor):
    """把A2A任务转交给MCP知识库工具。"""

    def __init__(self, mcp_client: McpKnowledgeClient) -> None:
        self.mcp_client = mcp_client

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        if not context.task_id or not context.context_id:
            raise RuntimeError("A2A请求缺少task_id或context_id。")
        if context.current_task is None:
            if context.message is None:
                raise RuntimeError("A2A请求缺少用户消息。")
            await event_queue.enqueue_event(
                new_task_from_user_message(context.message)
            )

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.start_work()
        try:
            result = await self.mcp_client.query(
                context.get_user_input(),
                context.context_id,
            )
            payload = json.dumps(result.model_dump(), ensure_ascii=False)
            await updater.add_artifact(
                [new_text_part(payload, media_type="application/json")],
                name="knowledge-answer",
            )
            await updater.complete()
        except Exception:
            await updater.failed(
                updater.new_agent_message(
                    [new_text_part("Knowledge Agent调用失败，请稍后重试。")]
                )
            )

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        if context.task_id and context.context_id:
            await TaskUpdater(
                event_queue,
                context.task_id,
                context.context_id,
            ).cancel()


agent_card = AgentCard(
    name="AgentCenter Knowledge Agent",
    description="通过MCP调用项目一RAG服务，回答编程面试知识问题。",
    supported_interfaces=[
        AgentInterface(
            url=f"{KNOWLEDGE_AGENT_BASE_URL.rstrip('/')}/a2a",
            protocol_binding=TransportProtocol.JSONRPC,
            protocol_version=PROTOCOL_VERSION_1_0,
        )
    ],
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=False),
    default_input_modes=["text/plain"],
    default_output_modes=["application/json"],
    skills=[
        AgentSkill(
            id="programming-interview-knowledge",
            name="编程面试知识库问答",
            description="检索项目一知识库并返回有来源标记的答案。",
            tags=["RAG", "编程面试", "知识库"],
            examples=["解释BGE-M3的稠密向量与稀疏向量。"],
        )
    ],
)

request_handler = DefaultRequestHandler(
    agent_executor=KnowledgeAgentExecutor(mcp_knowledge_client),
    task_store=InMemoryTaskStore(),
    agent_card=agent_card,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await mcp_knowledge_client.close()


app = FastAPI(
    title="AgentCenter Knowledge Agent",
    description="A2A知识库Agent服务",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", summary="Knowledge Agent健康检查")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "knowledge-agent"}


add_a2a_routes_to_fastapi(
    app,
    agent_card_routes=create_agent_card_routes(agent_card),
    jsonrpc_routes=create_jsonrpc_routes(request_handler, rpc_url="/a2a"),
)
