# 31 号统一开发实施 Prompt — 可行性分析与修订建议

> 审查对象：[31-深层认知与个人金融业务模型-统一开发实施Prompt.md](../prompts/31-深层认知与个人金融业务模型-统一开发实施Prompt.md)
>
> 审查依据：
> - 当前代码提交 `374375d`（159 passed）
> - [26-StockWise金融随身管家-需求更新版.md](../prompts/26-StockWise金融随身管家-需求更新版.md)（v2.1 基线）
> - [30-深层认知与金融业务模型-审查回归文档.md](./30-深层认知与金融业务模型-审查回归文档.md)
>
> 审查目的：判断 31 号作为"开发执行稿"的可行性，指出阻塞问题，给出修订后的可执行版本。
>
> 版本：2026-08-09

---

## 0. 总体判断

**可行性评分：5 / 10（方向对，但顺序和范围有硬伤）**

31 号 Prompt 的**架构思想是对的**（契约先行 / 薄层切分 / 垂直验证 / 渐进迁移），这四条策略我完全认同。但它作为"开发执行稿"有三个阻塞级问题：

1. **实施顺序跳跃**——v2.1 阶段二（Planner-Executor-Guardrails）尚未完成，31 号直接跳到认知内核分层
2. **单轮工作量超标**——7 个阶段一次铺开，预估 4-6 周，不是一个开发轮次能完成的
3. **"薄适配层"并不薄**——声称用 Adapter 包装旧 Graph，实际要新建 3 个顶层目录（domains/cognitive/skills）+ 20+ 文件

**结论：方向采纳，但必须拆分执行——先补完 v2.1 阶段二，再做 31 号的阶段 1-4（契约+适配层），最后做阶段 5-7（认知内核+任务）。**

---

## 1. 阻塞问题（P0，必须解决才能开工）

### P0-1：实施顺序跳跃——v2.1 阶段二未完成就跳到认知分层

**现状证据**（代码提交 `374375d`）：

```
31号声称"已有能力"：
  ✓ CapabilityRegistry         (tools/capabilities.py 存在)
  ✓ CapabilityRequirementPlanner (tools/requirement_planner.py 存在)
  ✓ IntentRoute/direct_response (contracts/route.py 存在)
  ✓ thread_id/run_id 分离       (api/routes.py 存在)

31号未提及但缺失的 v2.1 阶段二能力（grep 零命中）：
  ✗ TaskPlan / TaskStep         (31号 §4.3 的 Planner 要用它)
  ✗ Executor                    (31号 §8 的 Finance Runtime 要复用它)
  ✗ 四时点 Guardrails            (31号 §14 假设它"已定义但未实现"——实际连定义都没有)
```

**问题**：31 号 §8.2 说"第一版可以复用当前 Root Graph 或其内部节点"，但当前 Root Graph 用的是 `dispatch_workflow + WorkflowPlan`（固定任务链），不是 `Planner + TaskPlan`（动态计划）。31 号的 Finance Runtime 适配层要包装的是"动态计划执行"，但底层还是"固定任务链"——**适配层包装的是一个尚未存在的执行模型。**

**影响**：阶段 2（Finance Runtime 薄适配层）会在"旧执行模型（dispatch_workflow）"和"新契约（FinancialDomainOutcome）"之间产生严重的阻抗失配。要么适配层做成假的（只是改个名字），要么被迫先重写执行模型——后者就是 v2.1 阶段二的工作。

**修订建议**：在 31 号阶段 0 之前，插入一个 **"阶段 -1：补完 v2.1 阶段二"**：

```text
阶段 -1（前置，~1周）：
  · 实现 TaskPlan / TaskStep（替代固定 WorkflowPlan）
  · 实现 Executor（替代 dispatch_workflow 的 next_pending 选任务）
  · 实现四时点 Guardrails（Plan/Action/Data-quality/Response）
  · 重规划机制（≤2 次）
  → 完成后，执行层从"固定任务链"升级为"动态计划执行"
  → 31 号的 Finance Runtime 适配层才有东西可包
```

### P0-2：单轮工作量超标——7 阶段 ≈ 4-6 周

31 号定义了 7 个阶段（阶段 0-7），每个都有独立的验收门槛。粗估工作量：

| 阶段 | 内容 | 预估工作量 |
|---|---|---|
| 阶段 0 | 基线审计 | 0.5 天 |
| 阶段 1 | 领域边界契约 | 2 天 |
| 阶段 2 | Finance Runtime 适配层 | 3-5 天 |
| 阶段 3 | 股票研究结果下沉 | 3-5 天 |
| 阶段 4 | SuitabilityEngine v0 | 3-5 天 |
| 阶段 5 | 最小认知内核 | 5-7 天 |
| 阶段 6 | CommunicationPlan + Verify | 3-5 天 |
| 阶段 7 | 最小持续任务 | 3-5 天 |
| **合计** | | **~4-6 周** |

