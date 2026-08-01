"""对六个固定根因案例执行真实FixPilot诊断并输出分类结果。"""

import asyncio
import json
from pathlib import Path

import httpx

from app.config import FIXPILOT_API_BASE_URL


CASE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "diagnostic_cases.json"
)


async def main() -> None:
    cases = json.loads(CASE_PATH.read_text(encoding="utf-8"))
    results: list[dict[str, object]] = []
    async with httpx.AsyncClient(timeout=300, trust_env=False) as client:
        for case in cases:
            response = await client.post(
                f"{FIXPILOT_API_BASE_URL.rstrip('/')}/diagnose",
                json={"traceback": case["traceback"]},
            )
            response.raise_for_status()
            report = response.json()["report"]
            categories = [
                cause["category"] for cause in report["root_causes"]
            ]
            passed = case["expected_category"] in categories
            results.append(
                {
                    "id": case["id"],
                    "expected": case["expected_category"],
                    "predicted_top3": categories,
                    "passed": passed,
                }
            )

    passed_count = sum(bool(item["passed"]) for item in results)
    output = {
        "passed": passed_count,
        "total": len(results),
        "top3_recall": passed_count / len(results),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if passed_count != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
