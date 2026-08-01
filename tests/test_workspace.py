from pathlib import Path

import pytest

from app import workspace
from app.workspace import WorkspaceAccessError, WorkspacePolicy


def test_workspace_blocks_escape_and_sensitive_files(tmp_path, monkeypatch):
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "app.py").write_text(
        'API_KEY = "sk-abcdefghijklmnop"\nPASSWORD = "visible-secret"\n',
        encoding="utf-8",
    )
    (repository / ".env").write_text("PASSWORD=secret", encoding="utf-8")
    (repository / "credentials.yaml").write_text(
        "token: should-not-be-read",
        encoding="utf-8",
    )
    ignored = repository / ".venv"
    ignored.mkdir()
    (ignored / "ignored.py").write_text("secret", encoding="utf-8")
    outside = tmp_path / "outside.py"
    outside.write_text("outside", encoding="utf-8")

    monkeypatch.setattr(workspace, "WORKSPACE_ROOTS", (tmp_path,))
    listing = workspace.list_project_files(str(repository))
    assert listing["files"] == ["app.py"]

    content = workspace.read_source_file(str(repository), "app.py")["content"]
    assert "sk-abcdefghijklmnop" not in content
    assert "visible-secret" not in content
    assert "[REDACTED]" in content

    with pytest.raises(WorkspaceAccessError):
        workspace.read_source_file(str(repository), "../outside.py")
    with pytest.raises(WorkspaceAccessError):
        workspace.read_source_file(str(repository), ".env")


def test_workspace_rejects_repository_outside_allowlist(tmp_path):
    allowed = tmp_path / "allowed"
    denied = tmp_path / "denied"
    allowed.mkdir()
    denied.mkdir()
    policy = WorkspacePolicy((allowed,))
    with pytest.raises(WorkspaceAccessError):
        policy.resolve_repository(str(denied))


def test_search_and_dependency_reading(tmp_path, monkeypatch):
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "service.py").write_text(
        "def connect_service():\n    raise ConnectionError('refused')\n",
        encoding="utf-8",
    )
    (repository / "requirements.txt").write_text(
        "httpx==0.28.1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(workspace, "WORKSPACE_ROOTS", (tmp_path,))

    matches = workspace.search_code(
        str(repository),
        ["ConnectionError", "connect_service"],
    )
    manifests = workspace.read_dependency_manifests(str(repository))
    assert len(matches["matches"]) == 2
    assert manifests["manifests"][0]["path"] == "requirements.txt"
