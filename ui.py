"""FixPilot诊断、临时修复验证与最终人工确认页面。"""

from typing import Any

import requests
import streamlit as st

from app.api_client import (
    finish_repair,
    generate_repair,
    health_check,
    stream_diagnosis,
)


st.set_page_config(page_title="FixPilot", page_icon="🛠️", layout="wide")
st.title("FixPilot")
st.caption("面向Python/AI应用项目的智能故障诊断与安全修复系统")

for key, default in (
    ("diagnosis_report", None),
    ("diagnosis_repository", None),
    ("repair_result", None),
    ("repair_action_result", None),
):
    if key not in st.session_state:
        st.session_state[key] = default

with st.sidebar:
    st.subheader("服务状态")
    st.write("FixPilot API：", "正常" if health_check() else "未连接")
    st.divider()
    st.info(
        "诊断阶段只读。修复只发生在临时副本中，固定测试通过后仍需你最终确认；"
        "系统不执行任意Shell命令，也不会静默覆盖原文件。"
    )

with st.form("diagnosis-form"):
    left, right = st.columns(2)
    with left:
        traceback_text = st.text_area(
            "报错或完整Traceback *",
            height=300,
            placeholder="Traceback (most recent call last):\n...",
        )
        repository_path = st.text_input(
            "本地仓库路径（可选）",
            placeholder=r"D:\path\to\python-project",
        )
        command = st.text_input(
            "触发报错的命令（可选）",
            placeholder="python -m uvicorn app.main:app",
        )
    with right:
        expected_behavior = st.text_area(
            "预期行为（可选）",
            height=95,
        )
        python_version = st.text_input("Python版本（可选）")
        dependency_context = st.text_area(
            "依赖信息（可选）",
            height=95,
            placeholder="可粘贴requirements片段或关键包版本",
        )
        code_context = st.text_area(
            "最小代码上下文（可选）",
            height=95,
        )
    submitted = st.form_submit_button(
        "开始只读诊断",
        type="primary",
        use_container_width=True,
    )


def render_report(report: dict[str, Any]) -> None:
    st.subheader("诊断结论")
    st.write(report["summary"])

    traceback_info = report["traceback_info"]
    st.caption(
        f"异常：{traceback_info['exception_type']} · "
        f"仓库检查：{report['inspection_status']} · "
        f"取证模式：{report.get('inspection_mode', 'not_run')}"
    )

    st.markdown("#### 根因候选")
    for index, cause in enumerate(report["root_causes"], start=1):
        with st.expander(
            (
                f"{index}. {cause['title']} · "
                f"{cause['category']} · {cause['confidence']}"
            ),
            expanded=index == 1,
        ):
            st.write(cause["explanation"])
            if cause["evidence_ids"]:
                st.caption("证据：" + ", ".join(cause["evidence_ids"]))

    actions, verification = st.columns(2)
    with actions:
        st.markdown("#### 推荐处理")
        for item in report["recommended_actions"]:
            st.markdown(f"- {item}")
    with verification:
        st.markdown("#### 验证步骤")
        for item in report["verification_steps"]:
            st.markdown(f"- {item}")

    if report.get("inspection_steps"):
        st.markdown("#### 取证轨迹")
        for step in report["inspection_steps"]:
            evidence = ", ".join(step.get("evidence_ids", []))
            suffix = f" · 证据：{evidence}" if evidence else ""
            st.markdown(
                f"- `{step['index']}` `{step['tool_name']}` "
                f"{step['status']}：{step['summary']}{suffix}"
            )

    st.markdown("#### 证据")
    for item in report["evidence"]:
        label = item.get("path") or item["kind"]
        line = f":{item['line']}" if item.get("line") else ""
        with st.expander(f"{item['id']} · {label}{line}"):
            st.code(item["excerpt"])
            if item.get("detail"):
                st.caption(item["detail"])

    if report["limitations"]:
        st.markdown("#### 未确定项")
        for item in report["limitations"]:
            st.markdown(f"- {item}")


def render_test_results(results: list[dict[str, Any]]) -> None:
    for result in results:
        label = (
            f"{result['preset']} · {result['status']} · "
            f"{result['duration_seconds']}s"
        )
        with st.expander(label):
            if result.get("failed_tests"):
                st.write("失败用例：", ", ".join(result["failed_tests"]))
            st.code(result.get("output_excerpt") or "无输出")


