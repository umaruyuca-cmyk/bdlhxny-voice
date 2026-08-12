# 阶段 0-1、Guardrail 与 Toolset 实施审计

> 实施批次：`SW31-FOUNDATION-20260809`
>
> 审计基线：HEAD `07cd351`，2026-08-09
>
> 本文是带时间点的迁移记录；文件数量、测试数量和工作区状态不得当作永久事实。

## 1. 阶段 0 基线

| 检查项 | 审计结果 |
|---|---|
| 工作区 | 100 个状态项：62 个修改、38 个未跟踪；全部视为用户现有改动并保留 |
| Python 源码 | `stockwise-analysis/src` 下 88 个 `.py` 文件 |
| Python 测试 | 24 个测试文件、159 个测试用例 |
| 基线验证 | `compileall` 通过；`pytest -q` 为 `159 passed in 1.67s` |
| Graph | Root Graph、Query Graph、Market Data Graph 已存在 |
| State | `RootState` 与 Checkpointer 已存在；新 Cognitive/Finance State 尚未接线 |
| Capability | `CapabilityRegistry` 已有 14 个统一只读能力 |
| Planner/Coverage | Requirement Planner、候选白名单、COMPLETE/PARTIAL/LIMITED 已存在 |
| Adapter | MCP、Java、Web、Python Analysis Adapter 已存在 |
| Memory/History | Mem0/NoOp Memory、Analysis History 已存在 |
| 领域边界 | 未跟踪工作区中已有初版 `domains/`、`cognitive/contracts.py`，尚无契约测试 |
| Guardrail | 现有校验散落于白名单、预算、coverage 等模块；无独立四时点接口包 |
| Toolset | 无基于 Capability Registry 的分组派生视图 |

## 2. 本批次范围

| 目标能力 | 开始状态 | 本批次动作 | 是否切换运行路径 |
|---|---|---|---|
| 通用 DomainRequest/Outcome | 初版、未测试 | 审查、补约束、增加契约测试 | 否 |
| Financial Domain Contracts | 初版、未测试 | 补数据真实性契约和继承测试 | 否 |
| CognitiveAction | 初版、未测试 | 补 Action Policy 契约测试 | 否 |
| GuardrailResult | 无 | 新增强类型结果契约 | 否 |
| 四时点 Guardrail | 无独立接口 | 新增 Plan/Action/Data-quality/Response Protocol 骨架 | 否 |
| Toolset 分组 | 无 | 从现有 CapabilitySpec 派生六个分组视图 | 否 |

明确不在本批次实施：Finance Runtime、Stock Research Graph、SuitabilityEngine、Cognitive Graph、Task/Scheduler、旧 Root Graph 切换。

## 3. 模块实施标记

本批次采用模块 Docstring 标记，不增加影响运行时的迁移开关：

| 标记 | 含义 |
|---|---|
| `SW31-P1-DOMAIN-CONTRACTS` | 阶段 1 通用/金融领域边界契约 |
| `SW31-P1-COGNITIVE-ACTION` | 阶段 1 CognitiveAction 契约 |
| `SW31-GUARDRAIL-SKELETON` | GuardrailResult 与四时点接口骨架，尚未接入 Graph |
| `SW31-TOOLSET-VIEW` | 基于 Capability Registry 的只读派生分组 |

## 4. 安全覆盖说明

- 本批次不改变旧 Root Graph 的默认执行路径。
- Guardrail 包仅建立契约和接口，不得声称四时点策略已经在运行时生效。
- Toolset 只引用统一 Capability 名称，不包含 MCP 服务名、原始 Tool 名或供应商路由参数。
- 所有现有外部金融与账户能力继续保持只读。

## 5. 完成条件

- 新增契约均能严格校验并无损序列化；
- Guardrail 的 `modify` 必须带替换对象，拒绝结果具有稳定 audit code；
- 四个 Guardrail Protocol 可由后续阶段分别实现，不互相合并；
- 六个 Toolset 覆盖全部 14 个默认 Capability，Capability Registry 仍为唯一能力真源；
- 全量既有测试与新增测试通过；
- `git diff --check` 通过。

## 6. 本批次实施结果

| 模块 | 标记 | 结果 |
|---|---|---|
| `stockwise_analysis/domains/contracts.py` | `SW31-P1-DOMAIN-CONTRACTS` | 增加严格边界基类、预算和身份字段约束 |
| `stockwise_analysis/domains/finance/contracts.py` | `SW31-P1-DOMAIN-CONTRACTS` | 增加 `FinancialDataMode`、mock/用户确认数据一致性校验 |
| `stockwise_analysis/domains/registry.py` | `SW31-P1-DOMAIN-CONTRACTS` | 保留最小领域注册表，未接入运行路径 |
| `stockwise_analysis/cognitive/contracts.py` | `SW31-P1-COGNITIVE-ACTION` | 九类认知行动、首批启用集合和载荷互斥校验 |
| `stockwise_analysis/guardrails/contracts.py` | `SW31-GUARDRAIL-SKELETON` | 新增泛型 `GuardrailResult`、四类决定和审计约束 |
| `stockwise_analysis/guardrails/interfaces.py` | `SW31-GUARDRAIL-SKELETON` | 新增四个相互独立的 Protocol；尚未实现业务策略 |
| `stockwise_analysis/tools/capabilities.py` | `SW31-TOOLSET-VIEW` | Capability 规格增加唯一 Toolset 归属声明 |
| `stockwise_analysis/tools/toolsets.py` | `SW31-TOOLSET-VIEW` | 新增六个业务分组的动态只读派生视图 |

新增测试：

- `tests/contracts/test_foundation_contracts.py`：11 项；
- `tests/guardrails/test_guardrail_contracts.py`：8 项；
- `tests/tools/test_toolsets.py`：6 项。

最终验证：

- `python -m compileall -q src tests`：通过；
- `pytest -q`：`184 passed in 1.66s`；
- `git diff --check`：通过，仅有工作区既有 LF/CRLF 提示；
- 当前默认运行路径：未切换；
- Guardrail 运行时状态：仅契约/接口骨架，未接入 Graph；
- Toolset 运行时状态：派生 Registry 可用，尚未替换现有 Planner 的候选集生成入口。
