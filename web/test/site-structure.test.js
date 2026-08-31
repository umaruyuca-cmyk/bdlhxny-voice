import { readFile } from "node:fs/promises";
import { test } from "node:test";
import assert from "node:assert/strict";
import { REDIRECTS, redirectFor } from "../scripts/redirect-map.mjs";

/**
 * 站点结构契约(原型 v2 · 前端信息架构 §三):顶部五导航(公告 / 实验 / 我的测试 / 数据资产 / 文档),
 * 由 docs.js 注入所有页面;旧侧栏外壳由 CSS 隐藏,不再作为结构要求。
 * 公告单页(空框架 + 静态事实卡)+ 数据资产 /assets(用例库/工具目录/长上下文库)+
 * 文档 /docs(系统与复现/引擎与治理/上下文压缩/评判与口径/数据与运维)+
 * 实验 /experiment(模板中心为根;发起 run 与批次详情 batch 为二级页,带返回上级入口)。
 */

const NAV_HREFS = ["/", "/experiment/", "/test/", "/assets/", "/docs/"];

/** P1-2 薄页合并 + P1-3 运行记录统一后的页面清单；含上下文工作台两页。 */
const SITE_PAGES = [
  "/index.html",
  "/assets/index.html",
  "/docs/index.html",
  "/about/index.html", "/about/banks.html", "/about/repo.html",
  "/showcase/index.html", "/showcase/tools.html",
  "/experiment/index.html", "/experiment/compression.html",
  "/experiment/run.html", "/experiment/batch.html", "/experiment/series.html",
  "/experiment/context-workbench.html", "/experiment/context-build.html",
  "/test/index.html",
  "/context/index.html", "/context/library.html", "/context/design.html", "/context/results.html",
  "/judging/index.html", "/judging/judge.html", "/judging/invalid.html",
  "/engine/index.html", "/engine/catalog.html", "/engine/governance.html",
  "/ops/index.html", "/ops/run-api.html", "/ops/artifacts.html", "/ops/roadmap.html",
];

