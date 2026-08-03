import json
from pathlib import Path

from app import repair_workspace as workspace_module
from app.repair_service import RepairService, assess_repairability
from app.repair_workspace import sha256_bytes
from app.schemas import (
    DiagnosisReport,
    EvidenceItem,
    FileChange,
    RepairAgentResult,
    RepairGenerateRequest,
    RepairPlan,
    RootCause,
    TracebackFrame,
    TracebackInfo,
)
from app.workspace import WorkspacePolicy


def build_report(category: str = "code_error") -> DiagnosisReport:
    return DiagnosisReport(
        diagnosis_id="repair-diagnosis",
        summary="value函数返回值错误",
        traceback_info=TracebackInfo(
            exception_type="AssertionError",
            message="assert 0 == 1",
            frames=[
                TracebackFrame(
                    file="app.py",
                    line=2,
                    function="value",
                    code="return 0",
                )
            ],
        ),
        root_causes=[
            RootCause(
                category=category,
                title="返回值错误",
                explanation="源码证据显示返回了错误的值。",
                confidence="high",
                evidence_ids=["source-1"],
            )
        ],
        evidence=[
            EvidenceItem(
                id="source-1",
                kind="source",
                path="app.py",
                line=1,
                excerpt="def value():\n    return 0",
            )
        ],
        recommended_actions=["修正value返回值。"],
        verification_steps=["执行pytest。"],
        limitations=[],
        inspection_status="ok",
    )


class TwoAttemptClient:
    def __init__(self, second_value: int = 1):
        self.calls = []
        self.second_value = second_value

    async def generate(self, request):
        self.calls.append(request)
        target = Path(request.workspace_path) / "app.py"
        value = 2 if request.attempt == 1 else self.second_value
        return RepairAgentResult(
            status="ok",
            plan=RepairPlan(
                summary=f"第{request.attempt}轮修复",
                changes=[
                    FileChange(
                        relative_path="app.py",
                        base_sha256=sha256_bytes(target.read_bytes()),
                        updated_content=f"def value():\n    return {value}\n",
                        reason="根据测试反馈修正返回值",
                    )
                ],
            ),
        )


def create_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "中文修复项目"
    repository.mkdir()
    (repository / "app.py").write_text(
        "def value():\n    return 0\n", encoding="utf-8"
    )
    (repository / "test_app.py").write_text(
        "from app import value\n\ndef test_value():\n    assert value() == 1\n",
        encoding="utf-8",
    )
    return repository


def test_repair_service_uses_feedback_then_applies(tmp_path, monkeypatch):
    repository = create_repository(tmp_path)
    monkeypatch.setattr(
        workspace_module,
        "REPAIR_TEMP_ROOT",
        tmp_path / "fixpilot-repairs",
    )
    client = TwoAttemptClient()
    service = RepairService(
        client=client,
        workspace_policy=WorkspacePolicy((tmp_path,)),
    )

    import asyncio

    result = asyncio.run(
        service.generate(
            RepairGenerateRequest(
                repository_path=str(repository),
                report=build_report(),
            )
        )
    )

    assert result.status == "ready"
    assert [attempt.status for attempt in result.attempts] == [
        "tests_failed",
        "tests_passed",
    ]
    assert [item.status for item in result.baseline_test_results] == [
        "passed",
        "failed",
    ]
    assert result.attempts[0].remaining_failed_tests == [
        "test_app.py::test_value"
    ]
    assert "未优于上一最佳状态" in (result.attempts[0].feedback or "")
    assert client.calls[1].previous_feedback
    assert "FAILED" in client.calls[1].previous_feedback
    assert client.calls[1].current_diff is None
    assert "return 1" in result.diff
    assert "return 0" in (repository / "app.py").read_text(encoding="utf-8")

    applied = asyncio.run(service.apply(result.repair_id))
    assert applied.status == "applied"
    assert applied.applied_files == ["app.py"]
    assert "return 1" in (repository / "app.py").read_text(encoding="utf-8")


def test_failed_second_attempt_cannot_be_applied(tmp_path, monkeypatch):
    repository = create_repository(tmp_path)
    monkeypatch.setattr(
        workspace_module,
        "REPAIR_TEMP_ROOT",
        tmp_path / "fixpilot-repairs",
    )
    service = RepairService(
        client=TwoAttemptClient(second_value=3),
        workspace_policy=WorkspacePolicy((tmp_path,)),
    )

    import asyncio

    result = asyncio.run(
        service.generate(
            RepairGenerateRequest(
                repository_path=str(repository),
                report=build_report(),
            )
        )
    )
    rejected_apply = asyncio.run(service.apply(result.repair_id))
    rejected = asyncio.run(service.reject(result.repair_id))

    assert result.status == "tests_failed"
    assert rejected_apply.status == "tests_failed"
    assert rejected.status == "rejected"
    assert "return 0" in (repository / "app.py").read_text(encoding="utf-8")


