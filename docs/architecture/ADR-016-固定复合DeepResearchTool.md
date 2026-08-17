# ADR-016：固定复合 Deep Research Tool

> 状态：PROPOSED
> 批准人：待项目 owner 评审
> 日期：2026-08-13
> 依赖：[ADR-009](./ADR-009-Runtime-Domain-Skill定位与命名.md)、[ADR-012](./ADR-012-多Skill与多Agent演进门槛.md)、[ADR-014](./ADR-014-系统截断与用户截断Pause-Resume与会话入口路由.md)、[ADR-015](./ADR-015-Context组装服务与压缩策略.md)
> 影响：[00-BDLH-Agent-Runtime统一生产架构.md](./00-BDLH-Agent-Runtime统一生产架构.md) §5、§10、§13、§15、§18；[00-BDLH-Agent-Runtime生产开发实施Prompt.md](../prompts/00-BDLH-Agent-Runtime生产开发实施Prompt.md) §6.5；`bdlh-runtime-orchestrator/src/bdlh_runtime/tools/`、`bdlh-runtime-orchestrator/src/bdlh_runtime/runtime/`、`bdlh-web-search-adapter/`
> 参考实现：[langchain-ai/open_deep_research](https://github.com/langchain-ai/open_deep_research)，版本 `0.0.16`，提交 `1b7d2e80db9faa586165c60e09096dbbfd483a64`，MIT License

## 1. 决策目标

将 Deep Research 建模为 BDLH Runtime 编译期注册的一个固定、只读、复合 Capability Tool，
供获得授权的 Agent 按需调用。该 Tool 内部采用经 BDLH 适配的
`open_deep_research` 工作流形态，完成研究任务整理、研究子题拆分、并行研究、多轮搜索、
缺口判断、压缩和结构化研究资料装配。

本 ADR 冻结以下核心判断：

1. Deep Research 是固定 Tool，不是 Skill、Domain、客户入口或独立 Agent 服务；
2. 调用方 Agent 可以不经过 Skill，直接通过 Capability Gateway 调用该 Tool；
3. `open_deep_research` 是研究编排逻辑，不是 Search Provider；
4. Tool 内部继续需要私有原子搜索端口，首发复用现有
   `bdlh-web-search-adapter + SearXNG`；
5. 不因上游支持 MCP 而强制接入外部 Search MCP；
6. 上游工作流只能在替换模型、工具、状态、预算、错误与输出边界后接入；
7. 最终输出是供调用 Agent 消费的结构化 `ResearchBundle`，不是直接面向客户的报告。

本 ADR 处于 `PROPOSED` 时不授权生产切流。批准前只允许审计、契约草案、离线评测、
假 Provider 原型和不接默认流量的隔离实验。

## 2. 背景与现状

当前 Web Search 链路为：

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

### 7.1 必须保留底层 Search Provider

`open_deep_research` 没有互联网索引，不替代 SearXNG、Tavily、Exa、原生 Search 或 Search
MCP。它只是多轮研究编排器。

首发链路冻结为：

```text
Researcher
→ private AtomicSearchPort
→ bdlh-web-search-adapter
→ SearXNG
→ configured search engines
```

外部 Search MCP 不是前置依赖；未配置任何 Search MCP 时，本能力必须仍可通过现有 Node +
SearXNG 运行。

### 7.2 AtomicSearchPort

从现有 `HttpWebSearchAdapter` 提取或包裹私有端口：

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

原子搜索层负责：

- 鉴权、限流、缓存、熔断和 Provider fallback；
- URL 规范化和基础去重；
- HTML/Markdown 清洗和提示注入卫生；
- 标题、URL、摘要或受控正文、发布时间、检索时间和 Provider 元数据；
- 空结果、超时和 Provider 不可用的真实表达。

原子搜索层不负责拆解完整研究问题、判断研究完成或生成最终研究综合。

### 7.3 注册和递归规则

`AtomicSearchPort` 默认是 `DeepResearchToolExecutor` 的私有依赖，不对普通 Agent 暴露，
不创建第二份 Capability Registry。

若迁移期继续保留公开 `research.web_search`：

- 它只能作为旧路径、兼容投影或影子对照入口；
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

`APPROVED` 前 owner 必须在以下两项中裁定：

1. **新 ID（推荐）**：`research.deep_search` 为复合 Tool，`research.web_search` 迁移期保留；
2. **沿用旧 ID**：`research.web_search` 升级为复合 Tool，但必须升级 Schema 版本、提供旧格式
   投影，并明确超时/预算语义变化。

### 8.2 旧 Search 退出

旧 `research.web_search` 不得在新能力出现后立即删除。退出必须满足：

- 新旧同输入影子评测完成；
- 现有 Finance 消费方已迁移或使用确定性兼容投影；
- 新路径来源覆盖、错误率、延迟和成本达到放行阈值；
- Feature Flag 回滚演练通过；
- 稳定观察期结束；
- owner 明确批准 `RETIRED`。

兼容期可以存在两个公开 ID，但只能存在一份 Deep Research 核心工作流。

## 9. 输入与输出契约

### 9.1 `DeepResearchRequest`

严格 Pydantic 输入至少包含：

```text
request_id
question
objective
success_criteria[]
required_topics[]
time_range?
language
include_domains[]
exclude_domains[]
budget:
  runtime_seconds
  model_call_limit
  search_call_limit
  max_concurrent_research_units
  max_supervisor_iterations
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

确定性装配器负责最终裁定：

- 是否超预算；
- `required_topics` 和 `success_criteria` 覆盖情况；
- finding/source 引用是否闭合；
- 是否至少有一个有效来源；
- 关键冲突是否显式保留；
- Provider、模型和研究单元失败情况；
- 最终是 `COMPLETE`、`PARTIAL`、`LIMITED` 还是 `FAILED`。

模型调用 `ResearchComplete` 不能单独决定 `COMPLETE`。

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
3. 提取私有 `AtomicSearchPort`，旧 Search 行为保持不变；
4. 用假 LLM 和假 Search 实现确定性工作流测试；
5. 替换模型与工具装配，接 BDLH 预算和 Observation；
6. 接入现有 Node + SearXNG 做隔离实测；
7. 建立旧 Search 与 Deep Research 的同输入离线对照。

退出门槛：

- 没有 Skill/Domain 依赖；
- 没有外部 Search MCP 也能运行；
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
- 复用现有 Search Provider、Capability、Observation、预算和治理真源；
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

### 16.4 强制使用外部 Search MCP

拒绝。MCP 是可选 Provider 接法，不是工作流成立条件。首发复用现有 Node + SearXNG。

### 16.5 在旧 Capability ID 下静默改变语义

拒绝。若沿用 `research.web_search`，必须升级 Schema 并提供明确兼容层；推荐使用新的
`research.deep_search` ID。

## 17. 待 owner 批准项

ADR 从 `PROPOSED` 进入 `APPROVED` 前必须裁定：

1. 公开 Capability 使用 `research.deep_search`，还是升级现有 `research.web_search`；
2. 兼容期长度和旧路径 `RETIRED` 门槛；
3. 首发同步最大运行时间，超过后是否立即启用 ADR-014 长任务模式；
4. 默认 `model_call_limit / search_call_limit / concurrency`；
5. DeepSeek 结构化输出成功率、端到端成功率、P95 延迟和费用阈值；
6. 首发是否只使用 SearXNG，还是同时增加第二 Provider；
7. 是否移植上游代码；若移植，第三方通知文件的落位与维护责任人。
