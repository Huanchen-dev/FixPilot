"""延迟创建并复用FixPilot诊断模型。"""

from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.config import (
    DASHSCOPE_API_KEY,
    DIAGNOSIS_BASE_URL,
    DIAGNOSIS_MODEL,
)
from app.schemas import DiagnosisDraft, RepairProposal


def _require_api_key() -> None:
    if not DASHSCOPE_API_KEY:
        raise RuntimeError(
            "未配置DASHSCOPE_API_KEY，请在项目根目录.env或系统环境变量中设置。"
        )


@lru_cache(maxsize=1)
def get_base_model():
    """第一次使用时创建模型，供取证Agent与诊断节点共同复用。"""

    _require_api_key()
    return ChatOpenAI(
        model=DIAGNOSIS_MODEL,
        api_key=DASHSCOPE_API_KEY,
        base_url=DIAGNOSIS_BASE_URL,
        temperature=0.1,
    )


@lru_cache(maxsize=1)
def get_diagnosis_model():
    """返回遵循DiagnosisDraft契约的诊断模型。"""

    return get_base_model().with_structured_output(DiagnosisDraft)


def get_inspector_model():
    """返回可绑定仓库工具的Inspector决策模型。"""

    return get_base_model()


@lru_cache(maxsize=1)
def get_repair_model():
    """返回精确文本替换契约；Agent再物化为冻结RepairPlan。"""

    return get_base_model().with_structured_output(RepairProposal)
