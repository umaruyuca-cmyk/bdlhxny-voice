# Agent 运行链路可观测性优化设计

> 状态：阶段一（运行完成后可复查）已于 2026-08-29 实施；阶段二（SSE 实时）与阶段三（诊断对比）未实施
> 实施偏差说明：事件类型未严格收敛到 §6.3 清单——`output.completed`/`judgment.completed` 因 eval 链路依赖而保留，`model.requested`/`model.result_appended` 已增补
> 适用范围：Touchstone 正式模板运行、长上下文 Agent 运行、所有者批次详情
> 更新日期：2026-08-29

## 1. 背景与结论

当前系统已经具备部分运行遥测能力，但“已经采集”“已经落库”和“页面可见”三层没有完全打通。

现状可以概括为：

| 数据 | 当前采集 | 当前落库 | 当前页面 |
|---|---:|---:|---:|
| 模型调用次数、Token、耗时、状态 | 部分链路支持 | 部分链路支持 | 只显示汇总 |
| 每次模型输入消息 | 上下文评测链路支持 | `model_call_messages` 可保存 | 不展示 |
| 当轮 Tool Schema | 实际传给模型 | 未按模型调用保存 | 不展示 |
| 模型请求参数 | 运行配置中部分可追溯 | 分散在配置快照中 | 只显示批次级请求值/生效值 |
| Tool 名称、参数、结果 | 可采集 | `tool_calls` 可保存 | 只显示名称、状态、命中和耗时 |
| 模型与工具的逐步先后关系 | `run_events` 可表达 | 部分链路支持 | 不展示 |
| 正式模板运行明细 | 执行结果中有部分数据 | 尚未完整写入明细表 | 常出现空明细 |
| 运行中实时步骤 | AgentLoop 有观察接口 | 无完整实时传输链路 | 只显示批次进度 |

因此，本次优化目标不是单纯增加一个 JSON 展开框，而是建立一条完整的证据链：

```text
Agent 组装请求
→ 生成应用层请求快照
→ 模型调用事件
→ Tool 请求与治理判断
→ Tool 执行结果
→ 回填模型上下文
→ 明细落库
→ 页面按时间线展示
```

## 2. 设计目标

优化后，项目所有者应能回答以下问题：

1. 这次运行一共进行了几轮模型调用？
2. 每一轮给模型发送了哪些消息？
3. 每一轮向模型提供了哪些 Tool，完整参数 Schema 是什么？
4. `temperature`、`max_output_tokens`、`parallel_tool_calls` 等参数请求值和实际发送值分别是什么？
5. 模型选择了哪个 Tool，生成了什么调用参数？
6. 调用经过了哪些治理检查，为什么允许、拒绝或要求确认？
7. Tool 返回了什么结果，是否命中冻结数据，耗时多久？
8. Tool 结果如何进入下一轮模型上下文？
9. 运行在第几步结束，停止原因是什么？
10. 这些证据是否完整、是否经过脱敏、能否用于复查和实验归因？

## 3. 非目标与边界

### 3.1 不记录模型隐藏思维

系统只记录可观察输入输出，包括消息、Tool Schema、Tool Call、Tool Result、Token、耗时和状态，不记录或推断模型隐藏思维过程。

### 3.2 不默认保存原始 HTTP 抓包

本文中的“模型请求快照”指进入 SDK 前由应用组装的结构化请求，不是网络层抓包。默认不保存：

- API Key；
- Authorization Header；
- Cookie；
- 代理鉴权信息；
- SDK 内部重试请求的完整传输报文；
- 服务端返回的隐藏字段。

如果未来需要排查 OpenAI 兼容端点差异，应另设短期、受控、默认关闭的传输诊断模式，不能与正式实验遥测混用。

### 3.3 不改变实验变量

可观测性字段只能旁路记录执行事实，不能改变 Prompt、工具顺序、Schema、模型参数、重试策略或治理结果。同一实验在开启和关闭页面展示时，模型实际收到的内容必须一致。

## 4. 统一数据口径

### 4.1 四类参数状态

模型参数统一使用四种状态，避免把“配置里有字段”误写成“已经发给模型”。

