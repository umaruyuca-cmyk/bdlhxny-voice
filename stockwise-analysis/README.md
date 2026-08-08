# StockWise Analysis

StockWise 的 Python 分析流程服务。当前实现完成 Phase 0 / Phase 1 的可运行
LangGraph 骨架：动态 `WorkflowPlan`、Root Graph、Query Graph、用户中断恢复、
结构化 Observation、AnalysisInput/AnalysisResult 契约和本地 Mock Tool。

## 当前边界

- 已实现：流程状态、Checkpointer、`interrupt()/resume`、SSE API、测试骨架；
- 未实现：真实 MCP Gateway、Java Data Adapter、Letta Memory Adapter、生产级
  PostgreSQL/Redis Checkpointer、真实模型 Agent；
- Mock 数据只用于流程测试，不能用于任何真实市场结论。

## 本地运行

```powershell
uv sync --extra dev
uv run uvicorn stockwise_analysis.main:app --reload
```

## 测试

```powershell
uv run pytest tests -q
```

## 目录职责

- `runtime/`：配置、预算、错误、恢复与应用装配；
- `graph/`：Root Graph、子图、State 和节点；
- `contracts/`：跨层稳定契约；
- `tools/`：统一工具注册与运行时；
- `mcp/`：Phase 2 的底层 MCP 连接与适配；
- `agents/`：Query、Research 和 Summary Agent；
- `observation/`：外部结果标准化、质量和溯源；
- `domain/`：确定性领域计算；
- `skill/`：可选分析能力/Skill 适配边界。
