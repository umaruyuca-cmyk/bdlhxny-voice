# 31 号统一开发实施 Prompt — 可行性分析与修订建议（修订版）

> 审查对象：[31-深层认知与个人金融业务模型-统一开发实施Prompt.md](../prompts/31-深层认知与个人金融业务模型-统一开发实施Prompt.md)
>
> 替代关系：本文是 [32-31号开发实施Prompt-可行性分析与修订建议.md](./32-31号开发实施Prompt-可行性分析与修订建议.md) 的修订版。评审稿 32 中存在事实性错误（见 §1），**建议以本文为准**；是否将 32 号标注作废见 §6 待决策项 1。
>
> 审查依据（**以实际工作区为准，而非历史提交**）：
> - 当前工作区：`git status` 62 个文件、2163 行未提交改动（HEAD `07cd351`）
> - 当前测试：`.venv/Scripts/python.exe -m pytest -q` → **159 passed**
> - [26-StockWise金融随身管家-需求更新版.md](../prompts/26-StockWise金融随身管家-需求更新版.md)（v2.1 基线）
> - [28-深层认知模型-架构与处理逻辑.md](../architecture/28-深层认知模型-架构与处理逻辑.md)、[29-个人金融业务模型-架构与处理逻辑.md](../architecture/29-个人金融业务模型-架构与处理逻辑.md)
> - [30-深层认知与金融业务模型-审查回归文档.md](./30-深层认知与金融业务模型-审查回归文档.md)
>
> 审查目的：独立核实 31 号作为"开发执行稿"的可行性，修正评审稿 32 的事实错误，给出可直接并入 31 号的修订建议。
>
> 版本：2026-08-09（修订版）

---

## 0. 总体判断

**可行性评分：7 / 10（修订后可达 8 / 10）——方向正确、阶段自洽、断言经核实全部成立；剩余风险集中在阶段 2/3/4 的实现细节，不构成架构级阻塞。**

31 号的架构思想（契约先行 / 薄层切分 / 垂直验证 / 渐进迁移）成立；对当前代码"已有/缺失"能力的描述经逐项核对**全部准确**；对 30 号评审稿的三处修正也全部核实成立（§2）。

评审稿 32 判定为"5/10，三条 P0 阻塞"，其中**两条基于对 31 号原文的误读、一条被夸大**（§1）。真正需要补的不是"阶段 -1 补完 v2.1 阶段二"这类架构前置，而是阶段 2/3/4 的**工程实现约定**（§4 的六处修订建议）。

**结论：31 号可以按其自身阶段序执行，无需等待其他架构前置。建议按"轮次切分"组织人力节奏（§5），并在开工前落实 §4 修订。**

---

## 1. 评审稿 32 的事实错误修正（本版相对 32 的核心差异）

评审稿 32（下文称 32 号）已提交进 `docs/reviews/`（HEAD `07cd351`），但以下判断与事实不符，若按其执行会走错方向：

### 1.1 误引 31 号 §8.2 原文（影响：P0-1 前提不成立）

32 号 §1（P0-1）称：

> "31 号 §8.2 说'第一版可以复用当前 Root Graph 或其内部节点'……适配层包装的是一个尚未存在的执行模型。"

31 号 §8.2 原文（31 号第 582 行）是：

> "第一版**禁止**调用当前完整 Root Graph。……必须使用 `LegacyStockAnalysisAdapter` 包装纯领域处理链，或提取最小 Stock Research 子图。"

被包装的链 `resolve_instrument → market_data_graph → assemble_analysis → run_analysis → build_stock_research_result` **全部是当前已存在、可单测的节点**（`runtimes/langgraph/nodes/nodes.py`、`graphs/market_data_graph.py`）。"适配层包装的是一个尚未存在的执行模型"这一结论不成立。

### 1.2 "Guardrails 连定义都没有"是错的（影响：P0-1 的第三条证据）

32 号 §1 称四时点 Guardrails "实际连定义都没有"。事实：

- 26 号（v2.1）§4.5（26 号第 211-248 行）**完整定义了** `GuardrailResult` 与四时点（Plan / Action / Data-quality / Response）的职责与顺序；
- 31 号 §1 的表述（31 号第 57 行）"v2.1 需求已经定义四时点 Guardrails，当前问题是代码尚未完整实现"**准确**；
- 代码侧确实没有独立 `guardrails/` 策略层（校验散落在 `validate_analysis`、白名单、预算、coverage 中）——这与 31 号的"缺失"描述一致。

### 1.3 "TaskPlan / TaskStep 缺失"被夸大，且章节引用错误

