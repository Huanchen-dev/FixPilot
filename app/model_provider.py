"""延迟创建并复用AgentCenter使用的大模型客户端。"""

from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.config import CHAT_BASE_URL, CHAT_MODEL, DASHSCOPE_API_KEY
from app.schemas import RouterDecision


def _require_api_key() -> None:
    if not DASHSCOPE_API_KEY:
        raise RuntimeError(
            "未配置DASHSCOPE_API_KEY，请在项目根目录.env或系统环境变量中设置。"
        )


@lru_cache(maxsize=1)
def get_chat_model() -> ChatOpenAI:
    """第一次真正调用时创建模型，后续请求复用。"""

    _require_api_key()
    return ChatOpenAI(
        model=CHAT_MODEL,
        api_key=DASHSCOPE_API_KEY,
        base_url=CHAT_BASE_URL,
        temperature=0.2,
    )


@lru_cache(maxsize=1)
def get_router_model():
    """使用确定性模型配置，并约束Router只能返回规定意图。"""

    _require_api_key()
    router_model = ChatOpenAI(
        model=CHAT_MODEL,
        api_key=DASHSCOPE_API_KEY,
        base_url=CHAT_BASE_URL,
        temperature=0,
    )
    return router_model.with_structured_output(RouterDecision)
