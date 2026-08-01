import asyncio

from app import graph
from app.schemas import (
    DiagnosisDraft,
    DiagnosisRequest,
    EvidenceItem,
    InspectionResult,
    RootCause,
)


class FakeDiagnosisModel:
    async def ainvoke(self, messages):
        return DiagnosisDraft(
            summary="发现依赖导入问题。",
            root_causes=[
                RootCause(
                    category="missing_dependency",
                    title="缺少demo_package",
                    explanation="依赖清单中没有目标包。",
                    confidence="high",
                    evidence_ids=["dependency-1"],
                )
            ],
            recommended_actions=["在正确虚拟环境安装依赖。"],
            verification_steps=["执行最小import检查。"],
        )


async def fake_inspect(request, diagnosis_id):
    return InspectionResult(
        status="ok",
        repository_root=request.repository_path,
        files_scanned=3,
        evidence=[
            EvidenceItem(
                id="dependency-1",
                kind="dependency",
                path="requirements.txt",
                excerpt="fastapi==0.139.0",
            )
        ],
    )


def test_diagnosis_graph_builds_evidence_report(monkeypatch):
    monkeypatch.setattr(graph, "get_diagnosis_model", lambda: FakeDiagnosisModel())
    monkeypatch.setattr(graph.inspector_a2a_client, "inspect", fake_inspect)

    async def run():
        return await graph.diagnosis_graph.ainvoke(
            {
                "diagnosis_id": "graph-test",
                "request": DiagnosisRequest(
                    traceback=(
                        'Traceback (most recent call last):\n'
                        '  File "app/main.py", line 3, in <module>\n'
                        "    import demo_package\n"
                        "ModuleNotFoundError: No module named 'demo_package'"
                    ),
                    repository_path=r"D:\demo",
                ),
            }
        )

    state = asyncio.run(run())
    report = state["report"]
    assert report.diagnosis_id == "graph-test"
    assert report.traceback_info.exception_type == "ModuleNotFoundError"
    assert report.inspection_status == "ok"
    assert report.root_causes[0].evidence_ids == ["dependency-1"]
    assert {item.id for item in report.evidence} == {
        "traceback-1",
        "dependency-1",
    }


def test_fallback_diagnosis_does_not_require_model():
    info = graph.parse_traceback(
        "ModuleNotFoundError: No module named 'pymilvus'"
    )
    draft = graph._fallback_draft(info)
    assert "缺少" in draft.root_causes[0].title
    assert draft.root_causes[0].evidence_ids == ["traceback-1"]
