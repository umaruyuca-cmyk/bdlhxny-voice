# 金融场景包

> 状态：可选场景包。默认关闭；显式启用后才影响工具场景映射、危险动作词表、出口护栏与描述覆盖。

## 1. 定位

Touchstone 平台本体是**领域中立**的 Agent 对照评测系统。金融相关能力不删除，
但不再作为默认偏好、硬编码场景或首页主视觉。

金融场景包 = 下列资产的集合：

| 组成 | 位置 |
|---|---|
| 危险动作词表（原交易执行守卫） | `engine/src/bdlh_runtime/scenarios/finance/` |
| 场景标签 → toolset（market/portfolio/research/watch） | 同上，注入 `ToolLoader.SCENE_TOOLSETS` |
| 出口护栏关键词（危险执行 / 不当结论） | 注入 `OutputGuardrail` 默认检查 |
| 工具双目的描述与参数契约 overlay | 同上 |
| 用例与 DB 种子 | `engine/var/cases/scenarios/finance/`、`db/postgresql/changes/*finance*`（归档/增量） |
| 展示数据 | `web/public/showcase-data/scenarios/finance/`（若启用展示分区） |

## 2. 启用方式

环境变量（推荐演示/对照实验）：

```bash
# deploy/.env 或进程环境
SCENARIO_PACKS=finance
```

代码（测试或临时会话）：

```python
from bdlh_runtime.scenarios import enable_scenario_pack, disable_all_scenario_packs

enable_scenario_pack("finance")
# …运行需要垂直场景的用例…
disable_all_scenario_packs()
```

未设置 `SCENARIO_PACKS`、未调用 `enable_scenario_pack` 时：

- 默认场景仅为 `general`；
- 危险动作注册表为空（机制在，词表空）；
- 出口护栏默认只有数字溯源；
- 提示词为领域中立口径。

## 3. 与旧行为的关系

启用 `finance` 后，下列行为与改造前等价：

- `market` / `portfolio` / `research` / `watch` 场景装载范围；
- 工具注册时拦截买入/卖出/下单等执行语义（原 C-1）；
- 回答出口拦截交易指令与适当性拍板用语（原 C-1/C-2 出口检查）。

## 4. 注意事项

- 不要在未启用场景包时把金融用例写进默认首页或默认公开批次；
- 新增金融工具种子请放在独立 SQL 变更文件，由维护者手动执行；
- 核心链路（engine 循环、上下文构建、Session 交叉验证）对非金融用例应与改造前行为一致。