- 32 号称"31 号 §4.3 的 Planner 要用它"——31 号 §4.3 是"本次禁止扩展"清单，31 号**从不要求** TaskPlan/TaskStep；
- 代码已有 `WorkflowPlan` + `TaskSpec` + `next_pending()` + `dispatch_workflow`（`contracts/workflow.py`、`nodes.py:329-348`），本质是一个动态依赖计划的 mini Planner-Executor。缺的只是"LLM 版动态规划 + 独立 Executor 抽象"这一形态，而 31 号并未把它列为前置。

### 1.4 "单轮工作量超标"与 31 号自带的停止规则矛盾

32 号 P0-2 称"7 个阶段一次铺开，4-6 周不是一个开发轮次"。但 31 号 §0（第 31-37 行）已强制：

> "每个开发任务默认只允许执行一个阶段……其他阶段完成代码、测试、迁移矩阵和交付报告后必须停止。"

且 §4.1（第 166 行）明确"以上是本开发计划全部阶段的总交付范围，不表示一个开发任务必须一次完成"。**"阶段拆轮次"本身正确（见 §5），但这不是 31 号的缺陷，是 31 号已经内置的约束。**

### 1.5 可吸收的合理内核

32 号并非全错，其可取之处保留在 §5：

- 拆轮次组织人力节奏（但保持 31 号阶段序，见 §5 说明）；
- "隔离适配层（Isolation Adapter）"的措辞比"薄适配层"准确——31 号 §8 确实是隔离而非"薄"，该命名可并入 31 号；
- EvidenceFact/Finding 第一阶段落地为"运行期内存对象、随 Checkpointer 保存、跨会话召回交 Mem0"——31 号 §7.4 未明确，建议并入（见修订 2 旁注）。

---

## 2. 31 号 Prompt 断言核实（基于当前工作区）

### 2.1 "已有能力"清单（31 号 §2）——逐项核实成立

| 31 号断言 | 核实结果 |
|---|---|
| FastAPI + LangGraph | ✅ `main.py`、`runtimes/langgraph/graphs/root_graph.py` |
| `RootState` 和 Checkpointer | ✅ `graphs/state.py` + `runtime/checkpointers.py`（生产可替换后端） |
| direct_response / single_capability / agent_loop | ✅ `nodes.py:143-176` `route_execution` |
| Query Graph 和 Market Data Graph | ✅ 均存在且已编译（含 ReAct 子图与 mock 双模式） |
| `CapabilityRegistry` | ✅ `tools/capabilities.py`，注册时强制 `read_only`（第 61-63 行） |
| `CapabilityRequirementPlanner` | ✅ `tools/requirement_planner.py`，确定性策略 + 每轮候选 |
| 每轮 capability_candidates | ✅ `RootState.capability_candidates` + `candidate_manifest` |
| 工具执行前白名单检查 | ✅ `market_data_graph.py:343-361`（`CAPABILITY_NOT_ALLOWED`）+ `agents/research_agent.py` 白名单 |
| 预算控制 | ✅ `runtime/budgets.py` + 执行节点 `_budget_limit` |
| Observation / Normalizer / Provenance / DataQuality | ✅ `contracts/observation.py`、`observations/normalizer.py`、`provenance.py`、`quality.py` |
| COMPLETE / PARTIAL / LIMITED | ✅ `tools/coverage.py` + `market_data_graph.py:113-131` |
| MCP Gateway、Java Data Adapter、Web Search Adapter | ✅ 三适配器均存在，Java/Web 内置 mock 降级 |
| Python Analysis Capability | ✅ `tools/analysis_capability.py` → `domain/analysis_engine.py` |
| Mem0 / NoOp Memory | ✅ `memory/mem0/mem0_store.py`、`memory/noop.py` |
| Analysis History | ✅ `runtime/history.py` + `persist_history` 节点 |
| 多轮 thread_id 与单次 run_id 分离 | ✅ `api/routes.py:56-64`（thread_id 缺省等于 run_id），Checkpointer 内按用户隔离（第 171-174 行） |

### 2.2 "主要缺失"清单（31 号 §2）——成立

`src/stockwise_analysis/` 下不存在 `domains/`、`cognitive/`、`skills/` 三个新包；无 SuitabilityEngine、无 InputEvent/主动事件入口、无 CommunicationPlan/ResponseVerifier、无 Task/Commitment 持久化、无完整四时点 Guardrails 策略层。均与 31 号描述一致。

### 2.3 对 30 号评审稿的三处修正（31 号 §1）——核实成立

| 31 号修正 | 核实结果 |
|---|---|
| 代码基线不能只看 `42b0722`，以工作区为准 | ✅ 工作区有 62 文件/2163 行未提交改动 |
| 28 号 `NextAction` 是 9 种，不是 7 种 | ✅ 28 号第 243-253 行列出 9 种（含 `RETRIEVE_MEMORY`、`UPDATE_TASK`）；30 号第 71 行只列 7 种 |
| v2.1 已定义四时点 Guardrails，只是代码未实现 | ✅ 26 号 §4.5（见 §1.2） |

