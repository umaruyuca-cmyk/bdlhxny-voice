# ADR-015：Context 组装服务与压缩策略（挂靠 ADR-011）

> 状态：APPROVED
> 批准人：项目 owner
> 日期：2026-08-11
> 依赖：[ADR-011](./ADR-011-Memory分层与晋升边界.md)、[ADR-013](./ADR-013-RAG作为可插拔KnowledgeSkill的边界.md)、[ADR-014](./ADR-014-系统截断与用户截断Pause-Resume与会话入口路由.md)
> 影响：[00-BDLH-Agent-Runtime统一生产架构.md](./00-BDLH-Agent-Runtime统一生产架构.md) §9；[00-BDLH-Agent-Runtime生产开发实施Prompt.md](../prompts/00-BDLH-Agent-Runtime生产开发实施Prompt.md) §11、§15、§16
> 依据：桌面《Agent 记忆系统与上下文服务》的工程可操作部分，与 ADR-011 治理分层的合成；**不重新编号 Memory 层**

## 1. 决策目标

在**不改动 ADR-011 的 L0–L4 编号与晋升边界**的前提下，冻结：

1. **Context Service（组装器）** 的职责——存储 ≠ 上下文；
2. 各权威存储如何向单次推理供料；
3. 压缩阶梯（窗口 + 确定性裁剪为主，LLM 压缩为触发式增强）；
4. Mem0（ADR-011 L3）的读写收敛点。

本 ADR **不授权**把 Context Service 拆成独立微服务；一期同进程清晰边界即可。本 ADR 也不改变 Suitability / 账本权威性。

## 2. 为什么不采用桌面稿的另一套 L0–L4

桌面草案曾用：

| 桌面编号 | 含义 |
|---|---|
| L0 | Context 组装 |
| L1 | Dialog Store |
| L2 | Run State |
| L3 | User Facts |
| L4 | Mem0 |

这与已批准的 ADR-011（L0 工作记忆 / L1 会话 / L2 RAG / L3 Mem0 / L4 业务真源）**编号冲突**。生产只承认 ADR-011 编号。桌面职责拆分通过下表**映射吸收**，不再并列第二套层号。

## 3. 权威映射（必须使用）

| 工程职责（原桌面称呼） | ADR-011 层 / 组件 | 权威载体 | 回答的问题 |
|---|---|---|---|
| Dialog Store | **L1 会话记录** | PostgreSQL Chat Session / Messages | 这个 session 完整说了什么？ |
| Run State / Pause 书签 | **L0 工作记忆** + Run Registry + `pending_*` | Java Run State / Registry / Session 投影 | 任务做到哪？能否 resume？ |
| User Facts / 账本 | **L4 业务真源**（不是记忆） | Java 用户事实 v2 / 业务库 | 确认过的档案与持仓是什么？ |
| Semantic Memory（Mem0） | **L3 长期语义** | Mem0 | 跨会话偏好与确认软知识？ |
| RAG 检索知识 | **L2**（Skill，见 ADR-013） | 向量/文档源 → Observation | 可引用的检索证据候选？ |
| Context Service | **组装器，不是存储层** | 同进程模块（可演进） | 这一次给模型看什么？ |

正交关系（冻结）：

```text
恢复执行     → L0 + pending（ADR-014）
恢复聊过什么 → L1
恢复用户是谁 → L4（硬）+ L3（软偏好，低影响）
进模材料     → Context Service 只读组装
继续还是换题 → Turn Router（ADR-014），不是 Memory
```

## 4. Context Service 职责

### 4.1 定义

面向单次推理的**只读组装服务**：

- 从 ADR-011 各层与本轮 scratch **取料**；
- 按 `purpose` 与 `budget` **裁剪**；
- 输出 `ContextBundle`（可带 `context_id` 审计快照）；
- **不**写入 L1 权威消息、L0 Run State、L4 字段，**不**直接 `Mem0.add`，**不做** Turn Router，**不**执行领域主逻辑。

现有 `ContextBuilder` 七块组装是合法实现起点；本 ADR 将其提升为明确边界与压缩/预算规则，而不是推翻重写。

### 4.2 逻辑契约

```text
BuildContextRequest
  user_id                 # 网关注入
  session_id
  run_id?
  message
  purpose                 # classify | answer | plan | summarize | confirm_route | ...
  budget                  # max_tokens 或 small | default | heavy
  hints?

BuildContextResponse
  context_id?
  bundle:
    system
    user_facts              # ← L4 投影短卡片
    semantic_recalls        # ← L3 Top-K
    session_entities        # ← L0 / thread 实体
    recent_dialog           # ← L1 窗口（+ 可选 session_summary）
    run_scratch             # ← 本轮数据摘要
    user_input              # ← 当前句，禁止压缩丢弃
    tool_manifest?          # ← Capability/Toolset 派生视图
  usage: tokens_estimate, dropped[]
  provenance[]
```

