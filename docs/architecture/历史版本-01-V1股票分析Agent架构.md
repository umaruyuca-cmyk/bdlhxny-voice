# StockWise 历史版本档案 01：V1 股票分析 Agent 架构

> 版本性质：历史版本，已被后续统一架构取代  
> 形成日期：2026-08-04  
> 代表提交：`8676bea`  
> 原始版本：Agent 需求与开发设计 v1.1、代码目录设计 v1.0

## 1. 版本定位

V1 的目标是从零建设一套只做股票研究、组合分析、策略设计和回测的 Python Agent 系统。

这一阶段的 StockWise 是“股票分析系统”，尚未扩展为通用金融助手或个人金融持续服务平台。

## 2. 产品需求

系统需要支持：

- 自然语言股票问题理解；
- 实时行情、历史行情和市场状态分析；
- 个股、ETF、基金和行业板块研究；
- 新闻、公告和研究资料检索；
- 用户持仓和组合风险分析；
- 模拟调仓建议；
- 投资策略设计；
- 历史回测和风险指标计算；
- 研究结论、用户偏好和知识沉淀；
- 流式输出、运行状态查看和可恢复执行。

## 3. 明确不做

- 真实下单、撤单和改单；
- Broker MCP、券商适配器和交易执行 Worker；
- 订单状态机；
- 复杂人工交易审批；
- 付费模型门禁；
- 让一个大 Agent 自由访问全部系统能力；
- 通过 Skill 取代确定性 Domain Service；
- 让大模型执行指标、风险和回测计算。

## 4. 总体架构

```text
用户请求
  → FastAPI
  → Application Runtime
  → LangGraph Root StateGraph
  → 领域子图
  → Model / Agent / Tool 节点
  → Domain Service
  → 结构化分析结果
```

### 4.1 LangGraph

负责：

- Root Graph 和领域子图；
- 状态流转、条件边和循环；
- 动态执行路径；
- Checkpoint；
- `interrupt()` 和恢复；
- 流式事件；
- 成功、失败和有限结果终态。

### 4.2 LangChain

负责：

- 模型适配；
- 结构化输出；
- Tool 定义；
- 局部 Agent；
- 模型重试和降级；
- MCP Tool 适配。

### 4.3 Application Runtime

作为薄应用层负责：

- 创建 `run_id`；
- 创建或恢复 `thread_id`；
- 调用 Root Graph；
- 将事件转换为 SSE 或 JSON；
- 管理请求取消、超时、日志和指标；
- 连接数据库、Redis 和 Checkpointer。

## 5. Graph 需求

V1 规划了以下子图：

1. Query Understanding Graph：理解问题、识别实体和生成计划；
2. Market Research Graph：动态选择市场数据和研究资料；
3. Portfolio Analysis Graph：分析持仓、风险和模拟调仓；
4. Strategy Graph：生成结构化策略；
5. Backtest Graph：执行确定性回测；
6. Knowledge Graph：沉淀研究结论和用户偏好。

Root Graph 通过 `WorkflowPlan` 编排多个子图之间的依赖关系，而不是将所有请求塞入单一固定流程。

## 6. Agent 执行边界

V1.1 将自由 ReAct 收紧为单步决策模式：

```text
Agent 选择下一动作
  → Graph 校验工具、参数和预算
  → Graph 执行 Tool
  → 生成标准 Observation
  → Graph 更新状态
  → 条件边判断是否继续
```

固定内容：

- 节点类型；
- State Schema；
- 允许的终态；
- 工具来源；
- 资源和循环上限。

动态内容：

- 子图选择；
- 下一步工具；
- 是否继续取证；
- 是否重新规划；
- 最终输出的分析维度。

## 7. 数据与计算需求

- 所有外部调用结果转换为统一 `Observation`；
- Agent 负责理解、规划、比较和解释；
- Domain Service 负责指标、风险和回测；
- 关键计算必须可复现；
- 数据时效、缺失和格式由确定性代码校验；
- Strategy 到 Backtest 必须使用明确的结构化契约。

## 8. API 与运行要求

- 提供对话入口；
- 提供运行状态查询；
- 支持中断恢复；
- 支持结构化结果类型；
- 保存运行事件和审计信息；
- 控制缓存、限流、超时、重试和线程并发。

## 9. 分阶段实施

1. Phase 0：系统骨架和核心契约；
2. Phase 1：Query Understanding Graph；
3. Phase 2：Market Research Graph；
4. Phase 3：Portfolio Analysis Graph；
5. Phase 4：Strategy 和 Backtest Graph；
6. Phase 5：Knowledge 和 Memory；
7. Phase 6：重新设计 Skill。

## 10. 版本遗产

V1 留下并延续至今的核心原则包括：

- Graph 控制流程；
- Agent 只负责适合 LLM 的动态判断；
- 确定性 Domain 负责金融计算；
- 外部数据必须结构化；
- ReAct 必须有边界；
- 长流程必须可追踪、可中断、可恢复。

## 11. 被后续版本修改的内容

- 固定股票领域子图后来被更通用的执行模式和领域模型取代；
- Knowledge/Memory 后来拆分为 Checkpointer、Analysis History、Mem0 和 Task；
- 数据接入后来统一为 MCP、Java Data API 和 Capability Gateway；
- 股票分析最终下沉为个人金融领域中的 Stock Research Skill。
