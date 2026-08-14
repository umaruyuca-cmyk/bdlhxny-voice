# StockWise 历史版本档案 03：V2.x 统一单 Runtime 架构

> 版本性质：历史统一架构，核心边界已被 V3 和当前架构继承  
> 形成日期：2026-08-05～2026-08-06  
> 代表提交：`37aa186`  
> 原始版本：统一架构 v2.2、v2.3

## 1. 版本定位

V2.x 将 StockWise 定义为“Python 统一编排、MCP 负责取数、分析能力负责计算、Java 负责用户数据”的股票研究系统。

这一版本解决了 V1 融合方案中数据获取、Agent 编排和分析计算边界仍不够稳定的问题。

## 2. 产品需求

- 标的识别和市场数据查询；
- 实时行情和历史行情分析；
- 技术面、基本面和估值分析；
- 行业、板块、资金流向和新闻分析；
- 用户持仓和账户影响分析；
- 策略设计和回测；
- 经用户确认后的知识沉淀。

仍然明确不建设：

- 真实下单、撤单和改单；
- 券商交易执行；
- 无限 ReAct；
- Skill 内部查询市场数据；
- 让大模型代替确定性金融计算；
- 继续用 Java 承载新的 Agent 主流程。

## 3. 总体架构

```text
用户
  → Python Application Runtime
  → LangGraph Root Graph
      ├─ Query Graph
      ├─ Market Data Graph
      ├─ Analysis Capability
      └─ Summary Model
          ↓
          ├─ MCP Market Data Gateway
          ├─ Java Portfolio Data API
          └─ Python Analysis Engine
```

## 4. 组件边界

### 4.1 Python LangGraph

- 统一控制业务流程；
- 理解问题和生成数据需求；
- 执行局部有界 ReAct；
- 调用 MCP、Java Adapter 和分析能力；
- 控制预算、降级、中断和恢复；
- 生成事件流和最终回答。

### 4.2 MCP

- 只查询外部市场数据；
- 不生成最终分析结论；
- 不直接改变业务 State；
- 必须通过 MCP Adapter 和 Market Data Gateway 接入。

### 4.3 Java Data API

- 提供持仓、账户、交易记录和风险画像；
- 返回授权范围、数据时间和查询状态；
- 不再承担新 Agent 编排；
- Python 不允许绕过 Java API 直接读取用户业务表。

### 4.4 Analysis Capability

- 接收结构化 `AnalysisInput`；
- 生成结构化 `AnalysisResult`；
- 负责技术指标、风险、估值和领域总结；
- 不查询外部市场数据；
- 第一阶段默认由 Python Analysis Engine 实现。

## 5. 统一数据契约

V2.x 要求稳定以下跨层对象：

- `Observation`：外部工具结果的统一结构；
- `DataRequirement`：本轮需要的数据；
- `WorkflowPlan`：执行任务及其依赖；
- `AnalysisInput`：进入分析能力的标准输入；
- `AnalysisResult`：分析能力的标准输出。

每个 Observation 必须尽量携带：

- 来源；
- 观察时间；
- 数据时间；
- 状态；
- 错误；
- 数据质量；
- 是否可用于后续分析。

## 6. ReAct 与 Graph 要求

节点被分为：

```text
CODE
TOOL_ONLY
DIRECT_LLM
STRUCTURED_LLM
BOUNDED_REACT_AGENT
SUBGRAPH
INTERRUPT
```

约束包括：

- 数据校验、预算和状态修改使用确定性代码；
- MCP、Java 和分析能力通过 Tool/Adapter 调用；
- 问题理解和表达可以使用 LLM；
- 动态数据选择才使用有界 ReAct；
- 所有 ReAct 必须有白名单、轮数、工具调用数和时间预算；
- 缺少关键条件时通过 Interrupt 请求补充。

## 7. v2.2 数据源与运行需求

- MCP 以远程服务部署；
- 两个 MCP 分别配置协议、地址、认证、超时和连接池；
- 不假设两个 MCP 使用相同传输协议；
- 云端部署后重新验证每项能力可用性；
- 按数据域建立风险等级；
- push2 系实时行情、历史 K 线和资金流属于高风险域；
- datacenter 财务、北向资金和宏观数据相对低风险；
- 主源失败后执行有限备用切换；
- 同源失败时必须披露“已知不可用”。

## 8. v2.3 分析能力后置

v2.3 不再强制将 Node.js Skill 作为新链路的一部分。

调整后的要求：

- 第一阶段使用 Python Analysis Engine；
- `AnalysisInput / AnalysisResult` 是稳定契约；
- 分析能力的部署形式可以后续替换；
- 是否使用独立 Skill 服务取决于复用性、性能和部署成本；
- `stock-wrapper` 不进入新运行时；
- 增加交易日历验证；
- 增加固定 fixture 的离线回归测试。

## 9. 分阶段实施

1. Runtime 和基础契约；
2. Query Graph；
3. MCP Gateway 和 Market Data Graph；
4. 评估并最小实现分析能力；
5. 跑通完整分析能力链路；
6. 增加 Portfolio、Strategy 和 Backtest；
7. 增加 Knowledge 和 Memory。

## 10. 被 V3 继承的内容

- Python 是新系统主编排层；
- MCP 只负责取数；
- Java 只负责用户数据；
- 分析能力不自行查询数据；
- Tool 结果统一为 Observation；
- ReAct 有预算和白名单；
- 数据质量显式披露；
- Checkpointer、Interrupt 和恢复；
- 确定性金融计算与 Agent 解耦。

## 11. 被 V3 修改的内容

- 单一 LangGraph Runtime 扩展为可替换 Runtime；
- 引入 LangGraph + Mem0 主版本；
- 增加 Letta 对比版本；
- Tool、Domain 和数据契约上移为两个 Runtime 的共享层；
- Skill 被进一步收紧为纯分析服务。