def render_repair(result: dict[str, Any]) -> None:
    st.divider()
    st.subheader("安全修复候选")
    st.write(result["repairable_reason"])
    status = result["status"]
    if status == "not_repairable":
        st.warning("该问题不适合通过自动修改代码解决。")
        return
    if status == "error":
        st.error("修复候选生成失败。")
    elif status == "tests_failed":
        st.warning("两轮内未能通过固定验证，禁止应用到原仓库。")
    elif status == "ready":
        st.success("候选已在临时副本中通过允许的固定验证，等待最终确认。")

    for warning in result.get("warnings", []):
        st.warning(warning)
    if result.get("baseline_test_results"):
        st.markdown("#### 修复前基线")
        render_test_results(result["baseline_test_results"])
    if result.get("attempts"):
        st.markdown("#### 修复尝试")
        for attempt in result["attempts"]:
            st.markdown(
                f"- 第{attempt['attempt']}轮：`{attempt['status']}`"
            )
            status_summary = "；".join(
                f"{item['preset']}={item['status']}"
                for item in attempt.get("test_results", [])
            )
            if status_summary:
                st.caption(status_summary)
            comparisons = (
                ("相对基线已修复", attempt.get("fixed_tests", [])),
                ("基线中仍失败", attempt.get("remaining_failed_tests", [])),
                ("相对基线新增失败", attempt.get("new_failed_tests", [])),
                ("相对最佳候选重新失败", attempt.get("regressed_tests", [])),
            )
            for label, tests in comparisons:
                if tests:
                    st.write(f"{label}：{', '.join(tests)}")
    plan = result.get("final_plan")
    if plan:
        st.markdown("#### 修复计划")
        st.write(plan["summary"])
        for change in plan["changes"]:
            st.markdown(f"- `{change['relative_path']}`：{change['reason']}")
    if result.get("diff"):
        st.markdown("#### 最终Diff")
        st.code(result["diff"], language="diff")
    if result.get("test_results"):
        st.markdown("#### 固定验证")
        render_test_results(result["test_results"])


if submitted:
    if not traceback_text.strip():
        st.error("请至少输入报错信息或Traceback。")
    else:
        st.session_state.diagnosis_report = None
        st.session_state.diagnosis_repository = None
        st.session_state.repair_result = None
        st.session_state.repair_action_result = None
        payload = {
            "traceback": traceback_text,
            "repository_path": repository_path or None,
            "command": command or None,
            "expected_behavior": expected_behavior or None,
            "python_version": python_version or None,
            "dependency_context": dependency_context or None,
            "code_context": code_context or None,
        }
        progress = st.status("正在创建诊断任务……", expanded=True)
        report_data: dict[str, Any] | None = None
        try:
            for event, data in stream_diagnosis(payload):
                if event == "start":
                    progress.write(f"诊断编号：{data['diagnosis_id']}")
                elif event == "stage":
                    progress.write(str(data["label"]))
                elif event == "report":
                    report_data = data["report"]
                elif event == "done":
                    progress.update(label="诊断完成", state="complete")
                elif event == "error":
                    raise RuntimeError(str(data["message"]))
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            progress.update(label="诊断失败", state="error")
            st.error(str(exc))
        if report_data:
            st.session_state.diagnosis_report = report_data
            st.session_state.diagnosis_repository = repository_path or None

if st.session_state.diagnosis_report:
    render_report(st.session_state.diagnosis_report)
    if st.session_state.diagnosis_repository:
        if st.button(
            "生成安全修复方案",
            type="primary",
            use_container_width=True,
        ):
            try:
                with st.spinner("正在临时副本中生成并验证修复，最多尝试两轮……"):
                    st.session_state.repair_result = generate_repair(
                        st.session_state.diagnosis_repository,
                        st.session_state.diagnosis_report,
                    )
                st.session_state.repair_action_result = None
            except (requests.RequestException, ValueError) as exc:
                st.error(f"修复请求失败：{exc}")
    else:
        st.info("未提供仓库路径，本次报告只能查看，不能生成文件修复。")

if st.session_state.repair_result:
    render_repair(st.session_state.repair_result)
    if st.session_state.repair_result["status"] == "ready":
        apply_column, reject_column = st.columns(2)
        with apply_column:
            if st.button("确认应用到原仓库", type="primary", use_container_width=True):
                try:
                    st.session_state.repair_action_result = finish_repair(
                        st.session_state.repair_result["repair_id"], "apply"
                    )
                    st.session_state.repair_result["status"] = (
                        st.session_state.repair_action_result["status"]
                    )
                except (requests.RequestException, ValueError) as exc:
                    st.error(f"应用失败：{exc}")
        with reject_column:
            if st.button("拒绝并清理候选", use_container_width=True):
                try:
                    st.session_state.repair_action_result = finish_repair(
                        st.session_state.repair_result["repair_id"], "reject"
                    )
                    st.session_state.repair_result["status"] = (
                        st.session_state.repair_action_result["status"]
                    )
                except (requests.RequestException, ValueError) as exc:
                    st.error(f"拒绝操作失败：{exc}")
    elif st.session_state.repair_result["status"] in {"tests_failed", "error"}:
        if st.button("清理失败候选", use_container_width=True):
            try:
                st.session_state.repair_action_result = finish_repair(
                    st.session_state.repair_result["repair_id"], "reject"
                )
                st.session_state.repair_result["status"] = (
                    st.session_state.repair_action_result["status"]
                )
            except (requests.RequestException, ValueError) as exc:
                st.error(f"清理失败：{exc}")

if st.session_state.repair_action_result:
    action_result = st.session_state.repair_action_result
    if action_result["status"] == "applied":
        st.success(
            action_result["message"]
            + " 文件："
            + ", ".join(action_result.get("applied_files", []))
        )
    elif action_result["status"] == "rejected":
        st.info(action_result["message"])
    else:
        st.error(action_result["message"])
