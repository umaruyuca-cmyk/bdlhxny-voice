# 执行 Prompt 索引

针对 Session 交叉验证、两类用例和实验架构重构的执行 Prompt。每份 Prompt 自包含，可整段复制给任意 AI 会话在本仓库执行。01～05 处理单项能力；06 是旧版固定12格运行设计，在10完成前暂停使用；07 用于实施两类用例、运行页面和公告空框架，不运行公告实例或公告展示测试；10 用于把固定三种Agent重构为实验模板和独立配置变量。

| 编号 | 文件 | 目标 | 依赖 |
|---|---|---|---|
| 01 | [LLM一次性摘要器执行Prompt](./01-LLM一次性摘要器执行Prompt.md) | single-summary 接真模型摘要，Token/时长/成本入工件 | 无 |
| 02 | [模型Tokenizer精确计数执行Prompt](./02-模型Tokenizer精确计数执行Prompt.md) | LLM_TOKENIZER=tiktoken 可选精确口径 | 无 |
| 03 | [budgeted多因子评分接入执行Prompt](./03-budgeted多因子评分接入执行Prompt.md) | 公式五/六落地为 budgeted-v2，与 v1 受控对照 | 无 |
| 04 | [实验结果数据库落库执行Prompt](./04-实验结果数据库落库执行Prompt.md) | --save-db 复用 batch/run 契约持久化 | 无 |
| 05 | [网页三视图展示执行Prompt](./05-网页三视图展示执行Prompt.md) | --publish 发布器 + 原始 Session/四种输入/结果三视图 | 无 |
| 06 | [正式12组实验运行执行Prompt](./06-正式12组实验运行执行Prompt.md) | 手动选择一个压缩用例后运行 12 格、落库和发布 | 01-05 完成度决定可选参数；必须由所有者明确触发 |
| 07 | [两类用例与公告空框架开发执行Prompt](./07-两类用例与公告空框架开发执行Prompt.md) | 实现压缩用例、对比用例、匿名后台任务、20 条题库和公告空框架 | 不运行正式实验，不创建公告实例，不做公告展示自动化测试 |
| 08 | [Mock数据与调用关系修复开发执行Prompt](./08-Mock数据与调用关系修复开发执行Prompt.md) | 修复真实工具Schema、Mock参数匹配、嵌套依赖、三个Session证据和内容哈希 | 使用Fake验证；不调用真实LLM、不运行正式实验、不执行SQL |
| 09 | [项目去金融化执行Prompt](./09-项目去金融化执行Prompt.md) | 平台领域中立：清除金融默认/硬编码，护栏泛化为可配置策略，金融降级为可选场景包 | 建议在 01-05、08 之后、06 之前 |
| 10 | [实验变量配置化与单变量对照重构执行Prompt](./10-实验变量配置化与单变量对照重构执行Prompt.md) | 取消固定三种Agent和默认4×3，改为实验模板、独立变量、全量工具/工具搜索、治理开关和受控参数 | 不运行真实LLM、正式实验、SQL或公告实例；完成前暂停使用06 |

## 所有 Prompt 共同的约束（已写入各 Prompt 正文）

- 先 `git status`，工作区存在他人未提交修改，不得回滚、覆盖或提交；
- 未经明确要求不 commit、不 push，不执行任何数据库脚本；
- LLM 配置一律来自 `deploy/.env`（`infra/env.py` 的 `load_deploy_env()`），密钥不进代码与文档；
- gold（`engine/var/cases/*/gold/`）只允许 Mock 调度器与评测器读取，不得进入模型输入、摘要提示、工具描述或公开页面；
- 如实区分"已实现"与"设计稿"，交付说明必须列改动文件与验证证据。

## 当前工作区状态备注（2026-08-24）

`engine/src/bdlh_runtime/` 下已有未测试初稿：`infra/env.py`（env 加载器）、`context/token_count.py`（tiktoken 计数）、`context/scoring.py`（公式五/六）、`context/models.py` 与 `context/builder.py`（评分字段与 v2 路径）。各 Prompt 已要求执行方先核对这些初稿再继续。
