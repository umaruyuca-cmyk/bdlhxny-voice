# 08 · Mock数据与调用关系修复开发执行 Prompt

用途：将下面代码块中的全部内容复制给其他 AI，让其修复对比用例与压缩用例的 Mock 数据、真实工具定义、参数匹配、调用依赖和版本哈希。本任务只做开发与不访问真实模型的自动化验证，不运行正式实验。

```text
你是 D:\bdlh-agent\bdlhxny-agent 仓库 `touchstone` 分支的开发执行。请修复当前对比用例和压缩用例的 Mock 数据及调用关系，使 Mock 可以公平评价三种 Agent 的工具选择、参数传递、异常处理和最终回答依据。不要只写分析报告，必须完成代码、数据、SQL 设计和自动化验证；但不得运行真实 Agent 实验、公告实例或真实 LLM。

一、工作边界

1. 开始前执行 `git status --short --branch`，记录已有修改。当前工作区存在所有者和此前开发留下的未提交内容，不得回滚、覆盖、清理或使用破坏性 Git 命令。
2. 未经所有者明确要求，不 commit、不 push、不修改远端分支。
3. 数据库初始化和增量 SQL 只允许写入 `db/`，本任务不得执行任何 SQL。应用启动、容器启动和测试都不能自动执行数据库脚本。
4. 不运行真实压缩实验、不运行三种 Agent 的 9/12/15/36 次实验、不调用真实 LLM、不创建公告实例、不生成公告成绩、不执行公告展示测试。
5. 允许运行纯代码单元测试、接口契约测试和使用 Fake LLM/临时数据的集成测试。测试中的工具返回必须来自测试夹具，不能访问真实第三方服务。
6. 保持当前正确边界：生产 Agent 的工具选择和最终回答由真实 LLM 完成，只有工具执行返回是冻结 Mock。本任务不得把最终回答替换成固定字符串或 Mock 答案。
7. 当前判官仍是代码硬规则判官。LLM 语义判官不在本任务范围内；只为以后接入保留清晰的运行证据和数据结构，不实现、不调用 LLM 判官。

二、必须先完整阅读

按顺序完整阅读：

1. `docs/README.md`
2. `docs/design/压缩用例与对比用例设计.md`
3. `docs/design/匿名测试运行模块设计.md`
4. `docs/context/长上下文构建与压缩.md`
5. `docs/context/Session交叉验证设计.md`
6. `docs/evaluation/Agent对照评测与证据展示.md`
7. `db/README.md`
8. `db/docs/01-数据库总体设计.md`
9. `db/postgresql/changes/20260825-two-track-experiments.sql`
10. `engine/src/bdlh_runtime/evaluation/comparison_agent.py`
11. `engine/src/bdlh_runtime/experiments/comparison.py`
12. `engine/src/bdlh_runtime/experiments/judge.py`
13. `engine/src/bdlh_runtime/experiments/public_case_repository.py`
14. `engine/src/bdlh_runtime/session/mock_dispatcher.py`
15. 三个目录中的 `*.session.json`、`*.variants.json` 和 `gold/*.gold.json`：
    - `engine/var/cases/ctx-session-product-evolution-01/`
    - `engine/var/cases/ctx-session-context-engine-debug-01/`
    - `engine/var/cases/ctx-session-database-deploy-01/`

先核对实际实现和数据库结构，不要假定本 Prompt 中的行号仍然不变。

三、已确认的问题，必须逐项修复

1. 对比用例目前约有 40 条 Mock 返回，其中约 19 条使用空的 `match_arguments={}`。只要工具名相同，即使参数错误也会返回正确数据。
2. `comparison_tool_catalog()` 当前为每个工具生成空 `properties`、`additionalProperties=true` 的参数结构，缺少真实参数名、必填字段、类型、描述、权限和副作用信息。
3. 工具描述缺失时使用“冻结 Mock 工具:工具名”占位，真实 LLM 无法公平判断工具用途和参数。
4. 调用依赖使用 `工具名.字段`字符串，并按最后一个点拆分，不能正确表达 `product.search.items.0.product_id`、`web.search.results.0.url` 这类嵌套路径。
5. `database.describe_table.table → database.query`、`web.extract.text → document.summarize` 等目标没有明确目标参数，判官会把工具名错误拆开。
6. 三个压缩 Session 的 10 条左右工具返回大多只有“冻结只读工具返回，完整内容由用例 fixture 版本管理”，不能作为最终回答的真实证据。
7. `cmp-fixtures-v1` 的 `source_hash` 由固定说明字符串计算，不是由规范化后的实际 Mock 内容计算。修改 Mock 数据后哈希可能不变。
8. 对比用例的 Mock 内容目前内嵌在用例 `expected_checks`，同时又登记一个共享 fixture set；数据来源、版本和哈希之间没有形成单一可验证关系。
9. `stop_when_facts_available` 仍然是字面字符串检查。这个问题暂时不改成 LLM 判官，但必须保证硬规则数据结构清楚，并避免把近义表达误称为完整语义评价。

四、修复真实工具定义

1. 三种 Agent 在同一个实验批次必须看到相同顺序、相同内容的工具定义。
2. 对比执行器不得自己构造空 ToolCard。应从现有版本化工具目录或冻结工具目录快照中读取并筛选 `visible_tools`。
3. 每个工具至少保留：
   - 稳定工具名；
   - 普通语言描述；
   - 完整 JSON Schema；
   - `required` 参数；
   - 参数类型和必要说明；
   - 只读或副作用属性；
   - 权限范围；
   - 工具目录版本或哈希。
4. 如果用例引用的工具不在指定工具目录版本中，运行前将用例标记为配置无效并停止该任务，不能生成一个空 Schema 占位工具继续运行。
5. Mock执行器和真实工具目录分工明确：工具定义来自正式目录，工具执行结果来自冻结 Mock。不要复制两份互相漂移的工具 Schema。
6. 每次运行工件保存实际发送给模型的工具目录哈希和工具定义摘要，以证明三种 Agent 条件一致。

五、修复 Mock 参数匹配

1. 为 Mock 定义明确匹配方式，例如 `subset` 或 `exact`，默认采用关键参数子集匹配。不要依赖“空对象恰好全部匹配”的隐式行为。
2. `match_arguments={}` 只允许用于真正无参数的工具。若工具 Schema 有必填参数而 Mock 匹配条件为空，数据校验必须失败。
3. 每个关键 Mock 至少匹配决定业务结果的参数，例如：
   - 文件工具匹配 `path`；
   - 订单工具匹配 `order_id`；
   - 客户工具匹配 `query` 或 `customer_id`；
   - 商品工具匹配 `product_id`；
   - 网页读取匹配 `url`；
   - 数据库工具匹配 `connection_id`、`table` 或规范化查询标识；
   - 日历工具匹配参与人、日期和时长中的关键字段。
4. 参数未命中时统一返回 `NOT_IN_FIXTURE`，不返回正确内容，不调用 fallback 成功数据。
5. 统一状态：`success`、`empty`、`timeout`、`denied`、`stale`、`conflict`、`error`。所有返回都带 `simulated=true`、`fixture_id`、`fixture_version` 或能够追溯这些字段的运行记录。
6. `timeout`只模拟逻辑错误，不真实 sleep；不得把模拟耗时解释为真实第三方 API 延迟。
7. 同一批次和重复运行使用完全相同的冻结 Mock 版本，不随机改变结果。如果需要正常、超时和冲突三种情况，建立三个明确用例或 fixture 版本。
8. 写操作不得产生外部副作用。Mock只返回“需要确认”“拒绝”或模拟草稿结果。

六、改造调用依赖结构

1. 使用无歧义结构替代仅靠点分字符串拆工具名：

~~~json
{
  "from_tool": "product.search",
  "from_path": "items.0.product_id",
  "to_tool": "product.get_price",
  "to_argument": "product_id"
}
~~~

2. `from_path`支持嵌套对象和数组索引；`to_argument`必须是目标工具参数名。工具名中包含点不能影响解析。
3. 判定依赖时必须同时满足：
   - 来源调用先发生且返回状态允许提供数据；
   - 能按 `from_path`取得来源值；
   - 目标调用后发生；
   - 目标调用的 `to_argument`与来源值相等。
4. 为已有旧格式提供只读兼容转换时，只接受能够无歧义转换的记录；无法转换的用例在数据校验阶段报错，不要默默判失败。
5. 修改20条对比用例中的依赖配置，重点检查：
   - 商品搜索到价格查询；
   - 搜索结果URL到网页读取；
   - 表结构到数据库查询；
   - 网页正文到文档摘要；
   - 客户到订单；
   - 联系人到空闲时间；
   - 搜索结果到来源对比。
6. 保留 `required_calls`、`acceptable_alternatives`、`optional_calls`、`forbidden_calls`、`confirmation_required` 和停止条件，但不要重新退化成唯一线性 `expected_tools`。

七、校正20条对比用例的 Mock

逐条审查全部 `cmp-*` 用例，至少满足：

1. 每个 `required_call`都有同名且关键参数可命中的 Mock，或者该用例明确测试“禁止调用/无需调用”。
2. 每条 `required_dependency`的来源结果中真实存在 `from_path`，目标工具 Schema真实存在 `to_argument`，目标 Mock也匹配该参数。
3. 可接受替代路径中的每条路径都有完整工具定义和对应 Mock；没有实现的替代路径从配置中删除，不要保留虚假可选项。
4. `forbidden_calls`和`confirmation_required`对应的工具必须在工具目录中具有正确副作用或权限属性。
5. 异常用例必须清楚区分：
   - `empty`：查询成功但没有数据；
   - `timeout`：服务不可用，不能据此编造结果；
   - `conflict`：两个来源都有数据但结论冲突；
   - `denied`：权限或确认不足；
   - `stale`：数据存在但时间过期。
6. 提示注入用例中的恶意文字只存在于 Mock结果中，并以不可信数据身份回传；不能进入系统提示或评判规则。
7. 不在 Mock 返回里写“正确答案”“应该调用下一个工具”或其他直接泄露评判路径的提示。
8. 允许工具范围应包含目标工具、相似干扰工具和少量无关工具，但不能因为工具定义过多导致用例目标失焦。

八、补全三个压缩 Session 的工具证据

1. 保留三个 Session 和现有冻结路径，不重新创建旧 `ctx-*` 普通用例。
2. 将通用占位 `content_excerpt`替换为经过人工选择的真实、稳定、足以支持回答的文件片段。
3. 每条文件或代码 Mock 至少返回：
   - 请求路径；
   - 文件版本或内容哈希；
   - 行号或段落范围；
   - 真实内容片段；
   - `simulated=true`；
   - 必要时标记内容时间或是否过期。
4. 产品演进 Session 的片段需要支持判断当前产品边界、压缩用例与对比用例的关系、Session来源和页面职责。
5. 上下文引擎排查 Session 的片段需要支持判断四种上下文方式、当前消息处理、预算构建和循环内上下文重建。
6. 数据库与部署 Session 的片段需要支持判断 SQL手动执行、本地5432、Data服务职责和云部署边界。
7. 每个 Session 至少包含一个容易混淆但已废弃或不适用的片段，要求 Agent结合 Session中的当前约束辨别；不得把“obsolete”“gold”“required”等评测标签直接暴露给Agent。
8. 工具结果只作为Session运行时证据，不把完整文件复制进普通用例库。

九、建立真实的 Fixture版本和哈希

1. Mock数据应有单一内部来源。优先使用已有 `fixture_sets`和`fixture_tool_responses`，用例只引用 fixture set、版本和需要的 fixture编号，不在多个位置复制相同返回正文。
2. 如果当前Data服务读取模型必须暂时保留内嵌数据，至少建立明确过渡层，并在文档中登记剩余迁移工作；不能让 `fixture_set_id`只作为没有实际约束的标签。
3. 对规范化后的完整 fixture 内容计算 SHA-256。规范化内容至少包括工具名、匹配方式、匹配参数、状态、结果和版本，键排序固定，不能包含 `captured_at`等每次变化字段。
4. 任何 Mock参数、状态或结果变化都必须导致 `source_hash`变化，并创建新 fixture版本；不能覆盖已经被运行批次引用的旧版本。
5. 用例版本、fixture版本、工具目录版本分别记录，运行工件同时保存三者和三个哈希。
6. 公共接口和 `web/public/showcase-data/`不得输出 Mock正文、fixture内部编号、调用关系、禁止工具、标准答案或gold。

十、增加数据校验器

实现一个可被单元测试和维护脚本调用的纯代码校验器，在不运行Agent的情况下检查：

1. 用例引用的工具全部存在；
2. 标准可见工具是允许工具的子集；
3. 必需参数和Mock匹配参数符合工具JSON Schema；
4. 有必填参数的工具不能使用空匹配条件；
5. 每个必需调用和有效替代路径都有Mock；
6. 每条依赖的来源路径存在、目标参数存在且Mock数据值能够连通；
7. 禁止和确认工具的副作用、权限属性合理；
8. Mock状态属于允许集合；
9. fixture哈希由实际规范化内容计算且可重复；
10. 三个压缩Session不再包含通用占位返回；
11. 公开投影不包含内部评判配置和Mock正文。

校验失败时返回用例编号、fixture编号、字段和普通语言原因，不能只返回一个 `False`。

十一、自动化验证

只运行不访问真实模型和数据库的自动化验证。至少覆盖：

1. 正确参数命中对应Mock；
2. 错误文件路径、订单号、商品号和URL返回 `NOT_IN_FIXTURE`；
3. 有必填参数的工具拒绝空匹配条件；
4. success/empty/timeout/denied/stale/conflict/error状态按原样进入调用记录；
5. 嵌套来源路径和数组索引能够正确传到目标参数；
6. 来源在后、参数值不同、来源状态不可用时依赖判定失败；
7. 三种Agent获得相同的真实工具Schema和目录哈希；
8. 工具不存在时在运行前配置失败，不生成空Schema工具；
9. 修改任何Mock内容都会改变规范化哈希；键顺序变化不会改变哈希；
10. 20条用例全部通过静态数据校验；
11. 三个压缩Session的工具返回包含真实片段、路径、版本或哈希，不包含通用占位文字；
12. 公开用例JSON不泄露Mock、调用关系、gold或禁止规则；
13. Fake LLM收到Mock结果后可以生成测试答案，但生产代码没有固定或Mock最终答案的路径。

不得运行正式 `ab_eval`、`session_cross_eval`、公开对比任务、公告批次或任何需要 `LLM_API_KEY`的命令。不得执行数据库SQL。不得新增公告实例或公告展示测试。

十二、数据库和兼容处理

1. 如果需要改表，在 `db/postgresql/changes/`新增日期前缀增量脚本，不改写已经由其他环境执行过的历史脚本；如果当前 `20260825-two-track-experiments.sql`明确尚未执行，也仍应先核对仓库约定，优先采用新的修正脚本，避免环境状态不一致。
2. 同步更新 `db/docs/01-数据库总体设计.md`和相关README，说明工具目录、fixture set、fixture response、用例版本和运行批次之间的关系。
3. SQL只交付给所有者手动执行，交付说明提供绝对路径、前置条件、执行顺序和只读核验语句，不实际执行。
4. 旧调用关系格式如果已有历史运行引用，保留历史可读能力；新运行只接受新结构。不要修改历史运行工件冒充重新评判结果。

十三、交付说明

完成后用中文报告：

1. 修复了哪些问题，哪些仍未解决；
2. 修改和新增文件；
3. 20条对比用例逐条列出关键Mock、关键参数、异常状态和依赖关系；
4. 三个压缩Session分别补充了哪些证据片段；
5. 新调用依赖结构及旧格式兼容方式；
6. fixture内容哈希计算规则；
7. 数据库修正脚本绝对路径及维护者手动执行方案；
8. 自动化测试命令和结果；
9. 明确声明没有执行SQL、没有调用真实LLM、没有运行正式Agent实验、没有创建公告实例；
10. 最终 `git status --short`，区分任务开始前已有修改和本任务修改。

十四、验收标准

- 对比Agent使用真实、版本化工具描述和JSON Schema；
- 关键Mock不再依靠空参数匹配；
- 错误参数无法获得正确结果；
- 嵌套路径依赖和目标参数能够准确判断；
- 20条对比用例的数据关系全部通过静态校验；
- 三个压缩Session不再返回同一条通用占位内容；
- fixture哈希真正覆盖Mock内容；
- 内部Mock和评判规则不进入公开数据；
- 最终回答仍由生产LLM生成，Mock只负责工具返回；
- 所有验证不调用真实LLM、不运行正式实验、不执行SQL、不测试公告实例。
```
