"""AgentCenter的LangGraph路由与双Agent工作流。"""

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.a2a_client import knowledge_a2a_client
from app.model_provider import get_chat_model, get_router_model
from app.schemas import Intent


class AgentState(TypedDict, total=False):
    """一次请求在图中流转时携带的数据。"""

    messages: Annotated[list[BaseMessage], add_messages]
    intent: Intent
    response: str
    thread_id: str
    source: str


def _latest_message(state: AgentState) -> str:
    return str(state["messages"][-1].content)


def _fallback_intent(message: str) -> Intent:
    """模型路由不可用时保留确定性的最低可用分流。"""

    knowledge_keywords = (
        "知识库",
        "RAG",
        "检索",
        "面试题",
        "原理",
        "向量",
        "LangChain",
        "LangGraph",
    )
    return (
        "knowledge"
        if any(keyword.lower() in message.lower() for keyword in knowledge_keywords)
        else "chat"
    )


async def router_node(state: AgentState) -> dict[str, str]:
    """优先使用模型结构化路由，失败时回退到关键词规则。"""

    message = _latest_message(state)
    try:
        decision = await get_router_model().ainvoke(
            [
                SystemMessage(
                    content=(
                        "你只负责路由，不回答问题。"
                        "普通问候、闲聊、写作、翻译、通用任务选择chat；"
                        "明确询问编程面试知识、AI开发原理、项目笔记或RAG资料"
                        "时选择knowledge。无法确定时选择chat。"
                        "示例：'你好'选chat，'帮我写一句问候'选chat，"
                        "'什么是RAG'选knowledge，'解释Java事务原理'选knowledge。"
                    )
                ),
                state["messages"][-1],
            ]
        )
        return {"intent": decision.intent}
    except Exception:
        return {"intent": _fallback_intent(message)}


async def chat_agent_node(state: AgentState) -> dict[str, object]:
    """普通聊天路线直接调用Qwen，并明确覆盖本轮source。"""

    try:
        model_response = await get_chat_model().ainvoke(
            [
                SystemMessage(
                    content="你是AgentCenter的通用聊天助手，请简洁、准确地回答。"
                ),
                *state["messages"],
            ]
        )
        response = str(model_response.content)
        message: BaseMessage = model_response
        source = "CHAT"
    except Exception:
        response = "聊天模型暂时不可用，请检查模型配置后重试。"
        message = AIMessage(content=response)
        source = "CHAT_UNAVAILABLE"

    return {
        "messages": [message],
        "response": response,
        "source": source,
    }


async def knowledge_agent_node(state: AgentState) -> dict[str, object]:
    """通过A2A协议调用独立Knowledge Agent。"""

    result = await knowledge_a2a_client.query(
        _latest_message(state),
        state.get("thread_id", "agent-default"),
    )
    return {
        "messages": [AIMessage(content=result.answer)],
        "response": result.answer,
        "source": result.source,
    }


def choose_next_node(state: AgentState) -> Literal["chat_agent", "knowledge_agent"]:
    """把State中的意图转换为图中下一个节点名称。"""

    return "knowledge_agent" if state["intent"] == "knowledge" else "chat_agent"


def build_graph():
    """组装并编译工作流，供API请求重复复用。"""

    builder = StateGraph(AgentState)
    builder.add_node("router", router_node)
    builder.add_node("chat_agent", chat_agent_node)
    builder.add_node("knowledge_agent", knowledge_agent_node)

    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        "router",
        choose_next_node,
        {
            "chat_agent": "chat_agent",
            "knowledge_agent": "knowledge_agent",
        },
    )
    builder.add_edge("chat_agent", END)
    builder.add_edge("knowledge_agent", END)
    return builder.compile(checkpointer=InMemorySaver())


agent_graph = build_graph()
