from fastapi.testclient import TestClient

from app import main


class FakeGraph:
    async def ainvoke(self, inputs, config):
        return {
            "intent": "chat",
            "response": "测试回答",
            "source": "CHAT",
        }

    async def astream_events(self, inputs, config, version):
        yield {
            "event": "on_chain_end",
            "name": "router",
            "metadata": {"langgraph_node": "router"},
            "data": {"output": {"intent": "chat"}},
        }
        yield {
            "event": "on_chat_model_stream",
            "name": "ChatOpenAI",
            "metadata": {"langgraph_node": "chat_agent"},
            "data": {"chunk": type("Chunk", (), {"content": "测试"})()},
        }
        yield {
            "event": "on_chat_model_stream",
            "name": "ChatOpenAI",
            "metadata": {"langgraph_node": "chat_agent"},
            "data": {"chunk": type("Chunk", (), {"content": "回答"})()},
        }
        yield {
            "event": "on_chain_end",
            "name": "chat_agent",
            "metadata": {"langgraph_node": "chat_agent"},
            "data": {
                "output": {
                    "response": "测试回答",
                    "source": "CHAT",
                }
            },
        }


def test_health_and_chat(monkeypatch):
    monkeypatch.setattr(main, "agent_graph", FakeGraph())
    with TestClient(main.app) as client:
        health = client.get("/health")
        response = client.post(
            "/chat",
            json={"message": "你好", "thread_id": "api-test"},
        )

    assert health.status_code == 200
    assert response.status_code == 200
    assert response.json() == {
        "intent": "chat",
        "response": "测试回答",
        "source": "CHAT",
        "thread_id": "api-test",
    }


def test_chat_validation(monkeypatch):
    monkeypatch.setattr(main, "agent_graph", FakeGraph())
    with TestClient(main.app) as client:
        response = client.post(
            "/chat",
            json={"message": "", "thread_id": "api-test"},
        )
    assert response.status_code == 422


def test_sse_contract(monkeypatch):
    monkeypatch.setattr(main, "agent_graph", FakeGraph())
    with TestClient(main.app) as client:
        response = client.post(
            "/chat/stream",
            json={"message": "你好", "thread_id": "stream-test"},
        )

    assert response.status_code == 200
    assert "event: start" in response.text
    assert "event: route" in response.text
    assert response.text.count("event: token") == 2
    assert "event: done" in response.text
    assert '"intent": "chat"' in response.text
    assert '"source": "CHAT"' in response.text
