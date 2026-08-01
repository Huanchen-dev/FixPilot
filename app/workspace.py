"""FixPilot只读仓库检查与路径安全策略。"""

from __future__ import annotations

import platform
import re
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, Iterable

from app.config import MAX_PROJECT_FILES, MAX_SOURCE_FILE_BYTES, WORKSPACE_ROOTS


IGNORED_DIRECTORIES = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "models",
    "node_modules",
    "venv",
}
SENSITIVE_FILENAMES = {
    ".env",
    ".env.local",
    "credentials.json",
    "secrets.json",
}
SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
ALLOWED_SUFFIXES = {
    ".cfg",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
DEPENDENCY_FILENAMES = {
    "pyproject.toml",
    "poetry.lock",
    "pdm.lock",
    "requirements.txt",
    "requirements-dev.txt",
    "setup.cfg",
    "setup.py",
}
SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|secret|password)"
        r"\b(\s*[:=]\s*)(?:[\"'][^\"']*[\"']|[^\s,]+)"
    ),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
)


class WorkspaceAccessError(ValueError):
    """仓库路径或文件路径越过FixPilot配置的安全边界。"""


class WorkspacePolicy:
    """只允许在白名单根目录中读取受控文本文件。"""

    def __init__(
        self,
        allowed_roots: Iterable[Path] | None = None,
        max_file_bytes: int = MAX_SOURCE_FILE_BYTES,
        max_project_files: int = MAX_PROJECT_FILES,
    ) -> None:
        roots = WORKSPACE_ROOTS if allowed_roots is None else allowed_roots
        self.allowed_roots = tuple(Path(root).resolve() for root in roots)
        self.max_file_bytes = max_file_bytes
        self.max_project_files = max_project_files

    def resolve_repository(self, repository_path: str) -> Path:
        candidate = Path(repository_path).expanduser().resolve()
        if not candidate.is_dir():
            raise WorkspaceAccessError("目标仓库不存在或不是目录。")
        if not any(
            candidate == root or candidate.is_relative_to(root)
            for root in self.allowed_roots
        ):
            raise WorkspaceAccessError("目标仓库不在FIXPILOT_WORKSPACE_ROOTS白名单中。")
        return candidate

    def resolve_file(self, repository: Path, relative_path: str) -> Path:
        if Path(relative_path).is_absolute():
            raise WorkspaceAccessError("文件路径必须相对于目标仓库。")
        candidate = (repository / relative_path).resolve()
        if candidate != repository and not candidate.is_relative_to(repository):
            raise WorkspaceAccessError("文件路径越过了目标仓库边界。")
        if not candidate.is_file():
            raise WorkspaceAccessError("目标文件不存在。")
        self._validate_file(candidate)
        return candidate

    def _validate_file(self, path: Path) -> None:
        lower_name = path.name.lower()
        if (
            lower_name in SENSITIVE_FILENAMES
            or lower_name.startswith(".env")
            or "credential" in lower_name
            or "secret" in lower_name
            or path.suffix.lower() in SENSITIVE_SUFFIXES
        ):
            raise WorkspaceAccessError("安全策略禁止读取敏感文件。")
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            raise WorkspaceAccessError("文件类型不在只读白名单中。")
        if path.stat().st_size > self.max_file_bytes:
            raise WorkspaceAccessError("文件超过单文件读取大小限制。")

    def iter_files(self, repository: Path) -> list[Path]:
        files: list[Path] = []
        for path in repository.rglob("*"):
            relative = path.relative_to(repository)
            if any(part in IGNORED_DIRECTORIES for part in relative.parts):
                continue
            if path.is_symlink():
                continue
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved != repository and not resolved.is_relative_to(repository):
                continue
            try:
                self._validate_file(path)
            except WorkspaceAccessError:
                continue
            files.append(path)
            if len(files) >= self.max_project_files:
                break
        return sorted(files)


def redact_secrets(text: str) -> str:
    """遮盖常见密钥、Token和密码值，避免证据结果泄露秘密。"""

    redacted = text
    for pattern in SECRET_PATTERNS:
        if pattern.groups >= 3:
            redacted = pattern.sub(r"\1\2[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def list_project_files(repository_path: str) -> dict[str, Any]:
    policy = WorkspacePolicy()
    repository = policy.resolve_repository(repository_path)
    files = policy.iter_files(repository)
    return {
        "repository_root": str(repository),
        "files": [path.relative_to(repository).as_posix() for path in files],
        "files_scanned": len(files),
        "truncated": len(files) >= policy.max_project_files,
    }


def read_source_file(
    repository_path: str,
    relative_path: str,
    start_line: int = 1,
    end_line: int = 200,
) -> dict[str, Any]:
    policy = WorkspacePolicy()
    repository = policy.resolve_repository(repository_path)
    path = policy.resolve_file(repository, relative_path)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, start_line)
    end = min(len(lines), max(start, end_line), start + 199)
    excerpt = "\n".join(
        f"{line_number}: {lines[line_number - 1]}"
        for line_number in range(start, end + 1)
    )
    return {
        "path": path.relative_to(repository).as_posix(),
        "start_line": start,
        "end_line": end,
        "content": redact_secrets(excerpt),
    }


def search_code(
    repository_path: str,
    queries: list[str],
    max_results: int = 20,
) -> dict[str, Any]:
    policy = WorkspacePolicy()
    repository = policy.resolve_repository(repository_path)
    normalized_queries = [
        query.strip().lower()
        for query in queries[:12]
        if query.strip() and len(query.strip()) >= 3
    ]
    matches: list[dict[str, Any]] = []
    for path in policy.iter_files(repository):
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line_number, line in enumerate(lines, start=1):
            lowered = line.lower()
            matched = [query for query in normalized_queries if query in lowered]
            if not matched:
                continue
            matches.append(
                {
                    "path": path.relative_to(repository).as_posix(),
                    "line": line_number,
                    "excerpt": redact_secrets(line.strip())[:500],
                    "matched_terms": matched,
                }
            )
            if len(matches) >= max(1, min(max_results, 50)):
                return {"matches": matches}
    return {"matches": matches}


def read_dependency_manifests(repository_path: str) -> dict[str, Any]:
    policy = WorkspacePolicy()
    repository = policy.resolve_repository(repository_path)
    manifests: list[dict[str, str]] = []
    for path in policy.iter_files(repository):
        if (
            path.name.lower() not in DEPENDENCY_FILENAMES
            and not path.name.lower().startswith("requirements")
        ):
            continue
        relative = path.relative_to(repository).as_posix()
        content = read_source_file(repository_path, relative, 1, 200)["content"]
        manifests.append({"path": relative, "content": content})
    return {"manifests": manifests[:10]}


def get_python_environment(package_names: list[str] | None = None) -> dict[str, Any]:
    versions: dict[str, str] = {}
    for package_name in (package_names or [])[:30]:
        try:
            versions[package_name] = metadata.version(package_name)
        except metadata.PackageNotFoundError:
            versions[package_name] = "not-installed"
    return {
        "scope": "FixPilot运行环境，不代表目标仓库的独立虚拟环境",
        "python_version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "executable_name": Path(sys.executable).name,
        "requested_packages": versions,
    }
