"""AgentCenter 的本地环境与服务地址配置。"""

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
CHAT_MODEL = os.getenv("AGENT_CHAT_MODEL", "qwen3-max")
CHAT_BASE_URL = os.getenv(
    "AGENT_CHAT_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)

RAG_AGENT_BASE_URL = os.getenv("RAG_AGENT_BASE_URL", "http://127.0.0.1:8000")
RAG_AGENT_TIMEOUT = float(os.getenv("RAG_AGENT_TIMEOUT", "60"))

KNOWLEDGE_AGENT_BASE_URL = os.getenv(
    "KNOWLEDGE_AGENT_BASE_URL",
    "http://127.0.0.1:8200",
)
KNOWLEDGE_AGENT_TIMEOUT = float(os.getenv("KNOWLEDGE_AGENT_TIMEOUT", "90"))

AGENTCENTER_API_BASE_URL = os.getenv(
    "AGENTCENTER_API_BASE_URL",
    "http://127.0.0.1:8100",
)
