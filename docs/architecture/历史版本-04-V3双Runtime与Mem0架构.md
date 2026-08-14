# StockWise 历史版本档案 04：V3 双 Runtime 与 Mem0 架构

> 版本性质：现有股票分析架构基线，产品目标已继续向个人金融架构演进  
> 形成日期：2026-08-06  
> 双 Runtime 初稿提交：`03f551a`  
> v3.1 定稿提交：`7aba79b`

## 1. 版本定位

V3 在 V2.x 的数据/分析分离基础上，确立“双 Runtime 平行对比 + 工具和计算共享 + Mem0 记忆层”的架构。

主版本与对比版本分别为：

```text
生产主版本：LangGraph + Mem0
对比研究版：Letta / MemGPT
共享层：ToolRegistry、MCP Adapter、数据契约、Domain Engine
```

## 2. 产品需求

产品能力继续覆盖：

- 标的和市场数据查询；
- 技术面、基本面、估值和新闻研究；
- 用户持仓和账户影响；
- 策略与回测；
- 研究结果与用户偏好沉淀。

真实交易、券商执行和账户修改仍不在范围内。

## 3. 核心架构决策

- LangGraph + Mem0 优先实现；
- Letta 在主版本稳定后再开发；
- 两个 Runtime 通过共同协议接收请求并输出结果；
- 两个 Runtime 共享同一 ToolRegistry；
- 两个 Runtime 共享相同确定性 Domain Engine；
- Tool、数据和计算不依赖某个 Agent 框架；
- API 层不感知内部 Runtime；
- 通过黑箱边界对比两种 Agent 范式。

## 4. LangGraph 主版本

负责：

- Root Graph 和研究子图；
- 可控状态流转；
- 有界 ReAct；
- 预算和工具白名单；
- Checkpoint、Interrupt 和恢复；
- 结构化事件流；
- ContextBuilder；
- Mem0 首尾读写。

## 5. Letta 对比版本

目标不是替代主版本，而是在同样输入、工具和确定性计算条件下，对比更自主的 Agent 行为。

要求：

- 不复制 Tool 实现；
- 不复制 Domain 计算；
- 不改变外部 API 契约；
- 先通过最小 spike 验证相同 MCP 工具可在两端运行；
- 主版本稳定前不投入完整实现。

## 6. Mem0 记忆需求

- Mem0 只服务 LangGraph 主版本；
- 记忆在入口加载、出口持久化；
- 不在每个 Graph 节点中任意读写；
- 只保存经筛选的用户偏好和长期有价值事实；
- 不将 Checkpointer 当长期记忆；
- 不将所有中间 Observation 写入长期记忆；
- ContextBuilder 统一构建模型所需上下文。

## 7. 共享层要求

### 7.1 ToolRegistry

- 两个 Runtime 通过同一注册表获取工具；
- 工具实现不依赖 LangGraph 或 Letta；
- 工具有稳定 Schema、权限、预算和审计信息。

### 7.2 Domain Engine

- 不导入 LangGraph、LangChain、Letta、MCP 或 Mem0；
- 技术指标、风险、回测等计算保持确定性；
- 固定输入必须产生固定结果；
- 可以被两个 Runtime 等价调用。

### 7.3 数据接入

- MCP 提供外部市场数据；
- Java API 提供用户和账户数据；
- Adapter 负责转换内部契约；
- Observation Normalizer 负责统一外部结果。

## 8. Skill 纯分析要求

现有 Skill 必须完成服务化或边界重构：

- 切断 Data 层和 Analysis 层的反向依赖；
- 移除 Skill 内部 HTTP 取数；
- 提供纯计算入口；
- 输入 `AnalysisInput`；
- 输出 `AnalysisResult`；
- 断网条件下使用固定输入仍可运行；
- 不承担 Agent 编排和用户身份管理。

## 9. MCP 与数据质量

- cn-financial 作为主要 A 股数据源；
- akshare-one 用于补充新闻、内部交易和部分备用来源；
- SSE 与 Streamable HTTP 分别配置；
- 记录数据来源、时间和状态；
- 显式表达缺失、冲突和过期；
- 统一输出 `COMPLETE / PARTIAL / LIMITED`；
- 主备同源失效时启动逃生阀；
- 禁止调用旧 Wrapper 或模型补造数据。

## 10. 运行预算

预算按分析类型分档：

- `market_snapshot`：确定性快路径；
- `technical`：有限数据和计算步骤；
- `fundamental`：允许更多财务数据调用；
- `valuation`：以确定性估值计算为主；
- `portfolio_impact`：允许读取授权用户数据；
- `comprehensive`：完整有界 ReAct。

超出预算时停止执行，返回已完成部分和明确限制。

## 11. 实施顺序

1. Phase 0：LangGraph、Mem0、ToolRegistry 和 MCP 骨架；
2. Phase 0.5：Skill 纯分析服务化；
3. Phase 1：跑通 LangGraph 完整研究流程；
4. Phase 2：补全技术指标、风险和回测；
5. Phase 3：实现 Letta 对比版；
6. Phase 4：形成对比报告和架构沉淀。

## 12. 后续演进

金融随身管家 v2.1 将当前实现重点调整为 LangGraph + Mem0 生产闭环，Letta 继续延后。

深层认知与个人金融目标架构进一步将股票分析从顶层 Root Graph 下沉为 Finance Runtime 内的 Stock Research Skill，但继续复用 V3 的 Capability、Adapter、Observation 和 Domain Engine。
