# 后续数据库变更

数据库初始化完成后，新增字段、索引、约束或数据修复脚本放在本目录，由维护者手动执行。

文件名使用日期和普通说明：

```text
20260821-add-run-cancel-reason.sql
20260825-add-context-cache-index.sql
```

每份脚本必须：

1. 使用 `BEGIN` 和 `COMMIT`；
2. 设置合理的 `lock_timeout` 和 `statement_timeout`；
3. 在成功结束前写入 `touchstone.database_changes`；
4. 明确对现有数据的处理方式；
5. 说明是否需要先停止 Data 或 Engine 服务；
6. 执行前完成备份，失败后不得直接修改已执行脚本。

示例登记语句：

```sql
INSERT INTO touchstone.database_changes (script_name, description)
VALUES ('20260821-add-run-cancel-reason.sql', '为运行记录增加取消原因');
```

本目录不使用 Flyway 版本号，也不会被应用自动扫描。

## 脚本依赖顺序（2026-08-22 更新）

- `20260822-tool-catalog-extended-fields.sql`：**仅用于 2026-08-22 之前初始化的
  历史库**。此日期起 `setup/init.sql` 建表已直接包含评测轴三列，新库不再执行。
- `20260822-generic-mock-tools.sql`：依赖上述三列存在（历史库须先执行
  extended-fields；新库由 init.sql 提供）。内部两段冻结集大 INSERT 已带
  `ON CONFLICT DO NOTHING`，可安全重跑。
- `20260822-generic-phase1-cases.sql`：依赖 generic-mock-tools 的 96 个通用工具
  行存在（用例金标引用工具名）。
- `20260821-long-context-cases.sql`、`20260822-fixture-negative.sql`、
  `20260822-fixture-deep-search.sql`：相互独立，任意时间执行；均已幂等可重跑。
- `20260825-two-track-experiments.sql`：写入压缩/对比双轨实验结构与 20 条 cmp-* 用例。
- `20260826-fix-comparison-mock-and-deps.sql`：依赖上一脚本已写入 cmp-*；校正 Mock
  匹配参数、四字段依赖结构、登记 `cmp-fixtures-v2` 与内容哈希。可由
  `python -m` / `engine/scripts/generate_cmp_fix_sql.py` 从过渡层数据重新生成。

新库完整初始化顺序见 `../setup/README.md` 的《新库需要的后续变更脚本》。
