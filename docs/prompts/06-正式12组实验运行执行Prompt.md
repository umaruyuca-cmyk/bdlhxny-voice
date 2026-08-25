# 06 · 正式 12 组实验运行执行 Prompt

用途：交给可信的 AI 会话（或所有者本人按步骤执行），在全部前置代码就绪后运行正式 Session 交叉验证实验并发布。将下面整段内容原样复制给执行方。

```text
你是 D:\bdlh-agent\bdlhxny-agent 仓库 touchstone 分支的实验运行负责人。任务：在所有者手动选择一个压缩用例后，运行 Session 交叉验证实验（4 上下文策略 × 3 Agent 模式 × 每格 1 次 = 12 次运行），落库并按所有者指令发布结果。不得自动连续运行三个压缩用例。开始前必须 git status 并把未提交修改清单报告给所有者确认（工作区有他人未提交修改，不得回滚）；未经所有者明确要求不 commit、不 push，不执行数据库脚本。所有模型配置来自 deploy/.env（LLM_API_KEY/LLM_BASE_URL/LLM_MODEL），不得把密钥写入任何代码、文档或报告。

一、前置检查（全部通过才允许开跑，任何一项失败即停止并报告）：
1. cd engine && .venv/Scripts/python.exe -m pytest tests -q 全绿；
2. python -m bdlh_runtime.evaluation.session_cross_eval --compile-only 六项校验全 PASS：四变体来自同一 source_session_hash、四份 compiled_context_hash 互异、12 格矩阵完整、预算全部满足、required 全保留、编译链路结构上不读 gold；
3. 用 gold 评测器复算四变体约束保留率，记录基线（当前应为 full/single-summary/budgeted=100%，recent-window=33%）；
4. 确认本批次口径开关并记录：LLM_TOKENIZER（默认保守）、BUDGETED_SCORING（默认 v1）、LLM_SUMMARY（默认抽取式）——整批必须单一口径，中途不得切换；
5. 如需落库：本地 data 服务与 PostgreSQL 可用，DATA_API_BASE_URL 指向本地。

二、正式运行：
1. 仅在所有者点击运行按钮或明确下达运行指令后，执行 python -m bdlh_runtime.evaluation.session_cross_eval --runs 1 --save-db --publish（未接好 --save-db/--publish 时去掉对应参数并在报告注明）；EVAL_RUN_TIMEOUT_S 默认 300，EVAL_INTER_RUN_DELAY_S 默认 1，不要为赶进度调小超时；
2. 运行中记录每次基础设施异常（限流/超时/网络）：这些运行标记 INVALID，不进能力指标，但必须保留记录；禁止删除失败运行、禁止重跑覆盖同 run_key；
3. 中途断电/中断：已完成的格子保留，允许以相同参数补跑缺格，并在报告中注明补跑范围。

三、结果核验与报告（必须先核验再下结论）：
1. 每格只有 1 个实验样本，报告必须标注“单次样本”，不得计算稳定平均值或外推必然结论；
2. 交叉核验：同一上下文策略在三个 Agent 间使用相同 compiled_context_hash（报告 frozen_conditions 里四份 hash 与编译工件一致）；gold 未出现在任何模型输入（对 12 次运行的喂入文本检索 gold 特征字段零命中）；
3. 产出中文报告 cross-report.md，分别展示：固定上下文方式后三种 Agent 的本次结果；固定 Agent 后四种上下文方式的本次结果；逐格调用和回答证据。所有比较都标明只代表本批次样本，不得只报平均总分；
4. 与编译期基线对照：recent-window 的约束保留率应显著低于其他三组（预期 33% vs 100%），若运行期指标与编译期矛盾，先查实验缺陷再下结论；
5. 对外声明边界写入报告头：所有工具返回均为冻结 Mock（simulated），结论只覆盖 Agent 决策与上下文处理，不代表真实第三方 API 质量；Token 为保守/所选口径估算。

四、验收标准：12 条运行全部有记录（含 INVALID）；db 可查到批次与运行（若启用）；--publish 工件已生成且 gold 零泄漏；报告能下钻到具体 run_key 证据，并明确说明每格只有一个样本。
```
