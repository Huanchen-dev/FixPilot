import asyncio
import json

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import get_stream_response_text, new_text_message
from a2a.types import Role, SendMessageConfiguration, SendMessageRequest

from app import inspector_agent
from app.schemas import (
    EvidenceItem,
    InspectionRequest,
    InspectionResult,
    TracebackInfo,
)


def test_inspector_agent_card_and_a2a_message(monkeypatch):
    async def fake_inspect(request: InspectionRequest):
        return InspectionResult(
            status="ok",
            repository_root=request.repository_path,
            files_scanned=1,
            evidence=[
                EvidenceItem(
                    id="source-1",
                    kind="source",
                    path="app.py",
                    line=1,
                    excerpt="raise RuntimeError()",
                )
            ],
        )

    monkeypatch.setattr(
        inspector_agent.repository_inspector,
        "inspect",
        fake_inspect,
    )

    async def run():
        transport = httpx.ASGITransport(app=inspector_agent.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as http_client:
            card_response = await http_client.get("/.well-known/agent-card.json")
            factory = ClientFactory(
                ClientConfig(streaming=False, httpx_client=http_client)
            )
            client = await factory.create_from_url("http://testserver")
            inspection = InspectionRequest(
                repository_path=r"D:\demo",
                traceback_info=TracebackInfo(
                    exception_type="RuntimeError",
                    message="测试异常",
                    search_terms=["RuntimeError"],
                ),
            )
            request = SendMessageRequest(
                message=new_text_message(
                    inspection.model_dump_json(),
                    role=Role.ROLE_USER,
                    context_id="a2a-inspector-test",
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
    assert card_response.json()["name"] == "FixPilot Repository Inspector"
    result = InspectionResult.model_validate(json.loads(texts[-1]))
    assert result.status == "ok"
    assert result.evidence[0].path == "app.py"
