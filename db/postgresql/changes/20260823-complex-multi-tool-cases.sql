-- 20260823-complex-multi-tool-cases.sql
-- 复杂多工具用例(8 道):每题期望 7-8 个工具协作,非金融主导。
--
-- 设计原则:
--   * 场景=general(SCENE_TOOLSETS 新增,含全部工具组)
--   * expected_tools 为金标工具集合(7-8 个)
--   * expected_order 为期望调用序(链式推理)
--   * 冻结集:mock-eval-v1(通用正例,基础键覆盖全部 96 工具)
--   * 幂等:ON CONFLICT DO NOTHING
-- 回滚:按 cxm-% 前缀 DELETE(见尾注释)。

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '2min';

-- ── 用例定义 ──
INSERT INTO touchstone.case_definitions (id, title, status, current_version) VALUES
('cxm-travel-01',  '出差全面准备(7工具链)', 'ACTIVE', 1),
('cxm-competitor-01', '竞品产品分析(7工具链)', 'ACTIVE', 1),
('cxm-data-01',    '季度数据分析报告(7工具链)', 'ACTIVE', 1),
('cxm-learn-01',   '机器学习学习规划(7工具链)', 'ACTIVE', 1),
('cxm-project-01', '新项目启动准备(7工具链)', 'ACTIVE', 1),
('cxm-legal-01',   '服务合同审查(7工具链)', 'ACTIVE', 1),
('cxm-market-01',  '远程办公工具调研(7工具链)', 'ACTIVE', 1),
('cxm-devops-01',  '服务器性能诊断(7工具链)', 'ACTIVE', 1)
ON CONFLICT DO NOTHING;

-- ── 用例版本(v1) ──
INSERT INTO touchstone.case_versions (case_id, version, message, scene, authenticated, allowed_tools, context_profile, token_budget, expected_checks, public, created_at) VALUES

('cxm-travel-01', 1,
 '下周三我要去上海见客户,帮我全面准备:查上海那天的天气、看我的日历找出空闲时间段、搜索客户公司的背景资料、查航班选项、找附近的酒店、规划机场到市区的交通路线',
 'general', true, '[]', 'simple', 32768,
 '{"category":"出差准备","expected_tools":["weather.get_forecast","calendar.find_availability","web.search","travel.search_transport","travel.search_hotels","maps.search_places","maps.get_directions"],"expected_order":["weather.get_forecast","calendar.find_availability","web.search","travel.search_transport","travel.search_hotels","maps.search_places","maps.get_directions"],"note":"7工具链:天气→日历→搜索→交通→酒店→地点→路线"}',
 false, now()),

('cxm-competitor-01', 1,
 '帮我做一份竞品分析:搜索市场上同类产品的最新动态、对比它们的核心功能差异、查看它们在GitHub上的开源项目活跃度、了解各自的定价策略、整理成结构化的对比报告',
 'general', false, '[]', 'simple', 32768,
 '{"category":"竞品分析","expected_tools":["web.search","web.extract","product.compare","github.search_issues","product.get_price","document.compare","notes.search"],"note":"7工具链:搜索→提取→对比→GitHub→定价→文档→笔记"}',
 false, now()),

('cxm-data-01', 1,
 '季度结束了,帮我做数据分析报告:先看数据库里有哪些表、查询本季度的销售数据、导出成表格、计算汇总指标、创建可视化图表、生成摘要报告、更新团队看板',
 'general', true, '[]', 'simple', 32768,
 '{"category":"数据分析","expected_tools":["database.list_tables","database.query","data.export","spreadsheet.calculate","spreadsheet.create_chart","document.summarize","dashboard.get"],"note":"7工具链:库表→查询→导出→计算→图表→摘要→看板"}',
 false, now()),

('cxm-learn-01', 1,
 '我想系统学习机器学习,帮我制定学习计划:搜索最新的学习路线和推荐教程、了解核心概念、查找相关论文和资料、制定每周的学习任务和目标、设置日历提醒、创建自测题',
 'general', true, '[]', 'simple', 32768,
 '{"category":"学习规划","expected_tools":["web.search","web.extract","learning.explain_topic","knowledge.search","task.create","calendar.create_event","quiz.create"],"note":"7工具链:搜索→提取→概念→知识→任务→日历→自测"}',
 false, now()),

