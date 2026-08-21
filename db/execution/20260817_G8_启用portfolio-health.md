# G8：启用 portfolio-health Skill（已有库执行）

日期：2026-08-17

对已初始化 registry 的库执行：

```sql
UPDATE registry.bdlh_runtime_skill
SET status = 'CURRENT', enabled = TRUE
WHERE skill_id = 'portfolio-health';

INSERT INTO registry.bdlh_runtime_skill_operation(skill_id, operation_code, required)
VALUES
    ('portfolio-health', 'READ_FINANCIAL_GOALS', FALSE),
    ('portfolio-health', 'READ_MARKET_DATA', FALSE)
ON CONFLICT DO NOTHING;
```

空库请直接使用 `db/postgresql/seed/registry.sql` 全量种子，无需本脚本。
