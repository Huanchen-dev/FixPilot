import json
from pathlib import Path

import pytest

from app import repair_workspace as workspace_module
from app.repair_workspace import RepairWorkspace, sha256_bytes
from app.schemas import FileChange, RepairPlan
from app.workspace import WorkspaceAccessError, WorkspacePolicy


CASES = {
    "missing-module": (
        "import imaginary_math\n\ndef calculate():\n    return imaginary_math.sqrt(9)\n",
        "import math\n\ndef calculate():\n    return math.sqrt(9)\n",
        "from app import calculate\n\ndef test_calculate():\n    assert calculate() == 3\n",
    ),
    "package-api-mismatch": (
        "from math import sqrt_old\n\ndef calculate():\n    return sqrt_old(16)\n",
        "from math import sqrt\n\ndef calculate():\n    return sqrt(16)\n",
        "from app import calculate\n\ndef test_calculate():\n    assert calculate() == 4\n",
    ),
    "nested-event-loop": (
        "import asyncio\n\nasync def resolve():\n    return 42\n\nasync def get_value():\n    return asyncio.run(resolve())\n",
        "async def resolve():\n    return 42\n\nasync def get_value():\n    return await resolve()\n",
        "import asyncio\nfrom app import get_value\n\ndef test_value():\n    assert asyncio.run(get_value()) == 42\n",
    ),
}


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_known_answer_pipeline_before_model(tmp_path, monkeypatch, case_id):
    source, repaired, test_source = CASES[case_id]
    repository = tmp_path / f"中文仓库-{case_id}"
    repository.mkdir()
    (repository / "app.py").write_text(source, encoding="utf-8")
    (repository / "test_app.py").write_text(test_source, encoding="utf-8")
    monkeypatch.setattr(
        workspace_module,
        "REPAIR_TEMP_ROOT",
        tmp_path / "fixpilot-repairs",
    )

    repair = RepairWorkspace.create(
        str(repository),
        case_id,
        WorkspacePolicy((tmp_path,)),
    )
    baseline = repair.run_fixed_tests()
    assert any(result.status == "failed" for result in baseline)

    temporary_file = repair.temporary_repository / "app.py"
    plan = RepairPlan(
        summary=f"{case_id}已知答案用于验证确定性管道",
        changes=[
            FileChange(
                relative_path="app.py",
                base_sha256=sha256_bytes(temporary_file.read_bytes()),
                updated_content=repaired,
                reason="fixture中已知的最小修复",
            )
        ],
        validation_notes=["执行compileall和pytest固定预设。"],
    )
    repair.apply_plan(plan)
    results = repair.run_fixed_tests()

    assert repair.tests_acceptable(results)
    assert "app.py" in repair.diff()
    assert (repository / "app.py").read_text(encoding="utf-8") == source
    assert repair.apply_to_original() == ["app.py"]
    assert (repository / "app.py").read_text(encoding="utf-8") == repaired
    repair.cleanup()
    assert not repair.session_root.exists()


def test_stale_original_hash_blocks_final_apply(tmp_path, monkeypatch):
    repository = tmp_path / "repo"
    repository.mkdir()
    target = repository / "app.py"
    target.write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        workspace_module,
        "REPAIR_TEMP_ROOT",
        tmp_path / "fixpilot-repairs",
    )
    repair = RepairWorkspace.create(
        str(repository),
        "stale",
        WorkspacePolicy((tmp_path,)),
    )
    temporary = repair.temporary_repository / "app.py"
    repair.apply_plan(
        RepairPlan(
            summary="更新值",
            changes=[
                FileChange(
                    relative_path="app.py",
                    base_sha256=sha256_bytes(temporary.read_bytes()),
                    updated_content="value = 2\n",
                    reason="测试修复",
                )
            ],
        )
    )
    target.write_text("value = 3\n", encoding="utf-8")
    with pytest.raises(WorkspaceAccessError, match="外部修改"):
        repair.apply_to_original()
    assert target.read_text(encoding="utf-8") == "value = 3\n"


def test_plan_cannot_modify_tests(tmp_path, monkeypatch):
    repository = tmp_path / "repo"
    repository.mkdir()
    target = repository / "test_app.py"
    target.write_text("def test_value():\n    assert False\n", encoding="utf-8")
    monkeypatch.setattr(
        workspace_module,
        "REPAIR_TEMP_ROOT",
        tmp_path / "fixpilot-repairs",
    )
    repair = RepairWorkspace.create(
        str(repository),
        "test-protection",
        WorkspacePolicy((tmp_path,)),
    )
    temporary = repair.temporary_repository / "test_app.py"
    plan = RepairPlan(
        summary="试图降低测试断言",
        changes=[
            FileChange(
                relative_path="test_app.py",
                base_sha256=sha256_bytes(temporary.read_bytes()),
                updated_content="def test_value():\n    assert True\n",
                reason="错误地修改测试",
            )
        ],
    )
    with pytest.raises(WorkspaceAccessError, match="禁止修改测试"):
        repair.apply_plan(plan)


def test_invalid_python_is_rejected_before_test_execution(tmp_path, monkeypatch):
    repository = tmp_path / "repo"
    repository.mkdir()
    target = repository / "app.py"
    target.write_text("def value():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(
        workspace_module,
        "REPAIR_TEMP_ROOT",
        tmp_path / "fixpilot-repairs",
    )
    repair = RepairWorkspace.create(
        str(repository),
        "syntax-protection",
        WorkspacePolicy((tmp_path,)),
    )
    temporary = repair.temporary_repository / "app.py"
    plan = RepairPlan(
        summary="语法错误候选",
        changes=[
            FileChange(
                relative_path="app.py",
                base_sha256=sha256_bytes(temporary.read_bytes()),
                updated_content="def value():\n",
                reason="模型遗漏函数体",
            )
        ],
    )
    with pytest.raises(WorkspaceAccessError, match="语法无效"):
        repair.apply_plan(plan)
    assert temporary.read_text(encoding="utf-8") == target.read_text(encoding="utf-8")


def test_six_diagnostic_fixtures_define_repairability():
    path = Path(__file__).parent / "fixtures" / "diagnostic_cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert len(cases) == 6
    assert sum(bool(case["repairable"]) for case in cases) == 3
