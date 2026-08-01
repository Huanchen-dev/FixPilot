"""FixPilot各层共享的请求、证据与诊断报告契约。"""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


Confidence = Literal["high", "medium", "low"]
InspectionStatus = Literal["ok", "no_repository", "denied", "error"]
InspectionMode = Literal["agent", "fallback", "not_run"]
InspectionToolName = Literal[
    "list_project_files",
    "search_code",
    "read_source_file",
    "read_dependency_manifest",
    "get_python_environment",
]
CauseCategory = Literal[
    "missing_dependency",
    "version_incompatibility",
    "missing_configuration",
    "service_unavailable",
    "resource_lock",
    "async_runtime",
    "code_error",
    "unknown",
]


class DiagnosisRequest(BaseModel):
    """用户提交给FixPilot的一次只读诊断请求。"""

    traceback: str = Field(
        min_length=1,
        max_length=50_000,
        description="报错信息或完整Traceback",
    )
    repository_path: str | None = Field(
        default=None,
        max_length=2_000,
        description="可选的本地Python项目路径",
    )
    command: str | None = Field(default=None, max_length=4_000)
    expected_behavior: str | None = Field(default=None, max_length=8_000)
    python_version: str | None = Field(default=None, max_length=200)
    dependency_context: str | None = Field(default=None, max_length=30_000)
    code_context: str | None = Field(default=None, max_length=30_000)

    @model_validator(mode="after")
    def normalize_optional_text(self) -> "DiagnosisRequest":
        for name in (
            "repository_path",
            "command",
            "expected_behavior",
            "python_version",
            "dependency_context",
            "code_context",
        ):
            value = getattr(self, name)
            if isinstance(value, str):
                value = value.strip()
                setattr(self, name, value or None)
        self.traceback = self.traceback.strip()
        return self


class TracebackFrame(BaseModel):
    """Traceback中的一层调用帧。"""

    file: str
    line: int
    function: str
    code: str | None = None


class TracebackInfo(BaseModel):
    """从原始报错中确定性提取的结构化信息。"""

    exception_type: str
    message: str
    frames: list[TracebackFrame] = Field(default_factory=list)
    search_terms: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    """诊断报告可引用的一条客观证据。"""

    id: str
    kind: Literal[
        "traceback",
        "source",
        "dependency",
        "environment",
        "user_context",
    ]
    excerpt: str
    path: str | None = None
    line: int | None = None
    detail: str | None = None


class InspectionRequest(BaseModel):
    """主Graph通过A2A交给仓库检查Agent的任务。"""

    repository_path: str
    traceback_info: TracebackInfo
    command: str | None = None
    expected_behavior: str | None = None
    reported_python_version: str | None = None
    max_results: int = Field(default=20, ge=1, le=50)


class InspectionStep(BaseModel):
    """Inspector一次受控工具调用的可观察记录。"""

    index: int = Field(ge=0)
    tool_name: InspectionToolName
    status: Literal["ok", "error"]
    summary: str
    evidence_ids: list[str] = Field(default_factory=list)


class InspectionResult(BaseModel):
    """仓库检查Agent返回的只读证据包。"""

    status: InspectionStatus
    mode: InspectionMode = "not_run"
    repository_root: str | None = None
    files_scanned: int = 0
    evidence: list[EvidenceItem] = Field(default_factory=list)
    steps: list[InspectionStep] = Field(default_factory=list)
    environment: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class RootCause(BaseModel):
    """一个带证据引用的根因候选。"""

    category: CauseCategory
    title: str
    explanation: str
    confidence: Confidence
    evidence_ids: list[str] = Field(default_factory=list)


class DiagnosisDraft(BaseModel):
    """模型生成、尚未经过最终规范化的诊断内容。"""

    summary: str
    root_causes: list[RootCause] = Field(min_length=1, max_length=3)
    recommended_actions: list[str] = Field(min_length=1, max_length=8)
    verification_steps: list[str] = Field(min_length=1, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=8)


class DiagnosisReport(BaseModel):
    """FixPilot对外返回的完整只读诊断报告。"""

    diagnosis_id: str
    summary: str
    traceback_info: TracebackInfo
    root_causes: list[RootCause]
    evidence: list[EvidenceItem]
    recommended_actions: list[str]
    verification_steps: list[str]
    limitations: list[str]
    inspection_status: InspectionStatus
    inspection_mode: InspectionMode = "not_run"
    inspection_steps: list[InspectionStep] = Field(default_factory=list)


class DiagnosisResponse(BaseModel):
    """普通HTTP诊断接口响应。"""

    diagnosis_id: str
    report: DiagnosisReport
