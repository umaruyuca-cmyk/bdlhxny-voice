# 04 · 实验结果数据库落库执行 Prompt

用途：交给任意 AI 会话，把 Session 交叉验证的批次与运行结果持久化到 PostgreSQL（经 data 服务，不直连库）。将下面整段内容原样复制给执行方。

```text
你是 D:\bdlh-agent\bdlhxny-agent 仓库 touchstone 分支的后端开发者。任务：为 Session 交叉验证（engine/src/bdlh_runtime/evaluation/session_cross_eval.py）增加数据库落库能力。开始前必须 git status 检查工作区；工作区存在大量未提交修改（web/public、db、deploy/.env.example、docs/design/、engine 多个文件），是他人正在进行的工作，绝对不能回滚、覆盖或提交。未经用户明确要求不 commit、不 push；绝不执行任何 SQL 脚本——数据库脚本只允许维护者手动执行（项目铁律）。

一、先读代码与契约。落库完全复用既有表与接口，不新建表：
1. engine/src/bdlh_runtime/data_client.py：DataClient 已有 create_batch / create_run / save_events / save_context_build / save_tool_calls / save_evaluation / save_measurements / save_artifact / complete_run / complete_batch，载荷契约以该文件为准；
2. 参考落库范式：engine/src/bdlh_runtime/run_api.py 的 _persist_one_run（约 924 行起）——create_run 载荷字段（batchId/caseId/caseVersion/variantId/snapshotId/agentMode/contextStrategy/model/gitCommit/modelConfig）、evaluation 载荷（evaluatorVersion/validRun/status/checks/metrics）、工件登记（artifactType/storageRef/contentHash/publicArtifact）；
3. context_builds 载荷形状参考 run_telemetry.context_build_payload；
4. data 服务是 Java Spring（data/src/main/java/com/bdlh/touchstone/data/api/），注意 create_batch 硬编码 experimentType=agent-implementation：如该字段需要区分 session-cross，先读 Java 端确认字段是否自由文本；需要改 Java 或 SQL 时，产出变更文件与说明，交维护者手动执行，不代跑。

二、实现要求：
1. session_cross_eval.py 增加 --save-db 开关。开启后：先 create_batch（name 如 session-cross-{case_id}-{日期}，fixedConditions 放入 report.frozen_conditions 全量：模型、温度、工具目录版本、fixture 集、source_session_hash、四个 compiled_context_hash、评测器版本、git commit、tokenizer/scoring/摘要配置）；
2. 每格每次运行 create_run 一条：variantId 用 f"{context_variant}"，contextStrategy 用变体 strategy，agentMode 映射 baseline-tool-calling/langgraph-react/full-system（先查现有 agent_runs 枚举口径，若库里是 baseline/react/treatment 则在 modelConfig 里保留原始模式名并加映射说明）；随后 save_context_build（从该变体冻结工件的报告字段构造）、save_tool_calls（mock_records，含 fixture_id 与 simulated=true）、save_evaluation（checks=完整 judgment、metrics={duration_ms, tool_selection_rate, constraint_retention}、validRun=validity==VALID、status 真实透传 INVALID/COMPLETE）、complete_run（output 含 answer 摘要与 error）；
3. 批次收尾 complete_batch；整份 cross-report JSON 以 save_artifact 登记（artifactType=session_cross_report，contentHash=报告 sha256，public=false）；
4. 配置全部来自 deploy/.env（main() 已调用 load_deploy_env）：DATA_API_BASE_URL 默认是容器内地址 http://data:8080，本地运行需在 deploy/.env 或环境覆盖为本地 data 服务地址；data 服务未启动时 --save-db 给出明确错误与启动指引，不静默跳过；
5. --dry-db 开关：构造全部载荷并打印（脱敏 apiKey），不发送任何请求，供无环境验证；
6. 隔离红线：落库内容不得包含 gold 文件原文；judgment 里的 missing_constraints/superseded_misuse 等结论性字段可以入库（它们是评测输出，不是答案泄漏）。

三、验收标准：
1. --dry-db 在无 data 服务环境可完整跑通 --compile-only 与（若配置了 LLM）完整模式，打印的批/运行/评测载荷与契约字段一致；
2. 本地 data 服务 + PostgreSQL 可用时，--save-db 完整模式跑完后：库中可查到 1 个批次、12×runs 条运行，每条运行有关联的 context_build、tool_calls、evaluation；INVALID 运行如实入库不丢弃；
3. 重复运行 --save-db 生成新批次而不是覆盖旧批次（批次不可变）；
4. 新增单测（fake DataClient 记录调用序列）覆盖载荷构造与开关分支；全部测试通过；
5. 交付说明：落库行数统计（按表）、一个 run_id 的下钻查询示例（用 db/postgresql/queries 下的只读查询风格）、以及是否需要新的 changes/*.sql（如需要，附文件交维护者手动执行）。
```
