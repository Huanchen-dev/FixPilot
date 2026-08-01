"""FixPilot只读诊断Streamlit页面。"""

from typing import Any

import requests
import streamlit as st

from app.api_client import health_check, stream_diagnosis


st.set_page_config(page_title="FixPilot", page_icon="🛠️", layout="wide")
st.title("FixPilot")
st.caption("面向Python/AI应用项目的智能故障诊断系统 · 只读模式")

with st.sidebar:
    st.subheader("服务状态")
    st.write("FixPilot API：", "正常" if health_check() else "未连接")
    st.divider()
    st.info(
        "FixPilot只读取白名单仓库中的受控文本文件，"
        "不会修改文件，也不会自动执行Shell命令。"
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


if submitted:
    if not traceback_text.strip():
        st.error("请至少输入报错信息或Traceback。")
    else:
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
            render_report(report_data)