| 状态 | 含义 | 示例 |
|---|---|---|
| `requested` | 模板或用户请求的值 | `temperature=0.3` |
| `sent` | 应用实际交给 SDK 的值 | `temperature=0.3` |
| `effective` | SDK 或响应能够确认的生效值 | 响应返回 `temperature=0.3` |
| `unsupported` | 当前适配器未发送或模型不支持 | `reasoning_effort` 未接线 |

页面不能用 `effective` 冒充 `sent`。无法由响应确认时，可以显示“已发送，服务端未回显确认”。

### 4.2 三种请求视图

| 视图 | 内容 | 用途 |
|---|---|---|
| 业务视图 | 普通语言说明、消息角色、Tool 名称、关键参数 | 日常复查 |
| 应用请求快照 | `model/messages/tools/parameters` 结构化 JSON | 工程审计与复现 |
| 网络传输诊断 | 脱敏后的 SDK/HTTP 传输信息 | 临时故障排查，默认关闭 |

第一阶段只实现前两种视图。

### 4.3 每轮模型调用记录

建议每条模型调用至少记录：

```json
{
  "sequence": 1,
  "purpose": "AGENT",
  "model": "configured-model",
  "request_snapshot_version": 1,
  "messages": [
    {"order": 0, "role": "system", "content": "...", "tokens": 120},
    {"order": 1, "role": "user", "content": "...", "tokens": 35}
  ],
  "tool_schemas": [
    {
      "type": "function",
      "function": {
        "name": "market.get_realtime_quote",
        "description": "读取实时行情",
        "parameters": {
          "type": "object",
          "properties": {"symbol": {"type": "string"}},
          "required": ["symbol"]
        }
      }
    }
  ],
  "parameters": {
    "requested": {"temperature": 0.1, "tool_choice": "auto"},
    "sent": {"temperature": 0.1, "max_tokens": 1200, "parallel_tool_calls": false},
    "unsupported": {
      "tool_choice": "当前适配器未显式发送，由模型自行决定"
    }
  },
  "request_hash": "sha256:...",
  "response": {
    "decision": "call_tool",
    "tool_calls": [
      {"call_id": "call-1", "name": "market.get_realtime_quote", "arguments": {"symbol": "300750"}}
    ]
  },
  "usage": {"input_tokens": 840, "output_tokens": 32},
  "duration_ms": 820,
  "status": "COMPLETE"
}
```

`request_hash` 应覆盖经过规范化的 `model + messages + tool_schemas + sent parameters`，不能只覆盖消息，否则工具提供方式或模型参数改变后仍可能得到相同哈希。

### 4.4 每次 Tool 调用记录

```json
{
  "sequence": 2,
  "model_call_sequence": 1,
  "call_id": "call-1",
  "tool_name": "market.get_realtime_quote",
  "arguments": {"symbol": "300750"},
  "governance": {
    "decision": "allow",
    "audit_code": "RO-OK",
    "rule_ids": ["G1-VISIBLE", "G3-SCOPE"]
  },
  "execution": {
    "status": "SUCCESS",
    "fixture_hit": true,
    "duration_ms": 12
  },
  "result": {
    "summary": {"symbol": "300750", "price": 185.5},
    "result_hash": "sha256:...",
    "source_time": "2026-08-28T10:00:00+08:00"
  }
}
```

Tool 调用必须同时关联：

- 发起它的模型调用；
- 模型生成的 `call_id`；
- 全局运行事件序号；
- 治理检查；
- Tool Result 回填消息。

这样才能稳定重建 `模型 → 工具 → 模型` 的真实顺序。

## 5. 运行链路设计

### 5.1 采集点

```text
RunConfig
   │ requested 参数
   ▼
模型客户端构建 ──────────────── sent 参数快照
   │
   ▼
ContextBuilder ─────────────── messages 快照
   │
   ▼
ToolLoader ─────────────────── 当轮 Tool Schema 快照
   │
   ▼
LLM 调用 ───────────────────── response / usage / duration
   │ tool_calls
   ▼
GovernanceMiddleware ───────── allow / deny / confirmation
   │
   ▼
Tool Executor ──────────────── arguments / result / fixture / duration
   │
   ▼
ToolMessage 回填 ───────────── 下一轮 messages
```

采集应发生在值真正确定的位置：

- 参数在模型客户端完成适配后记录；
- 消息在每次 `invoke` 前记录；
- Tool Schema 在每次 `bind_tools` 后记录；
- Tool 参数以模型输出解析结果为准；
- Tool Result 以治理和执行器最终返回为准。

