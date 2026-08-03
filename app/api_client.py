"""Streamlit页面访问FixPilot API的轻量客户端。"""

import json
from collections.abc import Iterator
from typing import Any

import requests

from app.config import FIXPILOT_API_BASE_URL


def health_check() -> bool:
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(
                f"{FIXPILOT_API_BASE_URL.rstrip('/')}/health",
                timeout=3,
            )
            return response.ok
    except requests.RequestException:
        return False


def stream_diagnosis(
    payload: dict[str, Any],
) -> Iterator[tuple[str, dict[str, Any]]]:
    """请求诊断SSE接口，并逐个产出解析后的事件。"""

    with requests.Session() as session:
        session.trust_env = False
        with session.post(
            f"{FIXPILOT_API_BASE_URL.rstrip('/')}/diagnose/stream",
            json=payload,
            stream=True,
            timeout=(5, 300),
        ) as response:
            response.raise_for_status()
            event_name = "message"
            data_lines: list[str] = []
            for raw_line in response.iter_lines(decode_unicode=True):
                line = raw_line or ""
                if not line:
                    if data_lines:
                        yield event_name, json.loads("\n".join(data_lines))
                    event_name = "message"
                    data_lines = []
                elif line.startswith("event:"):
                    event_name = line.removeprefix("event:").strip()
                elif line.startswith("data:"):
                    data_lines.append(line.removeprefix("data:").strip())
            if data_lines:
                yield event_name, json.loads("\n".join(data_lines))


def generate_repair(
    repository_path: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    """请求后端在临时副本中完成生成、测试和最多两轮调整。"""

    with requests.Session() as session:
        session.trust_env = False
        response = session.post(
            f"{FIXPILOT_API_BASE_URL.rstrip('/')}/repair/generate",
            json={"repository_path": repository_path, "report": report},
            timeout=(5, 600),
        )
        response.raise_for_status()
        return response.json()


def finish_repair(repair_id: str, action: str) -> dict[str, Any]:
    """最终应用或拒绝后端持有的修复候选。"""

    if action not in {"apply", "reject"}:
        raise ValueError("不支持的修复操作。")
    with requests.Session() as session:
        session.trust_env = False
        response = session.post(
            f"{FIXPILOT_API_BASE_URL.rstrip('/')}/repair/{action}",
            json={"repair_id": repair_id},
            timeout=(5, 120),
        )
        response.raise_for_status()
        return response.json()
