"""FixPilot主编排器调用Repair Agent的A2A Client。"""

import hashlib
import json

import httpx
from a2a.client import A2AClientError, ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import (
    get_message_text,
    get_stream_response_text,
    new_text_message,
)
from a2a.types import Role, SendMessageConfiguration, SendMessageRequest

from app.config import REPAIR_AGENT_BASE_URL, REPAIR_AGENT_TIMEOUT
from app.schemas import RepairAgentRequest, RepairAgentResult


class RepairA2AClient:
    """发现Repair Agent并取得一轮结构化修复计划。"""

    async def generate(self, request: RepairAgentRequest) -> RepairAgentResult:
        context_id = hashlib.md5(request.repair_id.encode("utf-8")).hexdigest()
        try:
            async with httpx.AsyncClient(
                timeout=REPAIR_AGENT_TIMEOUT,
                trust_env=False,
            ) as http_client:
                factory = ClientFactory(
                    ClientConfig(streaming=False, httpx_client=http_client)
                )
                client = await factory.create_from_url(REPAIR_AGENT_BASE_URL)
                try:
                    message_request = SendMessageRequest(
                        message=new_text_message(
                            request.model_dump_json(),
                            role=Role.ROLE_USER,
                            context_id=context_id,
                        ),
                        configuration=SendMessageConfiguration(
                            accepted_output_modes=["application/json"]
                        ),
                    )
                    payload_text = ""
                    async for response in client.send_message(message_request):
                        payload_text = get_stream_response_text(response)
                        if (
                            not payload_text
                            and response.HasField("task")
                            and response.task.status.HasField("message")
                        ):
                            payload_text = get_message_text(response.task.status.message)
                finally:
                    await client.close()
            if not payload_text:
                raise ValueError("Repair Agent没有返回结果。")
            return RepairAgentResult.model_validate(json.loads(payload_text))
        except (
            A2AClientError,
            httpx.HTTPError,
            json.JSONDecodeError,
            ValueError,
            RuntimeError,
        ) as exc:
            return RepairAgentResult(
                status="error",
                warnings=[f"Repair Agent不可用：{type(exc).__name__}"],
            )


repair_a2a_client = RepairA2AClient()