### 5.2 正式模板链路补齐

正式模板运行必须与长上下文评测链路使用相同的遥测包装和落库协议。不能只把简化后的 `NativeRunRecord.tool_calls` 留在内存作业报告中。

建议统一为：

```text
run_native_agent
→ 创建 per-run recorder
→ 包装 LLM 与 Tool Executor
→ AgentLoop 执行
→ recorder 生成 events/model_calls/tool_calls/guardrail_checks
→ 创建 agent_runs 行
→ 分项持久化
→ 完成运行与工件登记
```

完成后，正式模板、上下文实验和历史诊断应返回同构的单次运行详情。

### 5.3 搜索式工具提供

`tool_delivery=search` 时，当轮 Tool Schema 会动态变化，必须逐模型调用保存，不能只保存运行结束时最后一次 `visible_tools`。

推荐展示：

| 轮次 | 提供给模型的工具 |
|---|---|
| 第 1 轮 | `search_tools` |
| 第 2 轮 | `search_tools`、检索命中的 A/B/C |
| 第 3 轮 | `search_tools`、累计缓存的 A/B/C/D |

同时保留目录版本、eligible catalog hash、当轮 Schema hash 和搜索日志，便于解释“为什么模型当时看不到某个工具”。

## 6. 存储优化建议

### 6.1 `model_calls`

建议新增：

| 字段 | 类型 | 说明 |
|---|---|---|
| `request_snapshot_version` | integer | 请求快照协议版本 |
| `request_payload` | jsonb | 应用层完整请求快照 |
| `tool_schemas` | jsonb | 当轮实际绑定的 Tool Schema |
| `requested_params` | jsonb | 模板请求值 |
| `sent_params` | jsonb | 实际交给 SDK 的值 |
| `unsupported_params` | jsonb | 未发送字段及原因 |
| `decision` | varchar | `call_tool` 或 `answer` |
| `response_summary` | jsonb | 可观察模型输出和 Tool Call 摘要 |

如果 `request_payload` 已包含消息与 Tool Schema，可以只将它作为不可变审计快照；现有 `model_call_messages` 继续用于 SQL 查询和页面分页。两者必须由同一份内存对象生成，避免内容不一致。

### 6.2 `tool_calls`

现有表已经覆盖大部分内容，建议补齐或真正写入：

- `model_call_id`；
- `call_id`；
- `requested_event_sequence`；
- `completed_event_sequence`；
- `result_ref`；
- 明确区分 `SUCCESS / FAILED / TIMEOUT / DENIED / INVALID`；
- 对 `NOT_IN_FIXTURE` 将 `fixture_hit` 记录为 `false`。

### 6.3 `run_events`

`run_events.sequence` 作为运行内全局顺序真源。建议事件类型保持少而稳定：

```text
run.started
context.completed
model.requested
model.completed
tool.requested
guardrail.completed
tool.completed
model.result_appended
run.completed
```

事件 payload 保存定位信息和小摘要，完整正文保存在明细表，避免事件表重复存储大块消息和 Tool Result。

## 7. API 设计

### 7.1 完成后详情

保留：

```http
GET /api/v1/runs/{run_id}/detail
```

建议响应按运行顺序组织，同时保留原始分表数据：

```json
{
  "run": {},
  "timeline": [
    {"sequence": 1, "type": "model", "model_call": {}},
    {"sequence": 2, "type": "tool", "tool_call": {}},
    {"sequence": 3, "type": "model", "model_call": {}}
  ],
  "modelCalls": [],
  "toolCalls": [],
  "guardrailChecks": [],
  "events": [],
  "measurements": []
}
```

JSONB 字段应由 API 返回 JSON 对象或数组，不应作为需要前端再次 `JSON.parse` 的字符串返回。

### 7.2 运行中实时详情

第二阶段增加所有者专用 SSE：

```http
GET /api/v1/runs/{run_id}/events/stream
Accept: text/event-stream
Last-Event-ID: 12
```

要求：

- 每个事件具有稳定递增 `sequence`；
- 断线后使用 `Last-Event-ID` 补发；
- 页面刷新后先读取数据库历史，再接实时事件；
- 事件至少一次投递，前端按 `(run_id, sequence)` 去重；
- 不通过 SSE 发送密钥或未脱敏的大结果；
- 运行结束发送 `run.completed` 并关闭流。

