# Session 交叉验证设计（4 上下文策略 × 2 Agent 模式；默认上下文实验为 4×1 原生底座）

本文档是"固定问题、冻结 Session、冻结 Mock Tools、比较不同 Agent 实现方式"
产品目标下的交叉验证完整设计，同时如实区分**已实现**与**仍属设计**的部分。
当前压缩用例使用三个固定长 Session：产品演进与需求决策、上下文引擎排查、
数据库与部署。每个 Session 独立生成 4×2 交叉诊断矩阵（历史上为 4×3/12 格，LangGraph 并入 native 底座后成为历史口径；默认上下文实验为 4×1）；页面默认一次只处理用户选择的
一个 Session，不自动连续执行三个 Session。

## 1. 实验目标和结论边界

**目标**：在同一份原始 Session、同一个当前问题、同一模型/温度/工具目录/
Mock fixture/评测标准下，单独观察两个变量：

1. 上下文处理方式（4 种）对 Agent 表现的影响；
2. Agent 实现方式（3 种）对上下文利用效率的影响；
3. 两者组合是否存在交互效应。

**结论边界**：

- 所有工具返回均为冻结 Mock。结论只覆盖 Agent 的工具选择、参数、调用顺序、
  权限、错误处理、上下文保留与任务完成，**不**覆盖真实第三方 API 的数据
  质量、网络性能或可用性；
- 模拟延迟均显式标记 `simulated: true`，不得对外冒充真实 API 延迟；
- 本用例 Session 约 9.4K token（保守估算），适合验证数据结构与全链路；
  32K/64K 窗口测试需要继续加入自然的完整文件内容、日志与工具结果，
  **不得**用编号短句批量填充长度。

## 2. 交叉矩阵与固定条件（4×2；默认上下文实验为 4×1）

| 上下文方式 ↓ / Agent 模式 → | 裸 Tool Calling | 完整工程 Agent |
|---|---|---|---|
| full-session（完整透传） | 运行 | 运行 |
| recent-window（最近窗口） | 运行 | 运行 |
| single-summary（一次摘要） | 运行 | 运行 |
| budgeted-session（按预算压缩） | 运行 | 运行 | 运行 |

每个单元格固定：同一 `source_session_hash`、同一当前问题、同一模型与温度
（0.1）、同一工具可见集（7 个只读工具）、同一 Mock fixture 集、同一最大
工具调用数（20）、同一重复次数（每格固定 1 次）、同一评测器与有效性规则。
每格记录：模型、温度、Agent 模式、Session 版本、上下文策略、
`compiled_context_hash`、公共提示词 hash、工具目录 hash、fixture hash、
Git commit 与评测器版本。

**冻结纪律**：四份派生输入先编译、hash、落盘（`compiled/*.json`），三个
Agent 模式读取同一份冻结工件。完整工程组通过 `FrozenContextBuilder` 按
item id 命中冻结构建结果，不重新生成；裸调用/ReAct 组直接消费冻结工件
渲染出的消息。算法、摘要提示或预算变化必须产生新的 `strategy_version`
和 hash，同批次工件不可修改。

## 3. Session 数据结构（已实现）

`loader.py` 加载并校验 `*.session.json`：

- `events[]`：`seq` 从 1 连续递增，`event_id` 唯一；类型限
  `user_message` / `assistant_message` / `tool_call` / `tool_result`；
- 每个 `tool_result` 必须紧跟配对的 `tool_call`（call_id 匹配、无悬挂）；
- `runtime_case.current_question` 非空、`visible_tools` 为工具可见集；
- `source_hash = sha256(规范化 JSON)`，四份派生输入必须同源。

原始事件正文只含自然对话与工具过程，不含任何评测标注。

## 4. 四种派生输入规则（已实现）

公共序列化（`serializer.py`）：用户/助手消息 → conversation 条目（保持
角色与顺序）；`tool_call`+`tool_result` → **合并为一条不可信数据条目**
（调用与结果不可拆开）。序列化只读 session，不读 gold。

| 策略 | 构建器映射 | 行为 | 预算 |
|---|---|---|---|
| full-session | `full` | 全部条目按序透传；超窗即失败（`invalid_context_too_large`），不静默截断 | 16384 |
| recent-window | `recent-n` | 公共系统规则与当前问题（required）**始终保留**；从最后事件向前选完整条目，预算耗尽即停 | 4096 |
| single-summary | `single-summary` | required 原文 + 最近事件原文（1024）+ 更早事件一次性摘要（≤2560）；摘要器与自研压缩器**分离** | 4096 |
| budgeted-session | `budgeted` | 自研算法：required 原文保留，其余按 priority+公平份额压缩/引用/省略（structured-text-v1 早期实现） | 4096 |

