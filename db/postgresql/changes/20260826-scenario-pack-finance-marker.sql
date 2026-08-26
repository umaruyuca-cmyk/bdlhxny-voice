-- 金融场景包标记脚本(不迁移大段数据,只登记场景包元信息)。
-- 手工执行;应用与测试不得自动扫描执行。
-- 前置: touchstone schema 已初始化。
-- 本脚本不删除任何既有金融用例或工具行。

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';

CREATE TABLE IF NOT EXISTS touchstone.scenario_packs (
    pack_id         VARCHAR(64) PRIMARY KEY,
    title           VARCHAR(200) NOT NULL,
    enabled_by_default BOOLEAN NOT NULL DEFAULT FALSE,
    description     TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO touchstone.scenario_packs (pack_id, title, enabled_by_default, description)
VALUES (
    'finance',
    '金融场景包',
    false,
    '可选垂直包:行情/持仓工具场景映射、危险动作词表与出口护栏档案。默认关闭。'
)
ON CONFLICT (pack_id) DO UPDATE SET
    title = EXCLUDED.title,
    description = EXCLUDED.description;

INSERT INTO touchstone.database_changes (script_name, description)
VALUES (
    '20260826-scenario-pack-finance-marker.sql',
    '登记 finance 可选场景包元信息(默认关闭)'
)
ON CONFLICT (script_name) DO NOTHING;

COMMIT;
