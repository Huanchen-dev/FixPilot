import asyncio
import json

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import get_stream_response_text, new_text_message
from a2a.types import Role, SendMessageConfiguration, SendMessageRequest

from app import knowledge_agent
from app.schemas import KnowledgeResult


def test_agent_card_and_a2a_message(monkeypatch):
    async def fake_query(question: str, session_id: str):
        return KnowledgeResult(answer=f"知识回答：{question}", source="RAG")

    monkeypatch.setattr(
        knowledge_agent.mcp_knowledge_client,
        "query",
        fake_query,
    )

    async def run():
        transport = httpx.ASGITransport(app=knowledge_agent.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as http_client:
            card_response = await http_client.get("/.well-known/agent-card.json")
            factory = ClientFactory(
                ClientConfig(
                    streaming=False,
                    httpx_client=http_client,
                )
            )
            client = await factory.create_from_url("http://testserver")
            request = SendMessageRequest(
                message=new_text_message(
                    "什么是RAG",
                    role=Role.ROLE_USER,
                    context_id="a2a-test-context",
                ),
                configuration=SendMessageConfiguration(
                    accepted_output_modes=["application/json"],
                ),
            )
            texts = []
            async for response in client.send_message(request):
                texts.append(get_stream_response_text(response))
            return card_response, texts

    card_response, texts = asyncio.run(run())
    assert card_response.status_code == 200
    assert card_response.json()["name"] == "AgentCenter Knowledge Agent"
    assert texts
    assert json.loads(texts[-1]) == {
        "answer": "知识回答：什么是RAG",
        "source": "RAG",
    }
