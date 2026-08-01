"""通过A2A协议提供只读仓库证据收集能力的独立Agent。"""

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

from app.config import INSPECTOR_AGENT_BASE_URL
from app.mcp_client import McpInspectorClient
from app.repository_inspector import RepositoryInspector
from app.schemas import InspectionRequest


mcp_inspector_client = McpInspectorClient()
repository_inspector = RepositoryInspector(mcp_inspector_client)


class RepositoryInspectorExecutor(AgentExecutor):
    """把A2A检查任务交给受限的仓库取证Agent。"""

    def __init__(self, inspector: RepositoryInspector) -> None:
        self.inspector = inspector

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
            request = InspectionRequest.model_validate_json(
                context.get_user_input()
            )
            result = await self.inspector.inspect(request)
            payload = json.dumps(result.model_dump(), ensure_ascii=False)
            await updater.add_artifact(
                [new_text_part(payload, media_type="application/json")],
                name="repository-evidence",
            )
            await updater.complete()
        except Exception:
            await updater.failed(
                updater.new_agent_message(
                    [new_text_part("Repository Inspector执行失败，请检查输入与服务状态。")]
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
    name="FixPilot Repository Inspector",
    description="自主选择MCP只读工具，收集Python项目的代码、依赖和环境证据。",
    supported_interfaces=[
        AgentInterface(
            url=f"{INSPECTOR_AGENT_BASE_URL.rstrip('/')}/a2a",
            protocol_binding=TransportProtocol.JSONRPC,
            protocol_version=PROTOCOL_VERSION_1_0,
        )
    ],
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=False),
    default_input_modes=["application/json"],
    default_output_modes=["application/json"],
    skills=[
        AgentSkill(
            id="python-repository-inspection",
            name="Python仓库只读检查",
            description="受限循环检查代码与依赖，并返回取证轨迹和结构化证据。",
            tags=["Python", "Traceback", "只读检查", "故障诊断"],
            examples=["根据ModuleNotFoundError收集相关源码和依赖证据。"],
        )
    ],
)

request_handler = DefaultRequestHandler(
    agent_executor=RepositoryInspectorExecutor(repository_inspector),
    task_store=InMemoryTaskStore(),
    agent_card=agent_card,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # MCP 的 stdio 上下文必须由同一个 asyncio task 负责进入和退出。
    # 因此连接跟随应用生命周期建立，不能等到某个 A2A 请求里再懒启动。
    await mcp_inspector_client.start()
    try:
        yield
    finally:
        await mcp_inspector_client.close()


app = FastAPI(
    title="FixPilot Repository Inspector",
    description="A2A只读仓库证据Agent",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", summary="Inspector Agent健康检查")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "repository-inspector"}


add_a2a_routes_to_fastapi(
    app,
    agent_card_routes=create_agent_card_routes(agent_card),
    jsonrpc_routes=create_jsonrpc_routes(request_handler, rpc_url="/a2a"),
)
