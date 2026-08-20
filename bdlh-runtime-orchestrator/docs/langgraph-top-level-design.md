# BDLH Agent Runtime LangGraph 顶层流程设计

> **状态：`RETIRED`（历史设计）**  
> **生效说明：2026-08-16 起，默认产品路径为 Cognitive Orchestrator（`cognitive_finance`）→ Domain Dispatcher → Finance Runtime。**  
> 本文描述的 Root Graph / Query Graph / Market Data Graph 已从代码删除，仅作历史对照，不指导开发。

当前实现请以：

- [统一生产架构](../../docs/architecture/00-BDLH-Agent-Runtime统一生产架构.md) §3
- `src/bdlh_runtime/cognitive/`
- `src/bdlh_runtime/domains/finance/`
- `src/bdlh_runtime/api/routes.py`

为准。

## 历史目标（已退役）

早期阶段曾规划可恢复、可追踪的 Root Graph 框架，通过 Query / Market Data 子图与 WorkflowPlan 动态调度完成股票分析。该路径已被 Cognitive + Finance Domain Skill 取代，不再装配、不再接流量、不得恢复。
