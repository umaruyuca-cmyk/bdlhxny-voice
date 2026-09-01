-- ══════════════════════════════════════════════════════════════════════
-- 归档旧六套 ctx-* 长上下文用例(旧变体口径 full-raw / budgeted-comp)
--
-- 背景:context_eval.COMPARISON_VARIANTS 已迁移为
-- full / budgeted-hybrid-v1 / budgeted-extractive,并由
-- 20260901-register-ctx-session-cases.sql 注册三套 ctx-session-* 替代用例。
-- 旧六套(ctx-port/val/news/weather/manual/chat)在新口径下不被任何通道
-- 消费,仅剩目录噪音;但存在 43 条历史运行(关联真实 variant_id 的
-- provenance 不可破坏),相关外键均为 ON DELETE NO ACTION,故按仓库既有
-- 退役机制归档(status='ARCHIVED',listCurrent 仅返回 ACTIVE):
--   - 用例从 /cases 目录、/lab 列表与 context-batches 对照集移除;
--   - 历史运行按 id/version/variant 直查仍可完整关联(FK 不动);
--   - 可逆(需要时置回 ACTIVE)。
--
-- 执行:psql <连接串> -v ON_ERROR_STOP=1 -f 20260901-archive-legacy-ctx-cases.sql
-- 幂等:UPDATE 带 status='ACTIVE' 守卫,可安全重跑。
-- ══════════════════════════════════════════════════════════════════════

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';

UPDATE touchstone.case_definitions
SET status = 'ARCHIVED', updated_at = now()
WHERE id IN ('ctx-port-01', 'ctx-val-01', 'ctx-news-01',
             'ctx-weather-01', 'ctx-manual-01', 'ctx-chat-01')
  AND status = 'ACTIVE';

INSERT INTO touchstone.database_changes (script_name, description)
VALUES ('20260901-archive-legacy-ctx-cases.sql',
        '归档旧六套 ctx-* 长上下文用例(旧变体口径不再被通道消费;保留历史运行 provenance,目录仅返回 ACTIVE)')
ON CONFLICT DO NOTHING;

COMMIT;
