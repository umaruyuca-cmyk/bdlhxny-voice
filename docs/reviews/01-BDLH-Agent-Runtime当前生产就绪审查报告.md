# BDLH Agent Runtime 当前生产就绪审查报告

> **审查日期：2026-08-10**  
> **代码基线：`ea87317`（当前 `main` 的 M1 代码基线）**  
> **工作区：文档治理改动随本报告单独提交；代码实现状态以 `ea87317` 为准**  
> **审查范围：Python Analysis、Java Backend、Frontend、Nginx 与云端 Compose**  
> **目标：统一生产架构完整目标及当前 M0 生产基线**  
> **审查规范：[00-BDLH-Agent-Runtime生产审查规范.md](./00-BDLH-Agent-Runtime生产审查规范.md)**

## 1. 最终结论

**判定：`NO-GO`。**

当前代码已经具备可运行、可测试的只读股票分析与认证会话基础，三端自动化测试均通过；但这只能证明开发基线稳定，不能证明完整生产架构可发布。

当前最主要的发布阻断是：

1. Agent Run、运行事件和分析历史仍依赖进程内存，重启和多实例场景无法保证恢复；
2. Python 服务只有 liveness，没有独立 readiness，云端 Compose 也没有为 Python/Java 配置健康门禁；
3. 尚无真实生产依赖、容器启动、数据库恢复和端到端发布验证证据；
4. M1 Finance Runtime 已完成独立、非默认装配；Guardrail、StockResearchResult 构建、Suitability、Cognitive Runtime 和 Task/Scheduler 尚未进入完整运行路径。

因此：现有代码可继续作为开发和集成基线，但在关闭本报告 P0 之前，不应宣称“统一生产架构已完成”或直接进行完整能力生产切流。

## 2. 本次验证证据

| 范围 | 命令或检查 | 结果 |
|---|---|---|
| Python | `uv run pytest -q` | `217 passed`，4.20s |
| Java | Maven test | 51 个 suites，163 tests，0 failure，0 error，2 skipped |
| Frontend | `npm test` | 8 passed，0 failed |
| Git 密钥检查 | `git ls-files` 检查 `.env`、私钥及生产配置 | 未发现被跟踪的匹配文件 |
| Nginx | 静态核对 chat、conversation、Java API 路由及 SSE 配置 | 路由已显式拆分，SSE buffering 已关闭 |
| Python 生产配置 | 静态核对 `BDLH_RUNTIME_ENV`、Postgres Checkpointer、JWT、外部服务地址 | 云端 Compose 已显式注入 |

本次没有执行：

- 真实 MCP、Web Search、LLM、Java 内部接口的生产凭证联调；
- Docker Compose 全栈启动与容器健康检查；
- 数据库迁移、备份恢复、服务重启和多实例验证；
- 性能、容量、故障注入、SAST/DAST、依赖漏洞与镜像扫描；
- 真实生产灰度和回滚演练。

上述内容不得根据单元测试结果推定为通过。

## 3. 阶段成熟度

| 阶段 | 目标 | 当前状态 | 说明 |
|---|---|---|---|
| M0 | 生产基线 | `PARTIAL` | JWT、Postgres Checkpointer、Postgres 会话、Nginx 路由已有；运行注册、事件和历史仍有内存状态，readiness 和发布验证不足 |
| M1 | Finance Runtime 边界 | `DEVELOPMENT_COMPLETE / RELEASE_BLOCKED` | 五类单标的兼容分析、精确授权、共享核心和独立 Application 注册已完成；按设计不接默认流量，发布受 M0 门禁阻塞 |
| M2 | StockResearchResult | `NOT IMPLEMENTED` | 强类型契约已存在，生产构建链和完整输出验收尚未接入 |
| M3 | Suitability | `NOT IMPLEMENTED` | `SuitabilityAssessment` 契约已存在，策略引擎和运行时接线尚未实现 |
| M4 | Cognitive + Guardrails | `NOT IMPLEMENTED` | CognitiveAction 与四类 Guardrail 只有契约/Protocol 骨架，没有业务策略和 Graph 接线 |
| M5 | 灰度切流 | `NOT IMPLEMENTED` | 没有可验证的影子流量、对照指标和自动回退证据 |
| M6 | Task / Scheduler | `NOT IMPLEMENTED` | Workflow 内部任务不等于持久化用户任务；调度、通知和承诺闭环尚未实现 |

