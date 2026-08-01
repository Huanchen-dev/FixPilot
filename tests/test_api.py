from fastapi.testclient import TestClient

from app import main
from app.schemas import (
    DiagnosisReport,
    EvidenceItem,
    RootCause,
    TracebackInfo,
)


def sample_report(diagnosis_id: str = "api-test") -> DiagnosisReport:
    return DiagnosisReport(
        diagnosis_id=diagnosis_id,
        summary="测试诊断",
        traceback_info=TracebackInfo(
            exception_type="RuntimeError",
            message="测试异常",
        ),
        root_causes=[
            RootCause(
                category="code_error",
                title="测试根因",
                explanation="测试证据支持该结论。",
                confidence="high",
                evidence_ids=["traceback-1"],
            )
        ],
        evidence=[
            EvidenceItem(
                id="traceback-1",
                kind="traceback",
                excerpt="RuntimeError: 测试异常",
            )
        ],
        recommended_actions=["执行测试修复。"],
        verification_steps=["重新运行测试。"],
        limitations=[],
        inspection_status="no_repository",
    )


class FakeGraph:
    async def ainvoke(self, inputs):
        return {"report": sample_report(inputs["diagnosis_id"])}

    async def astream(self, inputs, stream_mode):
        report = sample_report(inputs["diagnosis_id"])
        yield {"parse_traceback": {"traceback_info": report.traceback_info}}
        yield {
            "collect_evidence": {
                "inspection": type(
                    "Inspection",
                    (),
                    {"status": "no_repository"},
                )()
            }
        }
        yield {"analyze": {"draft": object()}}
        yield {"build_report": {"report": report}}


def test_health_and_diagnose(monkeypatch):
    monkeypatch.setattr(main, "diagnosis_graph", FakeGraph())
    with TestClient(main.app) as client:
        health = client.get("/health")
        response = client.post(
            "/diagnose",
            json={"traceback": "RuntimeError: 测试异常"},
        )
    assert health.json() == {"status": "ok", "service": "fixpilot"}
    assert response.status_code == 200
    assert response.json()["report"]["root_causes"][0]["title"] == "测试根因"


def test_diagnosis_validation(monkeypatch):
    monkeypatch.setattr(main, "diagnosis_graph", FakeGraph())
    with TestClient(main.app) as client:
        response = client.post("/diagnose", json={"traceback": ""})
    assert response.status_code == 422


def test_sse_contract(monkeypatch):
    monkeypatch.setattr(main, "diagnosis_graph", FakeGraph())
    with TestClient(main.app) as client:
        response = client.post(
            "/diagnose/stream",
            json={"traceback": "RuntimeError: 测试异常"},
        )
    assert response.status_code == 200
    assert "event: start" in response.text
    assert response.text.count("event: stage") == 4
    assert "event: report" in response.text
    assert "event: done" in response.text
    assert '"title": "测试根因"' in response.text