**问题**：这不是一个"开发轮次"（一次 Prompt 执行）能完成的。即使是最有经验的开发者，7 个阶段串联也要一个月。对于 AI 辅助开发，每个阶段都需要独立的测试验证 + 回归，不可能一次跑完。

**修订建议**：拆成 **3 个独立交付轮次**：

```text
轮次 A（~1.5周）：契约 + 适配层（31号阶段 0-2）
  · 基线审计 + 领域契约 + Finance Runtime 薄适配层
  · 交付物：旧 Graph 能通过适配层产出 FinancialDomainOutcome
  · 验收：旧 API 兼容 + 新契约测试通过

轮次 B（~2周）：股票研究下沉 + 适配性（31号阶段 3-4）
  · StockResearchResult + SuitabilityEngine v0
  · 交付物：股票分析产出结构化结果 + 适配性判断
  · 验收："茅台适合我买吗"端到端场景

轮次 C（~2周）：认知内核 + 沟通（31号阶段 5-6）
  · Cognitive Graph + ActionPolicy + CommunicationPlan
  · 交付物：顶层是认知内核，金融是领域子调用
  · 验收：认知内核选择 INVOKE_DOMAIN → 金融执行 → 回复

轮次 D（后续）：持续任务（31号阶段 7）
  · Task/Scheduler/通知
```

### P0-3："薄适配层"并不薄

31 号 §8 声称"不要立即重写现有股票 Graph，先建立一个金融领域适配器"。但实际上：

- 新建 `domains/finance/` 目录（runtime.py + state.py + adapter.py + contracts.py）
- 新建 `domains/contracts.py` + `domains/registry.py`
- 新建 `skills/registry.py` + `skills/stock_research/`（spec + adapter + result_builder）
- 新建 `cognitive/` 目录（contracts + state + graph + nodes + action_policy）

**合计 20+ 新文件**。这不是"薄层"，是**在旧系统旁边搭了一套平行架构**。"薄"这个措辞会误导执行者低估工作量。

**修订建议**：把"薄适配层"的措辞改成"**隔离适配层（Isolation Adapter）**"——它的价值不是"薄"，是"隔离新旧系统，让旧 Graph 不感知新契约"。

---

## 2. 设计问题（P1，建议修改）

### P1-1：阶段 5（认知内核）和阶段 2（金融适配层）的依赖关系倒置

31 号的实施顺序是：阶段 2（金融适配层）→ ... → 阶段 5（认知内核）。

但认知内核的 `select_next_action` 要决定"是否 INVOKE_DOMAIN"——**如果认知内核在阶段 5 才建，那阶段 2-4 的金融适配层是谁在调它？** 阶段 2 说"复用当前 Root Graph"，但当前 Root Graph 没有"调用领域运行时"的概念。

**修订建议**：调整依赖顺序——先建领域契约（阶段 1），再建认知内核骨架（阶段 5 提前到阶段 2 之后），最后才做金融适配层（它要被认知内核调用）。

### P1-2：EvidenceFact/Finding 缺少持久化策略

31 号 §7.3-7.4 定义了 EvidenceFact 和 Finding，但没说它们存哪、怎么查。当前系统只有 Analysis History（runtime/history.py）。如果每次运行都重新构建 Evidence，跨会话的"上次的证据"就丢了。

**修订建议**：第一阶段明确 EvidenceFact/Finding 是**运行期内存对象**（随 Checkpointer 保存，不独立持久化）。跨会话证据召回由 Mem0 负责（已确认的稳定事实）。这个边界要写进文档。

### P1-3：SuitabilityEngine v0 的"确定性规则"缺数据支撑

31 号 §10.4 定义了 6 条适配性规则，但其中 3 条依赖**当前不存在的数据**：

| 规则 | 依赖的数据 | 当前有吗 |
|---|---|---|
| 单一标的/同行业超阈值 | 用户持仓（portfolio.*） | 🟡 Java adapter 有 mock，真实数据未接 |
| 近期高流动性目标冲突 | FinancialGoal（用户财务目标） | ❌ 完全没有 |
| 风险画像缺失 | user.get_risk_profile | 🟡 Java adapter 有 mock |

**修订建议**：SuitabilityEngine v0 的规则集应该按"当前数据可支撑的"收窄——先只做"缺持仓→INSUFFICIENT_INFORMATION"和"研究LIMITED→不可SUITABLE"这两条（不需要新数据源），其余规则标为"待数据接入后启用"。

---

## 3. 亮点（这些设计正确，保留）

| 亮点 | 来源 | 为什么对 |
|---|---|---|
| 契约先行 | §7 | 先定义 DomainRequest/Outcome，再写逻辑——保证接口稳定 |
| 垂直切片验收 | §24 | "股票研究+适配性"端到端，不是横向铺开所有模块 |
| 客观研究 vs 用户适配分离 | §5.3 | 这是 29 号最有价值的思想，31 号正确落地了 |
| Action Policy 校验 | §11.5 | LLM 提候选，Policy 校验——黑箱可控 |
| API 兼容 + 双路径切换 | §17 | 新旧并行，对照测试后才切——风险可控 |
| Response Verification | §12.3 | 回复前复核"推断是否写成事实"——直击幻觉 |
| 全程只读 | §5.5 | 第一阶段不下单——安全边界清晰 |
| 阶段独立可回滚 | §4.1 | 每阶段独立测试，不依赖后续阶段 |

