# ADR-016：固定复合 Deep Research Tool

> 状态：APPROVED（开发阶段已裁定；默认流量仍 Feature Flag 关闭，生产切流走 M5）
> 批准人：项目 owner（2026-08-15 裁定 §17）
> 日期：2026-08-13
> 修订：2026-08-15（owner 裁定公开 ID、无兼容期、预算/SLO/百炼默认区间、策略直接生效、DB 登记）
> 依赖：[ADR-009](./ADR-009-Runtime-Domain-Skill定位与命名.md)、[ADR-012](./ADR-012-多Skill与多Agent演进门槛.md)、[ADR-014](./ADR-014-系统截断与用户截断Pause-Resume与会话入口路由.md)、[ADR-015](./ADR-015-Context组装服务与压缩策略.md)
> 影响：[00-BDLH-Agent-Runtime统一生产架构.md](./00-BDLH-Agent-Runtime统一生产架构.md) §5、§10、§13、§15、§18；[00-BDLH-Agent-Runtime生产开发实施Prompt.md](../prompts/00-BDLH-Agent-Runtime生产开发实施Prompt.md) §6.5；`bdlh-runtime-orchestrator/src/bdlh_runtime/tools/`、`bdlh-runtime-orchestrator/src/bdlh_runtime/runtime/`、`bdlh-web-search-adapter/`
> 参考实现：[langchain-ai/open_deep_research](https://github.com/langchain-ai/open_deep_research)，版本 `0.0.16`，提交 `1b7d2e80db9faa586165c60e09096dbbfd483a64`，MIT License

## 1. 决策目标

将 Deep Research 建模为 BDLH Runtime 登记的一个固定、只读、复合 Capability Tool
（公开 ID 默认 `research.deep_search`），供获得授权的 Agent 按策略调用。该 Tool 内部采用
经 BDLH 适配的 `open_deep_research` 工作流形态，完成研究任务整理、研究子题拆分、并行研究、
多轮搜索、缺口判断、压缩和结构化研究资料装配。

本 ADR 冻结以下核心判断：

1. Deep Research 是固定 Tool，不是 Skill、Domain、客户入口、独立 Agent 服务，也不是替换
   全部联网的「唯一底层搜索引擎」；
2. 调用方 Agent 可以不经过 Skill，直接通过 Capability Gateway 调用该 Tool；Skill 最多将
   其列为 optional 依赖以控制菜单资格；
3. `open_deep_research` 是研究编排逻辑，不是 Search Provider；
4. 当前 `research.web_search` 继续通过现有 `bdlh-web-search-adapter + SearXNG`
   提供普通查询；Deep Research 内部使用私有原子搜索端口，并固定接入百炼联网搜索 MCP；
5. 百炼 MCP 只能是 `AtomicSearchPort` 背后的受控 Provider，不能作为可由模型动态发现或直接
   调用的 MCP Tool；
6. 上游工作流只能在替换模型、工具、状态、预算、错误与输出边界后接入；
7. 最终输出是供调用 Agent 消费的结构化 `ResearchBundle`，不是直接面向客户的报告；
8. 职责分三层，不得混用：
   - **调用策略**（进 Deep 之前，BDLH Policy，见 §8.3）；
   - **内部编排**（Brief → Supervisor → 并行 Researcher → 压缩，参考官方）；
   - **确定性收口**（`assemble_research_bundle`，**由 BDLH 定义**，非官方 final_report）。

本 ADR 已由 owner **APPROVED（开发阶段）**：允许按 §14 做隔离实现与评测接线；
**不得**在 Feature Flag 关闭时改变默认生产搜索语义。生产灰度仍属 M5。

## 2. 背景与现状

当前普通 Web Search 链路为：

```text
Agent / Finance Planner
→ research.web_search
→ Python HttpWebSearchAdapter
→ bdlh-web-search-adapter
→ SearXNG
→ baidu / 360search
→ 标准化 SearchResult / Observation
```

现有链路已经具备鉴权、限流、缓存、熔断、结构化错误、基础清洗、Observation 与降级语义，
但研究能力较弱：

- 查询主要由固定模板生成；
- 一次调用只做一轮搜索；
- 不会根据已有结果识别信息缺口并补搜；
- 不会把复杂研究问题拆为并行子题；
- 结果主要是浅层 snippet；
- 缺少跨搜索批次的研究压缩和结构化综合。

`open_deep_research` 提供了适合借鉴的 LangGraph 工作流：Supervisor 拆题并调度并行
Researcher，Researcher 在搜索、阅读、判断缺口和补搜之间迭代，完成后压缩研究材料，最后
综合输出。但其官方实现默认自行创建模型、Tavily/原生 Search/MCP 工具，并以消息和自由文本
报告为主要状态与输出，不能原样接入 BDLH。

## 3. 形态裁定

### 3.1 它是什么

Deep Research 在 BDLH 中是：

```text
Capability: research.deep_search（提议名称，批准时冻结）
Executor: DeepResearchToolExecutor
Internal orchestration: adapted open_deep_research LangGraph
Internal dependency: AtomicSearchPort
Output: Observation<ResearchBundle>
```

Capability Registry 中的 `domain="research"` 只表示能力分类，不等于注册一个
`research` Domain Runtime。

### 3.2 它不是什么

本 Tool：

- 不创建 `SkillManifest`；
- 不创建 `DomainDescriptor`；
- 不经 Domain Dispatcher 路由；
- 不直接接收客户聊天请求；
- 不拥有客户会话或最终表达职责；
- 不直接向用户追问；
- 不作为独立进程或独立信任域 Agent；
- 不允许调用方绕过 Capability Gateway 直接调用执行器；
- 不允许内部递归调用自己的公开 Capability ID。

未来若要把 Deep Research 升级为面向用户的业务 Skill，必须另行提交 ADR，不能以本 ADR
自动获得授权。

## 4. 阶段归属

### 4.1 不新增 M 编号

统一生产架构已经冻结 M0–M6，禁止在其中插入新编号；M7 只用于插件契约验证。本能力不是
Skill 或 Domain 插件，因此**不属于 M7**，也不新增 M8。

### 4.2 分阶段挂靠

本能力按职责挂靠既有阶段：

| 工作内容 | 阶段归属 | 原因 |
|---|---|---|
| 请求/结果契约、原子 Search 拆分、Deep Research 子图、压缩、证据装配、隔离评测 | **M2 扩展切片** | 属于公开资料研究和证据生产能力升级 |
| Agent 工具候选、调用决策、Toolset/授权求交、四时点 Guardrail 与 Communication 消费 | **M4 接线切片** | 属于 Cognitive Graph 如何选择和消费 Tool |
| 影子流量、灰度比例、SLO、Feature Flag、回滚与旧路径退出 | **M5 发布切片** | 属于默认流量切换和生产放行 |
| 长任务持久化、Pause/Resume、Cancel、多副本恢复 | **M0 门禁 + ADR-014** | 属于生产恢复能力，不另造状态系统 |

一次开发任务仍只能处理一个切片：

- 做 M2 扩展时不得顺手修改 Cognitive 默认工具选择或切流；
- 做 M4 接线时不得重写研究执行器；
- 做 M5 灰度时不得继续改变核心输出语义。

当前仓库的 M2 Builder 已达到 `DEVELOPMENT_COMPLETE / RELEASE_BLOCKED`。本 ADR 的 M2 扩展
是独立的能力增强切片，不回退或作废既有 M2 交付，也不改变 M2 原退出条件；它必须有自己的
验收和回滚记录。

## 5. 上游参考边界

### 5.1 固定参考版本

| 项 | 固定值 |
|---|---|
| GitHub 项目 | `langchain-ai/open_deep_research` |
| 项目地址 | `https://github.com/langchain-ai/open_deep_research` |
| 上游版本 | `0.0.16` |
| 参考提交 | `1b7d2e80db9faa586165c60e09096dbbfd483a64` |
| 许可证 | MIT License，Copyright (c) 2025 LangChain |
| 主要参考文件 | `deep_researcher.py`、`configuration.py`、`state.py`、`utils.py`、`prompts.py` |

不得默认跟随 GitHub `main` 漂移。升级参考提交前必须重新完成依赖、许可证、安全、工作流、
DeepSeek 和回归审计。

### 5.2 允许复用的内容

允许复用或改写：

- Research Brief 生成形态；
- Supervisor / Supervisor Tools 循环；
- `ConductResearch` / `ResearchComplete` 内部控制语义；
- 并行 Researcher 子图；
- Researcher 的搜索—阅读—缺口判断—补搜循环；
- Researcher 级压缩；
- Token 超限后的受控压缩思路；
- 模型调用重试的基本形态。

### 5.3 必须替换的内容

必须替换：

| 上游实现 | BDLH 替代 |
|---|---|
| `clarify_with_user` 直接与用户交互 | 结构化 `NEEDS_CLARIFICATION` 返回给调用 Agent |
| `init_chat_model()` 自由模型配置 | BDLH 统一 LLM / Model Gateway 依赖注入 |
| `get_all_tools()` | 编译期固定的 BDLH 内部工具集合 |
| 直接创建 Tavily/原生 Search/MCP 工具 | 私有 `AtomicSearchPort` |
| 自行读取 Provider Key/MCP 配置 | BDLH 配置与 Adapter 边界 |
| `think_tool` reflection 落入 ToolMessage | 不持久化的瞬时缺口判断 |
| `raw_notes` 和完整消息作为跨层状态 | 来源引用、压缩结果和最小恢复状态 |
| `final_report_generation` 客户报告 | `assemble_research_bundle` 结构化装配 |
| 任意异常转普通文本或直接结束 | BDLH 稳定错误码与状态 |

复制或修改 MIT 源码时必须保留适用的版权和许可证通知，并增加第三方通知文件。禁止运行时
从 GitHub 下载源码、Prompt 或配置。

## 6. 目标工作流

### 6.1 对外调用链

```text
Authorized Agent
→ Capability Gateway
→ research.deep_search
→ DeepResearchToolExecutor
→ adapted Deep Research graph
→ ResearchBundle
→ Observation
→ calling Agent
```

调用 Agent 负责：

- 判断是否需要外部深度研究；
- 传入明确问题、目标、范围和预算；
- 将研究资料与行情、财务、持仓或其他业务事实结合；
- 执行最终领域判断、Response Guardrail 和客户表达。

Deep Research Tool 不负责上述职责。

### 6.2 内部工作流

```text
validate_research_request
→ write_research_brief
→ research_supervisor
   → supervisor / supervisor_tools
   → N 个并行 researcher_subgraph
      → researcher
      → execute_atomic_search
      → researcher（缺口存在且预算允许时继续）
      → compress_research
   → supervisor（判断是否追加研究单元）
→ assemble_research_bundle
→ Observation
```

Supervisor 和 Researcher 的“继续还是结束”属于模型建议；最终状态必须由确定性装配器根据
预算、来源、覆盖、冲突和错误裁定。

## 7. 原子搜索边界

### 7.1 Deep Research 的固定底层 Provider

`open_deep_research` 没有互联网索引，不替代任何搜索 Provider；它只是多轮研究编排器。

普通搜索与深度研究使用不同的 Provider 链路：

```text
research.web_search
→ bdlh-web-search-adapter
→ SearXNG
→ Bing / Bing News / Baidu / 360 Search / Sogou

research.deep_search
→ DeepResearchToolExecutor
→ private AtomicSearchPort
→ BailianWebSearchProvider
→ 百炼联网搜索 MCP
```

`research.deep_search` 不得把 SearXNG 当作成功时的隐式兜底：百炼 Provider 不可用、超时或
限流时，必须返回 `ATOMIC_SEARCH_UNAVAILABLE`、`PARTIAL` 或 `LIMITED`，并保留已获得的有效
来源。这样不会把“深度研究的稳定来源失败”伪装成普通聚合搜索成功。普通 `research.web_search`
不依赖百炼，百炼未配置时仍按原有链路运行。

### 7.2 AtomicSearchPort

建立独立的私有端口；不得让 Deep Research 经 Capability Gateway 回调现有
`HttpWebSearchAdapter`：

```text
search(
  request_id,
  queries[],
  mode,
  freshness,
  include_domains[],
  exclude_domains[],
  max_results
) → AtomicSearchBatch
```

`BailianWebSearchProvider` 负责以服务端凭证调用百炼 MCP，并把返回的页面/结果映射为
`AtomicSearchBatch`。原子搜索层负责：

- 鉴权、限流、缓存、熔断和受控重试；M2 首发不得切换到 SearXNG 或其他 Provider；
- URL 规范化和基础去重；
- HTML/Markdown 清洗和提示注入卫生；
- 标题、URL、摘要或受控正文、发布时间、检索时间和 Provider 元数据；
- 空结果、超时和 Provider 不可用的真实表达。

原子搜索层不负责拆解完整研究问题、判断研究完成或生成最终研究综合。

### 7.3 注册和递归规则

`AtomicSearchPort` 默认是 `DeepResearchToolExecutor` 的私有依赖，不对普通 Agent 暴露，
不创建第二份 Capability Registry。

公开 `research.web_search` 是长期保留的普通查询入口：

- 它继续走 `bdlh-web-search-adapter + SearXNG`，不承载 Deep Research 的多轮语义；
- Deep Research 内部不得通过 Capability Gateway 调用它；
- 内部只能直接调用私有 `AtomicSearchPort`，防止复合 Tool 递归进入自身或旧公开语义。

## 8. Capability 与兼容决策

### 8.1 提议的公开 ID

提议新增：

```text
research.deep_search
```

原因：它的输入、延迟、预算和输出与当前一次性 `research.web_search` 明显不同，使用新 ID
可以避免在同一 Capability 下静默改变契约。

### 8.1 公开 ID（已裁定）

**冻结使用新 ID：`research.deep_search`。**

- `research.web_search` 长期保留为普通 SearXNG 查询，不承载 Deep 多轮语义；
- **不设兼容期**：当前为开发阶段，不维护「旧 ID 承载复合语义」的双写或投影；
- 禁止在 `research.web_search` 下静默改变为 Deep 行为。

### 8.2 普通 Search 的长期边界

`research.web_search` 不因 `research.deep_search` 出现而退休；两者分别承担普通查询和深度研究。
它可以独立演进其 SearXNG 引擎清单、缓存和限流，但不得改变为多轮研究或复用 Deep Research 的
输出 Schema。未来若要退休或合并普通 Search，必须以独立 ADR 重新评审调用量、延迟、成本、来源
质量和迁移方案。

禁止在 `research.web_search` Adapter 内静默升级为 Deep。两个公开 Capability 显式调用；
策略层只做「选哪个」。

「旧路径」仅指 Deep 实验别名、双写执行器或兼容投影，**不是**删除长期 `research.web_search`。

### 8.3 调用策略（进 Deep 之前）

调用方必须先拼好结构化研究参数与目标，再由确定性 Policy 决定是否触发 Deep。
**默认走 `research.web_search`（或根本不搜）。** 满足以下**任一项** → 允许/应调用
`research.deep_search`（仍须 `allowed`、Feature Flag、预算与 entitlement 许可）：

1. 用户明确要求：深度调研、报告、比较、证据链、交叉验证；
2. `research_topics` 数量 ≥ 2；
3. `success_criteria` 数量 ≥ 2，且每条可验证（禁止空话凑数）；
4. 要求比较多个主体、归因、趋势、风险/机会或冲突观点；
5. 预期需要 ≥ 3 个独立检索问题，或明确需要补搜判断。

硬约束：

- Flag 关闭 / 未授予 / 不在本轮 `allowed` → 不得调用；
- 同步预算不足 → 降级浅搜、可解释 limitation，或 ADR-014 长任务；禁止砍轮次假 COMPLETE；
- 禁止把入口 Goal 的四值 `requested_topics`（含单独 `web_research`）自动升级为 Deep。

Policy 应输出可审计的 `deep_trigger_reasons[]`。

详细字段与验收见 00 Prompt §6.5.1a。

## 9. 输入与输出契约

### 9.1 `DeepResearchRequest`

严格 Pydantic 输入至少包含：

```text
request_id
question
objective
success_criteria[]
research_topics[]         # Deep 主题命名空间；独立于入口 Goal 的 requested_topics
time_range?
language
include_domains[]
exclude_domains[]
budget:
  runtime_seconds
  model_call_limit
  search_call_limit
  max_concurrent_research_units
  max_supervisor_iterations   # 对应上游 max_researcher_iterations（Supervisor 侧）
  max_react_tool_calls
```

调用方不得提供 Provider URL、API Key、模型名、MCP 配置或任意工具列表。Tool 不读取完整客户
会话，只消费调用 Agent 明确提交的研究任务和必要约束。

输入不足时返回：

```text
status = NEEDS_CLARIFICATION
missing_fields[]
clarification_questions[]
```

Tool 不直接向用户发送问题或等待用户输入。

### 9.2 `ResearchBundle`

输出至少包含：

```text
schema_version
request_id
question
research_brief
status                    # COMPLETE | PARTIAL | LIMITED | FAILED | NEEDS_CLARIFICATION
findings[]:
  finding_id
  statement
  source_ids[]
  confidence
sources[]:
  source_id
  title
  url
  domain
  published_at?
  retrieved_at
  summary
  source_type
conflicts[]
limitations[]
research_summary
clarification_questions[]
usage:
  model_calls
  search_calls
  research_units
  duration_ms
  budget_exhausted
```

### 9.3 Observation

`ResearchBundle` 必须包装成统一 `Observation`：

- `capability` 等于实际公开 Capability ID；
- provenance 聚合被最终 findings 引用的来源；
- completeness 由确定性覆盖规则计算；
- 每个 finding 至少引用一个真实 source；
- 无有效来源时不得返回 `COMPLETE`；
- 冲突、空结果、超时、预算耗尽和 Provider 失败不得静默丢失；
- 不输出隐藏思维链、Supervisor reflection、完整消息历史或无限网页正文；
- `research_summary` 和可选长报告不构成唯一权威输出。

旧 Finance 若需要 `results[]`，只能从 `sources[] / findings[]` 确定性投影，不能运行第二遍
LLM 形成第二真源。

## 10. 模型与工具适配

### 10.1 模型

模型由 BDLH `runtime/llm.py` 或后续统一 Model Gateway 注入。不得沿用上游运行时自由模型
配置，也不得允许调用方指定任意模型或凭证。

可以按角色提供受控模型槽位：

- Research Brief / Structured Output；
- Supervisor / Researcher；
- 页面与研究单元压缩；
- ResearchBundle 装配。

### 10.2 工具

官方 `get_all_tools()` 必须删除或替换。Researcher 只能看到编译期固定的内部工具：

```text
atomic_search
ResearchComplete
受控的缺口判断机制
```

不得动态加载任意 MCP Tool、供应商 Tool 或用户传入 Tool。

### 10.3 DeepSeek 放行

首发使用 DeepSeek 前必须验证：

- `with_structured_output()` 的成功率和重试；
- `bind_tools()` 多轮调用稳定性；
- 严格工具参数 Schema；
- 并行调用、空结果、长上下文和 Token 超限；
- 中文、英文和中英混合任务；
- 达到预算、超时或取消时可靠终止；
- 恶意网页文本不能改变工具白名单、系统指令或预算。

具体成功率、样本数、P95 延迟和费用门槛在 ADR 批准前由 owner 补充或在配套评测计划中冻结。

## 11. 预算、状态和持久化

### 11.1 统一预算

外层将 Deep Research 视为一次 Capability 调用，但执行器必须维护内部
`ResearchBudgetLedger`，记录：

- Supervisor / Researcher / Compression / Assembly 模型调用；
- 原子搜索调用和查询数量；
- 并行研究单元数；
- Token 和估算费用（可获得时）；
- 总运行时间、暂停和取消状态。

上游的三个循环参数只能从 BDLH 预算派生，不能成为第二套预算真源。

### 11.2 最小状态

Checkpoint 只允许保存：

- 当前阶段；
- 结构化 Research Brief 和子题；
- 来源 ID 与受控摘要；
- 压缩后的研究单元结果；
- 预算计数器和截止时间；
- 稳定错误与恢复书签。

不得保存 Secret、隐藏推理、完整原始网页和无限增长的消息列表。

### 11.3 Pause / Resume / Cancel

同步预算内可一次完成；超过同步请求预算时必须复用 ADR-014：

- Run Registry；
- Checkpointer；
- 安全点 Pause；
- Resume；
- Cancel；
- 身份和 thread/run 校验。

不得为 Deep Research 建立第二套长任务状态机。

## 12. 完成判断与错误

### 12.1 双层完成判断

模型负责建议：如何拆题、缺什么、是否补搜、是否建议结束。

确定性装配器负责最终裁定（收口规则由 BDLH 定义，非官方 final_report）：

- 是否超预算；
- `research_topics` 和 `success_criteria` 覆盖情况（不可计算则不得 `COMPLETE`）；
- finding/source 引用是否闭合；
- 是否至少有一个有效来源；
- 关键冲突是否显式保留；
- Provider、模型和研究单元失败情况；
- 最终是 `COMPLETE`、`PARTIAL`、`LIMITED` 还是 `FAILED`。

模型调用 `ResearchComplete` 不能单独决定 `COMPLETE`。Supervisor / Researcher 须有硬停（轮次上限、连续无新增 URL、预算耗尽）。

### 12.2 稳定错误码

至少冻结：

```text
DEEP_RESEARCH_INVALID_REQUEST
DEEP_RESEARCH_NEEDS_CLARIFICATION
DEEP_RESEARCH_BUDGET_EXHAUSTED
DEEP_RESEARCH_TIMEOUT
DEEP_RESEARCH_CANCELLED
DEEP_RESEARCH_MODEL_UNAVAILABLE
DEEP_RESEARCH_STRUCTURED_OUTPUT_FAILED
ATOMIC_SEARCH_UNAVAILABLE
ATOMIC_SEARCH_EMPTY_RESULTS
DEEP_RESEARCH_ASSEMBLY_FAILED
```

单个 Researcher 或 Provider 失败不应抹掉其他有效证据；有可信结果时优先返回 `PARTIAL`，
无可信证据时返回 `FAILED / UNAVAILABLE`，不得伪装成功。

## 13. 安全与治理

必须继承既有四时点 Guardrail 和以下约束：

- 网页内容始终是不可信输入；
- 原始网页不得改变系统指令、工具白名单、预算或触发额外 Capability；
- HTML/Markdown 先清洗，长内容先截断和结构化；
- URL 仅允许 HTTP/HTTPS，并执行 SSRF、重定向和私网地址防护；
- Search Provider、MCP、模型和凭证细节不得出现在跨层契约；
- 日志不记录 Secret、完整原文和隐藏思维链；
- 结构化来源必须保留 URL、检索时间和必要的发布时间；
- 财务、风险、估值和适配性计算仍由领域确定性逻辑执行，Deep Research 只提供公开研究资料。

## 14. 实施与验收

### 14.1 M2 扩展切片

顺序：

1. 冻结请求、ResearchBundle、Observation 投影、预算和错误码；
2. 建立金标准与失败/攻击样本；
3. 建立私有 `AtomicSearchPort` 和 `BailianWebSearchProvider`，旧 SearXNG Search 行为保持不变；
4. 用假 LLM 和假 Search 实现确定性工作流测试；
5. 替换模型与工具装配，接 BDLH 预算和 Observation；
6. 接入百炼联网搜索 MCP 做隔离实测；
7. 建立旧 Search 与 Deep Research 的同输入离线对照。

退出门槛：

- 没有 Skill/Domain 依赖；
- 百炼 MCP 未配置或不可用时，普通 Search 行为不变，Deep Research 返回真实的受限状态；
- 拆题、并行、补搜、压缩、装配和预算终止均有测试；
- findings/source 引用闭合；
- 空结果不能变成 `COMPLETE`；
- DeepSeek 达到批准时冻结的稳定性门槛；
- Feature Flag 关闭时现有 Search 行为不变。

### 14.2 M4 接线切片

只处理：

- Capability Registry / Toolset 注册；
- Agent 候选工具暴露；
- 调用 Policy 与精确授权；
- Plan/Tool/Result/Response Guardrail；
- 调用 Agent 对 `ResearchBundle` 的消费；
- 不需要研究时不调用该 Tool 的行为测试。

退出门槛：Agent 能按目标和预算选择或跳过该 Tool，且不能直接调用执行器或内部
AtomicSearchPort。

### 14.3 M5 发布切片

只处理：

- 影子流量；
- 小比例灰度；
- 费用、P95 延迟、错误率、PARTIAL/LIMITED 比例和来源覆盖观测；
- 一键关闭 Feature Flag；
- 回滚演练；
- 稳定期后旧路径退出。

## 15. 后果

正面：

- Agent 获得统一、可复用的深度公开资料研究工具；
- 无需创建虚假的 Skill 或 Domain；
- 复用 Capability、Observation、预算和治理真源；搜索 Provider **分层**（浅搜 SearXNG /
  Deep 私有百炼），不把两套语义混在一个公开 ID 下；
- 查询从单轮模板升级为受预算约束的多轮研究；
- 调用 Agent 继续掌握业务判断和最终表达。

代价与风险：

- 一次调用可能包含多次模型和搜索调用，延迟与费用显著提高；
- DeepSeek 长工具链和结构化输出稳定性尚需实测；
- 现有同步 HTTP 超时和旧 SearchResult 消费方式需要兼容迁移；
- Supervisor/Researcher 的模型判断具有不确定性，必须由确定性质量门槛收口；
- 复制上游实现会产生第三方通知和后续升级维护成本。

## 16. 拒绝的方案

### 16.1 新建 `general` Domain + `deep-research` Skill

拒绝。本需求是跨 Agent 复用的固定 Tool，不是面向用户的独立业务能力；增加 Domain/Skill
会引入不必要的调度层和错误产品定位。

### 16.2 原样部署 open_deep_research 为独立服务

拒绝。会形成第二套模型、工具、凭证、预算、状态和审计链，违反 BDLH 单一真源要求。

### 16.3 删除底层 Search，只保留工作流

拒绝。Deep Research 工作流没有互联网索引，必须依赖至少一个 Search Provider。

### 16.4 将百炼联网搜索 MCP 接入 Deep Research

接受，但边界固定：百炼 MCP 只通过 `BailianWebSearchProvider` 实现 `AtomicSearchPort`，不作为
普通 Agent Tool、不由模型动态加载，也不改变当前 `research.web_search → SearXNG` 的普通查询
路径。

### 16.5 在旧 Capability ID 下静默改变语义

拒绝。若沿用 `research.web_search`，必须升级 Schema 并提供明确兼容层；推荐使用新的
`research.deep_search` ID。

## 17. Owner 裁定（2026-08-15）

下列项已裁定；数值为开发阶段默认，可在评测后微调但须改本 ADR 修订记录。

| # | 议题 | 裁定 |
|---|---|---|
| 1 | 公开 Capability ID | **`research.deep_search`（新 ID）**；浅搜仍用 `research.web_search` |
| 2 | 兼容期 | **不设**。开发阶段不维护旧 ID 复合语义 / 双写兼容层 |
| 3 | 同步超时与长任务 | 见 §17.1 |
| 4 | 默认预算与硬停 | 见 §17.1 |
| 5 | DeepSeek 放行门槛 | 见 §17.2 |
| 6 | 百炼边界 | 见 §17.3 |
| 7 | 上游代码 | **同开发阶段策略**：不整包移植为独立服务；以 BDLH 自研骨架 + 经审查的官方思路/片段为准。若日后合入上游源码文件，再补 MIT 第三方通知与维护人，不在本阶段强制 |
| 8 | 调用策略 | **§8.3 五条直接生效**；须输出 `deep_trigger_reasons[]` |
| 9 | Capability 登记 | **入口资格菜单重写后的数据库目录**为真源；Deep 不进编译期硬编码清单兜底 |

### 17.1 同步时限与默认预算（开发默认）

| 项 | 默认值 | 合理区间 | 说明 |
|---|---|---|---|
| `budget.runtime_seconds` | **90** | 60–120 | 单次同步 Deep 墙钟上限 |
| 同步硬顶（网关/HTTP） | **120s** | 90–180 | 超过必须停；不得无限拖 |
| 何时启用 ADR-014 | 请求声明 `runtime_seconds > 90`，或同步已跑到 **75s** 仍有 PENDING 子题 | — | 开发阶段：优先返回 `PARTIAL` + `budget_exhausted` 并写 limitation；具备 Run Registry 后改为安全点 Pause |
| `model_call_limit` | **24** | 16–32 | Brief+Supervisor+Researcher+压缩合计 |
| `search_call_limit` | **20** | 12–30 | 原子搜索次数（非网页抓取次数） |
| `max_concurrent_research_units` | **3** | 2–4 | 并行 Researcher |
| `max_supervisor_iterations` | **5** | 3–6 | 对应上游 researcher iterations（总控侧） |
| `max_react_tool_calls` | **8** | 5–10 | 单 Researcher 工具轮次 |
| 空转硬停 N | **2** | 2–3 | 连续 N 轮无新增独立 URL → 强制进压缩 |

### 17.2 DeepSeek 放行门槛（开发默认）

评测集建议 ≥ 30 条（中/英/中英、空结果、冲突源、恶意页各若干）。开启非生产 Flag 前：

| 指标 | 门槛 | 说明 |
|---|---|---|
| `with_structured_output` 成功率 | **≥ 90%** | 含一次受控重试后 |
| 端到端可用率（有 ≥1 有效来源的 `PARTIAL`/`COMPLETE`） | **≥ 75%** | 开发门槛；生产 M5 建议升到 ≥ 80% |
| 同步路径 P95 | **≤ 90s** | 与默认 `runtime_seconds` 对齐 |
| 单次评测均费软警 | **≤ ¥0.5 / 请求** | 超则降并发或缩预算，非硬失败 |
| 月度实验室费用软顶 | **¥1000** | 告警用，可调 |

### 17.3 百炼 MCP（开发默认）

| 项 | 默认 | 说明 |
|---|---|---|
| 地域 | 中国大陆（阿里云默认地域） | 凭证仅服务端配置 |
| 单 Run 并发原子搜 | **3** | 与 `max_concurrent_research_units` 对齐 |
| 进程级并发软顶 | **10** | 防打爆配额 |
| 速率软顶 | **30 次搜索 / 分钟 / runtime** | 超则排队或 PARTIAL |
| 月度费用软顶 | **¥2000** | 实验室告警；生产另定 |
| 失败策略 | **不得**回落 SearXNG 伪装成功 | 返回 `ATOMIC_SEARCH_UNAVAILABLE` / `PARTIAL` / `LIMITED` |

### 17.4 登记与策略生效说明

- §8.3 调用策略在开发代码路径**直接生效**（仍受 Feature Flag / `allowed` / entitlement 约束）。
- `research.deep_search` 登记进 **Postgres 资格目录**（与入口重写同一真源）；未开 Flag 或未授予时不得出现在默认 `allowed`。
- `research.web_search` 行为不变。