('cxm-project-01', 1,
 '新项目要启动了,帮我做好准备工作:查团队核心成员的联系方式、搜索公司内部类似项目的经验文档、检查CI流水线当前状态、创建项目看板、分配首批任务、发邮件通知所有相关人',
 'general', true, '[]', 'simple', 32768,
 '{"category":"项目启动","expected_tools":["contacts.search","knowledge.search","ci.get_status","project.get_status","task.create","mail.send","dashboard.get"],"note":"7工具链:联系人→知识→CI→项目→任务→邮件→看板"}',
 false, now()),

('cxm-legal-01', 1,
 '帮我审查这份服务合同:提取其中的关键条款和风险点、与标准合同模板对比差异、搜索相关法规条文、查类似案例的判例、标记合规风险、生成审查意见',
 'general', false, '[]', 'simple', 32768,
 '{"category":"合同审查","expected_tools":["file.extract_text","contract.extract_terms","legal.compare_clauses","web.search","citation.lookup","compliance.check_text","document.compare"],"note":"7工具链:提取→条款→对比→法规→判例→合规→文档"}',
 false, now()),

('cxm-market-01', 1,
 '帮我调研远程办公工具市场:搜索当前主流产品、对比它们的功能特点和使用体验、查看用户评价和口碑、分析各自的定价模式、找最新的行业分析报告、核实信息时效性',
 'general', false, '[]', 'simple', 32768,
 '{"category":"市场调研","expected_tools":["web.search","product.search","product.compare","web.extract","web.compare_sources","research.deep_search","web.check_freshness"],"note":"7工具链:搜索→产品→对比→提取→比较→深搜→时效"}',
 false, now()),

('cxm-devops-01', 1,
 '服务器性能下降了,帮我排查:查看当前系统监控状态、检查CI/CD流水线是否有异常、搜索可能的性能瓶颈原因、查看最近的代码变更记录、搜索相关技术Issue、分析关键指标',
 'general', true, '[]', 'simple', 32768,
 '{"category":"性能诊断","expected_tools":["dashboard.get","ci.get_status","web.search","git.get_diff","github.search_issues","metrics.get","support.search_tickets"],"note":"7工具链:监控→CI→搜索→变更→Issue→指标→工单"}',
 false, now())
ON CONFLICT DO NOTHING;

-- ── 用例变体(default) ──
INSERT INTO touchstone.case_variants (case_id, case_version, variant_id, title, context_strategy, token_budget, data_fixture, public)
SELECT v.case_id, v.version, 'default', '默认变体', 'budgeted', 0,
       jsonb_build_object('context_items', '[]'), false
FROM touchstone.case_versions v
WHERE v.case_id LIKE 'cxm-%' AND v.version = 1
ON CONFLICT DO NOTHING;

-- ── 数据快照 ──
INSERT INTO touchstone.data_snapshots (id, case_id, case_version, variant_id, fixture_version, market_as_of, content, source_hash)
SELECT v.case_id || ':default:fixture-v1', v.case_id, v.version, 'default', 1, now(),
       jsonb_build_object('note', '复杂多工具用例;冻结集 mock-eval-v1'),
       'sha256:' || encode(digest(v.case_id || 'cxm-v1', 'sha256'), 'hex')
FROM touchstone.case_versions v
WHERE v.case_id LIKE 'cxm-%' AND v.version = 1
ON CONFLICT DO NOTHING;

-- ── 登记 ──
INSERT INTO touchstone.database_changes (script_name, description) VALUES
('20260823-complex-multi-tool-cases.sql', '复杂多工具用例 8 道(cxm-*):每题 7 工具协作链,场景=general,非金融主导')
ON CONFLICT DO NOTHING;

COMMIT;

-- 回滚参考(按依赖逆序):
-- DELETE FROM touchstone.data_snapshots WHERE case_id LIKE 'cxm-%';
-- DELETE FROM touchstone.case_variants WHERE case_id LIKE 'cxm-%';
-- DELETE FROM touchstone.case_versions WHERE case_id LIKE 'cxm-%';
-- DELETE FROM touchstone.case_definitions WHERE id LIKE 'cxm-%';
