import asyncio

from langchain_core.messages import AIMessage

from app import repository_inspector as inspector_module
from app.repository_inspector import RepositoryInspector
from app.schemas import InspectionRequest, TracebackInfo


class FakeMcpClient:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "list_project_files":
            return {
                "repository_root": arguments["repository_path"],
                "files": ["app/service.py", "requirements.txt"],
                "files_scanned": 2,
                "truncated": False,
            }
        if name == "search_code":
            return {
                "matches": [
                    {
                        "path": "app/service.py",
                        "line": 8,
                        "excerpt": "import missing_package",
                        "matched_terms": ["missing_package"],
                    }
                ]
            }
        if name == "read_source_file":
            return {
                "path": "app/service.py",
                "start_line": arguments["start_line"],
                "end_line": arguments["end_line"],
                "content": "8: import missing_package",
            }
        if name == "read_dependency_manifest":
            return {
                "manifests": [
                    {
                        "path": "requirements.txt",
                        "content": "fastapi==0.139.0",
                    }
                ]
            }
        if name == "get_python_environment":
            return {
                "scope": "FixPilot运行环境",
                "requested_packages": {"missing_package": "not-installed"},
            }
        raise AssertionError(f"unexpected tool: {name}")


class SequenceModel:
    def __init__(self, responses):
        self.responses = iter(responses)

    def bind_tools(self, tools):
        assert {item["function"]["name"] for item in tools}
        return self

    async def ainvoke(self, messages):
        return next(self.responses)


class FailingModel:
    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        raise RuntimeError("model unavailable")


def inspection_request():
    return InspectionRequest(
        repository_path=r"D:\demo",
        traceback_info=TracebackInfo(
            exception_type="ModuleNotFoundError",
            message="No module named 'missing_package'",
            search_terms=["ModuleNotFoundError", "missing_package"],
        ),
    )


def tool_message(name, arguments, index):
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": name,
                "args": arguments,
                "id": f"call-{index}",
                "type": "tool_call",
            }
        ],
    )


def test_agent_selects_subset_of_tools_and_stops():
    mcp_client = FakeMcpClient()
    model = SequenceModel(
        [
            tool_message(
                "search_code",
                {"queries": ["missing_package"], "max_results": 5},
                1,
            ),
            tool_message(
                "read_source_file",
                {
                    "relative_path": "app/service.py",
                    "start_line": 4,
                    "end_line": 12,
                },
                2,
            ),
            AIMessage(content="证据已经足够。"),
        ]
    )
    inspector = RepositoryInspector(mcp_client, lambda: model)

    result = asyncio.run(inspector.inspect(inspection_request()))

    assert result.status == "ok"
    assert result.mode == "agent"
    assert [name for name, _ in mcp_client.calls] == [
        "list_project_files",
        "search_code",
        "read_source_file",
    ]
    assert [step.tool_name for step in result.steps] == [
        "list_project_files",
        "search_code",
        "read_source_file",
    ]
    assert {item.id for item in result.evidence} == {
        "source-match-1",
        "source-context-1",
    }


def test_model_failure_uses_fixed_fallback():
    mcp_client = FakeMcpClient()
    inspector = RepositoryInspector(mcp_client, FailingModel)

    result = asyncio.run(inspector.inspect(inspection_request()))

    assert result.status == "ok"
    assert result.mode == "fallback"
    assert [name for name, _ in mcp_client.calls] == [
        "list_project_files",
        "search_code",
        "read_source_file",
        "read_dependency_manifest",
        "get_python_environment",
    ]
    assert any("固定取证降级" in warning for warning in result.warnings)


def test_repeated_calls_are_blocked_and_step_limit_stops(monkeypatch):
    monkeypatch.setattr(inspector_module, "MAX_INSPECTION_STEPS", 3)
    mcp_client = FakeMcpClient()
    model = SequenceModel(
        [
            tool_message("search_code", {"queries": ["missing_package"]}, 1),
            tool_message("search_code", {"queries": ["missing_package"]}, 2),
            tool_message("search_code", {"queries": ["missing_package"]}, 3),
        ]
    )
    inspector = RepositoryInspector(mcp_client, lambda: model)

    result = asyncio.run(inspector.inspect(inspection_request()))

    assert result.mode == "agent"
    assert [name for name, _ in mcp_client.calls] == [
        "list_project_files",
        "search_code",
    ]
    assert sum(step.status == "error" for step in result.steps) == 2
    assert any("最大工具调用步数" in warning for warning in result.warnings)