第一阶段可以先实现“运行完成后完整可见”，第二阶段再实现“运行中实时可见”，避免把持久化和实时传输一次性耦合。

## 8. 页面信息架构

单次运行明细采用“摘要 + 时间线 + 原始证据”三层结构。

```text
┌──────────────────────────────────────────────────────────────┐
│ 运行状态  VALID · FINAL_ANSWER · 3 步 · 2 次工具调用         │
│ 模型 / 模板 / 变体 / 配置哈希 / 目录版本 / 总 Token / 耗时   │
├──────────────────────────────────────────────────────────────┤
│ [全部] [模型] [工具] [治理] [上下文]                         │
├──────────────────────────────────────────────────────────────┤
│ ① 模型调用 #1 · 820ms · call_tool                            │
│   消息 2 条 · Tools 3 个 · 输入 840 / 输出 32 Token          │
│   [查看消息] [查看 Tool Schema] [查看参数] [请求 JSON]        │
│                         │                                    │
│ ② 治理检查 · allow · RO-OK                                  │
│                         │                                    │
│ ③ Tool · market.get_realtime_quote · SUCCESS · 12ms          │
│   参数 {symbol: 300750} · 冻结命中                           │
│   [查看返回结果]                                              │
│                         │                                    │
│ ④ 模型调用 #2 · 610ms · answer                               │
│   消息 4 条 · Tools 3 个 · 输入 1030 / 输出 88 Token         │
│   [查看消息] [查看 Tool Schema] [查看参数] [请求 JSON]        │
└──────────────────────────────────────────────────────────────┘
```

### 8.1 默认折叠规则

- 默认显示普通语言摘要，不直接铺开大段 JSON；
- 参数、Schema、消息、结果分别折叠；
- 每个 JSON 块提供复制按钮；
- 长消息显示字符数和 Token，展开后再渲染正文；
- Tool Result 默认显示摘要，完整结果受权限和大小限制；
- 失败与拒绝步骤默认展开原因；
- 当前正在执行的步骤使用明确的“等待模型”“治理检查中”“工具执行中”状态，不显示虚假百分比。

### 8.2 参数展示

每个模型调用显示请求值、发送值和支持状态：

| 参数 | 请求值 | 实际发送 | 状态 |
|---|---|---|---|
| `temperature` | `0.1` | `0.1` | 已发送 |
| `max_output_tokens` | `1200` | `max_tokens=1200` | 已映射并发送 |
| `parallel_tool_calls` | `false` | `false` | 已发送 |
| `tool_choice` | `auto` | — | 当前适配器未显式发送 |
| `reasoning_effort` | — | — | 未配置/未支持 |

## 9. 权限、脱敏与容量控制

### 9.1 权限

- 完整请求快照仅项目所有者可见；
- 匿名测试只允许查看自己的任务摘要，不返回系统提示和完整 Tool Result；
- 公告页只读取经过发布投影的数据；
- 数据服务内部接口继续使用服务令牌，浏览器不直连内部接口。

### 9.2 脱敏

入库前执行统一脱敏规则：

- 密钥、Token、Authorization、Cookie 全部替换；
- 邮箱、手机号、账号等按用例公开级别处理；
- 系统提示可在所有者视图完整保存，但公开投影只保存 hash 和版本；
- Tool Result 中的大文件、二进制或完整网页只保存 `result_ref + hash + summary`；
- 脱敏后再计算公开 hash，内部原始 hash 与公开 hash 分开。

### 9.3 容量

建议设置：

- 单条消息正文大小上限；
- 单个 Tool Schema 集合大小上限；
- 单个 Tool Result 内联大小上限；
- 超限内容写工件文件或对象存储，数据库只保留引用和 hash；
- 按运行和批次设置遥测总字节上限；
- 页面按模型轮次懒加载，不在批次首屏返回全部正文。

## 10. 分阶段实施建议

### 阶段一：完成后可复查

1. 定义请求快照协议和版本。
2. 每轮记录消息、Tool Schema、发送参数和响应摘要。
3. 正式模板运行接入统一 recorder。
4. 将模板运行的 events/model_calls/tool_calls/guardrail_checks 写入数据服务。
5. 运行详情 API 返回结构化 JSON。
6. 页面增加模型调用与 Tool 调用折叠详情。

