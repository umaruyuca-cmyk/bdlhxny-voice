-- 20260823-trim-simple-add-complex.sql
-- 题库重构:大幅精简单工具用例 + 新增多工具复杂用例
--
-- 精简原则:
--   gt8-sim(24道,1工具)→保留3;gt8-perm(12道,1工具)→保留3
--   gt8-absent(12道,0工具)→保留2;gt8-notool(12道,0工具)→保留2
--   gt8-dir(4道,1工具)→保留1;research(6道,1工具)→保留2
--   port(3道,1-3工具)→保留1;neg(8道,1工具)→保留3
--   基础对话(chat/know/miss/coref/follow)与 ctx/cxm 全保留
--
-- 新增 8 道多工具复杂用例(cxm2-*,每题 5-7 工具)
--
-- 幂等:DELETE 带精确 ID;INSERT ON CONFLICT DO NOTHING

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '2min';

-- ══ 第一部分:精简单工具用例 ══

-- 要删除的用例 ID 清单
CREATE TEMP TABLE cases_to_delete AS SELECT unnest(ARRAY[
  -- gt8-sim: 保留 01/08/16,删 21 道
  'gt8-sim-02','gt8-sim-03','gt8-sim-04','gt8-sim-05','gt8-sim-06','gt8-sim-07',
  'gt8-sim-09','gt8-sim-10','gt8-sim-11','gt8-sim-12','gt8-sim-13','gt8-sim-14','gt8-sim-15',
  'gt8-sim-17','gt8-sim-18','gt8-sim-19','gt8-sim-20','gt8-sim-21','gt8-sim-22','gt8-sim-23','gt8-sim-24',
  -- gt8-perm: 保留 01/05/09,删 9 道
  'gt8-perm-02','gt8-perm-03','gt8-perm-04','gt8-perm-06','gt8-perm-07','gt8-perm-08','gt8-perm-10','gt8-perm-11','gt8-perm-12',
  -- gt8-absent: 保留 01/06,删 10 道
  'gt8-absent-02','gt8-absent-03','gt8-absent-04','gt8-absent-05','gt8-absent-07','gt8-absent-08','gt8-absent-09','gt8-absent-10','gt8-absent-11','gt8-absent-12',
  -- gt8-notool: 保留 01/06,删 10 道
  'gt8-notool-02','gt8-notool-03','gt8-notool-04','gt8-notool-05','gt8-notool-07','gt8-notool-08','gt8-notool-09','gt8-notool-10','gt8-notool-11','gt8-notool-12',
  -- gt8-dir: 保留 01,删 3 道
  'gt8-dir-02','gt8-dir-03','gt8-dir-04',
  -- research: 保留 01/04,删 4 道
  'research-02','research-03','research-05','research-06',
  -- port: 保留 port-01,删 2 道
  'port-02','port-03',
  -- neg: 保留 empty-01/fail-01/partial-01,删 5 道
  'neg-empty-02','neg-fail-02','neg-partial-02','neg-timeout-01','neg-timeout-02'
]) AS case_id;

-- 按外键逆序删除
DELETE FROM touchstone.data_snapshots WHERE case_id IN (SELECT case_id FROM cases_to_delete);
DELETE FROM touchstone.case_variants WHERE case_id IN (SELECT case_id FROM cases_to_delete);
DELETE FROM touchstone.case_steps WHERE case_id IN (SELECT case_id FROM cases_to_delete);
DELETE FROM touchstone.case_versions WHERE case_id IN (SELECT case_id FROM cases_to_delete);
DELETE FROM touchstone.case_definitions WHERE id IN (SELECT case_id FROM cases_to_delete);

-- ══ 第二部分:新增多工具复杂用例 ══

INSERT INTO touchstone.case_definitions (id, title, status, current_version) VALUES
('cxm2-content-01',  '内容创作流水线(6工具)', 'ACTIVE', 1),
('cxm2-sales-01',    '客户跟进流程(6工具)', 'ACTIVE', 1),
('cxm2-audit-01',    '代码安全审计(6工具)', 'ACTIVE', 1),
('cxm2-event-01',    '团队活动策划(6工具)', 'ACTIVE', 1),
('cxm2-finance-01',  '季度财务审计(6工具)', 'ACTIVE', 1),
('cxm2-hr-01',       '新员工入职(6工具)', 'ACTIVE', 1),
('cxm2-migration-01','系统数据迁移(7工具)', 'ACTIVE', 1),
('cxm2-monitor-01',  '生产环境监控(6工具)', 'ACTIVE', 1)
ON CONFLICT DO NOTHING;

INSERT INTO touchstone.case_versions (case_id, version, message, scene, authenticated, allowed_tools, context_profile, token_budget, expected_checks, public, created_at) VALUES

('cxm2-content-01', 1,
 '帮我写一篇关于AI发展趋势的文章:先搜索最新的行业报告和新闻,提取关键数据和观点,对比不同来源的说法,翻译一段英文摘要,生成文章大纲,最后发邮件给编辑审阅',
 'general', true, '[]', 'simple', 32768,
 '{"category":"内容创作","expected_tools":["web.search","web.extract","web.compare_sources","translate.text","document.summarize","mail.send"],"expected_order":["web.search","web.extract","web.compare_sources","translate.text","document.summarize","mail.send"],"note":"6工具链:搜索→提取→对比→翻译→摘要→邮件"}',
 false, now()),

