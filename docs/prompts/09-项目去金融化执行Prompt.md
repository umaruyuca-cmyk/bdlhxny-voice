# 07 · 项目去金融化执行 Prompt

用途：交给任意 AI 会话，把平台改造为领域中立：清除一切把金融作为默认/硬编码的痕迹，金融降级为可选场景包，安全护栏泛化为可配置策略。将下面整段内容原样复制给执行方。

```text
你是 D:\bdlh-agent\bdlhxny-agent 仓库 touchstone 分支的平台架构负责人。任务：项目去金融化——平台必须领域中立，不允许任何金融偏好作为默认行为、硬编码或命名残留；金融内容只允许以「显式可选的场景包」形式存在。开始前必须 git status 检查工作区；工作区存在大量未提交修改（web/public、db、deploy/.env.example、docs/design/、engine 的 context/session/evaluation 等），是他人正在进行的工作，绝对不能回滚、覆盖或提交。未经用户明确要求不 commit、不 push，不执行任何数据库脚本。

一、总原则（三条红线）：
1. 去偏好 ≠ 删能力：安全护栏（如交易语义物理禁注册、数字必须有出处）不得删除，必须泛化为可配置策略；金融只是策略的一个预置档案，不是内置默认；
2. 去默认 ≠ 删数据：金融测试用例与工具不删除，迁移进可选场景包（独立目录/独立开关），平台默认状态不含金融内容；
3. 平台核心链路（engine 循环、上下文构建、评测器、Session 交叉验证）改造后必须与改造前行为等价（对非金融用例）。

二、先盘点再动手。执行 grep 全库扫描（engine/src、engine/tests、engine/prompts、db、web/public、docs、data/src），关键词：金融、股票、持仓、行情、交易、买入、卖出、下单、组合、市值、风险承受、C-1、C-2、market.、portfolio.、watch、fundamental、quote。产出「金融痕迹清单」，按下面三层分类后开始改。

三、三层改造。

A 层 · 代码与提示词默认（必须清除或中性化）：
1. engine/src/bdlh_runtime/infra/llm.py:43 注释「金融分析场景需要确定性」→ 改为「对照评测要求输出可复现」；
2. engine/src/bdlh_runtime/evaluation/baseline_agent.py 的 BASELINE_SYSTEM（「你是一个金融分析助手…」）→ 领域中立兜底（如「你是工具型助手，只使用提供的工具获取数据，不得编造」），并支持按场景注入；
3. engine/src/bdlh_runtime/engine/loader.py 的 SCENE_TOOLSETS（market/portfolio/research/watch 全是金融场景）：默认场景改为 general；金融场景映射迁移到场景包配置，核心代码不再枚举金融场景名；所有 scene_tag="research" 的调用点改 general；
4. engine/prompts/system_base.md、scene_chat.md、scene_direct.md：C-1/C-2 等金融合规表述改为通用安全条款（如「禁止执行任何被配置为危险的动作」「数字必须可溯源到工具返回」），不点名金融；
5. 评测与护栏里的金融耦合：output_guardrail 的 C1/C2 检查、guardrails/research_rules.py、data_quality_rules.py——改造为策略化接口（规则注册表 + 按场景包加载），金融规则挪进金融场景包档案；
6. C-1 交易语义守卫泛化：tools/catalog.py 的 is_trading_semantic 与 _TRADING_* 词表改为「危险动作语义注册表」（可配置动词/名词表，支持资金划转、删除、外发邮件等多类），金融交易词表降级为预置档案之一；默认档案可为空但机制必须在。

B 层 · 测试与种子（跟随改造）：
7. engine/tests 中断言金融语义的用例（market.get_realtime_quote 装载、scoped market 排除 portfolio 等）改用中性工具与中性场景断言；护栏测试改为策略化断言（配置危险词→拦截，不配置→放行）；
8. 注册表种子（registry seeded_store）与 data 服务种子里的金融工具：核心种子改为中性工具集；金融工具移入场景包种子（独立 SQL 变更文件，交维护者手动执行，不代跑）。

C 层 · 数据、展示与文档（降级为场景包）：
9. ctx-* 金融长上下文用例、组合/行情类 db 用例：保留但归档到金融场景包目录（如 engine/var/cases/scenarios/finance/ 与 db changes 下的场景包标记），平台默认用例列表以中性用例与 ctx-session-touchstone-design-01 为首；
10. web/public 展示数据与首页：默认展示不得以金融案例为主视觉；金融数据移入场景包分区或下线，索引同步更新；
11. docs：README、产品目标、架构、上下文、评测、showcase 文档中一切「金融/股票为本系统场景」的默认表述改为「领域中立对照平台 + 可选场景包」；删除历史股票 Skill 叙述（git 历史保留即可，文档不再提）；
12. 新增 docs/scenarios/finance/README.md 说明金融场景包的启用方式（场景包=工具种子+用例+护栏档案+展示数据的集合，显式开启才生效）。

四、禁止事项：
- 不得删除或绕过任何安全护栏机制本身；
- 不得删除金融测试资产（只迁移归档）；
- 不得改动 gold 隔离机制（编译器签名无 gold）；
- 不得让场景包在未显式启用时影响任何默认行为。

五、验收标准：
1. 全库 grep 金融关键词：engine/src、engine/prompts、docs 现状章节零命中（测试与场景包目录、历史 changelog、db 归档文件允许命中并集中管理）；
2. engine 全部测试通过；python -m bdlh_runtime.evaluation.session_cross_eval --compile-only 六项校验仍全 PASS（证明核心链路未受损）；
3. C-1 泛化验证：配置危险词表→含该语义的工具注册被物理拒绝；清空词表→注册放行；金融预置档案加载后行为与旧版等价；
4. 默认路径行为验证：不启用场景包时，工具目录、场景装载、提示词、护栏、web 首页均无金融内容；
5. 交付说明：金融痕迹清单（三层分类+处置结果）、改动文件清单、护栏泛化前后接口对照、场景包启用手册、以及一个中性演示用例的运行记录。
```
