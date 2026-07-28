"""项目一RAG服务的唯一HTTP访问入口。"""

import hashlib

import httpx

from app.config import RAG_AGENT_BASE_URL, RAG_AGENT_TIMEOUT
from app.schemas import KnowledgeResult


def map_session_id(session_id: str) -> str:
    """把任意会话标识稳定映射为项目一要求的32位标识。"""

    return hashlib.md5(session_id.encode("utf-8")).hexdigest()


async def query_rag_service(question: str, session_id: str) -> KnowledgeResult:
    """调用项目一问答接口，并把网络异常转换为明确降级结果。"""

    try:
        async with httpx.AsyncClient(
            timeout=RAG_AGENT_TIMEOUT,
            trust_env=False,
        ) as client:
            response = await client.post(
                f"{RAG_AGENT_BASE_URL.rstrip('/')}/qa",
                json={
                    "question": question,
                    "session_id": map_session_id(session_id),
                },
            )
            response.raise_for_status()
            payload = response.json()
        return KnowledgeResult(
            answer=str(payload["answer"]),
            source=str(payload.get("source", "RAG")),
        )
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return KnowledgeResult(
            answer="知识库服务暂时不可用，请稍后重试。",
            source="RAG_UNAVAILABLE",
        )