/** 实验模块页:允许匿名公开接口 + 同源所有者通道白名单(与 nginx/dev-server 反代同口径)。 */
const EXPERIMENT_PAGES = [
  "/experiment/index.html", "/experiment/compression.html",
  "/experiment/run.html", "/experiment/batch.html", "/experiment/series.html",
  "/experiment/context-workbench.html", "/experiment/context-build.html",
  "/test/index.html",
];
const EXPERIMENT_API_OK = /\/api\/v1\/(public(\/|$)|(login|logout|llm-config\/test|experiment-templates|template-batches|experiment-series|statistics|batches|jobs|runs|context)(\/|\?|["'`]|$))/;

async function readPage(page) {
  return readFile(new URL(`../public${page}`, import.meta.url), "utf8");
}

/** 旧地址只保留跳转:showcase 旧页回公告页,被合并的薄页(P1-2)与批次列表(P1-3)跳合并目标 */
const REDIRECT_ONLY_PAGES = [
  "/showcase/results.html", "/showcase/runs.html",
  "/engine/loading.html", "/engine/tools.html", "/engine/guardrail.html",
  "/judging/metrics.html", "/ops/deploy.html", "/experiment/batches.html",
];

test("旧展示地址保留跳转页(不重复公告内容)", async () => {
  for (const page of REDIRECT_ONLY_PAGES) {
    const html = await readPage(page);
    assert.match(html, /http-equiv="refresh"/, `${page} 需为跳转页`);
    assert.match(html, /href="\/[^"]*"/, `${page} 需提供继续查看链接`);
  }
});

test("模块页齐备,共享静态外壳(顶栏 wordmark + 构建期静态五导航 + 角色标签)", async () => {
  assert.equal(SITE_PAGES.length, 30);
  const sharedJs = await readFile(new URL("../public/docs/docs.js", import.meta.url), "utf8");
  for (const label of ["公告", "实验", "我的测试", "数据资产", "文档"]) {
    assert.ok(sharedJs.includes(`"${label}"`), `docs.js 高亮逻辑缺少模块标签「${label}」`);
  }
  assert.match(sharedJs, /role-label/, "docs.js 注入角色标签(匿名访客/登录所有者)");
  for (const page of SITE_PAGES) {
    const html = await readPage(page);
    assert.match(html, /docs\.css/, `${page} 必须引用 docs.css`);
    assert.match(html, /docs\.js/, `${page} 必须引入共享导航脚本`);
    assert.match(html, /class="brand"/, `${page} 顶栏必须有品牌行`);
    // P2-1:主导航静态化——HTML 自带五导航,JS 禁用也可导航
    assert.match(html, /<nav class="site-nav"/, `${page} 顶栏含静态五导航`);
    for (const href of NAV_HREFS) {
      assert.ok(html.includes(`href="${href}"`), `${page} 静态导航缺少模块 ${href}`);
    }
    assert.ok(html.includes("topbar-gh"), `${page} 顶栏需要 GitHub 外链`);
    assert.ok(html.includes("topbar-login"), `${page} 顶栏需要登录入口`);
  }
});

test("二级页面提供返回上级入口,无导航死胡同(IA §二.8)", async () => {
  const backLinks = {
    "/experiment/run.html": 'class="crumb" href="/experiment/"',
    "/experiment/batch.html": 'class="crumb" href="/test/"', // P1-3:批次详情返回运行记录
    "/experiment/series.html": 'class="crumb" href="/experiment/"',
  };
  for (const [page, probe] of Object.entries(backLinks)) {
    const html = await readPage(page);
    if (probe) assert.ok(html.includes(probe), `${page} 需要返回上级入口`);
  }
});

test("详情页使用正文居中、右侧页内目录的标准阅读比例", async () => {
  const css = await readFile(new URL("../public/docs/docs.css", import.meta.url), "utf8");
  assert.match(css, /\.topbar-actions\s*{[^}]*margin-left:\s*auto;/s, "顶栏动作需要贴右");
  assert.match(
    css,
    /\.detail-layout\s*{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+176px;/s,
    "桌面端正文应在左、页内目录应在右",
  );
  assert.match(css, /\.page-toc\s*{[^}]*grid-column:\s*2;/s, "页内目录需放入右栏");
  assert.match(css, /@media \(max-width:\s*1240px\)/, "中等屏幕需要收起三栏布局");
});

test("公告为独立单页:eyebrow/事实卡/单一空态面板,系统说明并入「系统概览」", async () => {
  const announce = await readPage("/index.html");
  assert.match(announce, /class="eyebrow"/, "公告页使用原型 eyebrow 版式");
  assert.match(announce, /stat-row/, "公告页有静态事实卡");
  assert.match(announce, /panel-dashed/, "公告页有虚线空态面板");
  for (const moved of ["id=\"architecture\"", "id=\"banks\"", "id=\"repo\""]) {
    assert.ok(!announce.includes(moved), `公告页不应再包含系统说明节 ${moved}(已迁入系统概览)`);
  }
  const about = await readPage("/about/index.html");
  assert.ok(about.includes('id="about"') && about.includes('id="architecture"'), "系统定位与架构在系统概览模块");
  const banks = await readPage("/about/banks.html");
  assert.ok(banks.includes('id="banks"'), "题库说明在系统概览模块");
  const repo = await readPage("/about/repo.html");
  assert.ok(repo.includes('id="repo"') && repo.includes('id="gates"'), "仓库与门禁在系统概览模块");
});

test("五模块导航静态化,JS 只做高亮增强(P2-1)", async () => {
  const sharedJs = await readFile(new URL("../public/docs/docs.js", import.meta.url), "utf8");
  assert.match(sharedJs, /querySelector\("nav\.site-nav"\)/, "docs.js 复用页面静态导航(缺省兜底注入)");
  assert.doesNotMatch(sharedJs, /nav\.className = "site-nav";\s*nav\.innerHTML[^(]*\)\.join\(""\);\s*inner\.insertBefore\(nav/, "docs.js 不再无条件创建主导航");
  for (const page of ["/index.html", "/assets/index.html", "/docs/index.html"]) {
    const html = await readPage(page);
    assert.match(html, /src="\/docs\/docs\.js"/, `${page} 依赖共享导航脚本`);
  }
  const assets = await readPage("/assets/index.html");
  for (const href of ["/cases/", "/tools/", "/context/library"]) {
    assert.ok(assets.includes(`href="${href}"`), `数据资产页缺少入口 ${href}`);
  }
  const docsHome = await readPage("/docs/index.html");
  for (const href of ["/about/", "/engine/", "/context/", "/judging/", "/ops/"]) {
    assert.ok(docsHome.includes(`href="${href}"`), `文档页缺少入口 ${href}`);
  }
});

test("品牌按原型呈现:wordmark Touchstone / Agent Eval,无主题化文案", async () => {
  for (const page of SITE_PAGES) {
    const html = await readPage(page);
    assert.doesNotMatch(html, /タカラダ|グリッド|ダイナゼノン|エヴァンゲリオン/, `${page} 不得出现主题化文案`);
  }
  const announce = await readPage("/index.html");
  assert.match(announce, /wordmark/, "品牌 wordmark 由顶栏承载");
});

test("机甲主题子页 /home 已下线:301 回公告页,服务器不再服务该前缀", async () => {
  await assert.rejects(() => readFile(new URL("../public/home/index.html", import.meta.url)), "/home 页面应已删除");
  assert.equal(redirectFor("/home"), "/");
  assert.equal(redirectFor("/home/"), "/");
  assert.equal(redirectFor("/home/index"), "/");

  const devServer = await readFile(new URL("../dev-server.js", import.meta.url), "utf8");
  assert.doesNotMatch(devServer, /"\/home"/, "dev-server 不再服务 /home 前缀");

  const nginx = await readFile(new URL("../nginx.conf", import.meta.url), "utf8");
  assert.match(nginx, /location = \/home \{ return 301 \/\; \}/, "nginx 将 /home 301 回公告页");
  assert.doesNotMatch(nginx, /location \/home\/ \{\s*try_files/, "nginx 不再服务 /home/ 目录");
  assert.match(nginx, /location \/about\//, "nginx 需服务系统概览模块前缀");
});

test("旧路径 301:redirect-map 与两台服务器一致;/docs/ 与 /assets/ 为模块首页", async () => {
  assert.equal(redirectFor("/docs/cases"), "/cases/");
  assert.equal(redirectFor("/docs/cases.html"), "/cases/");
  assert.equal(redirectFor("/showcase/context"), "/context/results");
  assert.equal(redirectFor("/docs"), null, "/docs 为文档模块首页,不再 301");
  assert.equal(redirectFor("/docs/docs.css"), null, "静态资产不重定向");
  // P1-2/P1-3:被合并薄页与批次列表的旧地址全部 301 到合并目标
  assert.equal(redirectFor("/engine/loading"), "/engine/");
  assert.equal(redirectFor("/engine/tools"), "/engine/catalog");
  assert.equal(redirectFor("/engine/guardrail"), "/engine/governance");
  assert.equal(redirectFor("/judging/metrics"), "/judging/");
  assert.equal(redirectFor("/ops/deploy"), "/ops/");
  assert.equal(redirectFor("/experiment/batches"), "/test/");
  assert.equal(redirectFor("/docs/tools"), "/engine/catalog", "/docs/tools 指向合并后的资源与工具页");

  const devServer = await readFile(new URL("../dev-server.js", import.meta.url), "utf8");
  assert.match(devServer, /redirectFor/, "dev-server 需接入 301 映射");
  assert.match(devServer, /301/, "dev-server 需以 301 重定向");
  assert.match(devServer, /"\/assets", "\/docs"/, "dev-server 需服务 /assets 与 /docs 模块前缀");

  const nginx = await readFile(new URL("../nginx.conf", import.meta.url), "utf8");
  for (const [from, to] of REDIRECTS) {
    if (from.endsWith("/")) continue; // 目录索引形式由等值规则覆盖
    assert.ok(
      nginx.includes(`location = ${from} { return 301 ${to}; }`),
      `nginx 缺少 301:${from} → ${to}`,
    );
  }
  assert.match(nginx, /location \/docs\/ \{[\s\S]*?\/docs\/index\.html/, "nginx /docs/ 回落到文档模块首页");
  assert.match(nginx, /location \/assets\/ \{[\s\S]*?\/assets\/index\.html/, "nginx 服务数据资产模块");
  assert.match(nginx, /location \/experiment\//, "nginx 需服务新模块前缀");
  assert.match(nginx, /location \/ops\//, "nginx 需服务新模块前缀");
});

test("公开页零后端依赖(实验模块页允许公开测试接口与所有者通道白名单)", async () => {
  for (const page of SITE_PAGES) {
    const html = await readPage(page);
    const isExperiment = EXPERIMENT_PAGES.includes(page);
    if (page === "/ops/run-api.html") {
      assert.doesNotMatch(html, /fetch\(|XMLHttpRequest|axios/, "ops/run-api 文档页也不得发起真实后端调用");
    } else if (isExperiment) {
      // 同源契约(前后端对接文档 §2):公开接口 + 所有者通道白名单,其余维护者端点禁止
      const offenders = [...html.matchAll(/\/api\/v1\/[a-z\-]+(\/[a-z\-]+)?/g)].map((m) => m[0]);
      for (const api of offenders) {
        assert.ok(EXPERIMENT_API_OK.test(api), `${page} 引用了白名单之外的端点:${api}`);
      }
    } else {
      assert.doesNotMatch(html, /\/api\/v1\//, `${page} 不得出现后端 API`);
    }
    // 任意文本输入全站禁止;选择控件(勾选/单选/下拉)仅实验模块页允许;
    // showcase 空框架页的 disabled 占位控件(display-only)豁免
    assert.doesNotMatch(html, /<textarea/, `${page} 不得出现文本域`);
    assert.doesNotMatch(html, /type="text"/, `${page} 不得出现任意文本输入`);
    const inertAllowed = isExperiment || page.startsWith("/showcase/");
    if (!inertAllowed) {
      assert.doesNotMatch(html, /<input|<form|<select/, `${page} 不得出现输入控件`);
    } else {
      assert.doesNotMatch(html, /<form/, `${page} 不得出现表单提交`);
    }
    // 会话读写收敛在共享脚本(docs.js/experiment.js),页面 HTML 不内联
    assert.doesNotMatch(html, /sessionStorage|localStorage/, `${page} 无内联会话读写`);
    assert.doesNotMatch(html, /href="\/lab/, `${page} 不得硬链接运行台(公开镜像物理排除 /lab)`);
    for (const url of [...html.matchAll(/fetch\((["'])([^"']+)\1/g)].map((m) => m[2])) {
      const allowed = url.startsWith("/showcase-data/") ||
        (isExperiment && EXPERIMENT_API_OK.test(url));
      assert.ok(allowed, `${page} 的 fetch 只允许 /showcase-data/(实验模块页另允许契约 API):${url}`);
    }
  }
});

test("实验模块:模板中心为唯一入口;发起与详情为二级页(原型 §实验)", async () => {
  const index = await readPage("/experiment/index.html");
  assert.match(index, /实验模板/, "实验根页是模板中心");
  assert.match(index, /唯一自变量|仅改变一个受控变量/, "模板中心写明单变量口径");
  assert.match(index, /loadTemplates|test-options|experiment-templates/, "模板中心从模板注册表读数据");
  assert.match(index, /\/experiment\/run\?template=/, "模板卡片进入统一发起页");
  assert.match(index, /selectedCase/, "从用例库进入模板中心时保留已选题号");
  assert.match(index, /运行记录/, "实验中心把历史运行指到统一运行记录页");

  // 模板卡片文案:规范中文展示名 + 变体标签映射(P1-4:技术口径收进折叠区)
  const experimentJs = await readFile(new URL("../public/docs/experiment.js", import.meta.url), "utf8");
  assert.match(experimentJs, /formal-single-variable/, "classification 兼容 real 注册表值");
  assert.match(experimentJs, /长上下文记忆策略对比/, "模板标题有中文展示名映射");
  assert.match(experimentJs, /完整上下文/, "变体标签有中文展示名映射");
  assert.match(experimentJs, /tpl-detail/, "模板 ID/变量路径收进技术详情折叠区");
  assert.match(experimentJs, /special-cross/, "徽章只表达例外(专项交叉),正式单变量不逐卡重复");

  // 统一发起页:plan → 确认 → 提交;变体不可编辑;预估条必须先显示
  const run = await readPage("/experiment/run.html");
  assert.match(run, /template-batches\/plan/, "发起页所有者路径接 plan 预估");
  assert.match(run, /精确运行数/, "预估条必须显示精确运行数");
  assert.match(run, /变体由模板定义,任何角色不可编辑/, "变体数组任何角色不可编辑");
  assert.match(run, /高级设置\(仅所有者/, "高级设置仅所有者渲染");
  assert.match(run, /受控变量/, "左栏展示受控变量");
  assert.match(run, /断开页面不影响后台任务/, "提交前提示断页不中断");

  // 批次详情:口径卡 + 请求/生效参数 + 按变量分组;哈希 8 位短显;返回运行记录
  const batch = await readPage("/experiment/batch.html");
  assert.match(batch, /实验口径/, "批次详情有口径卡");
  assert.match(batch, /请求参数与实际生效参数/, "批次详情有请求/生效对照表");
  assert.match(batch, /按受控变量分组/, "结果按模板变量分组(不按 agent_mode)");
  assert.match(batch, /个人测试 · 非正式结果/, "匿名任务视图标记非正式结果");
  assert.match(batch, /E\.hashChip/, "批次哈希统一用 hashChip 组件");
  assert.match(experimentJs, /slice\(0, 8\)/, "哈希 chip 8 位短显(共享组件)");
  assert.match(batch, /\/api\/v1\/runs\//, "所有者视图可下钻单次运行明细");
  assert.match(batch, /无模板/, "无模板批次挂中性标记");
  // 单次运行明细时间线(可观测性设计 §8):摘要 + 筛选页签 + 折叠证据
  assert.match(batch, /renderRunDetail/, "单次运行明细走时间线渲染函数");
  // 匿名任务详情页:逐步明细(模型调用 LLM 返回 + 工具调用交织)
  assert.match(batch, /runStepTimelineHtml/, "匿名任务详情页渲染逐步时间线");
  assert.match(batch, /model_calls/, "逐步时间线消费 model_calls(模型调用证据)");
  assert.match(batch, /responseSummary/, "逐步时间线展示 LLM 返回摘录(responseSummary)");
  assert.match(batch, /resultSummary/, "工具步骤展示模型所见的工具返回摘要");
  assert.match(batch, /早于逐步明细功能/, "旧任务无逐步数据时如实说明,不显示空白");
  assert.match(batch, /run-timeline/, "明细含时间线容器");
  assert.match(batch, /detail\.timeline/, "时间线优先消费 detail.timeline(全局事件序号交织)");
  assert.match(batch, /detail-tabs/, "明细含筛选页签(全部/模型/工具/治理/上下文)");
  assert.match(batch, /paramStateTable/, "模型调用展示参数三态(请求值/实际发送/状态)");
  assert.match(batch, /unsupported_params/, "不支持的参数展示原因(三态口径)");
  assert.match(batch, /copy-json/, "JSON 块提供复制按钮");
  assert.match(batch, /E\.esc\(JSON\.stringify\(/, "JSON 渲染经 HTML 转义,不可注入");
  assert.match(batch, /step-bad/, "失败/拒绝步骤标记并默认展开");
  assert.match(batch, /未命中冻结数据/, "工具步骤展示 fixture 命中状态");

  // 运行中实时步骤(阶段二,设计 §7.2):SSE 客户端 + 实验组页实时面板
  assert.match(experimentJs, /streamRunEvents/, "共享脚本提供 SSE 事件流客户端(Bearer 头经 fetch 流式解析)");
  assert.match(experimentJs, /Last-Event-ID/, "断线重连携带 Last-Event-ID 续传游标");
  const series = await readPage("/experiment/series.html");
  assert.match(series, /liveRunPanel/, "实验组页有运行中实时步骤面板");
  assert.match(series, /E\.streamRunEvents\(/, "实时面板消费共享 SSE 客户端");
  assert.match(series, /run\.completed/, "收到运行结束事件后停流收尾");
  assert.match(series, /至少一次投递/, "至少一次投递由前端按 sequence 去重");
  // 诊断与对比(阶段三,设计 §10):diff/检索/审计包/遥测体检
  assert.match(batch, /modelCallDiffPanelHtml/, "运行详情提供模型调用对比面板");
  assert.match(batch, /modelCallDiffHtml/, "模型调用 diff 覆盖消息/Schema/参数三态");
  assert.match(batch, /auditBannerHtml/, "详情页内嵌遥测体检结论(缺失/乱序可见)");
  assert.match(batch, /audit-package/, "单次运行审计包可导出");
  assert.match(batch, /renderDiagnostics/, "所有者结果区提供诊断与对比卡");
  assert.match(batch, /variantDiffCard/, "支持不同变体 Tool Schema 逐轮对比");
  assert.match(batch, /tool-calls\/search/, "批次级明细检索按工具/状态/审计码/参数字段");
  assert.match(batch, /exp-select/, "检索过滤一律下拉(select),不用文本输入");
  // 进度区真实性:作业 404(服务重启清内存)必须终止轮询并回刷批次终态,不能冻结在「进行中」
  assert.match(batch, /status === "gone"/, "作业 404 映射为清除终态(终止轮询)");
  assert.match(batch, /作业进度记录已随服务重启清除/, "清除态有明确文案");
  assert.match(batch, /function ownerMeta\(batch\)/, "meta 行抽为可刷新函数");
  assert.match(batch, /ownerMeta\(fresh\)/, "终态回刷同时刷新 meta 状态行");
  assert.match(batch, /最近完成:/, "进度 current 标注为最近完成(不冒充当前)");
  assert.match(batch, /不逐次计数/, "done 未计数时如实说明,不用假百分比");
});

test("实验组统计展示(统计模块修复方案 §9):有效样本唯一口径来自统计快照", async () => {
  const series = await readPage("/experiment/series.html");
  // 样本累计区三数并陈:有效/排除/完成全部读取统计模块输出(P0-2)
  assert.match(series, /included_count/, "有效样本读取统计 included_count");
  assert.match(series, /excluded_count/, "排除数读取统计 excluded_count");
  assert.match(series, /completed_count/, "完成数读取统计 completed_count");
  assert.match(series, /failed_count/, "失败数读取统计 failed_count");
  assert.match(series, /included_run_count/, "整体累计纳入读取统计顶层计数");
  assert.match(series, /excluded_run_count/, "整体累计排除读取统计顶层计数");
  // 结果等级直接读取快照,前端不按数字重复推导;整体等级读 sample_sufficiency
  assert.match(series, /sample_sufficiency/, "整体等级读取统计 sample_sufficiency");
  assert.match(series, /sample_level/, "每变体等级直接读取统计 sample_level");
  assert.ok(!series.includes("counts_by_variant"), "前端不再消费 done 口径的 counts_by_variant");
  assert.ok(!series.includes("个有效样本"), "不再把 done 计数写成「N 个有效样本」");
  assert.ok(!series.includes('"初步趋势"') && !series.includes('"单次观察"'), "前端不再本地推导等级文案");
  // 数据质量警告与对比区域
  assert.match(series, /data_quality_warnings/, "重复 run_id 的数据质量警告醒目展示");
  assert.match(series, /对比不可用/, "comparison.available=false 时展示原因,不渲染空图表");
  assert.match(series, /formal_available/, "正式对比可用状态同步展示");
  // 统计不可用时建议按钮停用,不回退 done 口径
  assert.match(series, /统计暂不可用/, "统计不可用时有明确提示");
  assert.ok(series.includes("|| !statsReady"), "统计快照未到达前不放开建议按钮");
  // 排除记录带说明列;定义区展示预期配置哈希
  assert.match(series, /row\.detail/, "排除记录展示简短说明");
  assert.match(series, /expected_config_hashes/, "实验定义区展示每变体预期配置哈希");
  // 匿名只读视图:未登录走公开统计接口,仅展示定义与聚合统计
  assert.match(series, /public\/experiment-series/, "匿名视图读取公开统计端点");
  assert.match(series, /loadPublicStatistics/, "匿名视图独立加载路径(不触碰所有者明细接口)");
  assert.match(series, /publicReadonly/, "匿名视图隐藏样本积累与运行记录面板");
});

test("运行记录页(P1-3):三 Tab 统一历史运行,匿名任务走公开接口", async () => {
  const page = await readPage("/test/index.html");
  assert.match(page, /运行记录/, "页面为统一运行记录页");
  // 三 Tab:我的测试(全员) / 我的批次(登录后追加) / 公告批次(全员)
  assert.match(page, /id="tabJobs"/, "Tab 1:我的测试(匿名任务)");
  assert.match(page, /id="tabBatches"/, "Tab 2:我的批次(登录后)");
  assert.match(page, /id="tabPub"/, "Tab 3:公告批次(正式发布)");
  assert.match(page, /tabBatches"\)[^;]*style\.display = "none"|\\"tabBatches\\".*style="display:none"|id="tabBatches"[^>]*style="display:none"/, "我的批次 Tab 登录前隐藏(登录后追加)");
  assert.match(page, /\/api\/v1\/public\/test-jobs/, "我的测试 Tab 读取公开任务接口");
  assert.match(page, /E\.get\("\/api\/v1\/batches\?limit=20"\)/, "我的批次 Tab 读所有者批次列表");
  assert.match(page, /publications\/index\.json/, "公告批次 Tab 读发布索引");
  assert.match(page, /个人测试结果不会进入公告|个人测试 · 非正式结果|匿名测试结果/, "页面固定显示非正式结果声明");
  assert.match(page, /尚未发起任何测试/, "空任务时显示真实空状态");
  assert.match(page, /每 5 秒自动刷新/, "运行中任务自动刷新进度");
  assert.match(page, /data-cancel/, "运行中任务可取消(只阻止未开始单元)");
  // 进度用共享状态化组件(P2-4),不内联第二份实现
  assert.match(page, /E\.jobProgress\(j\)/, "任务卡进度使用共享组件 E.jobProgress");
  assert.doesNotMatch(page, /function progressHtml/, "页面不再内联进度组件");
  // 全站时间格式:上屏时间一律经格式化工具,不直出 ISO 原始串
  assert.match(page, /E\.fmtTime\(j\.created_at\)/, "任务创建时间经 fmtTime 格式化");
  assert.doesNotMatch(page, /esc\(j\.created_at \|\| ""\)/, "不再直出原始 ISO 时间");
  // 顶部导航:五模块含「我的测试」,由共享脚本注入全站
  const sharedJs = await readFile(new URL("../public/docs/docs.js", import.meta.url), "utf8");
  assert.match(sharedJs, /\/test\//, "共享导航含我的测试入口");
  assert.match(sharedJs, /window\.SITE/, "共享脚本暴露全站时间格式工具");
  assert.match(sharedJs, /getHours\(\)\) \+ ":" \+ p2\(d\.getMinutes\(\)\) \+ ":" \+ p2\(d\.getSeconds\(\)\)/, "时间格式为 yyyyMMdd HH:mm:ss");
});

test("实验页手动触发:任务提交只在函数体内,由点击调用", async () => {
  // 压缩用例页:字面 fetch 封装在 postJob 内,按钮点击才调用
  const compression = await readPage("/experiment/compression.html");
  const posts = [...compression.matchAll(/fetch\(\"\/api\/v1\/public\/test-jobs\"/g)];
  assert.ok(posts.length > 0, "压缩页应有公开测试接口提交入口");
  const wrapped = [...compression.matchAll(/return fetch\(\"\/api\/v1\/public\/test-jobs\"/g)];
  assert.equal(wrapped.length, posts.length, "压缩页提交必须封装在函数内");
  assert.match(compression, /只在点击时调用公开测试接口/, "压缩页声明页面加载不创建任务");

  // 统一发起页:提交走共享 API 封装(E.post),由提交按钮点击触发;预估先行
  const run = await readPage("/experiment/run.html");
  assert.match(run, /E\.post\("\/api\/v1\/template-batches"/, "所有者提交走模板批次端点");
  assert.match(run, /E\.post\("\/api\/v1\/public\/test-jobs"/, "匿名提交走公开测试端点");
  const submitIdx = run.indexOf('document.getElementById("submitBtn").addEventListener("click", submit)');
  assert.ok(submitIdx > -1, "发起页提交必须由按钮点击触发(页面加载不创建任务)");
  assert.match(run, /disabled/, "提交按钮在预估确认前保持禁用");
});

test("用例库:数据驱动渲染,公开投影不含评判配置", async () => {
  const list = await readPage("/cases/index.html");
  assert.match(list, /catalog\.js/, "用例库页由目录脚本渲染");
  assert.doesNotMatch(list, /112 道/, "用例库 meta 不得保留过期硬编码数量");
  const data = JSON.parse(await readFile(new URL("../public/showcase-data/cases.json", import.meta.url), "utf8"));
  assert.equal(data.total, 20, "题库精简为 20 条对比用例");
  assert.equal(data.cases.length, 20);
  const kinds = {};
  for (const c of data.cases) {
    kinds[c.kind] = (kinds[c.kind] || 0) + 1;
    assert.ok(!c.id.startsWith("ctx-"), `旧长上下文用例 ${c.id} 不应保留在用例库`);
    assert.equal(c.test_type, "COMPARISON_CASE");
    assert.ok(Array.isArray(c.allowed_tools) && c.allowed_tools.length > 0, `${c.id} 需要标准工具范围`);
  }
  assert.deepEqual(kinds, { basic: 4, combo: 4, multi: 6, exception: 3, security: 3 }, "20 条按 基础4/组合4/多工具6/异常3/安全3 分布");
  const raw = JSON.stringify(data);
  for (const leaked of ["expected_tools", "required_calls", "required_dependencies", "acceptable_alternatives", "forbidden_calls", "confirmation_required", "stop_when_facts_available", "mock_fixtures", "gold"]) {
    assert.ok(!raw.includes(leaked), `公开用例 JSON 不得包含评判配置字段:${leaked}`);
  }
});

test("公告页空框架:只读正式发布索引与静态资产,未发布统一显示空状态", async () => {
  const announce = await readPage("/index.html");
  assert.match(announce, /<body class="dashboard-page">/, "首页保持全宽仪表盘布局体系");
  assert.match(announce, /尚未发布/, "未发布时统一显示「尚未发布」空状态");
  assert.doesNotMatch(announce, /id="(agent-summary|examples|drilldown|compression)"/, "五个空区块已合并为单一发布公告区(IA §4.5,不再有独立锚点节)");
  assert.match(announce, /publications\/index\.json/, "公告页只读正式发布索引");
  assert.doesNotMatch(announce, /\/api\/v1\//, "公告页零后端依赖(公开镜像无 engine 也可展示)");
  assert.doesNotMatch(announce, /showcase-data\/index\.json/, "公告页不再读取旧批次索引");
  assert.doesNotMatch(announce, /showcase-data\/batches\//, "公告页不再加载开发调试批次产物");
  assert.doesNotMatch(announce, /renderDashboard|renderHomeBanner/, "公告页不再渲染批次仪表盘");
  // 数据侧:发布索引存在且为空(本任务不选择公告实例、不生成公告数据)
  const publications = JSON.parse(await readFile(new URL("../public/showcase-data/publications/index.json", import.meta.url), "utf8"));
  assert.deepEqual(publications.formal_publications, [], "正式发布索引初始为空");
  const css = await readFile(new URL("../public/docs/docs.css", import.meta.url), "utf8");
  assert.match(css, /\.radar-svg\s*{[^}]*width:\s*min\(100%,\s*400px\);/s, "雷达图本体不得随全宽容器无上限放大");
});

test("公告页事实卡数字与数据真源一致(防硬编码脱节)", async () => {
  const announce = await readPage("/index.html");
  const nums = [...announce.matchAll(/class="stat"><b>(\d+)<\/b>/g)].map((m) => Number(m[1]));
  assert.equal(nums.length, 4, "公告页应有四张事实卡(工具/用例/Session/模板)");
  const [tools, cases, sessions, templates] = nums;

  const toolsData = JSON.parse(await readFile(new URL("../public/showcase-data/tools.json", import.meta.url), "utf8"));
  assert.equal(tools, toolsData.total, "工具目录数与 tools.json 一致");
  const casesData = JSON.parse(await readFile(new URL("../public/showcase-data/cases.json", import.meta.url), "utf8"));
  assert.equal(cases, casesData.total, "对比用例数与 cases.json 一致");
  const libraryData = JSON.parse(await readFile(new URL("../public/showcase-data/context-library.json", import.meta.url), "utf8"));
  assert.equal(sessions, libraryData.entries.length, "压缩 Session 数与 context-library.json 一致");
  // 模板数量真源是 engine 注册表:templates.py 顶层 _register() 调用次数(新增模板须同步公告页)
  const templatesPy = await readFile(
    new URL("../../engine/src/bdlh_runtime/experiments/templates.py", import.meta.url),
    "utf8",
  );
  const registered = (templatesPy.match(/^_register\(/gm) || []).length;
  assert.equal(templates, registered, `实验模板数与 templates.py 注册数一致(当前注册 ${registered} 个)`);
});

test("工具调用明细页:真实空状态,不使用演示数据", async () => {
  const tools = await readPage("/showcase/tools.html");
  assert.match(tools, /暂无已发布的调用明细|尚未发布/, "明细页保持空状态");
  assert.doesNotMatch(tools, /fetch\(/, "明细页无发布数据时不发起请求");
});

test("评判侧栏条目与公告数字入口一致(新口径)", async () => {
  const metrics = await readPage("/judging/metrics.html");
  const sideHtml = await readPage("/judging/index.html");
  for (const html of [metrics, sideHtml]) {
    assert.match(html, /指标定义总表|指标定义/, "评判模块条目为指标定义口径");
  }
});

test("长上下文库页与静态导出产物一致(三个压缩 Session)", async () => {
  const library = await readPage("/context/library.html");
  assert.match(library, /id="libraryList"/, "库页有列表容器");
  assert.match(library, /context\/library\.js/, "库页渲染脚本外置(公开 HTML 零后端)");
  const data = JSON.parse(await readFile(new URL("../public/showcase-data/context-library.json", import.meta.url), "utf8"));
  assert.equal(data.kind, "scenario-frozen-session-corpus", "文库为场景化冻结 Session 语料");
  assert.equal(data.git_commit.length, 40, "语料来源 git commit 可追溯");
  assert.equal(data.entries.length, 3, "三个压缩 Session:产品演进/上下文引擎排查/数据库与部署");
  for (const entry of data.entries) {
    assert.equal(entry.kind_key, "session", "主文库只展示完整 Session");
    assert.equal(entry.strategies.length, 4, `${entry.id} 附四种上下文方式实测`);
    const txt = await readFile(new URL(`../public${entry.txt}`, import.meta.url), "utf8");
    assert.ok(txt.length > 1000, `${entry.id} 的 txt 导出存在`);
  }
});

test("静态站生成不发起实验:生成器只读 showcase-data 静态产物", async () => {
  const generator = await readFile(new URL("../scripts/generate-site.mjs", import.meta.url), "utf8");
  // 生成器 Node 侧只用文件系统:断言 import 面(白名单 fs/path/url),不得引入网络模块。
  // 内联 <script> 字符串里的 fetch 属于产物页面的浏览器行为,不是生成器行为,不在此断言范围。
  const imports = [...generator.matchAll(/^import[^\n]*$/gm)].map((m) => m[0]);
  assert.ok(imports.length > 0, "生成器应显式 import(空 import 面无法白名单校验)");
  for (const line of imports) {
    assert.match(line, /from "node:(fs|path|url)/, `生成器 import 只允许 node:fs/path/url:${line}`);
  }
  assert.doesNotMatch(generator, /urllib|require\("https?"\)|from "(node:)?(http|https|net|undici|axios|node-fetch)/, "生成器不得引入网络请求模块");
});

test("旧题库口径已清零:无 98 道/旧两变体/旧路径/旧表述(生成器与产物同步)", async () => {
  const generator = await readFile(new URL("../scripts/generate-site.mjs", import.meta.url), "utf8");
  // 生成器源不得再含旧数量与旧入口(P0-1:重跑生成器不得回退)
  for (const stale of ["实现方式对照题库 98 道", "上下文压缩用例 6 套", 'href="/experiment/cases"', "被测内核与对照 runner", "六套 × 两变体"]) {
    assert.ok(!generator.includes(stale), `generate-site.mjs 不得再含旧口径:${stale}`);
  }
  const banks = await readPage("/about/banks.html");
  assert.match(banks, /对比用例题库 20 条/, "题库页写当前 20 条对比用例口径");
  assert.match(banks, /href="\/cases\/"/, "题库入口使用正式路径 /cases/");
  assert.doesNotMatch(banks, /\/experiment\/cases|98 道|6 套/, "题库页无旧数量与旧路径");
  const repo = await readPage("/about/repo.html");
  assert.match(repo, /评测运行引擎与实验执行/, "仓库构成使用当前 engine 定位表述");
  const design = await readPage("/context/design.html");
  assert.match(design, /context-strategy-comparison/, "长短对照设计写当前 4×1 模板口径");
  assert.doesNotMatch(design, /full-raw|budgeted-comp/, "旧两变体命名不再作为当前口径出现");
  for (const page of ["/about/banks.html", "/about/repo.html", "/context/design.html", "/ops/index.html", "/ops/run-api.html"]) {
    const html = await readPage(page);
    assert.doesNotMatch(html, /六套 × 两变体|6 用例 × 2 变体/, `${page} 无旧压缩对照数量口径`);
  }
});

test("主导航静态化取代 noscript 兜底(P2-1 覆盖 P0-2 方案)", async () => {
  // 导航已由构建期写入页面 HTML:noscript 兜底块与其样式一并移除
  for (const page of SITE_PAGES) {
    const html = await readPage(page);
    assert.doesNotMatch(html, /<noscript>/, `${page} 不再需要 noscript 导航兜底(静态导航常驻)`);
  }
  const css = await readFile(new URL("../public/docs/docs.css", import.meta.url), "utf8");
  assert.doesNotMatch(css, /\.noscript-nav/, "docs.css 移除 noscript 导航样式");
  // 禁用脚本可导航由静态导航保证(断言见「模块页齐备」);移动端两行可见仍在
  assert.match(css, /\.site-nav\{[^}]*flex-wrap:wrap/, "≤920px 五导航换行完整可见");
});

test("进度表达状态化:全站不出现无数据依据的百分比(P0-4/P2-4)", async () => {
  const batch = await readPage("/experiment/batch.html");
  // 固定 8% 假进度与完成态满格条已删:进度条仅在活动 + 总量已知 + 逐次计数时渲染
  assert.doesNotMatch(batch, /active \? 8/, "批次页不得用固定 8% 冒充进度");
  assert.match(batch, /role="progressbar"/, "进度条带 role/aria 可读属性");
  assert.match(batch, /var showBar = active && !gone && hasCount && total > 0/, "进度条仅在活动且总量已知时渲染");
  const myTests = await readPage("/test/index.html");
  assert.match(myTests, /E\.jobProgress\(j\)/, "任务卡进度走共享组件");
  const experimentJs = await readFile(new URL("../public/docs/experiment.js", import.meta.url), "utf8");
  assert.match(experimentJs, /j\.status === "RUNNING" && total > 0/, "共享进度组件仅在运行中且总量已知时渲染");
  assert.match(experimentJs, /job-phase/, "排队/完成态使用阶段文字而非进度条");
});

test("窄屏可用性样式:模板网格单列、目录表卡片化、长字段受控换行(P0-3)", async () => {
  const css = await readFile(new URL("../public/docs/docs.css", import.meta.url), "utf8");
  assert.match(css, /minmax\(min\(340px,100%\),1fr\)/, "模板网格在窄屏自动降到单列");
  assert.match(css, /\.cat-table td::before\{content:attr\(data-label\)/, "目录表窄屏卡片化并以 data-label 自说明");
  assert.match(css, /code,\.hash,\.tpl-tech\{overflow-wrap:anywhere\}/, "长 ID/路径/哈希受控换行不撑破布局");
  assert.match(css, /\.def-list li\{display:block\}/, "定义列表窄屏上下堆叠");
  const catalog = await readFile(new URL("../public/catalog/catalog.js", import.meta.url), "utf8");
  assert.match(catalog, /data-label="工具名"/, "工具表 td 带 data-label");
  assert.match(catalog, /data-label="题号"/, "用例表 td 带 data-label");
});

test("首页公告保留定位并提供三个下一步入口(P1-1)", async () => {
  const announce = await readPage("/index.html");
  assert.match(announce, /cta-row/, "公告页有下一步入口区");
  for (const [href, label] of [["/experiment/", "查看实验"], ["/cases/", "浏览案例"], ["/about/", "了解系统"]]) {
    assert.ok(announce.includes(`href="${href}"`), `首页 CTA 缺少 ${label}(${href})`);
  }
  assert.doesNotMatch(announce, /id="(agent-summary|examples|drilldown|compression)"/, "不恢复旧版三 Agent 对照区块");
});

test("页面目录仅在章节 ≥3 时出现,且表现为页内锚点(P1-6)", async () => {
  // 生成器按 sections.length>=3 输出目录;由产物双向验证
  const banks = await readPage("/about/banks.html"); // 2 节
  assert.doesNotMatch(banks, /page-toc/, "少于 3 个章节的页面不生成装饰性目录(about/banks)");
  const algo = await readPage("/context/index.html"); // 6 节
  assert.match(algo, /page-toc/, "长文档保留页内目录(context/)");
  assert.match(algo, /本页目录/, "目录带「本页目录」标题,明确是锚点而非标签页");
  const generator = await readFile(new URL("../scripts/generate-site.mjs", import.meta.url), "utf8");
  assert.match(generator, /sections\.length >= 3/, "shell 生成目录的章节阈值锁定为 3(重跑不回退)");
  const css = await readFile(new URL("../public/docs/docs.css", import.meta.url), "utf8");
  assert.match(css, /\.page-toc li a\{[^}]*position:relative/, "目录条目为锚点列表样式(圆点标记,非胶囊标签)");
});

test("docs 目录:静态资产保留,index 为文档模块首页(原型 v2)", async () => {
  const docsCss = await readFile(new URL("../public/docs/docs.css", import.meta.url), "utf8");
  assert.ok(docsCss.length > 0, "docs.css 必须保留(全站样式)");
  const docsHome = await readFile(new URL("../public/docs/index.html", import.meta.url), "utf8");
  assert.match(docsHome, /<h1>文档<\/h1>/, "docs/index.html 为文档模块首页");
  for (const legacy of ["cases", "eval", "agents", "skill", "tools", "comparison", "results"]) {
    await assert.rejects(
      () => readFile(new URL(`../public/docs/${legacy}.html`, import.meta.url)),
      `${legacy}.html 应已迁移删除`,
    );
  }
});


test("同源所有者通道白名单三处同源:共享常量 = dev-server = nginx(P0-2)", async () => {
  const { OWNER_API_SEGMENTS, ownerApiRegExp } = await import("../scripts/owner-api-allowlist.mjs");
  // 关键段落在清单内:实验组与统计是 P0-2 的修复点
  for (const required of ["experiment-series", "statistics", "template-batches", "context"]) {
    assert.ok(OWNER_API_SEGMENTS.includes(required), `共享白名单缺少 ${required}`);
  }
  // 正则可构建且锚定 /api/v1/ 前缀
  const pattern = ownerApiRegExp();
  assert.ok(pattern.test("/api/v1/experiment-series/series-1"));
  assert.ok(pattern.test("/api/v1/statistics/experiment-series/series-1"));
  assert.ok(pattern.test("/api/v1/context/builds/build-1"));
  assert.ok(!pattern.test("/api/v1/no-such/segment"));

  // dev-server 引入共享常量构建反代正则,不再维护第二份清单
  const devServer = await readFile(new URL("../dev-server.js", import.meta.url), "utf8");
  assert.match(devServer, /owner-api-allowlist\.mjs/, "dev-server 必须复用共享白名单常量");
  assert.doesNotMatch(
    devServer,
    /login\|logout\|llm-config/,
    "dev-server 不得再内联白名单正则(以共享常量为事实来源)",
  );
  // dev-server 服务 /experiment/series/<id> → series.html(与 nginx 同口径)
  assert.match(devServer, /\/experiment\/series\//, "dev-server 需服务实验组详情路由");
  assert.match(devServer, /experiment\/series\.html/, "dev-server 需回退到 series.html");
  assert.match(devServer, /\/experiment\/context-builds\//, "dev-server 需服务上下文构建详情路由");
  assert.match(devServer, /experiment\/context-build\.html/, "dev-server 需回退到 context-build.html");

  // nginx 的反代 location 覆盖共享清单的每一个段落
  const nginx = await readFile(new URL("../nginx.conf", import.meta.url), "utf8");
  const locationMatch = nginx.match(/location ~ \^\/api\/v1\/\(([^)]+)\)/);
  assert.ok(locationMatch, "nginx 需有所有者通道反代 location");
  for (const segment of OWNER_API_SEGMENTS) {
    assert.ok(
      locationMatch[1].includes(segment.replace("/", "/")),
      `nginx 反代白名单缺少共享清单中的 ${segment}`,
    );
  }
  // 实验组详情页路由:nginx 与 dev-server 都回落到 series.html
  assert.match(nginx, /location ~ \^\/experiment\/series\/ \{[\s\S]*?try_files \/experiment\/series\.html/);
  assert.match(nginx, /location ~ \^\/experiment\/context-builds\/ \{[\s\S]*?try_files \/experiment\/context-build\.html/);
});

test("静态产物与生成器同源:重跑 generate:site 不产生差异(P1-6)", async () => {
  // 生成器内的 ops/run-api 端点清单必须与当前产物一致(实验组/统计/退役口径)
  const generator = await readFile(new URL("../scripts/generate-site.mjs", import.meta.url), "utf8");
  const artifact = await readPage("/ops/run-api.html");
  for (const stale of ["— 按模板发起正式批次(固定用例 × 模板变体,统一原生底座)"]) {
    assert.ok(!generator.includes(stale), `generate-site.mjs 不得保留已退役口径:${stale}`);
  }
  for (const current of ["已退役(410)", "experiment-series", "statistics/experiment-series"]) {
    assert.ok(generator.includes(current), `generate-site.mjs 缺少当前端点口径:${current}`);
    assert.ok(artifact.includes(current), `产物 ops/run-api.html 缺少当前端点口径:${current}`);
  }
});


test("showcase-data JSON 无 BOM(浏览器 JSON.parse 可直接解析)", async () => {
  const { readdir, readFile } = await import("node:fs/promises");
  const root = new URL("../public/showcase-data/", import.meta.url);
  const files = ["cases.json", "tools.json", "index.json", "context-library.json", "publications/index.json"];
  for (const name of files) {
    const buf = await readFile(new URL(name, root)).catch(() => null);
    if (!buf) continue;
    assert.ok(!(buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf), `${name} 不得带 UTF-8 BOM`);
  }
});