---

## 4. 修订后的执行顺序（可直接替换 31 号 §6-§13）

```text
═══ 前置（v2.1 补完，~1周）═══════════════════════════
阶段 -1：Planner-Executor-Guardrails
  · TaskPlan / TaskStep 替代固定 WorkflowPlan
  · Executor 替代 dispatch_workflow
  · 四时点 Guardrails
  · 重规划机制
  → 执行层升级为"动态计划执行"

═══ 轮次 A（~1.5周）：契约 + 隔离边界 ═════════════════
阶段 0：基线审计（同 31 号 §6）
阶段 1：领域契约（同 31 号 §7，不变）
  · DomainRequest / DomainOutcome
  · FinancialDomainRequest / FinancialDomainOutcome
  · EvidenceFact / Finding
阶段 2：Finance Runtime 隔离适配层
  · 包装当前 Root Graph → FinancialDomainOutcome
  · 不新建认知内核（认知内核在轮次 C）
  · 驱动者：临时用 application.py 直接调（不经过认知内核）
  → 验收：旧 API 兼容 + 新契约产出合法

═══ 轮次 B（~2周）：股票研究 + 适配性 ═════════════════
阶段 3：StockResearchResult 下沉（同 31 号 §9）
阶段 4：SuitabilityEngine v0（收窄规则集）
  · 只做"缺持仓→INSUFFICIENT"和"研究LIMITED→不可SUITABLE"
  · 其余规则标"待数据接入"
  → 验收："茅台适合我买吗"端到端

═══ 轮次 C（~2周）：认知内核 ═══════════════════════════
阶段 5：最小 Cognitive Kernel
  · CognitiveState / CognitiveGraph
  · select_next_action（RESPOND/ASK_USER/INVOKE_DOMAIN）
  · Action Policy
  · 此时认知内核调用轮次 A/B 已建好的 Finance Runtime
阶段 6：CommunicationPlan + Response Verification
  → 验收：顶层是认知内核 → INVOKE_DOMAIN → 金融执行 → 回复

═══ 轮次 D（后续）：持续任务 ═══════════════════════════
阶段 7：FinancialTask / Scheduler（同 31 号 §13）
```

---

## 5. 修订后的目录结构建议

31 号 §20 的目录结构（domains/cognitive/skills 三个新顶层包）方向对，但**一次性建三个空目录会导致大量 .gitkeep 和空 __init__.py**。建议按轮次渐进创建：

```text
轮次 A 后：
  src/stockwise_analysis/
  ├── domains/
  │   ├── contracts.py          # DomainRequest/Outcome
  │   ├── registry.py           # 领域注册表
  │   └── finance/
  │       ├── contracts.py      # 金融契约
  │       └── adapter.py        # 隔离适配层
  ├── tools/                    # 已有（capabilities/adapter）
  └── domain/                   # 已有（确定性计算）

轮次 B 后：
  ├── domains/finance/
  │   ├── suitability.py        # 新增
  │   └── policies/             # 新增
  ├── skills/
  │   ├── registry.py           # 新增
  │   └── stock_research/       # 新增
  └── ...

轮次 C 后：
  ├── cognitive/                # 新增整个包
  │   ├── contracts.py
  │   ├── state.py
  │   ├── graph.py
  │   ├── nodes.py
  │   ├── action_policy.py
  │   └── communication.py
  └── ...
```

---

## 6. 待决策项（需拍板后才能进入轮次 A）

1. **是否同意"先补完 v2.1 阶段二，再做 31 号"？** （本报告的核心建议）
2. **EvidenceFact/Finding 第一阶段是否只做内存对象（不独立持久化）？**
3. **SuitabilityEngine v0 规则集是否收窄到"当前数据可支撑的 2 条"？**
4. **轮次 A 的 Finance Runtime 适配层，驱动者是 application.py 直调还是建一个临时 Cognitive Graph 骨架？**（本报告建议前者，更简单）
5. **31 号 §1 的文档优先级里，31 号高于 28/29 号——是否确认？**（这意味着 31 号与 28/29 冲突时以 31 号为准）

---

## 7. 一句话总结

> **31 号 Prompt 架构方向正确（分层/契约先行/垂直切片），但实施顺序有硬伤：它在 v2.1 阶段二（Planner-Executor-Guardrails）未完成的基础上直接跳到认知内核分层，且 7 阶段 4-6 周的工作量不是一个开发轮次能完成的。建议：先补完 v2.1 阶段二（~1 周），再把 31 号拆成 3 个独立交付轮次（契约+适配层 → 股票研究+适配性 → 认知内核），每轮次独立验收后再生效。**
