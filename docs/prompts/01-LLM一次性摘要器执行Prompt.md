# 01 · LLM 一次性摘要器执行 Prompt

用途：交给任意 AI 会话，在 touchstone 分支上完成 single-summary 策略的 LLM 摘要基准接入。将下面整段内容原样复制给执行方。

```text
你是 D:\bdlh-agent\bdlhxny-agent 仓库 touchstone 分支的引擎开发者。任务：为长上下文交叉验证的 single-summary 策略接入一次性 LLM 摘要基准。开始前必须 git status 检查工作区；工作区存在大量未提交修改（web/public、db、deploy/.env.example、docs/design/、engine 下 context/session/evaluation 多个文件），这些是他人正在进行的工作，绝对不能回滚、覆盖或提交。未经用户明确要求不 commit、不 push，不执行任何数据库脚本。

一、先读代码，区分已实现和初稿。当前状态：
1. engine/src/bdlh_runtime/context/summary.py 已有 ExtractiveSummarizer（确定性抽取式基准，extractive-uniform-v1）和 HistorySummarizer 协议；
2. ContextBuilder(summarizer=...) 已支持注入摘要器，builder 的 _build_single_summary 已改为「required 原文 + 最近事件原文(summary_recent_tokens) + 更早事件一次性摘要(summary_max_tokens)」；
3. engine/src/bdlh_runtime/session/compiler.py 的 SessionCompiler.compile() 接受 build_metrics 参数，工件已有 build_model_calls / build_input_tokens / build_output_tokens / build_cost / build_duration_ms 字段；
4. engine/src/bdlh_runtime/infra/env.py 已有 load_deploy_env()，把 deploy/.env 注入进程环境（已存在的环境变量优先）；
5. engine/src/bdlh_runtime/infra/llm.py 的 create_llm 从环境变量读配置，temperature 可传。
以上 1-5 均未跑过测试，先自行验证再扩展。

二、实现要求：
1. 新建 engine/src/bdlh_runtime/session/llm_summary.py，实现 LLMSummarizer，满足 HistorySummarizer 协议（summarize(texts, max_tokens, counter) -> str，同步）；内部用 create_llm(api_key=os.environ["LLM_API_KEY"], base_url=os.environ.get("LLM_BASE_URL"), model=os.environ.get("LLM_MODEL"), temperature=0)。variants 配置要求摘要温度固定 0，生成一次后冻结；
2. 摘要系统提示放在 engine/prompts/session_history_summary.md（新建文件），禁止内联长字符串；提示词要求：只依据给定材料、保留仍有效的决定和未完成任务、标注被推翻的旧方案为已废弃、不超过给定 Token 上限、不得引入材料外的信息；
3. 失败降级链：LLM 调用异常/超时/返回空/返回超过 max_tokens 且无法按句收缩时，回退到 ExtractiveSummarizer（对 LLM 输出按句边界收缩，仍超则直接用抽取式对原文摘要），降级事件记入返回工件的 warnings；
4. 成本记录：LLMSummarizer 统计 model_calls、input_tokens、output_tokens（从响应 usage_metadata 或 response_metadata.token_usage 提取，取不到按 counter.count 估算并标记 estimated=true）、duration_ms；cost = tokens × 单价，单价从环境变量 LLM_PRICE_INPUT_PER_MTOK / LLM_PRICE_OUTPUT_PER_MTOK 读取（每百万 Token 价格，未配置时 cost=0 并在 warnings 注明未配置单价）；
5. 接入运行器：engine/src/bdlh_runtime/evaluation/session_cross_eval.py 增加 --llm-summary 开关（或环境变量 LLM_SUMMARY=1）；开启时仅 single-summary 变体的构建器换用 LLMSummarizer，编译后把摘要的用量写进该变体工件的 build_* 字段；其余三个变体不受影响；
6. main() 入口第一行调用 load_deploy_env()，保证 LLM 配置全部来自 deploy/.env；
7. 隔离红线：摘要器输入只能是序列化后的 Session 事件文本，不得读取 gold 文件任何内容，不得复用 budgeted 策略的选择结果，摘要提示词中不得出现预期答案。

三、验收标准：
1. 无 --llm-summary 时行为与现状完全一致（抽取式），已有测试全部通过；
2. 配置 deploy/.env 后 python -m bdlh_runtime.evaluation.session_cross_eval --compile-only --llm-summary 可运行：single-summary 工件 build_model_calls=1、build_input_tokens>0、compiled_context_hash 与摘要文本一并冻结，重复运行两次摘要结果 hash 一致（temperature=0 冻结）；
3. LLM 不可用时不抛异常，自动回退抽取式并在 warnings 说明；
4. 新增单测覆盖：注入 fake LLM 的摘要路径、降级路径、成本计算、温度与提示词文件加载；运行 engine 全部测试通过；
5. 交付说明：列出改动文件、摘要提示词全文、一次真实 --compile-only --llm-summary 的工件摘要字段值。
```
