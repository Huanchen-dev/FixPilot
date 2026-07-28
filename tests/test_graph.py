import asyncio
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage

from app import graph
from app.schemas import KnowledgeResult, RouterDecision


class FakeRouterModel:
    async def ainvoke(self, messages):
        content = str(messages[-1].content)
        intent = "knowledge" if "RAG" in content else "chat"
        return RouterDecision(intent=intent)


class FakeChatModel:
    async def ainvoke(self, messages):
        return AIMessage(content=f"CHAT:{messages[-1].content}")


def test_fallback_router():
    assert graph._fallback_intent("请解释RAG原理") == "knowledge"
    assert graph._fallback_intent("帮我写一句问候") == "chat"


def test_source_is_reset_between_routes(monkeypatch):
    async def fake_knowledge_query(question: str, thread_id: str):
        return KnowledgeResult(answer=f"RAG:{question}", source="RAG")

    monkeypatch.setattr(graph, "get_router_model", lambda: FakeRouterModel())
    monkeypatch.setattr(graph, "get_chat_model", lambda: FakeChatModel())
    monkeypatch.setattr(
        graph.knowledge_a2a_client,
        "query",
        fake_knowledge_query,
    )

    async def run():
        thread_id = f"source-test-{uuid4().hex}"
        config = {"configurable": {"thread_id": thread_id}}
        knowledge_state = await graph.agent_graph.ainvoke(
            {
                "messages": [HumanMessage(content="什么是RAG")],
                "thread_id": thread_id,
            },
            config=config,
        )
        chat_state = await graph.agent_graph.ainvoke(
            {
                "messages": [HumanMessage(content="帮我写一句问候")],
                "thread_id": thread_id,
            },
            config=config,
        )
        return knowledge_state, chat_state

    knowledge_state, chat_state = asyncio.run(run())
    assert knowledge_state["source"] == "RAG"
    assert chat_state["source"] == "CHAT"
    assert chat_state["response"].startswith("CHAT:")