“存在类型定义”不等于“阶段已实现”；只有生产路径接线和阶段验收同时完成才能改为 `PASS`。

## 4. 已验证的有效基础

### 4.1 身份与用户隔离

- Python API 已支持 JWT 校验，生产 Compose 设置 `BDLH_RUNTIME_AUTH_REQUIRED=true`；
- 会话、运行与历史相关测试覆盖认证隔离；
- Java 内部数据调用具有独立 Token 配置；
- 前端测试覆盖自动携带 JWT 和本地会话按用户隔离。

状态：`PASS`（代码和自动化测试层）；生产密钥轮换及真实跨服务联调仍为 `NOT VERIFIED`。

### 4.2 Checkpointer 与会话存储

- 生产配置选择 Postgres Checkpointer；
- Python `main.py` 在生产路径初始化异步 Postgres Saver；
- Chat Session 提供 Postgres 实现；
- 生产环境拒绝 memory Checkpointer。

状态：`PASS`（实现层）；数据库故障恢复和迁移仍为 `NOT VERIFIED`。

### 4.3 数据真实性边界

- Java 与 Web Adapter 在 production 模式禁止 Mock 降级；
- Observation 和金融契约携带 Mock、来源与质量语义；
- 外部服务失败可以表达为不可用，而不是伪造成功结果。

状态：`PARTIAL`。默认 Graph 中仍保留开发 Mock 节点，必须通过生产启动和端到端测试证明生产装配不会进入这些路径。

### 4.4 Gateway 与 SSE

- `/api/v1/chat/*`、`/api/v1/conversations*` 指向 Python；
- 其他 `/api/v1/*` 指向 Java；
- Nginx 对流式路由关闭 proxy buffering，并设置读取超时。

状态：`PASS`（配置静态审查）；断线重连、长连接容量和真实代理链路仍为 `NOT VERIFIED`。

## 5. P0 发布阻断项

### SW-R-001：运行注册、事件和分析历史不可持久恢复

- 级别：`P0`
- 状态：`OPEN`
- 影响：`agent-runs`、事件查询、恢复、分析历史、多实例部署
- 证据：`runtime/run_registry.py` 和 `runtime/history.py` 的工厂固定返回内存实现；`api/routes.py` 还创建进程内 `InMemoryRunStore`
- 风险：服务重启后运行定位和事件丢失；多实例请求可能落到不同进程并返回 404 或不一致状态
- 修复要求：为 Run Registry、Run/Event Store 和 Analysis History 提供生产持久化实现；明确定义所有权、保留期、幂等键和清理策略
- 验收：生产配置下启动两个实例，创建运行后重启/切换实例，仍可按同一用户查询、恢复并获得有序且不重复的终态事件

### SW-R-002：缺少可用性就绪门禁

- 级别：`P0`
- 状态：`OPEN`
- 影响：Python/Java 启动、部署切流、外部依赖故障
- 证据：Python 只暴露 `/health`；云端 Compose 的 Python 和 Java 服务没有 healthcheck、健康依赖或明确启动门禁
- 风险：进程已启动但数据库、Checkpointer 或关键内部服务不可用时仍接收流量，造成启动期失败和错误切流
- 修复要求：分离 liveness/readiness；readiness 至少验证生产必需配置、数据库/Checkpointer和内部用户数据服务；Compose 与发布流程使用 readiness
- 验收：依赖正常时 readiness 为 200；断开任一必需依赖时在时限内变为非 2xx；liveness 仍能反映进程存活；Gateway 不向未就绪实例转发新流量

### SW-R-003：缺少等价生产环境发布证据

