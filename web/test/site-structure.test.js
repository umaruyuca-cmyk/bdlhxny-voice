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

const SITE_PAGES = [
  "/index.html",
  "/assets/index.html",
  "/docs/index.html",
  "/about/index.html", "/about/banks.html", "/about/repo.html",
  "/showcase/index.html", "/showcase/tools.html",
  "/experiment/index.html", "/experiment/compression.html",
  "/experiment/run.html", "/experiment/batches.html", "/experiment/batch.html",
  "/test/index.html",
  "/context/index.html", "/context/library.html", "/context/design.html", "/context/results.html",
  "/judging/index.html", "/judging/metrics.html", "/judging/judge.html", "/judging/invalid.html",
  "/engine/index.html", "/engine/loading.html", "/engine/catalog.html",
  "/engine/governance.html", "/engine/guardrail.html", "/engine/tools.html",
  "/ops/index.html", "/ops/run-api.html", "/ops/artifacts.html",
  "/ops/deploy.html", "/ops/roadmap.html",
];

/** 实验模块页:允许匿名公开接口 + 同源所有者通道白名单(与 nginx/dev-server 反代同口径)。 */
const EXPERIMENT_PAGES = [
  "/experiment/index.html", "/experiment/compression.html",
  "/experiment/run.html", "/experiment/batches.html", "/experiment/batch.html",
  "/test/index.html",
];
const EXPERIMENT_API_OK = /\/api\/v1\/(public(\/|$)|(login|logout|llm-config\/test|experiment-templates|template-batches|batches|jobs|runs)(\/|\?|["'`]|$))/;

async function readPage(page) {
  return readFile(new URL(`../public${page}`, import.meta.url), "utf8");
}

/** 旧地址只保留跳转:showcase/results → 公告页,showcase/runs → 公告页 */
const REDIRECT_ONLY_PAGES = ["/showcase/results.html", "/showcase/runs.html"];

test("旧展示地址保留跳转页(不重复公告内容)", async () => {
  for (const page of REDIRECT_ONLY_PAGES) {
    const html = await readPage(page);
    assert.match(html, /http-equiv="refresh"/, `${page} 需为跳转页`);
    assert.match(html, /href="\/[^"]*"/, `${page} 需提供继续查看链接`);
  }
});

test("模块页齐备,共享原型外壳(顶栏 wordmark + docs.js 注入五导航 + 角色标签)", async () => {
  assert.equal(SITE_PAGES.length, 33);
  const sharedJs = await readFile(new URL("../public/docs/docs.js", import.meta.url), "utf8");
  for (const href of NAV_HREFS) {
    assert.ok(sharedJs.includes(`"${href}"`), `docs.js 注入的导航缺少模块 ${href}`);
  }
  for (const label of ["公告", "实验", "我的测试", "数据资产", "文档"]) {
    assert.ok(sharedJs.includes(`"${label}"`), `docs.js 导航缺少条目「${label}」`);
  }
  assert.match(sharedJs, /role-label/, "docs.js 需注入角色标签(匿名访客/登录所有者)");
  for (const page of SITE_PAGES) {
    const html = await readPage(page);
    assert.match(html, /docs\.css/, `${page} 必须引用 docs.css`);
    assert.match(html, /docs\.js/, `${page} 必须引入共享导航脚本`);
    assert.match(html, /class="brand"/, `${page} 顶栏必须有品牌行`);
    assert.ok(html.includes("topbar-gh"), `${page} 顶栏需要 GitHub 外链`);
    assert.ok(html.includes("topbar-login"), `${page} 顶栏需要登录入口`);
  }
});

test("二级页面提供返回上级入口,无导航死胡同(IA §二.8)", async () => {
  const backLinks = {
    "/experiment/run.html": 'class="crumb" href="/experiment/"',
    "/experiment/batches.html": null, // 一级模块页,顶栏导航即返回
    "/experiment/batch.html": 'class="crumb" href="/experiment/batches"',
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

test("五模块导航由共享脚本注入,每个模块首页可达(原型 §总览)", async () => {
  const sharedJs = await readFile(new URL("../public/docs/docs.js", import.meta.url), "utf8");
  assert.match(sharedJs, /site-nav/, "docs.js 注入顶部导航");
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

  // 模板卡片:标题/受控变量用规范中文,技术口径行保留原变量名(IA §二.7 文案分层)
  const experimentJs = await readFile(new URL("../public/docs/experiment.js", import.meta.url), "utf8");
  assert.match(experimentJs, /formal-single-variable/, "classification 兼容 real 注册表值");
  assert.match(experimentJs, /长上下文记忆策略对比/, "模板标题有中文展示名映射");
  assert.match(experimentJs, /完整上下文/, "变体标签有中文展示名映射");

  // 统一发起页:plan → 确认 → 提交;变体不可编辑;预估条必须先显示
  const run = await readPage("/experiment/run.html");
  assert.match(run, /template-batches\/plan/, "发起页所有者路径接 plan 预估");
  assert.match(run, /精确运行数/, "预估条必须显示精确运行数");
  assert.match(run, /变体由模板定义,任何角色不可编辑/, "变体数组任何角色不可编辑");
  assert.match(run, /高级设置\(仅所有者/, "高级设置仅所有者渲染");
  assert.match(run, /受控变量/, "左栏展示受控变量");
  assert.match(run, /断开页面不影响后台任务/, "提交前提示断页不中断");

  // 批次列表:公告 Tab + 我的批次 Tab
  const batches = await readPage("/experiment/batches.html");
  assert.match(batches, /公告批次/, "批次列表有公告 Tab");
  assert.match(batches, /我的批次/, "批次列表有我的批次 Tab");
  assert.match(batches, /publications\/index\.json/, "公告 Tab 读发布索引");
  assert.match(batches, /个人测试 · 非正式结果/, "匿名批次标记非正式结果");

  // 批次详情:口径卡 + 请求/生效参数 + 按变量分组;哈希 8 位短显
  const batch = await readPage("/experiment/batch.html");
  assert.match(batch, /实验口径/, "批次详情有口径卡");
  assert.match(batch, /请求参数与实际生效参数/, "批次详情有请求/生效对照表");
  assert.match(batch, /按受控变量分组/, "结果按模板变量分组(不按 agent_mode)");
  assert.match(batch, /个人测试 · 非正式结果/, "匿名任务视图标记非正式结果");
  assert.match(batch, /E\.hashChip/, "批次哈希统一用 hashChip 组件");
  assert.match(experimentJs, /slice\(0, 8\)/, "哈希 chip 8 位短显(共享组件)");
  assert.match(batch, /\/api\/v1\/runs\//, "所有者视图可下钻单次运行明细");
  assert.match(batch, /无模板/, "无模板批次挂中性标记");
});

test("我的测试页:读公开任务接口,空状态与匿名声明齐全", async () => {
  const page = await readPage("/test/index.html");
  assert.match(page, /\/api\/v1\/public\/test-jobs/, "我的测试页读取公开任务接口");
  assert.match(page, /个人测试结果不会进入公告|匿名测试结果/, "页面固定显示非正式结果声明");
  assert.match(page, /不会进入公告|不进入公告指标/, "声明不进入公告");
  assert.match(page, /尚未发起任何测试/, "空任务时显示真实空状态");
  assert.match(page, /每 5 秒自动刷新/, "运行中任务自动刷新进度");
  assert.match(page, /data-cancel/, "运行中任务可取消(只阻止未开始单元)");
  assert.doesNotMatch(page, /\/api\/v1\/(?!public\/)/, "只允许匿名公开接口");
  // 顶部导航:五模块含「我的测试」,由共享脚本注入全站
  const sharedJs = await readFile(new URL("../public/docs/docs.js", import.meta.url), "utf8");
  assert.match(sharedJs, /\/test\//, "共享导航含我的测试入口");
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
  // 文档正文可以描述 API 路径,但生成器本身不发起任何网络请求(只读本地 showcase-data)
  assert.doesNotMatch(generator, /fetch\(|urllib|http\.request|axios/, "generate-site.mjs 不发起网络请求");
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
