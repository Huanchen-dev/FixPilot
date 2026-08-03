"""FixPilot的FastAPI诊断入口与SSE进度事件。"""

import json
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI
from starlette.responses import StreamingResponse

from app.graph import diagnosis_graph
from app.repair_service import repair_service
from app.schemas import (
    DiagnosisRequest,
    DiagnosisResponse,
    RepairApplyRequest,
    RepairApplyResponse,
    RepairGenerateRequest,
    RepairGenerateResponse,
)


app = FastAPI(
    title="FixPilot",
    description="面向Python/AI应用项目的智能故障诊断系统",
    version="2.0.0",
)

STAGE_LABELS = {
    "parse_traceback": "解析Traceback",
    "collect_evidence": "收集仓库证据",
    "analyze": "分析根因候选",
    "build_report": "生成诊断报告",
}


@app.get("/health", summary="服务健康检查")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "fixpilot"}


@app.post(
    "/diagnose",
    response_model=DiagnosisResponse,
    summary="执行一次只读故障诊断",
)
async def diagnose(request: DiagnosisRequest) -> DiagnosisResponse:
    diagnosis_id = uuid4().hex
    final_state = await diagnosis_graph.ainvoke(
        {"diagnosis_id": diagnosis_id, "request": request}
    )
    return DiagnosisResponse(
        diagnosis_id=diagnosis_id,
        report=final_state["report"],
    )


def sse_event(event: str, data: dict[str, object]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


async def stream_diagnosis_events(
    request: DiagnosisRequest,
) -> AsyncIterator[str]:
    """逐节点发送诊断进度，最终发送完整结构化报告。"""

    diagnosis_id = uuid4().hex
    yield sse_event("start", {"diagnosis_id": diagnosis_id})
    state: dict[str, object] = {
        "diagnosis_id": diagnosis_id,
        "request": request,
    }
    try:
        async for update in diagnosis_graph.astream(
            state,
            stream_mode="updates",
        ):
            for node_name, output in update.items():
                if isinstance(output, dict):
                    state.update(output)
                yield sse_event(
                    "stage",
                    {
                        "name": node_name,
                        "label": STAGE_LABELS.get(node_name, node_name),
                    },
                )
        report = state.get("report")
        if report is None:
            raise RuntimeError("诊断工作流没有生成报告。")
        yield sse_event("report", {"report": report.model_dump()})
        yield sse_event("done", {"diagnosis_id": diagnosis_id})
    except Exception as exc:
        yield sse_event(
            "error",
            {
                "diagnosis_id": diagnosis_id,
                "message": f"FixPilot诊断失败：{type(exc).__name__}",
            },
        )


@app.post("/diagnose/stream", summary="以SSE返回诊断进度和报告")
async def diagnose_stream(request: DiagnosisRequest) -> StreamingResponse:
    return StreamingResponse(
        stream_diagnosis_events(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post(
    "/repair/generate",
    response_model=RepairGenerateResponse,
    summary="在临时副本中生成并验证安全修复候选",
)
async def generate_repair(
    request: RepairGenerateRequest,
) -> RepairGenerateResponse:
    return await repair_service.generate(request)


@app.post(
    "/repair/apply",
    response_model=RepairApplyResponse,
    summary="人工确认后将已验证候选安全应用到原仓库",
)
async def apply_repair(request: RepairApplyRequest) -> RepairApplyResponse:
    return await repair_service.apply(request.repair_id)


@app.post(
    "/repair/reject",
    response_model=RepairApplyResponse,
    summary="拒绝修复候选并清理临时副本",
)
async def reject_repair(request: RepairApplyRequest) -> RepairApplyResponse:
    return await repair_service.reject(request.repair_id)