### 4.3 在总链路中的位置

```text
Auth → Turn Router（ADR-014）
  ├─ ask_which：极简上下文或不用完整 Agent
  ├─ resume：先恢复 L0，再 Context.build
  └─ new_turn：创建/绑定 run，再 Context.build
→ Context.build（L3 读点在此）
→ Agent / Graph
→ Persist：L1 助手消息、L0 状态
→ Memory Writer（L3 写点在出口，严过滤）
```

### 4.4 purpose 配方（规范级示例）

| purpose | 侧重 |
|---|---|
| `classify` | 短 dialog + entities；少 L3 |
| `answer` | dialog 窗口 + L4 facts + scratch + 适量 L3 |
| `plan` | L4 + entities + 工具相关；dialog 中等 |
| `confirm_route` | pending 摘要 + 当前句；几乎不召回 L3 |
| `summarize` | 允许更长 dialog 或显式摘要任务 |

## 5. 压缩策略

总方针：

> **主路径 = 窗口读取 + 确定性裁剪 + 结构化摘要；  
> LLM 压缩 = 异步增量滚动摘要或超限兜底；  
> 禁止 = 每轮全量读取会话全文再压缩。**

每轮默认读取：

1. L1：最近 N 轮（或按 token 从新到旧填至预算）；
2. 已有 `session_summary`（若存在，一条）；
3. L0：当前 entities + 本 run scratch 摘要；
4. L4：用户事实短卡片（可短 TTL 缓存）；
5. L3：Mem0 Top-K search（按当前 query，禁止 dump 全库）；
6. L2：仅当本轮 Skill 需要检索时，经 Observation 进入，不由 Cognitive 直连。

压缩阶梯：

```text
Level 0  设定 budget / purpose
Level 1  手动裁剪（默认同步必做）
Level 2  结构化摘要（工具结果 / 表格 / 多 Observation digest）
Level 3  LLM 压缩（触发才用；优先异步滚动摘要）
Level 4  失败降级回 Level 1
```

硬规则：

- `user_input` 不压缩丢弃；
- 超预算砍序：旧语义召回 → 更早对话 → 冗长工具原文；后砍本轮关键指标与 L4 facts；
- 滚动摘要只把「新滑出窗口的轮次 + 旧 summary」增量更新；禁止每轮全历史重压；
- 摘要不得替换并删除 L1 原文；不得代替 L0 checkpoint；数字/标的丢失后不得当作唯一依据。

## 6. Mem0（L3）读写收敛

```text
读：仅 Context Service → MemoryStore.search(user_id, query, top_k)
写：仅 Run 出口 → MemoryWriter.filter →（确认策略）→ Mem0.add
```

禁止：Graph 中间节点随手 search/add；工具回调写长期记忆；Chat API 把每句对话同步进 Mem0。

适合写入：表达偏好、确认过的稳定兴趣等软知识。  
禁止写入：完整对话、Pause 进度、持仓/风险等级权威值、临时行情/Observation 原文、未确认推断。

与 L4 冲突时以 L4 为准；L3 失败 → `semantic_recalls` 为空，主链路继续（degraded）。

## 7. 各层读写摘要

| 层/组件 | 写 | 读进模 |
|---|---|---|
| L1 Dialog | 用户消息进 Agent 前立即写；助手定稿后写 | 窗口投影，不整表灌入 |
| L0 Run | Graph/Pause/Resume 更新 checkpoint 与 pending | entities + scratch 摘要 |
| L4 Facts | 独立认证设置/确认 API；Agent 默认只读 | 确定性短卡片 |
| L3 Mem0 | 出口 Writer，严过滤 | Top-K + provenance |
| L2 RAG | Skill 经 Capability | Observation → Evidence 候选 |
| Context | 可选 `context_id` 审计快照 | — |

## 8. 验收要点

1. 「完整对话」问题答案只能来自 L1；Pause 进度只来自 L0/Registry/pending；持仓/风险等级只来自 L4；
2. 单轮 build 不得出现「全量加载 session 再压缩」主路径；
3. Mem0 生产写路径仅出口 Writer；失败可降级；
4. 文档与代码注释禁止写「Mem0 = 全部记忆」或使用与 ADR-011 冲突的另一套 L 编号。

## 9. 后果

正面：保留 ADR-011 金融治理边界，同时吸收桌面稿的可实施组装/压缩模型。

代价：现有 `ContextBuilder` 需逐步补齐 purpose/budget/dropped 可观测性；滚动摘要为增强项，不得阻塞主路径。
