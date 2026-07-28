"""在三个后端服务启动后执行AgentCenter真实全链路检查。"""

import asyncio
import json
from uuid import uuid4

import httpx

from app.config import AGENTCENTER_API_BASE_URL, KNOWLEDGE_AGENT_BASE_URL


async def main() -> None:
    thread_id = f"e2e-{uuid4().hex}"
    async with httpx.AsyncClient(timeout=240, trust_env=False) as client:
        agent_health = await client.get(
            f"{AGENTCENTER_API_BASE_URL.rstrip('/')}/health"
        )
        knowledge_health = await client.get(
            f"{KNOWLEDGE_AGENT_BASE_URL.rstrip('/')}/health"
        )
        card = await client.get(
            f"{KNOWLEDGE_AGENT_BASE_URL.rstrip('/')}"
            "/.well-known/agent-card.json"
        )
        for response in (agent_health, knowledge_health, card):
            response.raise_for_status()

        knowledge = await client.post(
            f"{AGENTCENTER_API_BASE_URL.rstrip('/')}/chat",
            json={
                "message": "请根据知识库解释BGE-M3的稠密向量和稀疏向量",
                "thread_id": thread_id,
            },
        )
        knowledge.raise_for_status()
        knowledge_data = knowledge.json()
        if knowledge_data["intent"] != "knowledge":
            raise AssertionError(f"知识问题路由错误：{knowledge_data}")
        if knowledge_data["source"] == "RAG_UNAVAILABLE":
            raise AssertionError("项目一RAG服务未完成真实全链路响应。")

        chat = await client.post(
            f"{AGENTCENTER_API_BASE_URL.rstrip('/')}/chat",
            json={
                "message": "请用一句话向我问好",
                "thread_id": thread_id,
            },
        )
        chat.raise_for_status()
        chat_data = chat.json()
        if chat_data["intent"] != "chat" or chat_data["source"] != "CHAT":
            raise AssertionError(f"Chat路线或source重置错误：{chat_data}")

        async with client.stream(
            "POST",
            f"{AGENTCENTER_API_BASE_URL.rstrip('/')}/chat/stream",
            json={
                "message": "帮我写一句简短问候",
                "thread_id": f"{thread_id}-stream",
            },
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
        if not {"start", "route", "done"}.issubset(events):
            raise AssertionError(f"SSE事件不完整：{events}")
        if "token" not in events and "message" not in events:
            raise AssertionError(f"SSE没有回答内容：{events}")

    print(
        json.dumps(
            {
                "agentcenter_health": agent_health.json(),
                "knowledge_agent_health": knowledge_health.json(),
                "agent_card": card.json()["name"],
                "knowledge_source": knowledge_data["source"],
                "chat_source": chat_data["source"],
                "sse_events": events,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
