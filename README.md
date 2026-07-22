# AgentCenter

基于 FastAPI、LangChain 和 LangGraph 的多智能体协同中台学习项目。

## 当前进度

当前已完成最小 FastAPI 工程骨架、LangGraph 双路路由工作流、真实聊天模型节点和进程内会话记忆。工具调用、MCP、A2A 与 RAG 集成尚未实现。

## 本地启动

运行前需要在系统环境变量或项目根目录 `.env` 中提供百炼API Key：

```dotenv
DASHSCOPE_API_KEY=你的API Key
```

真实 `.env` 已被 `.gitignore` 排除，不应提交到Git仓库。

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100
```

启动后访问：

- 健康检查：`http://127.0.0.1:8100/health`
- 接口文档：`http://127.0.0.1:8100/docs`

路由测试接口：`POST http://127.0.0.1:8100/chat`

请求示例：

```json
{
  "thread_id": "demo-001",
  "message": "什么是RAG？"
}
```

同一个 `thread_id` 会恢复本次进程内的消息历史；当前使用 `InMemorySaver`，服务重启后记忆会清空。这是教学阶段的内存版Checkpointer，后续可替换为数据库持久化实现。
