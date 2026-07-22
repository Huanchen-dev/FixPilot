"""AgentCenter 的第一个 LangGraph 双路工作流。"""

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.message import add_messages
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from app.config import CHAT_BASE_URL, CHAT_MODEL, DASHSCOPE_API_KEY


class AgentState(TypedDict, total=False):
    """一次请求在图中流转时携带的数据。"""

    messages: Annotated[list[BaseMessage], add_messages]
    intent: Literal["chat", "knowledge"]
    response: str


# 模型客户端只创建一次，后续每个聊天请求都复用这个对象。
chat_model = ChatOpenAI(
    model=CHAT_MODEL,
    api_key=DASHSCOPE_API_KEY,
    base_url=CHAT_BASE_URL,
    temperature=0.2,
)


def router_node(state: AgentState) -> dict[str, str]:
    """根据用户输入设置意图；这里只负责选择路线，不负责回答。"""

    message = str(state["messages"][-1].content)
    knowledge_keywords = ("知识库", "RAG", "检索", "面试题", "原理")
    intent = "knowledge" if any(keyword in message for keyword in knowledge_keywords) else "chat"
    return {"intent": intent}


def chat_agent_node(state: AgentState) -> dict[str, object]:
    """普通交流路线：调用大模型，并把文本回答写回State。"""

    model_response = chat_model.invoke(
        [
            SystemMessage(content="你是AgentCenter的通用聊天助手，请简洁、准确地回答。"),
            *state["messages"],
        ]
    )
    return {
        "messages": [model_response],
        "response": str(model_response.content),
    }


def knowledge_agent_node(state: AgentState) -> dict[str, object]:
    """知识问答路线的占位节点，后续会在这里接入RAG Agent。"""

    message = str(state["messages"][-1].content)
    response = f"Knowledge Agent占位处理：{message}"
    return {
        "messages": [{"role": "assistant", "content": response}],
        "response": response,
    }


def choose_next_node(state: AgentState) -> Literal["chat_agent", "knowledge_agent"]:
    """把State中的意图转换为图中下一个节点的名称。"""

    return "knowledge_agent" if state["intent"] == "knowledge" else "chat_agent"


def build_graph():
    """组装并编译一次工作流，供API请求重复复用。"""

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
