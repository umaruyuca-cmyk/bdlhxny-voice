# M4 Cognitive Graph 与 Communication 实施报告

> **路径收敛附注（2026-08-16）：** Cognitive 现已是默认且唯一产品编排路径；“未切换旧 Root Graph/API”仅为当时状态。旧 Root Graph 其后已删除。
>
> 实施日期：2026-08-12  
> 状态：`DEVELOPMENT_COMPLETE / RELEASE_BLOCKED`（历史）  
> 范围（历史）：独立、非默认流量；未切换旧 Root Graph/API

## 1. 交付结果

- 完成严格 `InputEvent / CognitiveState / CommunicationPlan / PublicResponse` 契约扩展；
- 完成仅启用 `RESPOND / ASK_USER / INVOKE_DOMAIN` 的确定性 Cognitive 编排；
- 完成 Finance-owned 自然语言证券提及提取、受控解析、歧义追问和显式指代继承；
- 解析唯一证券后可在同一 run 继续 `STOCK_RESEARCH`；
- 完成 Plan / Action / Data-quality / Response 四时点最低 Guardrail 并接入编排；
- 完成独立 Action Policy，未启用行动稳定返回 `ACTION_NOT_ENABLED`；
- 完成 DomainOutcome 不可变校验、证据白名单、累计预算和限制披露；
- CognitiveState 只保存行动摘要与领域引用，不保存完整请求、账户或供应商载荷；
- 歧义候选支持下一轮受控选择；显式指代和省略式追问受用户、会话及轮次约束；
- PublicResponse 按知识、追问、研究、适配性、能力提示和安全阻断结构化输出；
- 在 Application 中独立装配 `cognitive_application`，默认 `graph` 路径不变。

## 2. 安全覆盖矩阵

| 安全能力 | 旧路径 | 新 Cognitive 路径 | 自动化测试 | M5 切换门槛 |
|---|---|---|---|---|
| JWT 身份绑定 | API 已有认证上下文 | `InputEvent.user_id` 与 `DomainRequest.authenticated_user_id` 强校验 | Guardrail 与 API 既有测试 | 保持通过 |
| 跨用户隔离 | 既有 API/Checkpoint 隔离 | 会话实体表按 `user_id + session_id` 隔离，并限制继承轮次 | Cognitive flow 测试 | 持久化实体表后复核 |
| Plan 约束 | 旧 Graph 独立规则 | 只读范围、启用领域、单步及累计预算上限 | Guardrail/Safety 测试 | 保持通过 |
| Action 白名单 | 旧 Graph AgentAction | 独立 Action Policy 仅启用三类行动 | Action Policy/Orchestrator 测试 | 保持通过 |
| 外部金融只读 | 既有 Capability 授权 | Cognitive 仅调用 DomainDispatcher；交易语义被阻断 | Guardrail 与内核纯净度测试 | 保持通过 |
| 标的解析与消歧 | 无统一入口 | 名称/简称/代码受控解析；歧义候选追问；显式指代受控继承 | Cognitive flow 与 Resolver 测试 | 接真实主数据验收 |
| 数据真实性 | 各 Adapter 标记 | MOCK/TEST_FIXTURE/UNAVAILABLE 阻断 | `test_guardrail_policies.py` | 保持通过 |
| Coverage/Provenance | M2/M3 契约 | COMPLETE 与覆盖率冲突阻断；引用递归进入 PublicResponse | Cognitive/Guardrail 测试 | 保持通过 |
| Response Verification | 旧 summary_model | 证据白名单、限制、交易承诺、账户泄漏、DomainOutcome 不可变 | Cognitive/Guardrail/Safety 测试 | 保持通过 |

## 3. 验证结果

- M4 定向回归：`49 passed`；
- Orchestrator 全量回归：`326 passed`；
- Python 静态编译通过；
- `cognitive/`、`guardrails/` 对 `domains.finance` 零 import 门禁通过；
- 未执行真实影子流量，使用离线同输入对照测试替代。

## 4. 已知发布门禁

- M4 未持久化 Cognitive Checkpoint；进程重启后实体引用不会恢复，不能宣称多轮恢复生产就绪；
- 默认 API/Root Graph 未切流，切换属于 M5；
- M0 发布基线以及 Suitability v0 审批门禁尚未在本任务关闭；
- `SUITABILITY` 请求已按契约路由，但当前 Finance Runtime 若执行链未启用会返回稳定
  `ACTION_NOT_ENABLED`，Cognitive 不会伪造个性化结论。

因此本次只标记 `DEVELOPMENT_COMPLETE / RELEASE_BLOCKED`。