single-summary 的默认摘要器是确定性的 `ExtractiveSummarizer`
（均匀分配预算、按句边界抽取，`extractive-uniform-v1`）；接口支持注入
一次性 LLM 摘要（生成后冻结，Token/时长/成本单独记入工件
`build_model_calls/build_input_tokens/build_output_tokens/build_cost`）。
摘要器不得读取 gold，也不得复用 budgeted 的选择结果。

## 5. 派生工件（已实现）

每份工件含 `variants.compiled_context_artifact_required_fields` 全集：
`case_id / case_version / source_session_hash / variant_id / strategy_version /
token_budget / compiled_messages / compiled_context_hash / input_event_ids /
kept|compressed|referenced|omitted_event_ids / original_tokens /
working_tokens / build_duration_ms / build_model_calls / build_input_tokens /
build_output_tokens / build_cost / warnings`，另有 `status`（COMPLETE 或
INVALID+错误）与 `required_retained / budget_fit`。事件桶四项并集恒等于
全部事件 id（含合并的工具对两个 id）。

## 6. Mock fixture 规则（已实现）

`mock_dispatcher.py` 按 gold 的 `runtime_mock_fixtures` 匹配：

- 精确参数子集匹配 → 返回冻结结果（成功或错误状态），均带 `simulated: true`；
- 同名 fallback fixture → `FILE_NOT_IN_FIXTURE`，**绝不把正确内容当兜底**；
- 未登记工具 → `TOOL_NOT_IN_FIXTURE`；
- 每次调用记录 step、工具名、参数、命中 fixture、状态与结果摘要。

错误路径不返回正确答案，参数错误必须返回参数错误，这样工具选择错误与
参数错误才能进入统计。

## 7. 内部标准答案（gold）结构与使用边界

gold 含：`current_active_constraints`（含证据事件 id）、
`superseded_decisions`（旧说法+替代说法）、`required_facts`、
`forbidden_claims`、`expected_tool_plan`（必需/可选/不必要/禁止/不存在
工具与顺序规则）、`runtime_mock_fixtures`、`answer_rubric`、
`evaluation_checks`。

gold 存放于 `gold/` 子目录，仅 `mock_dispatcher`（配置冻结返回）与
`gold_eval`（运行后评测）允许读取；`SessionCompiler.compile()` 签名不含
gold，接口层阻断答案泄漏。禁止把 gold 拼入摘要提示、工具描述或公开页面。

## 8. 指标公式（已实现机械部分）

**工具指标**（`gold_eval.grade_tool_calls`）：

- 正确工具选择率 = 名称+关键参数命中的 required 调用数 / required 总数；
- 漏调用：required 工具名称从未出现；参数不匹配单独计 `argument_mismatch`；
- 额外/不必要/禁止/不存在工具调用与重复调用（同参数规范化键）分别计数；
- 顺序正确：required 命中位置单调递增。

**上下文指标**（`grade_compiled_constraints`，按编译工件计算，与运行无关）：

- 约束保留率 = 任一证据事件被保留（kept/compressed/referenced）的约束数 /
  要求约束总数。

**答案指标**（`grade_answer`，机械近似）：

- 废弃决定误用：答案含旧说法特征片段（或字符 bigram 重叠 ≥ 0.6 的近似复述）；
- 禁用说法：`forbidden_claims` 同口径检查；
- 未修改文件声明：答案含"未修改/没有修改"等关键词。

当前这份 Session 的基线对照（编译阶段即可复现）：full / single-summary /
budgeted 的约束保留率均为 100%，**recent-window 仅 33%**（丢失 6 个早期
决定）——这正是简单窗口基准应当暴露的缺陷。

## 9. 无效运行规则

- 基础设施故障、模型限流、余额不足、评测器失败 → INVALID，不进能力指标；
- Agent 自身失败（选错工具、参数错误、超出调用预算、违反权限、任务未完成、
  循环内预算耗尽被诚实停止）→ 有效失败，进入统计；
- 单运行设超时熔断（`EVAL_RUN_TIMEOUT_S`，默认 300s），超时按 INVALID 收尾；
- 失败案例保留，可按 `run_key` 下钻到 `tool_calls` 与 `mock_records`。

