import { readFile } from "node:fs/promises";
import { test } from "node:test";
import assert from "node:assert/strict";
import { REDIRECTS, redirectFor } from "../scripts/redirect-map.mjs";

/**
 * 站点结构契约(两类实验口径):公告单页(空框架)+ 系统概览 /about(3)+
 * 实例展示 /showcase + 实验 /experiment(只有压缩用例与对比用例两个入口)+
 * 上下文压缩 /context(4,含长上下文库)+ 评判标准 /judging(4)+
 * 引擎与治理 /engine(6)+ 数据与运行 /ops(5)+ 工具目录 /tools + 用例库 /cases。
 * 公告为独立单页模块:侧栏直达链接、无子级;全站去品牌化(不出现项目代号)。
 */

const MODULE_HREFS = ["/", "/about/", "/showcase/", "/experiment/", "/test/", "/context/", "/judging/", "/engine/", "/ops/"];

const SITE_PAGES = [
  "/index.html",
  "/about/index.html", "/about/banks.html", "/about/repo.html",
  "/showcase/index.html", "/showcase/tools.html",
  "/experiment/index.html", "/experiment/compression.html", "/experiment/comparison.html",
  "/test/index.html",
  "/context/index.html", "/context/library.html", "/context/design.html", "/context/results.html",
  "/judging/index.html", "/judging/metrics.html", "/judging/judge.html", "/judging/invalid.html",
  "/engine/index.html", "/engine/loading.html", "/engine/catalog.html",
  "/engine/governance.html", "/engine/guardrail.html", "/engine/tools.html",
  "/ops/index.html", "/ops/run-api.html", "/ops/artifacts.html",
  "/ops/deploy.html", "/ops/roadmap.html",
];

/** 实验/我的测试三页:唯一允许调用公开测试接口与使用交互控件的公开页。 */
const EXPERIMENT_PAGES = ["/experiment/compression.html", "/experiment/comparison.html", "/test/index.html"];

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

