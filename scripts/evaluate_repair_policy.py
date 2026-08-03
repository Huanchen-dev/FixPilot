"""复用六个诊断fixture评估确定性自动修复准入策略。"""

import json
from pathlib import Path

from app.repair_service import assess_repairability
from app.schemas import (
    DiagnosisReport,
    EvidenceItem,
    RootCause,
    TracebackInfo,
)


CASE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "diagnostic_cases.json"
)


def main() -> None:
    cases = json.loads(CASE_PATH.read_text(encoding="utf-8"))
    results: list[dict[str, object]] = []
    for case in cases:
        report = DiagnosisReport(
            diagnosis_id=f"policy-{case['id']}",
            summary="修复准入策略fixture",
            traceback_info=TracebackInfo(
                exception_type=case["expected_category"],
                message=case["traceback"],
            ),
            root_causes=[
                RootCause(
                    category=case["expected_category"],
                    title="fixture根因",
                    explanation="使用已知类别隔离验证修复准入策略。",
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
                    excerpt="fixture source",
                )
            ],
            recommended_actions=["按fixture验证策略。"],
            verification_steps=["比较期望和实际准入结果。"],
            limitations=[],
            inspection_status="ok",
        )
        actual, reason = assess_repairability(report)
        expected = bool(case["repairable"])
        results.append(
            {
                "id": case["id"],
                "expected_repairable": expected,
                "actual_repairable": actual,
                "passed": actual == expected,
                "reason": reason,
            }
        )

    passed = sum(bool(result["passed"]) for result in results)
    output = {
        "passed": passed,
        "total": len(results),
        "repairability_accuracy": passed / len(results),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
