"""AgentCenter主图调用Knowledge Agent的A2A Client。"""

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

from app.config import KNOWLEDGE_AGENT_BASE_URL, KNOWLEDGE_AGENT_TIMEOUT
from app.schemas import KnowledgeResult


class KnowledgeA2AClient:
    """发现Knowledge Agent并通过A2A消息取得结构化结果。"""

    async def query(self, question: str, thread_id: str) -> KnowledgeResult:
        context_id = hashlib.md5(thread_id.encode("utf-8")).hexdigest()
        try:
            async with httpx.AsyncClient(
                timeout=KNOWLEDGE_AGENT_TIMEOUT,
                trust_env=False,
            ) as http_client:
                factory = ClientFactory(
                    ClientConfig(
                        streaming=False,
                        httpx_client=http_client,
                    )
                )
                client = await factory.create_from_url(KNOWLEDGE_AGENT_BASE_URL)
                try:
                    request = SendMessageRequest(
                        message=new_text_message(
                            question,
                            role=Role.ROLE_USER,
                            context_id=context_id,
                        ),
                        configuration=SendMessageConfiguration(
                            accepted_output_modes=["application/json"],
                        ),
                    )
                    payload_text = ""
                    async for response in client.send_message(request):
                        payload_text = get_stream_response_text(response)
                        if (
                            not payload_text
                            and response.HasField("task")
                            and response.task.status.HasField("message")
                        ):
                            payload_text = get_message_text(
                                response.task.status.message
                            )
                finally:
                    await client.close()

            if not payload_text:
                raise ValueError("A2A Agent没有返回结果。")
            return KnowledgeResult.model_validate(json.loads(payload_text))
        except (
            A2AClientError,
            httpx.HTTPError,
            json.JSONDecodeError,
            ValueError,
            RuntimeError,
        ):
            return KnowledgeResult(
                answer="Knowledge Agent暂时不可用，请稍后重试。",
                source="RAG_UNAVAILABLE",
            )


knowledge_a2a_client = KnowledgeA2AClient()