test("模块页齐备,共享级联导航壳(顶栏动作 + 侧栏级联模块树 + 页内目录)", async () => {
  assert.equal(SITE_PAGES.length, 29);
  for (const page of SITE_PAGES) {
    const html = await readPage(page);
    assert.match(html, /docs\.css/, `${page} 必须引用 docs.css`);
    assert.match(html, /docs\.js/, `${page} 必须引入共享导航脚本`);
    assert.match(html, /class="brand"/, `${page} 顶栏必须有品牌行`);
    assert.match(html, /class="side-tree"/, `${page} 侧栏必须有级联模块树`);
    for (const href of MODULE_HREFS) {
      // 实验模块只有两个子入口,模块根以子链接前缀出现在侧栏树
      const probe = href === "/experiment/" ? 'href="/experiment/' : `href="${href}"`;
      assert.ok(html.includes(probe), `${page} 侧栏树缺少模块 ${href}`);
    }
    assert.ok(html.includes("topbar-gh"), `${page} 顶栏需要 GitHub 外链`);
    // 单页模块(公告 / 我的测试)在侧栏是直达链接,无分组展开
    if (page !== "/index.html" && page !== "/test/index.html") {
      assert.match(html, /side-group here" open/, `${page} 当前模块必须默认展开`);
    }
    if (page === "/test/index.html") {
      assert.match(html, /class="side-item active" href="\/test\/"/, "我的测试当前页直达链接高亮");
    }
  }
});

test("本页目录与正文同在详情区,不占用模块侧栏", async () => {
  for (const page of SITE_PAGES) {
    const html = await readPage(page);
    const aside = html.match(/<aside class="docs-side"[\s\S]*?<\/aside>/);
    assert.ok(aside, `${page} 模块侧栏存在`);
    assert.ok(!aside[0].includes("本页目录"), `${page} 模块侧栏不得放本页目录`);
    if (page === "/index.html") {
      assert.doesNotMatch(html, /class="page-toc"/, "数据首页已有左侧模块目录,不应再显示重复的页内目录");
      assert.match(html, /class="detail-layout detail-layout-full"/, "数据首页应使用全宽详情区");
      continue;
    }
    if (page === "/experiment/index.html") {
      continue; // 实验模块根是跳转页(两个入口的导航壳在子页)
    }
    assert.match(html, /class="page-toc"/, `${page} 需有页内目录`);
    assert.match(html, /aria-label="本页目录"/, `${page} 页内目录需有可访问标签`);
    // 生成页:页内目录为 aside,位于 detail-layout 内。
    // DOM 中保持目录在正文前,桌面端由 CSS 放到右侧,窄屏放回正文上方;
    // showcase 三页手维护,自身侧栏已含目录,只检查存在性
    if (!page.startsWith("/showcase/")) {
      const m = html.match(/<div class="detail-layout">\s*<aside class="page-toc"/);
      assert.ok(m, `${page} 页内目录须位于 detail-layout 内`);
      assert.match(html, /class="detail-body"/, `${page} 正文须在 detail-body 内`);
    }
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

test("公告为独立单页:侧栏直达链接无子级,系统说明并入新模块「系统概览」", async () => {
  const announce = await readPage("/index.html");
  assert.match(announce, /<a class="side-item[^>]*>(?:<svg[\s\S]*?<\/svg>)?公告<\/a>/, "公告必须是侧栏直达链接(单页模块)");
  const 公告块 = announce.match(/<a class="side-item[^>]*>公告<\/a>\s*<details/);
  assert.equal(公告块, null, "公告之后不应再有属于公告的子级分组");
  for (const anchor of ["about", "batches", "agent-summary", "compression", "examples", "drilldown"]) {
    assert.ok(announce.includes(`id="${anchor}"`), `公告页缺少第 ${anchor} 节`);
  }
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

test("模块首页从公告页可达(互链)", async () => {
  const home = await readPage("/index.html");
  for (const href of MODULE_HREFS.slice(1)) {
    // 实验模块只有两个子入口(压缩/对比),模块根以子链接前缀可达
    const probe = href === "/experiment/" ? 'href="/experiment/' : `href="${href}"`;
    assert.ok(home.includes(probe), `公告页缺少模块入口 ${href}`);
  }
});

test("全站去品牌化:公开页不出现项目代号,品牌行为通用描述", async () => {
  for (const page of SITE_PAGES) {
    const html = await readPage(page);
    assert.doesNotMatch(html, /touchstone/i, `${page} 不得出现项目代号`);
    assert.doesNotMatch(html, /タカラダ|グリッド|ダイナゼノン|エヴァンゲリオン/, `${page} 不得出现主题化文案`);
  }
  const announce = await readPage("/index.html");
  assert.match(announce, /Agent 对照评测/, "品牌行为中性描述");
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

test("旧路径 301:redirect-map 与两台服务器一致", async () => {
  assert.equal(redirectFor("/docs/cases"), "/cases/");
  assert.equal(redirectFor("/docs/cases.html"), "/cases/");
  assert.equal(redirectFor("/showcase/context"), "/context/results");
  assert.equal(redirectFor("/docs"), "/");
  assert.equal(redirectFor("/docs/docs.css"), null, "静态资产不重定向");

  const devServer = await readFile(new URL("../dev-server.js", import.meta.url), "utf8");
  assert.match(devServer, /redirectFor/, "dev-server 需接入 301 映射");
  assert.match(devServer, /301/, "dev-server 需以 301 重定向");

  const nginx = await readFile(new URL("../nginx.conf", import.meta.url), "utf8");
  for (const [from, to] of REDIRECTS) {
    if (from.endsWith("/")) continue; // 目录索引形式由等值规则覆盖
    assert.ok(
      nginx.includes(`location = ${from} { return 301 ${to}; }`),
      `nginx 缺少 301:${from} → ${to}`,
    );
  }
  assert.match(nginx, /location \/experiment\//, "nginx 需服务新模块前缀");
  assert.match(nginx, /location \/ops\//, "nginx 需服务新模块前缀");
});

test("公开页零后端依赖(实验两页仅允许公开测试接口)", async () => {
  for (const page of SITE_PAGES) {
    const html = await readPage(page);
    const isExperiment = EXPERIMENT_PAGES.includes(page);
    if (page === "/ops/run-api.html") {
      assert.doesNotMatch(html, /fetch\(|XMLHttpRequest|axios/, "ops/run-api 文档页也不得发起真实后端调用");
    } else if (isExperiment) {
      assert.doesNotMatch(html, /\/api\/v1\/(?!public)/, `${page} 只允许 /api/v1/public/ 公开测试接口`);
    } else {
      assert.doesNotMatch(html, /\/api\/v1\//, `${page} 不得出现后端 API`);
    }
    // 任意文本输入全站禁止;选择控件(勾选/单选/下拉)仅实验两页允许;
    // showcase 空框架页的 disabled 占位控件(display-only)豁免
    assert.doesNotMatch(html, /<textarea/, `${page} 不得出现文本域`);
    assert.doesNotMatch(html, /type="text"/, `${page} 不得出现任意文本输入`);
    const inertAllowed = isExperiment || page.startsWith("/showcase/");
    if (!inertAllowed) {
      assert.doesNotMatch(html, /<input|<form|<select/, `${page} 不得出现输入控件`);
    } else {
      assert.doesNotMatch(html, /<form/, `${page} 不得出现表单提交`);
    }
    assert.doesNotMatch(html, /sessionStorage|localStorage/, `${page} 无会话概念`);
    assert.doesNotMatch(html, /href="\/lab/, `${page} 不得硬链接运行台(公开镜像物理排除 /lab)`);
    for (const url of [...html.matchAll(/fetch\((["'])([^"']+)\1/g)].map((m) => m[2])) {
      const allowed = url.startsWith("/showcase-data/") || (isExperiment && url.startsWith("/api/v1/public/"));
      assert.ok(allowed, `${page} 的 fetch 只允许 /showcase-data/(实验页另允许公开测试接口):${url}`);
    }
  }
});

test("实验模块只有压缩用例与对比用例两个入口", async () => {
  const index = await readPage("/experiment/index.html");
  assert.match(index, /\/experiment\/compression/, "实验根页指向压缩用例");
  assert.match(index, /\/experiment\/comparison/, "实验根页指向对比用例");
  const compression = await readPage("/experiment/compression.html");
  const comparison = await readPage("/experiment/comparison.html");
  // 侧栏树只有两个子项
  for (const html of [compression, comparison]) {
    const module = html.match(/<details class="side-group[^>]*open[^>]*>\s*<summary>[\s\S]*?<\/details>/g) || [];
    const experimentGroup = module.find((block) => block.includes("实验"));
    assert.ok(experimentGroup, "实验模块侧栏分组存在");
    assert.equal((experimentGroup.match(/<li>/g) || []).length, 2, "实验模块一级只有两个入口");
  }
  // 压缩用例页:Session 为原地选中,不得有指向自身的「进入实验」链接
  assert.doesNotMatch(compression, /用该 Session 进入压缩用例实验/, "压缩页内不得有自指的进入实验链接");
  assert.match(compression, /data-select-session/, "压缩页 Session 列表有原地选中按钮");
  assert.match(compression, /currentSessionId/, "压缩页操作区显示当前作用于的 Session");
  // 压缩用例页:三个手动操作 + 12 格矩阵空状态
  assert.match(compression, /生成四份上下文/, "压缩页有「生成四份上下文」按钮");
  assert.match(compression, /运行当前组合/, "压缩页有「运行当前组合」按钮");
  assert.match(compression, /运行完整 4×3/, "压缩页有「运行完整 4×3」按钮");
  assert.match(compression, /context-library\.json/, "压缩页读长上下文库(三个 Session 数据源)");
  const matrixCells = (compression.match(/matrix-empty/g) || []).length;
  assert.ok(matrixCells >= 12, `压缩页 4×3 矩阵需 12 个空状态格子(实际 ${matrixCells})`);
  // 对比用例页:重复 3/5、9/15、工具范围与自定义条件提示
  assert.match(comparison, /cases\.json/, "对比页读用例库公开投影");
  assert.match(comparison, /value="3"/, "对比页提供重复 3 次选项");
  assert.match(comparison, /value="5"/, "对比页提供重复 5 次选项");
  assert.doesNotMatch(comparison, /value="[24678]"/, "对比页不提供 3/5 之外的重复次数");
  assert.match(comparison, /9 个运行/, "对比页显示 3×3=9");
  assert.match(comparison, /15 个运行/, "对比页显示 3×5=15");
  assert.match(comparison, /自定义条件/, "对比页提示自定义工具范围口径");
  assert.match(comparison, /尚未发起/, "对比页任务进度为真实空状态");
});

test("我的测试页:读公开任务接口,空状态与匿名声明齐全", async () => {
  const page = await readPage("/test/index.html");
  assert.match(page, /\/api\/v1\/public\/test-jobs/, "我的测试页读取公开任务接口");
  assert.match(page, /匿名测试结果/, "页面固定显示匿名结果声明");
  assert.match(page, /不进入公告指标/, "声明不进入公告指标");
  assert.match(page, /尚未发起任何测试/, "空任务时显示真实空状态");
  assert.match(page, /每 5 秒自动刷新/, "运行中任务自动刷新进度");
  assert.match(page, /data-cancel/, "运行中任务可取消(只阻止未开始单元)");
  assert.doesNotMatch(page, /\/api\/v1\/(?!public\/)/, "只允许匿名公开接口");
  // 顶栏导航:全站页面提供「我的测试」入口
  const home = await readPage("/index.html");
  assert.match(home, /href="\/test\/"/, "顶栏需有我的测试入口");
});

test("实验页手动触发:任务提交只在函数体内,由点击调用", async () => {
  for (const page of ["/experiment/compression.html", "/experiment/comparison.html"]) {
    const html = await readPage(page);
    const posts = [...html.matchAll(/fetch\("\/api\/v1\/public\/test-jobs"/g)];
    assert.ok(posts.length > 0, `${page} 应有公开测试接口提交入口`);
    // 静态口径:提交调用必须封装在函数内(return fetch),或全部出现在点击处理函数注册之后
    const wrapped = [...html.matchAll(/return fetch\("\/api\/v1\/public\/test-jobs"/g)];
    const clickIdx = html.indexOf('addEventListener("click"');
    const firstPost = html.indexOf('fetch("/api/v1/public/test-jobs"');
    const encapsulated =
      wrapped.length === posts.length ||
      (clickIdx !== -1 && firstPost > clickIdx);
    assert.ok(encapsulated, `${page} 的任务提交必须由点击触发(页面加载不创建任务)`);
    assert.match(html, /addEventListener\("click"/, `${page} 需有点击触发入口`);
    assert.match(html, /页面加载|不会创建实验任务|只在点击时/, `${page} 需声明页面加载不创建任务`);
  }
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

test("公告页空框架:只读正式发布索引,未发布统一显示空状态", async () => {
  const announce = await readPage("/index.html");
  assert.match(announce, /<body class="dashboard-page">/, "首页保持全宽仪表盘布局体系");
  assert.match(announce, /正式发布批次说明/, "公告页预留批次说明区");
  assert.match(announce, /Agent 对比汇总/, "公告页预留 Agent 对比汇总区");
  assert.match(announce, /压缩结果/, "公告页预留压缩结果区");
  assert.match(announce, /代表性实例/, "公告页预留代表性实例区");
  assert.match(announce, /单次运行下钻/, "公告页预留单次运行下钻区");
  assert.match(announce, /尚未发布/, "未发布时统一显示「尚未发布」空状态");
  assert.match(announce, /publications\/index\.json/, "公告页只读正式发布索引");
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

test("旧 docs 页面已删除,资产保留", async () => {
  const docsCss = await readFile(new URL("../public/docs/docs.css", import.meta.url), "utf8");
  assert.ok(docsCss.length > 0, "docs.css 必须保留(全站样式)");
  for (const legacy of ["index", "cases", "eval", "agents", "skill", "tools", "comparison", "results"]) {
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
