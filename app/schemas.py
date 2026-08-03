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
RepairStatus = Literal[
    "not_repairable",
    "generating",
    "ready",
    "tests_failed",
    "applied",
    "rejected",
    "expired",
    "error",
]
RepairAttemptStatus = Literal[
    "invalid_plan",
    "tests_passed",
    "tests_failed",
    "syntax_only",
    "error",
]
TestStatus = Literal["passed", "failed", "skipped", "timed_out", "error"]


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


class FileChange(BaseModel):
    """Repair Agent建议对一个现有文件执行的完整内容替换。"""

    relative_path: str = Field(min_length=1, max_length=500)
    base_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    updated_content: str = Field(max_length=300_000)
    reason: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_relative_path(self) -> "FileChange":
        normalized = self.relative_path.replace("\\", "/").strip()
        parts = [part for part in normalized.split("/") if part]
        if (
            not normalized
            or normalized.startswith("/")
            or ":" in parts[0]
            or any(part in {".", ".."} for part in parts)
        ):
            raise ValueError("FileChange必须使用仓库内的相对路径。")
        self.relative_path = "/".join(parts)
        return self


class TextReplacement(BaseModel):
    """Repair Agent内部模型提出的一项精确文本替换。"""

    relative_path: str = Field(min_length=1, max_length=500)
    base_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    old_text: str = Field(min_length=1, max_length=50_000)
    new_text: str = Field(max_length=50_000)
    reason: str = Field(min_length=1, max_length=2_000)


class RepairProposal(BaseModel):
    """模型易于稳定生成、由程序物化为RepairPlan的内部契约。"""

    summary: str = Field(min_length=1, max_length=4_000)
    replacements: list[TextReplacement] = Field(min_length=1, max_length=6)
    validation_notes: list[str] = Field(default_factory=list, max_length=6)


class RepairPlan(BaseModel):
    """Repair Agent与主编排器之间冻结的修复计划契约。"""

    summary: str = Field(min_length=1, max_length=4_000)
    changes: list[FileChange] = Field(min_length=1, max_length=3)
    validation_notes: list[str] = Field(default_factory=list, max_length=6)


class TestRunResult(BaseModel):
    """一个固定测试预设的受控执行结果。"""

    preset: Literal["compileall", "pytest"]
    status: TestStatus
    exit_code: int | None = None
    duration_seconds: float = Field(ge=0)
    output_excerpt: str = Field(default="", max_length=20_000)
    failed_tests: list[str] = Field(default_factory=list, max_length=50)


class RepairAttemptResult(BaseModel):
    """一次生成、临时写入和测试形成的可观察记录。"""

    attempt: int = Field(ge=1, le=2)
    status: RepairAttemptStatus
    plan: RepairPlan | None = None
    diff: str = Field(default="", max_length=80_000)
    test_results: list[TestRunResult] = Field(default_factory=list)
    fixed_tests: list[str] = Field(default_factory=list, max_length=50)
    remaining_failed_tests: list[str] = Field(default_factory=list, max_length=50)
    new_failed_tests: list[str] = Field(default_factory=list, max_length=50)
    regressed_tests: list[str] = Field(default_factory=list, max_length=50)
    feedback: str | None = Field(default=None, max_length=20_000)
    warnings: list[str] = Field(default_factory=list, max_length=10)


class RepairGenerateRequest(BaseModel):
    """根据一次已完成诊断生成安全修复候选。"""

    repository_path: str = Field(min_length=1, max_length=2_000)
    report: DiagnosisReport


class RepairAgentRequest(BaseModel):
    """编排器通过A2A交给Repair Agent的一轮任务。"""

    repair_id: str
    workspace_path: str
    report: DiagnosisReport
    attempt: int = Field(ge=1, le=2)
    previous_feedback: str | None = Field(default=None, max_length=20_000)
    current_diff: str | None = Field(default=None, max_length=40_000)


class RepairAgentResult(BaseModel):
    """Repair Agent的结构化A2A结果。"""

    status: Literal["ok", "error"]
    plan: RepairPlan | None = None
    warnings: list[str] = Field(default_factory=list, max_length=10)


class RepairGenerateResponse(BaseModel):
    """生成接口返回的完整候选、测试和确认状态。"""

    repair_id: str
    diagnosis_id: str
    status: RepairStatus
    repairable_reason: str
    baseline_test_results: list[TestRunResult] = Field(default_factory=list)
    attempts: list[RepairAttemptResult] = Field(default_factory=list)
    final_plan: RepairPlan | None = None
    diff: str = Field(default="", max_length=80_000)
    test_results: list[TestRunResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, max_length=20)
    expires_at: str | None = None


class RepairApplyRequest(BaseModel):
    """用户最终确认应用一个已经测试的修复候选。"""

    repair_id: str = Field(min_length=1, max_length=100)


class RepairApplyResponse(BaseModel):
    """应用或拒绝修复后的状态。"""

    repair_id: str
    status: RepairStatus
    applied_files: list[str] = Field(default_factory=list)
    message: str