---

## 3. 分阶段可行性评估

| 阶段 | 内容 | 可行性 | 关键条件 / 风险 |
|---|---|---|---|
| 0-1 | 审计 + 纯契约 | **高** | 与现有 Pydantic 契约风格一致；无前置依赖 |
| 2 | Finance Runtime 适配层 | 中-高 | **必须先定子图复用策略**（修订 1） |
| 3 | StockResearchResult 下沉 | 中 | 需字段来源映射表（修订 2）；"下沉"实为"重组" |
| 4 | SuitabilityEngine v0 | 中 | 需测试夹具 + 验收分支约定（修订 3） |
| 5 | 最小认知内核 | 中-高 | 新包独立，与旧装配并存即可（独立 Application 装配） |
| 6 | CommunicationPlan + Verify | 中-高 | 依赖阶段 5 的 compose/verify 链 |
| 7 | 持续任务 | 低（严格推迟） | 需 TaskRepository + Scheduler + DB，31 号自列为第二阶段交付 |

**总判断**：没有"不补完 XX 就不能开工"的架构阻塞。阶段 0-1 可直接开工；阶段 2 开工前落实修订 1；阶段 3-4 前落实修订 2-3。

---

## 4. 对 31 号 Prompt 的修订建议（可直接并入 31 号原文）

### 修订 1（§8.2）：明确编译子图复用方式——三选一，开工前定

31 号 §8.2 要求"提取最小 Stock Research 子图"或"复用已编译子图"，但当前 `build_market_data_graph` 是 `RootState` Schema 的编译子图，与新 `CognitiveState` / `FinancialBusinessState` **Schema 不同，直接内嵌会通道不兼容**。建议在阶段 2 的审计（§6）中验证并选择其一，写入迁移矩阵：

```text
方案 A：Finance Runtime 节点内用 graph.invoke(投影后的 FinancialBusinessState) 调编译子图
        —— 最省事，但需处理"子图入口快照覆盖"风险（与 31 号 §8.2 禁止嵌套调用的动机一致）；
方案 B：重编译一份以 FinancialBusinessState 为 Schema 的独立 Stock Research 子图
        —— 最干净，工作量为"复制拓扑 + 改 State 类型"，推荐；
方案 C：按节点链手工调用（resolve → market_data → assemble → run）
        —— 无子图边界，但丢失 ReAct 循环封装。
```

无论选哪种，都必须满足 §8.4 验收："MCP 调用数量与预算不增加"。

### 修订 2（§9）：补 StockResearchResult 字段来源映射表

31 号 §9.2 要求 11 个 section，但现有 `AnalysisResult`（`contracts/analysis.py:45-59`）只有通用形状 `facts/calculated_indicators/signals/risk_flags/conclusions`。好消息：`AnalysisInput` 已携带 `financial_data / valuation_data / industry_context / money_flow_data / news_context / portfolio_context` 全字段，`result_builder` 可重组。建议 §9 增加强制交付物：

```text
StockResearchResult 字段 → 数据来源映射表
  instrument         ← AnalysisInput.instrument
  market_snapshot    ← realtime_quote（含 source_time）
  fundamentals       ← financial_data
  valuation          ← valuation_data
  technicals         ← historical_prices + calculated_indicators
  money_flow         ← money_flow_data
  industry_context   ← industry_context
  events/news        ← news_context（MCP 新闻 + Web Search 合并列表）
  scenarios/risks    ← signals / risk_flags（确定性派生）
  evidence           ← observations[].provenance + data_quality
  coverage/confidence/limitations ← data_quality + coverage
```

旁注：按 32 号可吸收项，建议明确 EvidenceFact/Finding 第一阶段是**运行期内存对象**（随 Checkpointer 保存，不独立持久化），跨会话召回由 Mem0 负责——写进 §7.4。

### 修订 3（§10）：Suitability 测试夹具与验收分支约定

开发环境 Java 适配器 mock 返回空持仓（`nodes.py:407-423`），真实 Java 未接。§10.5 场景 1（行业过度集中）因此无法在默认环境触发。建议 §10 增加：

```text
· 阶段 4 必须提供"注入持仓"的测试夹具（构造 FinancialSnapshot 直接注入 SuitabilityEngine）；
· 开发环境空持仓时，场景 1/3/4 明确落入 INSUFFICIENT_INFORMATION 分支验收，
  不要求输出 CONDITIONALLY_SUITABLE / CURRENTLY_NOT_SUITABLE；
· 规则 2/3/4（依赖持仓/风险画像/流动性的）标记为"真实数据接入后启用"，
  与"缺持仓→INSUFFICIENT"、"LIMITED→不可 SUITABLE"两条无数据依赖的规则区分。
```

