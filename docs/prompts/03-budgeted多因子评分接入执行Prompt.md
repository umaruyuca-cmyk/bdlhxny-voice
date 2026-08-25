# 03 · budgeted 多因子评分接入执行 Prompt

用途：交给任意 AI 会话，把文档中的公式五（重要度评分）与公式六（性价比选择）落到可运行的 budgeted-v2，并与 v1 形成受控对照。将下面整段内容原样复制给执行方。

```text
你是 D:\bdlh-agent\bdlhxny-agent 仓库 touchstone 分支的上下文算法负责人。任务：完成 budgeted 策略的多因子重要度评分（公式五）与性价比选择（公式六）实现、接线与对照开关。开始前必须 git status 检查工作区；工作区存在大量未提交修改（web/public、db、deploy/.env.example、docs/design/、engine 下 context/session/evaluation 多个文件），是他人正在进行的工作，绝对不能回滚、覆盖或提交。未经用户明确要求不 commit、不 push，不执行数据库脚本。

一、先读设计与代码。规范文档：docs/context/重要度评分与性价比选择公式设计.md（公式定义、因子表、场景权重表、选择算法、失败降级）。当前代码状态（存在未测试初稿，必须逐一核对，不符合设计稿的按设计稿修正）：
1. engine/src/bdlh_runtime/context/scoring.py 初稿：ScoringWeights（校验：权重和非负和为 1±0.001、ws≤0.3、至少一项≥0.20，违反即抛错）、七场景权重表 + 默认权重、MultiFactorScorer（八因子计算、priority 夹取 [0,1]、selection_value = priority/representation_tokens）、scorer_from_env()（BUDGETED_SCORING=multi-factor-v2 时启用）；
2. engine/src/bdlh_runtime/context/models.py 初稿：ContextItem 新增 relevance(默认0.5)/authority_level(默认None)/cited_by/superseded 四字段；新增 ItemScore 数据类；ContextReport 新增 scores 与 scoring_version 字段（带默认值，向后兼容）；
3. engine/src/bdlh_runtime/context/builder.py 初稿：ContextBuilder(scorer=...) 注入点；_build_budgeted_v2 按 selection_value 降序遍历（完整→压缩→引用兜底，引用排序键恒 -1.0 防止「一切降级为引用」陷阱），REQUIRED 语义不变，公平份额保留为单条压缩目标上限；decision.reason 携带 selection_value 与 priority。
已知初稿缺陷（必须修复）：压缩表示对的 token 估算用头部+目标长度近似，需按实际压缩结果复核预算；serializer 尚未计算 superseded（同 source_id 出现更晚 observed_at 即标记旧条 superseded）与 cited_by（条目 source_id 指向另一条目 item_id 时建立反向引用）；v2 的 scores 未写入 session 派生工件。

二、实现要求：
1. 修复上述缺陷：session/serializer.py 在序列化时补 superseded 与 cited_by；scoring.py 的因子实现与设计稿逐条对照（authority 默认表、freshness 半衰期表、source_quality 档位、task_impact 档位、citation_dependency=min(1,被引/3)、failure_risk、staleness、时间缺失取中性 0.5）；
2. context/__init__.py 导出 ScoringWeights、MultiFactorScorer、ItemScore、scorer_from_env、SCORING_VERSION；
3. 接线：环境变量 BUDGETED_SCORING=multi-factor-v2 时，session_cross_eval 的 budgeted-session 变体使用 v2 构建器，strategy_version 写 multi-factor-v2；未设置时完全走 v1（structured-text-v1），保证 v1/v2 可做受控对照；
4. 派生工件：budgeted-session.json 新增 scores 数组（item_id、八因子值、priority、选中表示、representation_tokens、selection_value）与 scoring_version；网页与报告据此可解释每个决定；
5. 确定性：同输入同输出；同分用 (-selection_value, sequence, item_id, 表示优先级) 消解；评分器不读 gold、不调用 LLM、不跨运行学习；
6. 场景权重：BUDGETED_SCORING_SCENE 可选场景（market/research/portfolio/suitability/watch/intercept/knowledge，缺省 default）；权重校验失败直接拒绝构建，不静默归一化。

三、验收标准：
1. 不设环境变量时全部现有测试通过、v1 行为与数值完全不变；
2. 设 BUDGETED_SCORING=multi-factor-v2 后 --compile-only 成功：budgeted-session 工件含 scores 与 scoring_version=multi-factor-v2，required 全保留、预算不超、事件桶（kept+compressed+referenced+omitted）覆盖全部事件 id；
3. 用 gold 评测器核对 v2 的约束保留率不低于 v1（当前 v1 为 100%）；若低于，按因子/权重分析原因并在交付说明中给出调参建议，不得篡改结果；
4. 新增单测：权重校验各失败分支、八因子典型取值、确定性（两次构建 decisions 与 scores 完全一致）、v2 下 distractor 隔离与 required 保留；全部测试通过；
5. 交付说明：v1 与 v2 在同一 Session 上的 decisions 对照（至少列出 5 个条目两种排序的差异及因子解释）。
```
