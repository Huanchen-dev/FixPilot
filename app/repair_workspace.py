"""FixPilot自动修复使用的临时副本、固定测试与安全落盘管道。"""

from __future__ import annotations

import ast
import difflib
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import (
    MAX_REPAIR_DIFF_CHARS,
    MAX_REPAIR_FILES,
    MAX_SOURCE_FILE_BYTES,
    MAX_TEST_OUTPUT_CHARS,
    REPAIR_TEMP_ROOT,
    REPAIR_TEST_TIMEOUT,
)
from app.schemas import FileChange, RepairPlan, TestRunResult
from app.workspace import WorkspaceAccessError, WorkspacePolicy, redact_secrets


def _is_test_path(relative: Path) -> bool:
    name = relative.name.lower()
    return (
        "tests" in {part.lower() for part in relative.parts[:-1]}
        or name.startswith("test_")
        or name == "conftest.py"
    )


def _is_repairable_path(relative: Path) -> bool:
    if _is_test_path(relative):
        return False
    if relative.suffix.lower() == ".py":
        return True
    return (
        relative.suffix.lower() == ".txt"
        and relative.name.lower().startswith("requirements")
    )


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_atomic(path: Path, content: bytes) -> None:
    handle, temporary_name = tempfile.mkstemp(
        prefix=".fixpilot-",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _output_excerpt(output: str) -> str:
    normalized = output.replace("\x00", "")
    if len(normalized) <= MAX_TEST_OUTPUT_CHARS:
        return normalized
    half = max(1, MAX_TEST_OUTPUT_CHARS // 2)
    return (
        normalized[:half]
        + "\n... FixPilot省略中间测试输出 ...\n"
        + normalized[-half:]
    )[:MAX_TEST_OUTPUT_CHARS]


def _failed_tests(output: str) -> list[str]:
    failed: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("FAILED "):
            name = stripped.removeprefix("FAILED ").split(" - ", 1)[0]
            if name and name not in failed:
                failed.append(name)
        if len(failed) >= 50:
            break
    return failed


@dataclass
class AppliedPlanSnapshot:
    """一轮候选写入前的内容，用于测试倒退时回滚该轮。"""

    contents: dict[str, bytes]


@dataclass
class RepairWorkspace:
    """一个原仓库及其隔离临时副本。"""

    repair_id: str
    original_repository: Path
    session_root: Path
    temporary_repository: Path
    original_hashes: dict[str, str]

    @classmethod
    def create(
        cls,
        repository_path: str,
        repair_id: str,
        policy: WorkspacePolicy | None = None,
    ) -> "RepairWorkspace":
        source_policy = policy or WorkspacePolicy()
        original = source_policy.resolve_repository(repository_path)
        REPAIR_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        session_root = Path(
            tempfile.mkdtemp(
                prefix=f"{repair_id[:12]}-",
                dir=REPAIR_TEMP_ROOT,
            )
        ).resolve()
        temporary = session_root / "repository"
        temporary.mkdir()
        original_hashes: dict[str, str] = {}
        try:
            for source in source_policy.iter_files(original):
                relative = source.relative_to(original).as_posix()
                target = temporary / Path(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                content = source.read_bytes()
                target.write_bytes(content)
                original_hashes[relative] = sha256_bytes(content)
        except Exception:
            shutil.rmtree(session_root, ignore_errors=True)
            raise
        if not original_hashes:
            shutil.rmtree(session_root, ignore_errors=True)
            raise WorkspaceAccessError("目标仓库没有可安全复制的文本文件。")
        return cls(
            repair_id=repair_id,
            original_repository=original,
            session_root=session_root,
            temporary_repository=temporary,
            original_hashes=original_hashes,
        )

    def _temporary_file(self, relative_path: str) -> Path:
        policy = WorkspacePolicy(
            (self.temporary_repository,),
            max_file_bytes=MAX_SOURCE_FILE_BYTES,
        )
        path = policy.resolve_file(self.temporary_repository, relative_path)
        relative = path.relative_to(self.temporary_repository)
        if _is_test_path(relative):
            raise WorkspaceAccessError("自动修复禁止修改测试文件或conftest.py。")
        if not _is_repairable_path(relative):
            raise WorkspaceAccessError("文件类型不在自动修复白名单中。")
        return path

    def apply_plan(self, plan: RepairPlan) -> AppliedPlanSnapshot:
        if len(plan.changes) > MAX_REPAIR_FILES:
            raise WorkspaceAccessError("单次修复超过允许修改的文件数量。")

        already_changed = {
            relative_path
            for relative_path, original_hash in self.original_hashes.items()
            if (
                self.temporary_repository / Path(relative_path)
            ).is_file()
            and sha256_bytes(
                (self.temporary_repository / Path(relative_path)).read_bytes()
            )
            != original_hash
        }
        requested_paths = {change.relative_path for change in plan.changes}
        if len(already_changed | requested_paths) > MAX_REPAIR_FILES:
            raise WorkspaceAccessError("多轮累计修复超过允许修改的文件数量。")

        prepared: list[tuple[FileChange, Path, bytes]] = []
        seen_paths: set[str] = set()
        for change in plan.changes:
            if change.relative_path in seen_paths:
                raise WorkspaceAccessError("同一修复计划不能重复修改同一文件。")
            seen_paths.add(change.relative_path)
            path = self._temporary_file(change.relative_path)
            current = path.read_bytes()
            if sha256_bytes(current) != change.base_sha256:
                raise WorkspaceAccessError(
                    f"{change.relative_path}已变化，RepairPlan的基础哈希已过期。"
                )
            updated = change.updated_content.encode("utf-8")
            if len(updated) > MAX_SOURCE_FILE_BYTES:
                raise WorkspaceAccessError("修复后的文件超过单文件大小限制。")
            if redact_secrets(change.updated_content) != change.updated_content:
                raise WorkspaceAccessError("修复内容疑似包含明文密钥或密码。")
            if path.suffix.lower() == ".py":
                try:
                    ast.parse(change.updated_content, filename=change.relative_path)
                except SyntaxError as exc:
                    raise WorkspaceAccessError(
                        f"{change.relative_path}语法无效：第{exc.lineno or '?'}行。"
                    ) from exc
            prepared.append((change, path, current))

        snapshot = AppliedPlanSnapshot(
            contents={change.relative_path: current for change, _, current in prepared}
        )
        written: list[tuple[Path, bytes]] = []
        try:
            for change, path, current in prepared:
                _write_atomic(path, change.updated_content.encode("utf-8"))
                written.append((path, current))
        except Exception:
            for path, previous in reversed(written):
                _write_atomic(path, previous)
            raise
        return snapshot

    def rollback(self, snapshot: AppliedPlanSnapshot) -> None:
        for relative_path, content in snapshot.contents.items():
            _write_atomic(self._temporary_file(relative_path), content)

    def diff(self) -> str:
        chunks: list[str] = []
        for relative_path, original_hash in sorted(self.original_hashes.items()):
            target = self.temporary_repository / Path(relative_path)
            if not target.is_file():
                continue
            current = target.read_bytes()
            if sha256_bytes(current) == original_hash:
                continue
            original_path = self.original_repository / Path(relative_path)
            before = original_path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines(keepends=True)
            after = current.decode("utf-8", errors="replace").splitlines(
                keepends=True
            )
            chunks.extend(
                difflib.unified_diff(
                    before,
                    after,
                    fromfile=f"a/{relative_path}",
                    tofile=f"b/{relative_path}",
                )
            )
        rendered = "".join(chunks)
        if len(rendered) > MAX_REPAIR_DIFF_CHARS:
            return (
                rendered[:MAX_REPAIR_DIFF_CHARS]
                + "\n... FixPilot已截断过长Diff ...\n"
            )
        return rendered

    def current_plan(
        self,
        summary: str,
        reasons: dict[str, str],
    ) -> RepairPlan:
        """把多轮增量修改合并成与最终Diff一致的完整候选。"""

        changes: list[FileChange] = []
        for relative_path, original_hash in sorted(self.original_hashes.items()):
            target = self.temporary_repository / Path(relative_path)
            if not target.is_file():
                continue
            content = target.read_bytes()
            if sha256_bytes(content) == original_hash:
                continue
            changes.append(
                FileChange(
                    relative_path=relative_path,
                    base_sha256=original_hash,
                    updated_content=content.decode("utf-8", errors="replace"),
                    reason=reasons.get(
                        relative_path,
                        "合并前序修复尝试后保留的最终文件变更。",
                    ),
                )
            )
        if not changes:
            raise WorkspaceAccessError("临时副本中没有可合并的最终文件变更。")
        return RepairPlan(
            summary=summary,
            changes=changes,
            validation_notes=["最终候选由当前临时副本相对原仓库重新生成。"],
        )

    def run_fixed_tests(self) -> list[TestRunResult]:
        compile_result = self._run_preset(
            "compileall",
            [sys.executable, "-m", "compileall", "-q", "."],
        )
        if compile_result.status != "passed":
            return [compile_result]
        pytest_result = self._run_preset(
            "pytest",
            [sys.executable, "-m", "pytest", "-q"],
            no_tests_exit_code=5,
        )
        return [compile_result, pytest_result]

    def _run_preset(
        self,
        preset: str,
        command: list[str],
        no_tests_exit_code: int | None = None,
    ) -> TestRunResult:
        started = time.monotonic()
        environment = os.environ.copy()
        environment.update(
            {
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        try:
            completed = subprocess.run(
                command,
                cwd=self.temporary_repository,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=REPAIR_TEST_TIMEOUT,
                shell=False,
                check=False,
            )
            output = f"{completed.stdout}\n{completed.stderr}".strip()
            if no_tests_exit_code is not None and completed.returncode == no_tests_exit_code:
                status = "skipped"
            else:
                status = "passed" if completed.returncode == 0 else "failed"
            return TestRunResult(
                preset=preset,
                status=status,
                exit_code=completed.returncode,
                duration_seconds=round(time.monotonic() - started, 3),
                output_excerpt=_output_excerpt(output),
                failed_tests=_failed_tests(output),
            )
        except subprocess.TimeoutExpired as exc:
            raw_output = "\n".join(
                str(item or "") for item in (exc.stdout, exc.stderr)
            )
            return TestRunResult(
                preset=preset,
                status="timed_out",
                duration_seconds=round(time.monotonic() - started, 3),
                output_excerpt=_output_excerpt(raw_output),
            )
        except OSError as exc:
            return TestRunResult(
                preset=preset,
                status="error",
                duration_seconds=round(time.monotonic() - started, 3),
                output_excerpt=f"无法启动固定测试：{type(exc).__name__}",
            )

    @staticmethod
    def tests_acceptable(results: list[TestRunResult]) -> bool:
        return bool(results) and all(
            result.status in {"passed", "skipped"} for result in results
        )

    @staticmethod
    def syntax_only(results: list[TestRunResult]) -> bool:
        return any(
            result.preset == "pytest" and result.status == "skipped"
            for result in results
        )

    @staticmethod
    def test_failure_score(results: list[TestRunResult]) -> tuple[int, int, int]:
        """按编译阶段、测试状态和失败数量比较候选，分数越低越好。"""

        by_preset = {result.preset: result for result in results}

        def status_rank(result: TestRunResult | None) -> int:
            if result is None:
                return 3
            if result.status in {"passed", "skipped"}:
                return 0
            if result.status == "failed":
                return 1
            return 2

        compile_rank = status_rank(by_preset.get("compileall"))
        if compile_rank != 0:
            return compile_rank, 3, 0

        pytest_result = by_preset.get("pytest")
        pytest_rank = status_rank(pytest_result)
        failed_count = (
            max(1, len(pytest_result.failed_tests))
            if pytest_result is not None and pytest_result.status == "failed"
            else 0
        )
        return 0, pytest_rank, failed_count

    def apply_to_original(self) -> list[str]:
        changed: list[tuple[str, Path, bytes, bytes]] = []
        for relative_path, baseline_hash in sorted(self.original_hashes.items()):
            original = self.original_repository / Path(relative_path)
            temporary = self.temporary_repository / Path(relative_path)
            if not original.is_file() or not temporary.is_file():
                raise WorkspaceAccessError("原仓库或临时副本中的目标文件已不存在。")
            before = original.read_bytes()
            if sha256_bytes(before) != baseline_hash:
                raise WorkspaceAccessError(
                    f"{relative_path}在生成修复后已被外部修改，拒绝覆盖。"
                )
            after = temporary.read_bytes()
            if sha256_bytes(after) != baseline_hash:
                changed.append((relative_path, original, before, after))
        if not changed:
            raise WorkspaceAccessError("修复候选没有产生可应用的文件变更。")

        written: list[tuple[Path, bytes]] = []
        try:
            for _, path, before, after in changed:
                _write_atomic(path, after)
                written.append((path, before))
        except Exception:
            for path, before in reversed(written):
                _write_atomic(path, before)
            raise
        return [relative_path for relative_path, _, _, _ in changed]

    def cleanup(self) -> None:
        root = REPAIR_TEMP_ROOT.resolve()
        target = self.session_root.resolve()
        if target == root or not target.is_relative_to(root):
            raise WorkspaceAccessError("拒绝清理修复临时根目录之外的路径。")
        shutil.rmtree(target, ignore_errors=False)


def collect_repair_context(
    workspace_path: str,
    candidate_paths: list[str],
    max_files: int = 5,
    max_chars: int = 60_000,
) -> list[dict[str, str]]:
    """Repair Agent受控读取临时副本中与诊断相关的少量文件。"""

    configured_root = REPAIR_TEMP_ROOT.resolve()
    repository = Path(workspace_path).expanduser().resolve()
    if repository == configured_root or not repository.is_relative_to(configured_root):
        raise WorkspaceAccessError("Repair Agent只能读取FixPilot创建的临时副本。")
    if not repository.is_dir() or repository.is_symlink():
        raise WorkspaceAccessError("修复临时副本不存在或不安全。")

    policy = WorkspacePolicy((repository,))
    available = {
        path.relative_to(repository).as_posix(): path
        for path in policy.iter_files(repository)
        if _is_repairable_path(path.relative_to(repository))
    }
    selected: list[str] = []
    for raw_path in candidate_paths:
        normalized = str(raw_path).replace("\\", "/").lstrip("./")
        direct = normalized if normalized in available else None
        if direct is None:
            matches = [
                path for path in available if normalized.endswith(path) or path.endswith(normalized)
            ]
            direct = matches[0] if len(matches) == 1 else None
        if direct and direct not in selected:
            selected.append(direct)
        if len(selected) >= max_files:
            break

    if not selected:
        selected = [
            path
            for path in available
            if path.endswith(".py")
        ][:max_files]

    contexts: list[dict[str, str]] = []
    remaining = max_chars
    for relative_path in selected:
        raw_content = available[relative_path].read_bytes()
        content = raw_content.decode("utf-8", errors="replace")
        if redact_secrets(content) != content:
            # RepairPlan返回完整文件内容，不能把脱敏占位符重新写回真实源码。
            continue
        if remaining <= 0:
            break
        content = content[:remaining]
        if len(content.encode("utf-8")) != len(raw_content):
            # 完整内容替换不能建立在被截断的文件上。
            continue
        remaining -= len(content)
        contexts.append(
            {
                "relative_path": relative_path,
                "base_sha256": sha256_bytes(raw_content),
                "content": content,
            }
        )
    return contexts


def format_test_feedback(results: list[TestRunResult]) -> str:
    """保留失败用例和首尾日志，为下一轮模型提供稳定反馈。"""

    parts: list[str] = []
    for result in results:
        parts.append(
            f"[{result.preset}] status={result.status} exit_code={result.exit_code}"
        )
        if result.failed_tests:
            parts.append("failed_tests=" + ", ".join(result.failed_tests))
        if result.output_excerpt:
            parts.append(result.output_excerpt)
    return "\n".join(parts)[:20_000]