### 修订 4（§17.2）：过渡期默认路径的 Guardrails 说明

§14 的四时点 Guardrails 在新路径（Cognitive/Finance）上落地；§17.2 过渡期默认仍走旧 Root Graph，而旧路径没有独立 Guardrails 层。两者执行时会被视为矛盾。建议补一句：

> "切换前，默认路径（旧 Root Graph）不强制具备新四时点 Guardrails；新路径在受控配置下全量具备。Guardrails 覆盖收敛由切换计划统一完成，不与 §17.2 的双路径并行原则冲突。"

### 修订 5（§7.2）：澄清"认知行动 vs 工具动作"分层

31 号 §7.2 说"禁止继续复用旧 `AgentAction` 表达认知层动作"，但旧 ReAct 层 `research_agent.choose_next_action` 返回的 `AgentAction` 是**工具动作**（同一层、不同用途）。建议明确：

> "`CognitiveAction` 是认知层的行动模型；旧 `AgentAction` 是 ReAct 数据获取层的工具动作模型，两者分属不同层，本 Prompt 不要求删除或改名旧 `AgentAction`，仅要求认知层不得复用它。"

### 修订 6（§15）：目录命名定稿 + "51 个工具"标注

- §15 的 `domain/` vs `domains/` 单复数已在 Prompt 中留了 `domain_runtime/` 选项，但要求"阶段 0 决定、不得并存"——建议改为**硬性默认**：采用 `domains/`（新层）+ 保留 `domain/`（确定性计算层），并明确二者边界注释；`domain_runtime/` 仅作为团队不认可单复数时的备选，避免每个开发者各自裁决。
- §15 的"51 个原始 MCP Tool"在仓库内无出处（应为外部 MCP 服务器工具清单），建议标注"以实际 MCP 工具清单数量为准"，避免文档数字与运行时漂移。

---

## 5. 执行顺序建议

**保持 31 号阶段序（契约 → 适配 → 研究下沉 → 适配性 → 认知 → 沟通 → 任务），按轮次组织人力节奏。** 不采用 32 号的"阶段 -1 补完 v2.1 阶段二"前置——那是对旧 Root Graph 的改造，正是 31 号 §1 明确排除的顺序（"不采用先继续做大旧 Root Graph，再整体拆分"）。

```text
轮次 A（阶段 0-1）：基线审计 + 领域契约
  · 交付：契约 + 迁移矩阵（契约先行，无业务逻辑改动）
  · 同时拍板：修订 1 的子图方案、修订 6 的目录命名

轮次 B（阶段 2）：Finance Runtime 隔离适配层
  · 交付：旧节点链可产出合法 FinancialDomainOutcome
  · 验收：旧 API 兼容 + MCP 调用/预算不增加

轮次 C（阶段 3-4）：StockResearchResult + SuitabilityEngine v0
  · 交付："茅台适合我买吗"端到端（含注入持仓夹具）
  · 验收：§10.5 场景 1-6 + LIMITED 不得 SUITABLE

轮次 D（阶段 5-6）：最小认知内核 + CommunicationPlan/Verify
  · 交付：认知内核 → INVOKE_DOMAIN → 金融执行 → 复核回复
  · 验收：§11.6 + §12.4 + §24 总门槛

轮次 E（第二阶段）：阶段 7 持续任务（FinancialTask/Scheduler）
  · 前置：TaskRepository、取消接口、去重键、唤醒条件、恢复测试
```

## 6. 待决策项（需拍板后才能开工）

1. **评审稿 32 的处理**：保留作历史但顶部加"已被 33 替代"作废声明，还是直接修订 32 号正文？（建议前者：保留审计轨迹）
2. **修订 1 的子图复用方案**：A（节点内 invoke）/ B（重编译独立子图，推荐）/ C（节点链直调）？
3. **修订 3 的 Suitability 验收分支**：真实 Java 接入前，是否接受"空持仓 → INSUFFICIENT_INFORMATION"作为开发环境验收路径？
4. **修订 6 的目录命名**：默认 `domains/` 单复数并存，还是统一 `domain_runtime/`？
5. **31 号 §1 文档优先级（31 > 28/29 > 26 > 30）**：是否确认？若确认，31 号与 28/29 冲突时以 31 号为准。

## 7. 一句话总结

> **31 号 Prompt 方向正确、阶段自洽、对代码事实的描述经工作区核实全部准确，可按自身阶段序直接执行（7/10，落实修订 1-6 后 8/10）。评审稿 32 的三条 P0 阻塞中两条是误读、一条被夸大；真正要补的是阶段 2/3/4 的工程约定（子图复用方式、StockResearchResult 字段映射、Suitability 测试夹具），而非架构级前置。**
