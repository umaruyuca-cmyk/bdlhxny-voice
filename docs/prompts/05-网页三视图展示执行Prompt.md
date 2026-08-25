# 05 · 网页三视图展示执行 Prompt

用途：交给任意 AI 会话，为 Session 交叉验证建设网页三视图（原始 Session / 四种模型输入 / 实验结果）。将下面整段内容原样复制给执行方。

```text
你是 D:\bdlh-agent\bdlhxny-agent 仓库 touchstone 分支的前端开发者。任务：为 Session 交叉验证用例（ctx-session-touchstone-design-01）建设网页三视图。开始前必须 git status 检查工作区；特别注意 web/public 下已有多处未提交修改（index.html、showcase/ 多个页面、shared.js、generate-site.mjs 等），这是页面负责人正在进行的工作，绝对不能覆盖或回滚；新增文件为主，确需改共享文件时先向用户确认。未经用户明确要求不 commit、不 push。

一、先读现状。web 是纯静态站：web/public/ + showcase-data/（cases.json、context-library*、batches/、runs/）+ showcase/ 页面组 + shared.js；构建脚本 web/scripts/generate-site.mjs。数据源在 engine/var/cases/ctx-session-touchstone-design-01/：session.json（102 事件）、variants.json（四变体配置与 12 格矩阵）、compiled/*.json（四份冻结派生工件：compiled_messages、token、hash、kept/compressed/referenced/omitted 事件桶）。gold/ 目录是内部标准答案，绝对不能进入任何公开文件。

二、实现要求分两部分。

A. 发布器（engine 侧，Python）：session_cross_eval.py 增加 --publish 开关，把脱敏静态工件写到 web/public/showcase-data/session-cross/：
1. index.json：用例元信息（case_id、版本、事件数、source_session_hash、变体列表与各自 token 预算/hash、12 格矩阵、报告时间）；
2. session.json：按序事件时间线（user_message/assistant_message/tool_call/tool_result 的正文与状态），不得含任何评测标注（required/priority/expected_tools/答案标签一律禁止）；
3. compiled/{variant_id}.json：直接复制冻结工件（消息、token、hash、事件桶、warnings）；若工件含 scores（v2 评分）一并发布（因子值是可解释性证据，不是答案）；
4. report.json + report.md：最新一次实验的 by_variant/by_mode 聚合与逐格下钻（answer、tool_calls、mock_records）；未跑实验时 report.json 用 {status:"not_run"} 占位；
5. --publish 在 --compile-only 之后即可单独工作（不含实验结果时只发前三类）；发布是覆盖式快照，但 gold 永不发布，发布器代码里不得 import gold 相关模块。

B. 页面（web 侧，静态）：新增 web/public/session-cross/ 页面组（或并入 showcase/，遵循现有导航与 shared.js 风格），三个视图：
1. 原始 Session 视图：时间线渲染 102 事件，用户/助手/工具调用/工具结果分色，工具对折叠展示（点击展开 call+result），错误结果显眼标记；页面不得出现任何评测标签；
2. 四种模型输入视图：full-session / recent-window / single-summary / budgeted-session 四列或四页签对照：各自 compiled_messages、original/working tokens、压缩率、构建时长、compiled_context_hash；每个变体展示哪些事件被保留/压缩/引用/省略（按事件桶），可点击跳回原始 Session 视图定位对应事件；若工件含 v2 scores，展示条目因子构成条形图；
3. 实验结果视图：12 格矩阵（行=上下文策略、列=Agent 模式），每格显示有效运行数、工具选择率、约束保留率、废弃决定误用、时长；点击格子进入单次运行下钻（answer、工具调用序列、mock 返回、判定明细）；INVALID 运行可见且标注原因；
4. 交互约束：纯前端渲染本地 JSON，无任何重新运行入口、无后端调用、无 gold 数据；所有 Mock 结果展示处必须带「simulated/冻结 Mock」标记；页面顶部注明「所有工具返回均为冻结 Mock，不代表真实 API」。

三、验收标准：
1. python -m bdlh_runtime.evaluation.session_cross_eval --compile-only --publish 生成全部静态工件；对发布目录全文检索 gold 特征字段（current_active_constraints/superseded_decisions/expected_tool_plan/answer_rubric）零命中；
2. 三个视图在浏览器（file:// 或 dev-server.js）可正常渲染与互相跳转；事件数、token 数与工件 JSON 一致；
3. 不破坏 web 现有任何页面（index、showcase 各页、cases 等）——现有页面改动仅限导航入口新增一条；
4. 交付说明：新增文件清单、一个视图截图路径或 DOM 验证脚本、发布工件与源工件的 hash 一致性说明。
```
