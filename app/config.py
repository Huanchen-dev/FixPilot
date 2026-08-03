"""FixPilot的本地环境、安全边界与服务地址配置。"""

import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DIAGNOSIS_MODEL = os.getenv("FIXPILOT_MODEL", "qwen3-max")
DIAGNOSIS_BASE_URL = os.getenv(
    "FIXPILOT_MODEL_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)

INSPECTOR_AGENT_BASE_URL = os.getenv(
    "INSPECTOR_AGENT_BASE_URL",
    "http://127.0.0.1:8200",
)
INSPECTOR_AGENT_TIMEOUT = float(os.getenv("INSPECTOR_AGENT_TIMEOUT", "90"))

REPAIR_AGENT_BASE_URL = os.getenv(
    "REPAIR_AGENT_BASE_URL",
    "http://127.0.0.1:8300",
)
REPAIR_AGENT_TIMEOUT = float(os.getenv("REPAIR_AGENT_TIMEOUT", "180"))

FIXPILOT_API_BASE_URL = os.getenv(
    "FIXPILOT_API_BASE_URL",
    "http://127.0.0.1:8100",
)


def _workspace_roots() -> tuple[Path, ...]:
    configured = os.getenv("FIXPILOT_WORKSPACE_ROOTS", "").strip()
    if not configured:
        return (PROJECT_ROOT.parent.resolve(),)
    return tuple(
        Path(item.strip()).expanduser().resolve()
        for item in configured.split(os.pathsep)
        if item.strip()
    )


WORKSPACE_ROOTS = _workspace_roots()
MAX_SOURCE_FILE_BYTES = int(
    os.getenv("FIXPILOT_MAX_SOURCE_FILE_BYTES", str(256 * 1024))
)
MAX_PROJECT_FILES = int(os.getenv("FIXPILOT_MAX_PROJECT_FILES", "500"))
MAX_PROMPT_EVIDENCE_CHARS = int(
    os.getenv("FIXPILOT_MAX_PROMPT_EVIDENCE_CHARS", "40000")
)
MAX_INSPECTION_STEPS = int(os.getenv("FIXPILOT_MAX_INSPECTION_STEPS", "6"))
MAX_INSPECTION_OBSERVATION_CHARS = int(
    os.getenv("FIXPILOT_MAX_INSPECTION_OBSERVATION_CHARS", "24000")
)
_configured_repair_temp_root = os.getenv("FIXPILOT_REPAIR_TEMP_ROOT", "").strip()
REPAIR_TEMP_ROOT = Path(
    _configured_repair_temp_root
    or str(Path(tempfile.gettempdir()) / "fixpilot-repairs")
).expanduser().resolve()
MAX_REPAIR_FILES = int(os.getenv("FIXPILOT_MAX_REPAIR_FILES", "3"))
MAX_REPAIR_ATTEMPTS = min(
    2,
    max(1, int(os.getenv("FIXPILOT_MAX_REPAIR_ATTEMPTS", "2"))),
)
REPAIR_TEST_TIMEOUT = int(os.getenv("FIXPILOT_REPAIR_TEST_TIMEOUT", "120"))
REPAIR_SESSION_TTL_SECONDS = int(
    os.getenv("FIXPILOT_REPAIR_SESSION_TTL_SECONDS", "1800")
)
MAX_REPAIR_DIFF_CHARS = int(
    os.getenv("FIXPILOT_MAX_REPAIR_DIFF_CHARS", "80000")
)
MAX_TEST_OUTPUT_CHARS = int(
    os.getenv("FIXPILOT_MAX_TEST_OUTPUT_CHARS", "16000")
)