阶段一完成后，用户在运行结束后可以完整查看每一步。

### 阶段二：运行中实时可见

1. 创建 per-run 事件发布器。
2. 增加 SSE 和断线续传。
3. 执行过程中增量持久化关键事件。
4. 页面将历史事件与实时事件合并去重。
5. 增加等待、执行、失败和完成状态。

### 阶段三：诊断与对比

1. 支持两个模型调用请求快照差异比较。
2. 支持不同变体 Tool Schema 差异比较。
3. 支持导出单次运行审计包。
4. 支持按 Tool、状态、审计码和参数字段检索。
5. 增加存储量、缺失遥测和事件乱序监控。

## 11. 当前代码映射与改造点

| 模块 | 当前职责 | 优化方向 |
|---|---|---|
| `engine/engine/loop.py` | 每轮加载工具、绑定 Schema、调用模型、执行 Tool | 在实际绑定与调用点生成逐轮快照 |
| `engine/evaluation/run_telemetry.py` | 记录消息、模型调用、Tool 调用和事件 | 扩展请求快照，关联 model call 与 tool call |
| `engine/experiments/template_runner.py` | 正式模板原生 Tool Calling 执行 | 接入统一 recorder，并输出完整遥测 |
| `engine/run_api.py` | 创建批次、执行模板、运行落库 | 正式模板运行持久化全部明细 |
| `data/RunPayloads.java` | 数据服务写入契约 | 增加请求快照与动态 Tool Schema 字段 |
| `data/RunRepository.java` | 明细写入与详情查询 | 保存 JSONB，返回结构化详情和时间线 |
| `db/postgresql/setup/init.sql` | 总体表结构 | 增加快照字段与调用关联字段 |
| `web/experiment/batch.html` | 批次结果与单次运行下钻 | 增加逐步时间线和折叠证据视图 |

## 12. 验收标准

### 12.1 数据完整性

- 每次真实模型调用对应且只对应一条 `model_calls`；
- 每条记录包含当轮消息、Tool Schema、sent 参数和请求 hash；
- 每次 Tool 调用能关联发起它的模型调用和 `call_id`；
- 搜索式工具提供每轮保存不同的实际 Tool 集合；
- 正式模板运行不再出现“运行成功但明细表为空”；
- `request_hash` 对消息、工具或发送参数任一变化都发生变化；
- 不记录 API Key、鉴权头和隐藏思维。

### 12.2 页面

- 单次运行可以按顺序看到模型、治理和 Tool 步骤；
- 可以查看模型输入消息、当轮 Tool Schema 和 sent 参数；
- 可以查看 Tool 参数、状态、冻结命中和结果摘要；
- 不支持的参数明确显示原因；
- 大 JSON 默认折叠且可复制；
- 失败、超时、拒绝、取消和达到步数上限均有明确状态；
- 运行中页面不使用无依据的百分比。

### 12.3 回归测试

- Fake 模型验证两轮请求保存不同消息；
- `all` 模式验证每轮 Schema 一致；
- `search` 模式验证第二轮新增命中工具；
- 治理拒绝验证无真实执行但保留 DENIED Tool 记录；
- `NOT_IN_FIXTURE` 验证 `fixture_hit=false`；
- 429、超时和取消验证已有证据仍可查看；
- 页面测试验证所有 JSON 均经转义，不可注入 HTML；
- 权限测试验证匿名用户无法读取完整请求快照。

## 13. 推荐决策

建议采用以下默认方案：

1. 第一阶段先做“运行完成后完整可见”，随后再做 SSE 实时展示。
2. 保存应用层请求快照，不保存默认网络抓包。
3. 每轮保存实际 Tool Schema，不使用最终 `visible_tools` 代替历史轮次。
4. 使用 `run_events.sequence` 作为全局时间线顺序，以明细表作为完整内容真源。
5. 完整快照仅所有者可见，公告使用单独的脱敏发布投影。
6. 不记录模型隐藏思维，只记录可观察的模型输入、Tool Call 和输出。

该方案能满足“看到每一步调用了什么 Tool、给 LLM 发送了什么、当时有哪些 Tool”的核心需求，同时保持实验可复现、数据可审计和公开展示安全。
