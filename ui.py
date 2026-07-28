"""AgentCenter的最小Streamlit展示页面。"""

from uuid import uuid4

import requests
import streamlit as st

from app.api_client import health_check, stream_chat


st.set_page_config(page_title="AgentCenter", page_icon="🤖", layout="centered")
st.title("AgentCenter")
st.caption("LangGraph Router · A2A Agent协作 · MCP知识库工具")

if "thread_id" not in st.session_state:
    st.session_state.thread_id = uuid4().hex
if "messages" not in st.session_state:
    st.session_state.messages = []

with st.sidebar:
    st.subheader("当前会话")
    st.code(st.session_state.thread_id)
    if st.button("新建会话", use_container_width=True):
        st.session_state.thread_id = uuid4().hex
        st.session_state.messages = []
        st.rerun()
    st.divider()
    st.write("AgentCenter服务：", "正常" if health_check() else "未连接")

for item in st.session_state.messages:
    with st.chat_message(item["role"]):
        st.markdown(item["content"])
        if item.get("meta"):
            st.caption(item["meta"])

if prompt := st.chat_input("输入普通问题或编程面试知识问题"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    answer = ""
    intent = ""
    source = ""
    with st.chat_message("assistant"):
        placeholder = st.empty()
        meta_placeholder = st.empty()
        try:
            for event, data in stream_chat(prompt, st.session_state.thread_id):
                if event == "route":
                    intent = str(data.get("intent", ""))
                elif event == "token":
                    answer += str(data.get("content", ""))
                    source = str(data.get("source", source))
                    placeholder.markdown(answer)
                elif event == "message":
                    answer = str(data.get("content", answer))
                    source = str(data.get("source", source))
                    placeholder.markdown(answer)
                elif event == "done":
                    intent = str(data.get("intent", intent))
                    source = str(data.get("source", source))
                elif event == "error":
                    raise RuntimeError(str(data.get("message", "请求失败")))

            meta = f"路线：{intent or '未知'} · 来源：{source or '未知'}"
            meta_placeholder.caption(meta)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            answer = f"请求失败：{exc}"
            meta = "请确认AgentCenter服务已经启动。"
            placeholder.error(answer)
            meta_placeholder.caption(meta)

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer,
            "meta": meta,
        }
    )
