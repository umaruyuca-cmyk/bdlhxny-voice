# 02 · 模型 Tokenizer 精确计数执行 Prompt

用途：交给任意 AI 会话，把交叉验证的 Token 计数从保守估算升级为可选的精确口径。将下面整段内容原样复制给执行方。

```text
你是 D:\bdlh-agent\bdlhxny-agent 仓库 touchstone 分支的引擎开发者。任务：为上下文预算与工件提供可选的 tiktoken 精确计数口径。开始前必须 git status 检查工作区；工作区存在大量未提交修改（web/public、db、deploy/.env.example、docs/design/、engine 下 context/session/evaluation 多个文件），是他人正在进行的工作，绝对不能回滚、覆盖或提交。未经用户明确要求不 commit、不 push，不执行数据库脚本。

一、先读代码，区分已实现和初稿。当前状态（均未跑过测试）：
1. engine/src/bdlh_runtime/context/token_count.py 已有初稿：TiktokenCounter（tiktoken cl100k_base 词表，版本号 tiktoken-cl100k-base-v1）和 counter_from_env()（环境变量 LLM_TOKENIZER=tiktoken 时启用，否则保守口径，ImportError 时回退）；engine/.venv 已安装 tiktoken 0.13.0；
2. 保守口径 ConservativeTokenCounter（conservative-cjk1-latin4-v1）是当前所有预算、工件和网页的正式口径；
3. engine/src/bdlh_runtime/infra/env.py 已有 load_deploy_env()。
验证初稿行为后再继续。

二、实现要求：
1. 口径选择只由环境变量 LLM_TOKENIZER 控制，默认保守口径不变；两种口径的版本号都必须写入派生工件（tokenizer_version 字段），同批次内禁止混用两种口径（切换口径必须生成新的 strategy_version 批次）；
2. 在 engine/src/bdlh_runtime/session/compiler.py 与 session_cross_eval.py 接线：SessionCompiler 用 counter_from_env() 选择计数器；编译报告 compile-report.json 增加 tokenizer_version 字段；
3. 如实标注近似性：Qwen 系列没有公开 tiktoken 词表，cl100k_base 是通用近似（中文通常每字 0.6~1 token，一般低于保守口径）。代码注释、工件 warnings 和文档三处都要写明「cl100k_base 为近似口径，跨口径数据不可直接比较」；
4. 在 docs/context/长上下文构建与压缩.md 的「当前代码对应关系」表补一行：精确口径开关与版本号说明；在 docs/context/Session交叉验证设计.md 的缺口清单更新该项状态；
5. 不改变保守口径的任何数值行为；不删除、不改名 ConservativeTokenCounter。

三、验收标准：
1. 不设 LLM_TOKENIZER 时全部现有测试通过、工件数值与现状完全一致；
2. LLM_TOKENIZER=tiktoken 时 python -m bdlh_runtime.evaluation.session_cross_eval --compile-only 正常完成，四个变体工件的 token 数值变化合理（变小），tokenizer_version 变为 tiktoken-cl100k-base-v1；
3. 新增单测：两种口径对同一中文文本计数、counter_from_env 的三种分支（默认/tiktoken/tiktoken 未安装）；
4. 交付说明：两种口径下四个变体的 original_tokens/working_tokens 对照表，以及口径切换对预算语义的影响说明（同预算能放更多内容）。
```
