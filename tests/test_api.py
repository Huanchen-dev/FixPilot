from fastapi.testclient import TestClient

from app import main
from app.schemas import (
    DiagnosisReport,
    EvidenceItem,
    RepairApplyResponse,
    RepairGenerateResponse,
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


class FakeRepairService:
    async def generate(self, request):
        return RepairGenerateResponse(
            repair_id="repair-api-test",
            diagnosis_id=request.report.diagnosis_id,
            status="not_repairable",
            repairable_reason="测试策略拒绝",
        )

    async def apply(self, repair_id):
        return RepairApplyResponse(
            repair_id=repair_id,
            status="applied",
            applied_files=["app.py"],
            message="测试应用成功",
        )

    async def reject(self, repair_id):
        return RepairApplyResponse(
            repair_id=repair_id,
            status="rejected",
            message="测试拒绝成功",
        )


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


def test_repair_generate_apply_and_reject_contract(monkeypatch):
    monkeypatch.setattr(main, "repair_service", FakeRepairService())
    report = sample_report().model_dump()
    with TestClient(main.app) as client:
        generated = client.post(
            "/repair/generate",
            json={"repository_path": r"D:\demo", "report": report},
        )
        applied = client.post(
            "/repair/apply",
            json={"repair_id": "repair-api-test"},
        )
        rejected = client.post(
            "/repair/reject",
            json={"repair_id": "repair-api-test"},
        )
    assert generated.status_code == 200
    assert generated.json()["status"] == "not_repairable"
    assert applied.json()["applied_files"] == ["app.py"]
    assert rejected.json()["status"] == "rejected"
