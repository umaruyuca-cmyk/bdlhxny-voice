# gold 目录（evaluator_only）

本目录存放内部标准答案，**禁止**：

- 拼入待测 Agent 的模型输入（包括四份派生输入的编译过程）；
- 拼入摘要提示或上下文算法的任何输入；
- 写入工具描述或在公开原文页面展示；
- 帮助上下文算法挑选 required 事件。

只有 `bdlh_runtime.session.mock_dispatcher`（配置冻结 Mock 返回）与
`bdlh_runtime.session.gold_eval`（运行结束后评测）允许读取本目录。
