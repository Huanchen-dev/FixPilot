"""AgentCenter 的本地环境和模型配置。"""

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

