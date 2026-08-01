"""在Inspector Agent与FixPilot API启动后执行真实诊断链检查。"""

import asyncio
import json

import httpx

from app.config import (
    FIXPILOT_API_BASE_URL,
    INSPECTOR_AGENT_BASE_URL,
    PROJECT_ROOT,
)


TRACEBACK_SAMPLE = (
    "Traceback (most recent call last):\n"
    f'  File "{PROJECT_ROOT / "app" / "model_provider.py"}", '
    'line 5, in <module>\n'
    "    import imaginary_fixpilot_dependency\n"
    "ModuleNotFoundError: No module named 'imaginary_fixpilot_dependency'"
)


async def main() -> None:
    payload = {
        "traceback": TRACEBACK_SAMPLE,
        "repository_path": str(PROJECT_ROOT),
        "command": "python -m app.model_provider",
        "expected_behavior": "程序应进入诊断模型初始化。",
        "python_version": "3.14",
    }
    async with httpx.AsyncClient(timeout=300, trust_env=False) as client:
        fixpilot_health = await client.get(
            f"{FIXPILOT_API_BASE_URL.rstrip('/')}/health"
        )
        inspector_health = await client.get(
            f"{INSPECTOR_AGENT_BASE_URL.rstrip('/')}/health"
        )
        card = await client.get(
            f"{INSPECTOR_AGENT_BASE_URL.rstrip('/')}"
            "/.well-known/agent-card.json"
        )
        for response in (fixpilot_health, inspector_health, card):
            response.raise_for_status()

        diagnosis = await client.post(
            f"{FIXPILOT_API_BASE_URL.rstrip('/')}/diagnose",
            json=payload,
        )
        diagnosis.raise_for_status()
        report = diagnosis.json()["report"]
        if report["inspection_status"] != "ok":
            raise AssertionError(f"仓库检查未成功：{report}")
        if report["inspection_mode"] != "agent":
            raise AssertionError(f"Inspector没有执行自主取证：{report}")
        if len(report["inspection_steps"]) < 2:
            raise AssertionError(f"Inspector缺少真实工具决策轨迹：{report}")
        if not report["root_causes"] or not report["evidence"]:
            raise AssertionError(f"诊断报告缺少根因或证据：{report}")
        if "missing_dependency" not in {
            cause["category"] for cause in report["root_causes"]
        }:
            raise AssertionError(f"缺失依赖未进入根因前三：{report}")
        if any("诊断模型不可用" in item for item in report["limitations"]):
            raise AssertionError("真实诊断没有成功调用配置的大模型。")

        async with client.stream(
            "POST",
            f"{FIXPILOT_API_BASE_URL.rstrip('/')}/diagnose/stream",
            json={**payload, "repository_path": None},
        ) as stream_response:
            stream_response.raise_for_status()
            body = "".join(
                [chunk async for chunk in stream_response.aiter_text()]
            )
        events = [
            line.removeprefix("event:").strip()
            for line in body.splitlines()
            if line.startswith("event:")
        ]
        if not {"start", "stage", "report", "done"}.issubset(events):
            raise AssertionError(f"SSE事件不完整：{events}")
        if events.count("stage") != 4:
            raise AssertionError(f"SSE节点进度数量错误：{events}")

    print(
        json.dumps(
            {
                "fixpilot_health": fixpilot_health.json(),
                "inspector_health": inspector_health.json(),
                "agent_card": card.json()["name"],
                "diagnosis_id": report["diagnosis_id"],
                "inspection_status": report["inspection_status"],
                "inspection_mode": report["inspection_mode"],
                "inspection_tools": [
                    step["tool_name"] for step in report["inspection_steps"]
                ],
                "root_cause_count": len(report["root_causes"]),
                "evidence_count": len(report["evidence"]),
                "sse_events": events,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
