"""FixPilot双Agent安全修复编排、内存会话与人工确认。"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.config import MAX_REPAIR_ATTEMPTS, REPAIR_SESSION_TTL_SECONDS
from app.repair_client import RepairA2AClient, repair_a2a_client
from app.repair_workspace import (
    RepairWorkspace,
    format_test_feedback,
)
from app.schemas import (
    DiagnosisReport,
    RepairAgentRequest,
    RepairApplyResponse,
    RepairAttemptResult,
    RepairGenerateRequest,
    RepairGenerateResponse,
    RepairPlan,
    RepairStatus,
    TestRunResult,
)
from app.workspace import WorkspaceAccessError, WorkspacePolicy


REPAIRABLE_CATEGORIES = {
    "async_runtime",
    "code_error",
    "missing_dependency",
    "version_incompatibility",
}
NON_REPAIRABLE_CATEGORIES = {
    "missing_configuration",
    "resource_lock",
    "service_unavailable",
    "unknown",
}


def _failed_test_names(results: list[TestRunResult]) -> set[str]:
    return {
        failed
        for result in results
        for failed in result.failed_tests
    }


def _comparison_feedback(
    message: str,
    results: list[TestRunResult],
    fixed_tests: set[str],
    remaining_failed_tests: set[str],
    new_failed_tests: set[str],
    regressed_tests: set[str],
) -> str:
    lines = [message]
    if fixed_tests:
        lines.append("相对基线已修复：" + ", ".join(sorted(fixed_tests)))
    if remaining_failed_tests:
        lines.append(
            "基线中仍失败：" + ", ".join(sorted(remaining_failed_tests))
        )
    if new_failed_tests:
        lines.append(
            "相对基线新增失败：" + ", ".join(sorted(new_failed_tests))
        )
    if regressed_tests:
        lines.append(
            "相对最佳候选重新失败：" + ", ".join(sorted(regressed_tests))
        )
    lines.append(format_test_feedback(results))
    return "\n".join(lines)[:20_000]


def assess_repairability(report: DiagnosisReport) -> tuple[bool, str]:
    """用确定性规则阻止把外部环境问题错误地包装成代码修复。"""

    primary_category = report.root_causes[0].category
    if primary_category not in REPAIRABLE_CATEGORIES:
        if primary_category in NON_REPAIRABLE_CATEGORIES:
            return False, "当前根因属于配置、外部服务、资源状态或证据不足，不应自动改代码。"
        return False, "当前诊断没有进入允许自动修复的根因类别。"
    paths = {
        item.path
        for item in report.evidence
        if item.path and item.kind in {"source", "dependency"}
    }
    paths.update(frame.file for frame in report.traceback_info.frames if frame.file)
    if not paths:
        return False, "诊断没有定位到可验证的源码或依赖文件。"
    if report.inspection_status != "ok":
        return False, "仓库只读取证没有成功，缺少生成代码修复所需的事实基础。"
    return True, "诊断类别和仓库证据满足受限代码修复条件。"


@dataclass
class RepairSession:
    repair_id: str
    report: DiagnosisReport
    workspace: RepairWorkspace
    repairable_reason: str
    created_at: datetime
    expires_at: datetime
    baseline_test_results: list[TestRunResult]
    status: RepairStatus = "generating"
    attempts: list[RepairAttemptResult] = field(default_factory=list)
    final_plan: RepairPlan | None = None
    test_results: list[TestRunResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def response(self) -> RepairGenerateResponse:
        return RepairGenerateResponse(
            repair_id=self.repair_id,
            diagnosis_id=self.report.diagnosis_id,
            status=self.status,
            repairable_reason=self.repairable_reason,
            baseline_test_results=self.baseline_test_results,
            attempts=self.attempts,
            final_plan=self.final_plan,
            diff=self.workspace.diff(),
            test_results=self.test_results,
            warnings=self.warnings,
            expires_at=self.expires_at.isoformat(),
        )


class RepairSessionStore:
    """保存等待人工确认的短期修复状态，重启后自然失效。"""

    def __init__(self) -> None:
        self._sessions: dict[str, RepairSession] = {}
        self._lock = threading.RLock()

    def put(self, session: RepairSession) -> None:
        with self._lock:
            self._purge_expired()
            self._sessions[session.repair_id] = session

    def get(self, repair_id: str) -> RepairSession | None:
        with self._lock:
            self._purge_expired()
            session = self._sessions.get(repair_id)
            if session is None:
                return None
            return session

    def pop(self, repair_id: str) -> RepairSession | None:
        with self._lock:
            self._purge_expired()
            return self._sessions.pop(repair_id, None)

    def _purge_expired(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [
            repair_id
            for repair_id, session in self._sessions.items()
            if now >= session.expires_at
        ]
        for repair_id in expired:
            session = self._sessions.pop(repair_id)
            try:
                session.workspace.cleanup()
            except (OSError, WorkspaceAccessError):
                pass
            session.status = "expired"


class RepairService:
    """协调Inspector结论、Repair Agent、临时测试与最终人工确认。"""

    def __init__(
        self,
        client: RepairA2AClient | None = None,
        store: RepairSessionStore | None = None,
        workspace_policy: WorkspacePolicy | None = None,
    ) -> None:
        self.client = client or repair_a2a_client
        self.store = store or RepairSessionStore()
        self.workspace_policy = workspace_policy

    async def generate(
        self,
        request: RepairGenerateRequest,
    ) -> RepairGenerateResponse:
        repair_id = uuid4().hex
        repairable, reason = assess_repairability(request.report)
        if not repairable:
            return RepairGenerateResponse(
                repair_id=repair_id,
                diagnosis_id=request.report.diagnosis_id,
                status="not_repairable",
                repairable_reason=reason,
            )

        try:
            workspace = await asyncio.to_thread(
                RepairWorkspace.create,
                request.repository_path,
                repair_id,
                self.workspace_policy,
            )
        except (OSError, WorkspaceAccessError, ValueError) as exc:
            return RepairGenerateResponse(
                repair_id=repair_id,
                diagnosis_id=request.report.diagnosis_id,
                status="error",
                repairable_reason=reason,
                warnings=[f"无法创建安全临时副本：{str(exc)}"],
            )

        now = datetime.now(timezone.utc)
        session = RepairSession(
            repair_id=repair_id,
            report=request.report,
            workspace=workspace,
            repairable_reason=reason,
            created_at=now,
            expires_at=now + timedelta(seconds=REPAIR_SESSION_TTL_SECONDS),
            baseline_test_results=[],
        )
        baseline_results = await asyncio.to_thread(workspace.run_fixed_tests)
        session.baseline_test_results = baseline_results
        if workspace.tests_acceptable(baseline_results):
            session.warnings.append(
                "修复前固定测试已经通过；修复后通过只能证明没有破坏现有测试，"
                "不能单独证明原始运行错误已消失。"
            )

        previous_feedback: str | None = None
        baseline_score = workspace.test_failure_score(baseline_results)
        baseline_failed_tests = _failed_test_names(baseline_results)
        best_score = baseline_score
        best_failed_tests = baseline_failed_tests
        best_plan: RepairPlan | None = None
        best_results = baseline_results
        retained_reasons: dict[str, str] = {}

        for attempt_number in range(1, MAX_REPAIR_ATTEMPTS + 1):
            agent_result = await self.client.generate(
                RepairAgentRequest(
                    repair_id=repair_id,
                    workspace_path=str(workspace.temporary_repository),
                    report=request.report,
                    attempt=attempt_number,
                    previous_feedback=previous_feedback,
                    current_diff=workspace.diff() or None,
                )
            )
            if agent_result.status != "ok" or agent_result.plan is None:
                feedback = "；".join(agent_result.warnings) or "Repair Agent未返回计划。"
                session.attempts.append(
                    RepairAttemptResult(
                        attempt=attempt_number,
                        status="error",
                        feedback=feedback,
                        warnings=agent_result.warnings,
                    )
                )
                previous_feedback = feedback
                continue

            plan = agent_result.plan
            previous_reasons = retained_reasons.copy()
            try:
                snapshot = await asyncio.to_thread(workspace.apply_plan, plan)
            except (OSError, UnicodeError, WorkspaceAccessError, ValueError) as exc:
                feedback = f"修复计划未通过安全校验：{str(exc)}"
                session.attempts.append(
                    RepairAttemptResult(
                        attempt=attempt_number,
                        status="invalid_plan",
                        plan=plan,
                        feedback=feedback,
                    )
                )
                previous_feedback = feedback
                continue

            for change in plan.changes:
                retained_reasons[change.relative_path] = change.reason

            test_results = await asyncio.to_thread(workspace.run_fixed_tests)
            current_diff = workspace.diff()
            if workspace.tests_acceptable(test_results):
                syntax_only = workspace.syntax_only(test_results)
                attempt_status = "syntax_only" if syntax_only else "tests_passed"
                warnings = []
                if syntax_only:
                    warning = "目标仓库没有pytest用例，本次只证明Python语法检查通过。"
                    session.warnings.append(warning)
                    warnings.append(warning)
                session.attempts.append(
                    RepairAttemptResult(
                        attempt=attempt_number,
                        status=attempt_status,
                        plan=plan,
                        diff=current_diff,
                        test_results=test_results,
                        warnings=warnings,
                    )
                )
                session.status = "ready"
                session.final_plan = workspace.current_plan(
                    plan.summary,
                    retained_reasons,
                )
                session.test_results = test_results
                break

            score = workspace.test_failure_score(test_results)
            current_failed_tests = _failed_test_names(test_results)
            fixed_tests = baseline_failed_tests - current_failed_tests
            remaining_failed_tests = baseline_failed_tests & current_failed_tests
            new_failed_tests = current_failed_tests - baseline_failed_tests
            regressed_tests = current_failed_tests - best_failed_tests
            improved = score < best_score
            attempt_diff = current_diff
            if new_failed_tests or regressed_tests or not improved:
                await asyncio.to_thread(workspace.rollback, snapshot)
                retained_reasons = previous_reasons
                if new_failed_tests or regressed_tests:
                    message = "本轮测试发生倒退，已撤销本轮修改并保留上一最佳状态。"
                else:
                    message = "本轮测试未优于上一最佳状态，已撤销本轮修改。"
                feedback = _comparison_feedback(
                    message,
                    test_results,
                    fixed_tests,
                    remaining_failed_tests,
                    new_failed_tests,
                    regressed_tests,
                )
                current_diff = workspace.diff()
                selected_plan = best_plan
                selected_results = best_results if best_plan is not None else []
            else:
                best_score = score
                best_failed_tests = current_failed_tests
                best_plan = plan
                best_results = test_results
                feedback = _comparison_feedback(
                    "本轮相对上一最佳状态有所改善，保留候选并继续验证。",
                    test_results,
                    fixed_tests,
                    remaining_failed_tests,
                    new_failed_tests,
                    regressed_tests,
                )
                selected_plan = plan
                selected_results = test_results

            session.attempts.append(
                RepairAttemptResult(
                    attempt=attempt_number,
                    status="tests_failed",
                    plan=plan,
                    diff=attempt_diff,
                    test_results=test_results,
                    fixed_tests=sorted(fixed_tests),
                    remaining_failed_tests=sorted(remaining_failed_tests),
                    new_failed_tests=sorted(new_failed_tests),
                    regressed_tests=sorted(regressed_tests),
                    feedback=feedback,
                )
            )
            session.final_plan = (
                workspace.current_plan(
                    selected_plan.summary,
                    retained_reasons,
                )
                if selected_plan is not None
                else None
            )
            session.test_results = selected_results
            previous_feedback = feedback

        if session.status != "ready":
            session.status = (
                "tests_failed"
                if any(item.status == "tests_failed" for item in session.attempts)
                else "error"
            )
        self.store.put(session)
        return session.response()

    async def apply(self, repair_id: str) -> RepairApplyResponse:
        session = self.store.get(repair_id)
        if session is None:
            return RepairApplyResponse(
                repair_id=repair_id,
                status="expired",
                message="修复候选不存在或已过期，请重新生成。",
            )
        if session.status != "ready":
            return RepairApplyResponse(
                repair_id=repair_id,
                status=session.status,
                message="只有通过固定验证的修复候选才能应用。",
            )
        try:
            applied_files = await asyncio.to_thread(
                session.workspace.apply_to_original
            )
        except (OSError, WorkspaceAccessError, ValueError) as exc:
            return RepairApplyResponse(
                repair_id=repair_id,
                status="error",
                message=f"安全落盘失败：{str(exc)}",
            )
        session.status = "applied"
        self.store.pop(repair_id)
        try:
            await asyncio.to_thread(session.workspace.cleanup)
        except (OSError, WorkspaceAccessError):
            pass
        return RepairApplyResponse(
            repair_id=repair_id,
            status="applied",
            applied_files=applied_files,
            message="修复已在最终哈希校验后安全应用。",
        )

    async def reject(self, repair_id: str) -> RepairApplyResponse:
        session = self.store.pop(repair_id)
        if session is None:
            return RepairApplyResponse(
                repair_id=repair_id,
                status="expired",
                message="修复候选不存在或已过期。",
            )
        try:
            await asyncio.to_thread(session.workspace.cleanup)
        except (OSError, WorkspaceAccessError):
            pass
        session.status = "rejected"
        return RepairApplyResponse(
            repair_id=repair_id,
            status="rejected",
            message="修复候选已拒绝，临时副本已清理，原仓库未修改。",
        )


repair_service = RepairService()
