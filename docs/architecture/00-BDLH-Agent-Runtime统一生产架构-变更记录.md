# 00-BDLH-Agent-Runtime 统一生产架构 — 版本变更记录

> 本文件独立保存 [00-BDLH-Agent-Runtime统一生产架构.md](./00-BDLH-Agent-Runtime统一生产架构.md) 的版本变更历史。
> 定位：只用于追溯，不参与开发执行。架构文档本身不再内嵌历史版本记录，只保留生效日期。

版本号只反映架构文档的表述与登记变化；阶段范围、契约字段语义与发布门禁的任何调整必须另有 ADR。

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-08-10 | 统一生产架构首个权威基线 |
| v1.1 | 2026-08-11 | 定位升级（ADR-009 ~ ADR-012）：产品身份声明、§1 主线标注内核/域、§2 拆分内核范围与首个 Domain、§5.4 引用 `SkillManifest`、§9.1 引用 Memory 分层 |
| v1.2 | 2026-08-11 | 文档面收口（ADR-013）：§0.3 新增版本记录；§3/§7 登记 Domain Dispatcher、manifest 契约与内核纯净度门禁；§18 M1 改名并追加可选 M7；§19.1 登记架构边界测试；§22 补录 README 与图纸处置；§23 拆出「已起草未批准」并登记 ADR-004；配套架构图标签对齐 |
| v1.3 | 2026-08-11 | §22 登记新增的 `docs/00-BDLH-Agent-Runtime仓库文件管理树.md`（文件归属索引，非决策来源） |
| v1.4 | 2026-08-11 | 文档与代码现状对齐 + 通用化沉淀：§0.2 补登记 `TRANSITION`/`DEVELOPMENT_COMPLETE`/`RELEASE_BLOCKED`；§3 更新 Dispatcher（已带 descriptor）、SkillManifest（已落地 ADR-010 §6.1）、PortfolioValuationBuilder（M3 完成）、Toolset/能力计数；§4 拓扑图插入 Domain Dispatcher 节点并与 §1 主线对齐；§4.2 内核行去金融词；§10.1 补 Toolset 命名规则、§10.2 标注为 finance 实例；§13.2/§15.3 拆分为通用内核规则 + finance 域实例标注 |
| v1.5 | 2026-08-11 | 修正实施状态残留：统一 ADR-010 已落地、PortfolioValuationBuilder 已完成但尚未发布的表述；同步 M3、§20、§23.1 与 01 号说明的术语和 Skill 状态 |
| v1.6 | 2026-08-11 | 收口文档治理与状态语义：更新 §0.1 的历史文档称呼；补充基础设施级 `CURRENT` 不等于默认切流的说明；§19.1 登记 manifest/descriptor 启动校验测试 |
| v1.7 | 2026-08-11 | 合成桌面 Resume/记忆草案与现网契约：§2.1/§8/§9/§12 吸收 [ADR-014](./ADR-014-系统截断与用户截断Pause-Resume与会话入口路由.md)（系统/用户截断同构、Turn Router）与 [ADR-015](./ADR-015-Context组装服务与压缩策略.md)（Context 组装挂靠 ADR-011，禁止第二套 L 编号）；§23.1 登记两份 ADR |
| v1.10 | 2026-08-16 | P0 就绪：Orchestrator `/health`+`/ready`；Java Actuator 启动探测；§3 对齐 Java 远程持久化与退役 Checkpointer |
| v1.11 | 2026-08-16 | P1：ADR-014 Turn Router + Pause（`/chat/stream` 分流、`POST .../pause`、Console Esc）；§3 状态表更新 |
| v1.12 | 2026-08-16 | P1：Suitability fail-closed 垂直切片（Cognitive→SUITABILITY→Preflight；ADR-004 前无个性化结论） |
| v1.13 | 2026-08-17 | 开发阶段文档收敛：删除旧迁移主线的执行效力；入口与 Registry 采用全量重写；数据库只允许根目录全量脚本且应用启动不执行 DDL/seed |
| v1.14 | 2026-08-17 | 清理过渡残留：移除 `RETIRED` / `DEVELOPMENT_COMPLETE` / `RELEASE_BLOCKED` 状态标记与 §3 已删除组件状态行；PortfolioValuationBuilder 改为 `FOUNDATION`；§23.3 删除 ADR-001/002/008 待补项；ADR-009 对齐 ADR-010 引用 |
| v1.15 | 2026-08-17 | 文档对齐生产唯一标准：头部与 §17/§18 取消开发/生产双轨产品路径；§3 pending resume 标为 `CURRENT`/`TARGET`（真 checkpoint 未关闭）；ADR-014 登记实现缺口；实施 Prompt 增补 §2/§5 与架构一致 |
