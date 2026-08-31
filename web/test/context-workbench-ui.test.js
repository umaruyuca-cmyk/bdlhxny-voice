import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

// 上下文工作台前端接线契约:渲染逻辑必须消费后端真实字段,
// 不允许退化为硬编码或估算展示(需求 §19/§23 P1)。

const workbenchJs = await readFile(
  new URL("../public/experiment/context-workbench.js", import.meta.url),
  "utf8",
);
const buildPage = await readFile(
  new URL("../public/experiment/context-build.html", import.meta.url),
  "utf8",
);
const workbenchPage = await readFile(
  new URL("../public/experiment/context-workbench.html", import.meta.url),
  "utf8",
);
const workbenchCss = await readFile(
  new URL("../public/experiment/context-workbench.css", import.meta.url),
  "utf8",
);

test("Agent 运行卡渲染工具循环真实字段(步数/停止原因/工具调用)", () => {
  assert.match(workbenchJs, /run\.steps/, "必须渲染模型往返步数 run.steps");
  assert.match(workbenchJs, /run\.stop_reason/, "必须渲染停止原因 run.stop_reason");
  assert.match(workbenchJs, /run\.tool_calls/, "必须渲染工具调用记录 run.tool_calls");
  assert.match(workbenchJs, /FINAL_ANSWER/, "停止原因需映射人读文案(FINAL_ANSWER)");
  assert.match(workbenchJs, /MAX_AGENT_STEPS/, "停止原因需映射人读文案(MAX_AGENT_STEPS)");
  assert.match(workbenchJs, /agent_tool_calls/, "指标需消费分项计量 agent_tool_calls");
  assert.match(workbenchJs, /run\.estimated/, "估算口径必须显式标注,不得冒充精确值");
});

test("构建详情页 Agent 运行说明与工具循环底座口径一致", () => {
  assert.match(buildPage, /Tool Calling/, "说明需注明经统一原生 Tool Calling 底座执行");
  assert.match(buildPage, /多轮工具调用/, "说明需注明支持多轮工具调用");
  assert.match(buildPage, /不触网/, "说明需注明工具返回来自冻结记录,不触网");
});

test("事件分页接线:工作台按游标续载,构建页按窗口展示", () => {
  // 工作台:消费后端 next_cursor/total,不再一次拉取整个长会话
  assert.match(workbenchJs, /next_cursor/, "工作台必须消费后端分页游标 next_cursor");
  assert.match(workbenchJs, /加载更多事件/, "工作台需提供按页续载入口");
  assert.match(workbenchJs, /EVENT_PAGE_SIZE/, "工作台分页页大小需显式常量");
  assert.ok(!/events\?limit=200/.test(workbenchJs), "工作台不得再用一次 200 条拉全长会话");
  assert.match(workbenchPage, /id="eventPager"/, "工作台页需要分页条容器");
  // 构建页:工件事件为冻结快照,按窗口分批渲染
  assert.match(workbenchJs, /eventLimit/, "构建页事件需按窗口分批展示");
  assert.match(workbenchJs, /显示更多事件/, "构建页需提供窗口扩展入口");
  assert.match(workbenchJs, /ensureEventWindow/, "来源高亮不得因分页失效,需自动扩窗");
  assert.match(buildPage, /id="eventPager"/, "构建详情页需要分页条容器");
});

test("窄屏纵向布局:链路与步骤条在窄屏单列堆叠", () => {
  assert.match(workbenchCss, /@media \(max-width: 900px\)/, "需要 900px 窄屏断点(网格纵向)");
  assert.match(workbenchCss, /@media \(max-width: 560px\)/, "需要 560px 极窄断点(步骤条单列)");
  const narrow = workbenchCss.match(/@media \(max-width: 560px\)[\s\S]*?\n\}/)[0];
  assert.match(narrow, /\.context-steps\s*\{\s*grid-template-columns:\s*1fr/, "极窄屏步骤条必须单列");
});