def test_second_attempt_regression_restores_first_candidate(tmp_path, monkeypatch):
    repository = tmp_path / "regression-repo"
    repository.mkdir()
    (repository / "app.py").write_text(
        "def one():\n    return 0\n\ndef two():\n    return 0\n",
        encoding="utf-8",
    )
    (repository / "test_app.py").write_text(
        "from app import one, two\n\ndef test_one():\n    assert one() == 1\n\n"
        "def test_two():\n    assert two() == 1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        workspace_module,
        "REPAIR_TEMP_ROOT",
        tmp_path / "fixpilot-repairs",
    )

    class RegressionClient:
        async def generate(self, request):
            target = Path(request.workspace_path) / "app.py"
            content = (
                "def one():\n    return 1\n\ndef two():\n    return 0\n"
                if request.attempt == 1
                else "def one():\n    return 0\n\ndef two():\n    return 1\n"
            )
            return RepairAgentResult(
                status="ok",
                plan=RepairPlan(
                    summary="回归保护测试",
                    changes=[
                        FileChange(
                            relative_path="app.py",
                            base_sha256=sha256_bytes(target.read_bytes()),
                            updated_content=content,
                            reason="按当前失败用例调整",
                        )
                    ],
                ),
            )

    import asyncio

    service = RepairService(
        client=RegressionClient(),
        workspace_policy=WorkspacePolicy((tmp_path,)),
    )
    result = asyncio.run(
        service.generate(
            RepairGenerateRequest(
                repository_path=str(repository),
                report=build_report(),
            )
        )
    )

    assert result.status == "tests_failed"
    assert "return 1" in result.diff
    assert result.attempts[0].fixed_tests == ["test_app.py::test_one"]
    assert result.attempts[0].remaining_failed_tests == [
        "test_app.py::test_two"
    ]
    assert result.attempts[1].regressed_tests == ["test_app.py::test_one"]
    assert "相对最佳候选重新失败" in (result.attempts[1].feedback or "")


def test_candidate_with_new_baseline_failure_is_rolled_back(tmp_path, monkeypatch):
    repository = tmp_path / "new-regression-repo"
    repository.mkdir()
    (repository / "app.py").write_text(
        "def one():\n    return 0\n\ndef two():\n    return 1\n",
        encoding="utf-8",
    )
    (repository / "test_app.py").write_text(
        "from app import one, two\n\ndef test_one():\n    assert one() == 1\n\n"
        "def test_two():\n    assert two() == 1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        workspace_module,
        "REPAIR_TEMP_ROOT",
        tmp_path / "fixpilot-repairs",
    )

    class NewRegressionClient:
        async def generate(self, request):
            target = Path(request.workspace_path) / "app.py"
            return RepairAgentResult(
                status="ok",
                plan=RepairPlan(
                    summary="引入新失败的候选",
                    changes=[
                        FileChange(
                            relative_path="app.py",
                            base_sha256=sha256_bytes(target.read_bytes()),
                            updated_content=(
                                "def one():\n    return 1\n\n"
                                "def two():\n    return 0\n"
                            ),
                            reason="修复one但错误修改two",
                        )
                    ],
                ),
            )

    import asyncio

    service = RepairService(
        client=NewRegressionClient(),
        workspace_policy=WorkspacePolicy((tmp_path,)),
    )
    result = asyncio.run(
        service.generate(
            RepairGenerateRequest(
                repository_path=str(repository),
                report=build_report(),
            )
        )
    )

    assert result.status == "tests_failed"
    assert result.final_plan is None
    assert result.diff == ""
    assert result.attempts[0].fixed_tests == ["test_app.py::test_one"]
    assert result.attempts[0].new_failed_tests == ["test_app.py::test_two"]
    assert "相对基线新增失败" in (result.attempts[0].feedback or "")


def test_six_fixture_categories_use_deterministic_policy():
    case_path = Path(__file__).parent / "fixtures" / "diagnostic_cases.json"
    cases = json.loads(case_path.read_text(encoding="utf-8"))
    for case in cases:
        report = build_report(case["expected_category"])
        repairable, _ = assess_repairability(report)
        assert repairable is bool(case["repairable"]), case["id"]
