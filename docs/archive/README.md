# 历史档案归档

> **状态：HISTORICAL — 不指导开发**
> **归档日期：2026-08-11**

本目录存放已被取代或退出生产链路的文档与图。这些文件**只用于追溯**——理解某个设计当初为什么被否、旧链路长什么样。**不得照此开发。**

当前有效的架构、ADR、Prompt 与审查报告仍在各自原目录：

- 当前架构：`docs/architecture/00-BDLH-Agent-Runtime统一生产架构.md`
- 当前配套图：`docs/architecture/00-BDLH-Agent-Runtime生产架构.drawio`
- 当前 ADR：`docs/architecture/ADR-*.md`

## 归档内容

| 子目录 | 内容 | 原位置 | 退出原因 |
|---|---|---|---|
| `architecture/` | 5 个历史架构版本（V1 股票分析 Agent → V3 双 Runtime + Mem0 → 金融随身管家 V2.1） | `docs/architecture/` | 已被 `00-BDLH-Agent-Runtime统一生产架构.md` 统一取代 |
| `diagrams/` | 7 个旧 Java 链路时期架构图 | 仓库根 `diagrams/` | 当前唯一配套图是 `docs/architecture/00-BDLH-Agent-Runtime生产架构.drawio` |
| `proposals/` | 3 个旧提案（三层路由、付费模型路由、langchain4j 记忆优化） | 仓库根 `proposals/` | 已实施或已否决，头部自述「不作真源」 |
| `reviews/` | 已被当前架构状态取代的阶段报告 | `docs/reviews/` | 保留阶段事实与解锁条件，仅用于追溯，不再作为当前状态依据 |

## 维护规则

- 新增归档文件须在本表登记原位置与退出原因；
- 归档文件不得被当前有效文档引用为决策依据；
- 归档文件之间的相对引用保持原样（随文件一起移动，路径不变）。
