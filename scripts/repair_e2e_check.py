"""真实验证Inspector、Repair Agent、临时测试和最终安全落盘。"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import httpx

from app.config import (
    FIXPILOT_API_BASE_URL,
    INSPECTOR_AGENT_BASE_URL,
    PROJECT_ROOT,
    REPAIR_AGENT_BASE_URL,
)


async def main() -> None:
    e2e_root = (PROJECT_ROOT / ".fixpilot-e2e").resolve()
    repository = (e2e_root / f"repair-{uuid4().hex[:8]}").resolve()
    if repository == e2e_root or not repository.is_relative_to(e2e_root):
        raise RuntimeError("E2E临时仓库路径校验失败。")
    repository.mkdir(parents=True)
    calculator = repository / "calculator.py"
    calculator.write_text(
        "def add(left, right):\n    return left - right\n",
        encoding="utf-8",
    )
    (repository / "test_calculator.py").write_text(
        "from calculator import add\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    traceback_text = (
        "Traceback (most recent call last):\n"
        f'  File "{calculator}", line 2, in add\n'
        "    return left - right\n"
        "AssertionError: assert -1 == 5"
    )

    try:
        async with httpx.AsyncClient(timeout=600, trust_env=False) as client:
            health_urls = {
                "fixpilot": f"{FIXPILOT_API_BASE_URL.rstrip('/')}/health",
                "inspector": f"{INSPECTOR_AGENT_BASE_URL.rstrip('/')}/health",
                "repair": f"{REPAIR_AGENT_BASE_URL.rstrip('/')}/health",
            }
            health = {}
            for name, url in health_urls.items():
                response = await client.get(url)
                response.raise_for_status()
                health[name] = response.json()

            repair_card = await client.get(
                f"{REPAIR_AGENT_BASE_URL.rstrip('/')}/.well-known/agent-card.json"
            )
            repair_card.raise_for_status()

            diagnosis = await client.post(
                f"{FIXPILOT_API_BASE_URL.rstrip('/')}/diagnose",
                json={
                    "traceback": traceback_text,
                    "repository_path": str(repository),
                    "command": "python -m pytest -q",
                    "expected_behavior": "add(2, 3)应返回5。",
                    "python_version": sys.version.split()[0],
                },
            )
            diagnosis.raise_for_status()
            report = diagnosis.json()["report"]
            if report["inspection_status"] != "ok":
                raise AssertionError(f"Inspector取证失败：{report}")
            if report["inspection_mode"] != "agent":
                raise AssertionError("真实E2E不接受Inspector固定降级。")
            if "code_error" not in {
                cause["category"] for cause in report["root_causes"]
            }:
                raise AssertionError(f"代码错误没有进入根因前三：{report}")

            generated = await client.post(
                f"{FIXPILOT_API_BASE_URL.rstrip('/')}/repair/generate",
                json={"repository_path": str(repository), "report": report},
            )
            generated.raise_for_status()
            repair = generated.json()
            if repair["status"] != "ready":
                raise AssertionError(f"真实Repair Agent未生成可应用候选：{repair}")
            if not repair["diff"] or not repair["test_results"]:
                raise AssertionError("修复候选缺少Diff或固定测试证据。")
            if "left - right" not in calculator.read_text(encoding="utf-8"):
                raise AssertionError("最终确认前原仓库已被提前修改。")

            applied = await client.post(
                f"{FIXPILOT_API_BASE_URL.rstrip('/')}/repair/apply",
                json={"repair_id": repair["repair_id"]},
            )
            applied.raise_for_status()
            applied_result = applied.json()
            if applied_result["status"] != "applied":
                raise AssertionError(f"安全落盘失败：{applied_result}")

        environment = os.environ.copy()
        environment.update(
            {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        )
        verification = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=repository,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            shell=False,
            check=False,
        )
        if verification.returncode != 0:
            raise AssertionError(
                "原仓库落盘后测试失败：\n"
                + verification.stdout
                + verification.stderr
            )

        print(
            json.dumps(
                {
                    "health": health,
                    "repair_agent_card": repair_card.json()["name"],
                    "diagnosis_id": report["diagnosis_id"],
                    "inspection_tools": [
                        step["tool_name"] for step in report["inspection_steps"]
                    ],
                    "repair_id": repair["repair_id"],
                    "repair_attempts": [
                        attempt["status"] for attempt in repair["attempts"]
                    ],
                    "test_statuses": [
                        f"{item['preset']}:{item['status']}"
                        for item in repair["test_results"]
                    ],
                    "applied_files": applied_result["applied_files"],
                    "post_apply_pytest": verification.returncode,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        if repository.exists():
            shutil.rmtree(repository)
        if e2e_root.exists() and not any(e2e_root.iterdir()):
            e2e_root.rmdir()


if __name__ == "__main__":
    asyncio.run(main())
