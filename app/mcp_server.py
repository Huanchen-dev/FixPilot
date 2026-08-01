"""把FixPilot受控仓库读取能力暴露为标准MCP工具。"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from app.workspace import (
    get_python_environment as inspect_python_environment,
    list_project_files as inspect_project_files,
    read_dependency_manifests as inspect_dependency_manifests,
    read_source_file as inspect_source_file,
    search_code as inspect_code,
)


mcp = FastMCP(
    "FixPilot Read-Only Repository Tools",
    instructions=(
        "只允许在配置白名单中扫描、读取和搜索Python项目；"
        "不提供文件写入、删除或命令执行能力。"
    ),
)


@mcp.tool()
async def list_project_files(repository_path: str) -> dict[str, Any]:
    """列出白名单仓库内可安全读取的文本文件。"""

    return inspect_project_files(repository_path)


@mcp.tool()
async def read_source_file(
    repository_path: str,
    relative_path: str,
    start_line: int = 1,
    end_line: int = 200,
) -> dict[str, Any]:
    """按相对路径和行号范围读取一个受控源文件。"""

    return inspect_source_file(
        repository_path,
        relative_path,
        start_line,
        end_line,
    )


@mcp.tool()
async def search_code(
    repository_path: str,
    queries: list[str],
    max_results: int = 20,
) -> dict[str, Any]:
    """在受控文本文件中搜索Traceback相关符号。"""

    return inspect_code(repository_path, queries, max_results)


@mcp.tool()
async def read_dependency_manifest(repository_path: str) -> dict[str, Any]:
    """读取requirements、pyproject等依赖声明文件。"""

    return inspect_dependency_manifests(repository_path)


@mcp.tool()
async def get_python_environment(
    package_names: list[str] | None = None,
) -> dict[str, Any]:
    """返回FixPilot运行环境及指定Python包的安装版本。"""

    return inspect_python_environment(package_names)


if __name__ == "__main__":
    mcp.run("stdio")