test("下载/复制经权限校验并写审计(RBAC 接线)", () => {
  assert.match(workbenchJs, /CONTEXT_CONTENT_COPY/, "复制动作必须申报审计 CONTEXT_CONTENT_COPY");
  assert.match(workbenchJs, /artifactDownload/, "构建页需提供冻结工件下载入口");
  assert.match(workbenchJs, /下载与复制均记录访问审计/, "下载/复制需明示审计口径");
  // 下载必须重新走服务端工件接口(服务端审计),不得直接用页面缓存另存
  assert.match(
    workbenchJs,
    /artifactDownload[\s\S]{0,600}EXP\.get\("\/api\/v1\/context\/builds\/" \+ encodeURIComponent\(buildId\) \+ "\/artifact"\)/,
    "下载需经服务端工件接口(权限校验+审计)",
  );
});

test("工作台审计与运维脱敏视图接线", () => {
  assert.match(workbenchPage, /id="auditPanel"/, "工作台需要本人审计区块");
  assert.match(workbenchPage, /id="opsPanel"/, "工作台需要运维脱敏视图区块");
  assert.match(workbenchPage, /运维身份不能读取任何所有者原文/, "运维区块需注明脱敏边界");
  assert.match(workbenchJs, /\/api\/v1\/context\/audit/, "需读取本人审计事件");
  assert.match(workbenchJs, /\/api\/v1\/context\/ops\/builds/, "需读取运维脱敏构建列表");
  assert.match(workbenchJs, /owner_ref/, "运维视图只展示脱敏所有者引用");
});

test("P2 跨构建趋势与摘要质量抽检接线", () => {
  assert.match(workbenchPage, /id="trendPanel"/, "工作台需要跨构建趋势区块");
  assert.match(workbenchPage, /id="qualityPanel"/, "工作台需要摘要质量抽检区块");
  assert.match(workbenchJs, /\/build-trend/, "需消费跨构建趋势端点");
  assert.match(workbenchJs, /segment-quality/, "需消费摘要质量抽检端点");
  assert.match(workbenchJs, /compression_rate/, "趋势需展示真实压缩率 compression_rate");
  assert.match(workbenchPage, /不调用 LLM/, "抽检区块需注明确定性校验口径");
  assert.match(workbenchJs, /problems/, "抽检需展示逐段问题码");
});

test("语义抽检结果接线(定时分析任务产出,页面只读)", () => {
  assert.match(workbenchJs, /payload\.semantic/, "抽检区块需消费 semantic 持久化结果");
  assert.match(workbenchJs, /missing_facts/, "语义评审需展示遗漏清单");
  assert.match(workbenchJs, /hallucinations/, "语义评审需展示编造清单");
  assert.match(workbenchJs, /评审失败/, "ERROR 评审需如实展示失败而非通过");
  assert.match(workbenchJs, /后台定时分析任务产出/, "需注明语义结果来源,页面不触发 LLM");
});

test("运维定时分析报告区块与手动触发接线", () => {
  assert.match(workbenchPage, /id="opsAnalysisPanel"/, "需要运维分析报告区块");
  assert.match(workbenchPage, /id="analysisRunButton"/, "需要手动触发按钮");
  assert.match(workbenchPage, /会产生评审 LLM 调用/, "触发按钮需注明会产生 LLM 调用");
  assert.match(workbenchJs, /\/api\/v1\/context\/ops\/analysis/, "需读取分析运行与报告");
  assert.match(workbenchJs, /ops\/analysis\/run/, "手动触发需调用分析运行端点");
  assert.match(workbenchJs, /threshold_groups/, "报告需展示阈值/预算分组对照");
  assert.match(workbenchJs, /token_savings_per_generation_call/, "报告需展示每次调用节省(成本收益)");
  assert.match(workbenchJs, /样本不足/, "相关性样本不足需如实标注,不硬算");
});