('cxm2-sales-01', 1,
 '帮我跟进一个重要客户:查CRM里这个客户的资料和历史沟通记录,搜索他们公司最近的新闻动态,看看有没有新的业务机会,写一封跟进邮件,创建下周的回访提醒,更新销售看板数据',
 'general', true, '[]', 'simple', 32768,
 '{"category":"客户跟进","expected_tools":["crm.search_customer","crm.get_account","web.search","mail.draft","calendar.create_reminder","dashboard.get"],"expected_order":["crm.search_customer","crm.get_account","web.search","mail.draft","calendar.create_reminder","dashboard.get"],"note":"6工具链:CRM→客户→搜索→邮件→提醒→看板"}',
 false, now()),

('cxm2-audit-01', 1,
 '帮我做一次代码安全审计:读取目标模块的源码,查看最近一个月的git提交记录,搜索这些代码涉及的已知CVE漏洞,对比修复前后的差异,检查是否有敏感信息泄露,提交一个安全工单',
 'general', true, '[]', 'simple', 32768,
 '{"category":"代码审计","expected_tools":["code.search","code.read","git.get_diff","web.search","compliance.check_text","support.create_ticket"],"expected_order":["code.search","code.read","git.get_diff","web.search","compliance.check_text","support.create_ticket"],"note":"6工具链:代码→阅读→变更→搜索→合规→工单"}',
 false, now()),

('cxm2-event-01', 1,
 '帮我策划下周五的团队建设活动:搜索附近的团建场地,对比几家的价格和评价,查大家的日历空闲时间,给全员发邀请邮件,预订场地,创建活动提醒',
 'general', true, '[]', 'simple', 32768,
 '{"category":"活动策划","expected_tools":["maps.search_places","product.compare","calendar.find_availability","mail.send","travel.search_hotels","calendar.create_event"],"expected_order":["maps.search_places","product.compare","calendar.find_availability","mail.send","travel.search_hotels","calendar.create_event"],"note":"6工具链:搜索→对比→日历→邮件→预订→日程"}',
 false, now()),

('cxm2-finance-01', 1,
 '季度财务审计:从数据库导出本季度的全部交易流水,按部门和类别做汇总统计,对比预算执行情况,筛出异常大额支出,生成审计报告,通知财务审批',
 'general', true, '[]', 'simple', 32768,
 '{"category":"财务审计","expected_tools":["database.query","data.export","spreadsheet.calculate","spreadsheet.find_rows","document.summarize","message.send"],"expected_order":["database.query","data.export","spreadsheet.calculate","spreadsheet.find_rows","document.summarize","message.send"],"note":"6工具链:查询→导出→计算→筛选→摘要→通知"}',
 false, now()),

('cxm2-hr-01', 1,
 '新员工下周一入职,帮我准备好一切:搜索公司的入职流程文档,查看IT系统的设备清单,给新员工发欢迎邮件和入职指引,安排导师见面会,创建第一周的任务清单,设置入职提醒',
 'general', true, '[]', 'simple', 32768,
 '{"category":"员工入职","expected_tools":["knowledge.search","device.list","mail.send","calendar.create_event","task.create","calendar.create_reminder"],"expected_order":["knowledge.search","device.list","mail.send","calendar.create_event","task.create","calendar.create_reminder"],"note":"6工具链:知识→设备→邮件→日历→任务→提醒"}',
 false, now()),

('cxm2-migration-01', 1,
 '系统要做数据迁移:先列出旧库的全部表和结构,导出需要迁移的数据,转换数据格式,写入新数据库,验证数据完整性,生成迁移报告,通知运维团队',
 'general', true, '[]', 'simple', 32768,
 '{"category":"数据迁移","expected_tools":["database.list_tables","database.describe_table","data.export","data.transform","database.query","document.summarize","message.send"],"expected_order":["database.list_tables","database.describe_table","data.export","data.transform","database.query","document.summarize","message.send"],"note":"7工具链:列表→结构→导出→转换→验证→报告→通知"}',
 false, now()),

('cxm2-monitor-01', 1,
 '生产环境出了告警:查看当前系统监控面板,检查CI/CD流水线状态,搜索相关错误信息的解决方案,查看最近的代码变更是否引入了问题,分析关键性能指标,创建事件工单跟踪',
 'general', true, '[]', 'simple', 32768,
 '{"category":"生产监控","expected_tools":["dashboard.get","ci.get_status","web.search","git.get_diff","metrics.get","support.create_ticket"],"expected_order":["dashboard.get","ci.get_status","web.search","git.get_diff","metrics.get","support.create_ticket"],"note":"6工具链:监控→CI→搜索→变更→指标→工单"}',
 false, now())
ON CONFLICT DO NOTHING;

-- 变体
INSERT INTO touchstone.case_variants (case_id, case_version, variant_id, title, context_strategy, token_budget, data_fixture, public)
SELECT v.case_id, v.version, 'default', '默认变体', 'budgeted', 32768,
       jsonb_build_object('context_items', '[]'), false
FROM touchstone.case_versions v
WHERE v.case_id LIKE 'cxm2-%' AND v.version = 1
ON CONFLICT DO NOTHING;

-- 快照
INSERT INTO touchstone.data_snapshots (id, case_id, case_version, variant_id, fixture_version, market_as_of, content, source_hash)
SELECT v.case_id || ':default:fixture-v1', v.case_id, v.version, 'default', 1, now(),
       jsonb_build_object('note', '多工具复杂用例;冻结集 mock-eval-v1'),
       'sha256:' || encode(digest(v.case_id || 'cxm2-v1', 'sha256'), 'hex')
FROM touchstone.case_versions v
WHERE v.case_id LIKE 'cxm2-%' AND v.version = 1
ON CONFLICT DO NOTHING;

-- 登记
INSERT INTO touchstone.database_changes (script_name, description) VALUES
('20260823-trim-simple-add-complex.sql', '题库重构:精简63道单工具用例+新增8道多工具复杂用例(cxm2-*,6-7工具链),非金融主导')
ON CONFLICT DO NOTHING;

COMMIT;
