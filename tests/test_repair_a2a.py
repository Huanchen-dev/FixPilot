import asyncio
import json

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import get_stream_response_text, new_text_message
from a2a.types import Role, SendMessageConfiguration, SendMessageRequest

from app import repair_agent
from app.schemas import (
    DiagnosisReport,
    FileChange,
    RepairAgentRequest,
    RepairAgentResult,
    RepairPlan,
    RootCause,
    TracebackInfo,
)


def test_repair_agent_card_and_a2a_message(monkeypatch):
    async def fake_generate(request: RepairAgentRequest):
        return RepairAgentResult(
            status="ok",
            plan=RepairPlan(
                summary="测试修复",
                changes=[
                    FileChange(
                        relative_path="app.py",
                        base_sha256="a" * 64,
                        updated_content="value = 1\n",
                        reason="测试",
                    )
                ],
            ),
        )

    monkeypatch.setattr(repair_agent, "generate_repair_plan", fake_generate)

    async def run():
        transport = httpx.ASGITransport(app=repair_agent.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as http_client:
            card_response = await http_client.get("/.well-known/agent-card.json")
            factory = ClientFactory(
                ClientConfig(streaming=False, httpx_client=http_client)
            )
            client = await factory.create_from_url("http://testserver")
            report = DiagnosisReport(
                diagnosis_id="a2a-repair",
                summary="测试",
                traceback_info=TracebackInfo(
                    exception_type="AssertionError",
                    message="test",
                ),
                root_causes=[
                    RootCause(
                        category="code_error",
                        title="测试",
                        explanation="测试",
                        confidence="high",
                    )
                ],
                evidence=[],
                recommended_actions=["测试"],
                verification_steps=["测试"],
                limitations=[],
                inspection_status="ok",
            )
            payload = RepairAgentRequest(
                repair_id="repair-a2a",
                workspace_path="C:/temp/fixpilot/repository",
                report=report,
                attempt=1,
            )
            request = SendMessageRequest(
                message=new_text_message(
                    payload.model_dump_json(),
                    role=Role.ROLE_USER,
                    context_id="repair-a2a-test",
                ),
                configuration=SendMessageConfiguration(
                    accepted_output_modes=["application/json"]
                ),
            )
            texts = []
            async for response in client.send_message(request):
                texts.append(get_stream_response_text(response))
            return card_response, texts

    card_response, texts = asyncio.run(run())
    assert card_response.status_code == 200
    assert card_response.json()["name"] == "FixPilot Repair Agent"
    result = RepairAgentResult.model_validate(json.loads(texts[-1]))
    assert result.status == "ok"
    assert result.plan.changes[0].relative_path == "app.py"
