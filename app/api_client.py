"""Streamlit页面访问AgentCenter API的轻量客户端。"""

import json
from collections.abc import Iterator
from typing import Any

import requests

from app.config import AGENTCENTER_API_BASE_URL


def health_check() -> bool:
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(
                f"{AGENTCENTER_API_BASE_URL.rstrip('/')}/health",
                timeout=3,
            )
            return response.ok
    except requests.RequestException:
        return False


def stream_chat(message: str, thread_id: str) -> Iterator[tuple[str, dict[str, Any]]]:
    """请求SSE接口，并逐个产出解析后的事件。"""

    with requests.Session() as session:
        session.trust_env = False
        with session.post(
            f"{AGENTCENTER_API_BASE_URL.rstrip('/')}/chat/stream",
            json={"message": message, "thread_id": thread_id},
            stream=True,
            timeout=(5, 180),
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