- 级别：`P0`
- 状态：`OPEN`
- 影响：完整发布
- 证据：本次只有本地自动化测试与静态配置核对，没有全栈 Compose、真实外部依赖和恢复演练记录
- 风险：环境变量、网络协议、数据库初始化、SSE 代理或真实供应商响应问题只能在发布后暴露
- 修复要求：在隔离的等价环境执行全栈启动、认证会话、股票分析、降级、断线恢复、重启恢复和回滚冒烟
- 验收：保留带提交号、镜像标识、命令、时间、脱敏日志和结果的发布证据；所有 P0 场景通过

### SW-R-004：安全策略只有契约骨架，未进入运行路径

- 级别：`P0`（启用 M3/M4 个性化金融输出前）
- 状态：`OPEN`
- 影响：计划、工具动作、数据质量和最终响应
- 证据：`guardrails/` 仅包含 Result/Protocol；代码搜索未发现生产策略或 Root Graph 调用；原阶段审计也明确“未接入 Graph”
- 风险：契约存在会造成安全能力已生效的错觉，个性化结论无法被强制阻断或改写
- 修复要求：实现四时点策略并接入真实 Graph；每次决策产生稳定 audit code 和可观测事件
- 验收：覆盖允许、修改、拒绝、低质量数据、越权 Tool、Prompt injection 与不当金融表达；证明被拒绝路径不会调用外部能力或输出被禁止内容

## 6. P1 风险项

### SW-R-005：生产可观测性证据不足

- 状态：`OPEN`
- 现状：已有结构化事件和部分运行标识，但没有本次可验证的指标、仪表板、告警与审计保留配置
- 要求：建立请求/运行/用户关联日志，以及延迟、错误率、外部依赖、数据质量、Guardrail 和 SSE 终态指标
- 验收：通过一次可控故障触发预期指标和告警，并能从 `request_id/run_id` 还原链路

### SW-R-006：生产依赖与镜像可重复性仍需加固

- 状态：`OPEN`
- 现状：Python 使用 `uv.lock` 和 `uv sync --frozen`；基础镜像仍使用可移动 tag，未提供镜像扫描或 SBOM 证据
- 要求：发布镜像使用可追溯 digest/制品标识，生成 SBOM 并执行依赖和镜像漏洞扫描
- 验收：相同提交构建得到可追踪制品，扫描无未接受的高危漏洞

### SW-R-007：阶段切流和遗留路径退出标准缺失

- 状态：`OPEN`
- 现状：新 Domain、Finance、Cognitive 和 Guardrail 契约与旧 Root Graph 并存，但尚无每阶段流量开关、对照指标和删除条件的运行证据
- 要求：为 M1～M5 定义开关、影子执行、差异指标、自动停止条件和遗留路径删除门槛
- 验收：灰度期间可以按用户/会话稳定路由，指标异常时自动停止，回退后状态和会话连续

## 7. 推荐关闭顺序

1. `M0-01`：统一运行、事件和历史的生产持久化；
2. `M0-02`：实现 readiness、Compose 健康门禁和优雅停机；
3. `M0-03`：建立全栈集成、重启恢复、SSE 与回滚验证；
4. `M0-04`：补齐指标、告警、制品和安全扫描证据；
5. 按 M1 → M2 → M3 → M4 顺序接入 Finance、Research、Suitability、Cognitive 与四时点 Guardrail；
6. M5 完成灰度切流后，才删除被替代的旧运行路径；
7. M6 单独实施持久化 Task/Scheduler，不与 Graph 内部 `WorkflowPlan` 混为一谈。

## 8. 重新判定为可发布的最低条件

- 本报告 SW-R-001～004 全部关闭；
- Python、Java、前端测试继续全绿，并新增持久化、readiness、生产禁 Mock 和 Guardrail 运行时测试；
- 等价生产环境全栈冒烟、外部依赖失败、服务重启和回滚演练通过；
- 没有开放 P0，所有剩余 P1 都有批准的风险接受、负责人、期限和监控；
- 发布报告绑定最终提交与镜像，不把本报告的 `ea87317` 开发验收结论等同于生产发布结论。

## 9. 审查限制

本报告是代码与配置层面的生产就绪快照，不是金融合规意见、渗透测试报告或线上 SLA 证明。代码发生实质变化后，必须重新执行检查并更新基线提交；不得只修改日期继续使用旧结论。