## 10. 数据库保存与网页展示（设计，未实现）

当前工件先落文件系统（`var/cases/<case>/compiled/`、`cross-report-*.json`）。
数据库化后按 db 设计保存：用例版本、原始 Session 版本与 hash、派生工件、
批次、运行、逐事件处理决定、Mock 调用、判定与聚合。网页分三视图：
原始 Session（无评测标签）、四种模型输入（消息/Token/hash/保留-压缩决定）、
实验结果（12 组对照 + 单运行下钻）。公开页只读已发布静态工件，不触发重跑、
不接触 gold。**这部分尚未接入 db/web，属下一步工作。**

## 11. 当前代码差距（诚实清单）

已实现：session 加载校验、序列化（工具对合并）、四策略独立编译、工件
hash 冻结、Mock 调度器、gold 机械评测、4×2 runner（历史上为 12 格；compile-only 可无
模型运行）、`--runs N` 完整模式。

仍属设计/未完成（状态更新 2026-08-24）：

1. ~~budgeted 的多因子重要度与 `selection_value` 未实现~~ **已实现（可选开关）**：
   `context/scoring.py`（`MultiFactorScorer`，公式五/六）+ `BUDGETED_SCORING=multi-factor-v2`
   环境变量接线；serializer 序列化时补 `superseded`/`cited_by` 引用元数据供因子消费；
   v2 的 scores 与 `scoring_version` 写入 budgeted-session 派生工件。未设开关时 v1
   行为与数值不变，可做受控对照；
2. ~~single-summary 的 LLM 摘要器未接入~~ **已实现（可选开关）**：`session/llm_summary.py`
   （`LLMSummarizer`，提示词 `engine/prompts/session_history_summary.md`，temperature=0）；
   `--llm-summary`（或 `LLM_SUMMARY=1`）启用，失败降级抽取式，Token/时长/成本入工件
   `build_*` 字段；
3. ~~Token 计数未接模型 tokenizer~~ **已实现（可选开关）**：`LLM_TOKENIZER=tiktoken`
   启用 cl100k_base 精确口径（`tokenizer_version=tiktoken-cl100k-base-v1` 写入工件），
   默认保守口径不变;另支持 `LLM_TOKENIZER=qwen`（Qwen 官方词表精确口径，`tiktoken-qwen-v1`，`--init-qwen` 初始化词表）。跨口径数据不可直接比较；
4. db 落库与 web 展示视图未实现；
5. 更长 Session（32K+）的第二个用例尚未制作。

## 12. 自动化测试

- `tests/context/test_builder.py`：recent-window 保 required、预算截断；
  single-summary 独立摘要；conversation 消息形态；
- `tests/context/test_summary.py`：抽取摘要确定性、句边界、预算内、
  注入摘要器不走规则压缩器；
- `tests/engine/test_loop_budget.py`：历史/问题计入预算、Schema 预留、
  每轮 refit 折叠更早轮、配对保持、诚实失败；
- `tests/session/test_session_pipeline.py`：加载校验、序列化配对、
  四派生输入同源异构、工件字段全集、事件桶覆盖、Mock 匹配与不泄漏、
  gold 工具计划/约束/废弃判定。

## 13. 分阶段实施计划与验收标准

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0（本次完成） | 修复污染实验的缺陷；session 包；数据入库；compile-only 链路 | 全部单测通过；6 项编译校验 PASS；四工件 hash 互异且同源 |
| P1 | 用户手动选择一个压缩用例后运行 4×1 默认上下文实验（或显式触发 4×2 交叉诊断） | 每格准确运行 1 次；报告按样本展示并可下钻，不生成稳定性结论 |
| P2（已实现，开关启用） | 接入模型 tokenizer、LLM 摘要器、成本记录 | 摘要成本单独入工件（`--llm-summary`；`LLM_TOKENIZER=tiktoken`） |
| P3 | db 落库 + web 三视图 + 脱敏发布 | 公开站无 gold、无重跑入口 |
| P4（已实现，开关启用） | 多因子重要度与 selection_value 实现与对照 | budgeted-v2 与 v1 的受控对照（`BUDGETED_SCORING=multi-factor-v2`） |

运行方式：

```bash
# 无模型验证编译链路
python -m bdlh_runtime.evaluation.session_cross_eval --compile-only
# 正式 12 组实验(需 LLM_API_KEY)
python -m bdlh_runtime.evaluation.session_cross_eval --runs 3
```
