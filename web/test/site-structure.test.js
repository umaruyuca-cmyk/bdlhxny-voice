import { readFile } from "node:fs/promises";
import { test } from "node:test";
import assert from "node:assert/strict";
import { REDIRECTS, redirectFor } from "../scripts/redirect-map.mjs";

/**
 * 站点结构契约(信息架构 v2):公告单页 / + 系统概览 /about(3)+ 实证展示 /showcase(4)+
 * 对照实验 /experiment(3)+ 上下文压缩 /context(4,含长上下文库)+ 评判标准 /judging(4)+
 * 引擎与治理 /engine(6)+ 数据与运行 /ops(5)。
 * 公告为独立单页模块:侧栏直达链接、无子级;全站去品牌化(不出现项目代号)。
 */

const MODULE_HREFS = ["/", "/about/", "/showcase/", "/experiment/", "/context/", "/judging/", "/engine/", "/ops/"];

const SITE_PAGES = [
  "/index.html",
  "/about/index.html", "/about/banks.html", "/about/repo.html",
  "/showcase/index.html", "/showcase/results.html", "/showcase/tools.html", "/showcase/runs.html",
  "/experiment/index.html", "/experiment/cases.html", "/experiment/reproduce.html",
  "/context/index.html", "/context/library.html", "/context/design.html", "/context/results.html",
  "/judging/index.html", "/judging/metrics.html", "/judging/judge.html", "/judging/invalid.html",
  "/engine/index.html", "/engine/loading.html", "/engine/catalog.html",
  "/engine/governance.html", "/engine/guardrail.html", "/engine/tools.html",
  "/ops/index.html", "/ops/run-api.html", "/ops/artifacts.html",
  "/ops/deploy.html", "/ops/roadmap.html",
];

async function readPage(page) {
  return readFile(new URL(`../public${page}`, import.meta.url), "utf8");
}

test("模块页齐备,共享级联导航壳(顶栏动作 + 侧栏级联模块树 + 页内目录)", async () => {
  assert.equal(SITE_PAGES.length, 30);
  for (const page of SITE_PAGES) {
    const html = await readPage(page);
    assert.match(html, /docs\.css/, `${page} 必须引用 docs.css`);
    assert.match(html, /docs\.js/, `${page} 必须引入共享导航脚本`);
    assert.match(html, /class="brand"/, `${page} 顶栏必须有品牌行`);
    assert.match(html, /class="side-tree"/, `${page} 侧栏必须有级联模块树`);
    for (const href of MODULE_HREFS) {
      assert.ok(html.includes(`href="${href}"`), `${page} 侧栏树缺少模块 ${href}`);
    }
    assert.ok(html.includes("topbar-gh"), `${page} 顶栏需要 GitHub 外链`);
    if (page !== "/index.html") {
      assert.match(html, /side-group here" open/, `${page} 当前模块必须默认展开`);
    }
  }
});

test("本页目录竖排在详情区左侧(detail-layout 三栏),不占用模块侧栏", async () => {
  for (const page of SITE_PAGES) {
    const html = await readPage(page);
    assert.match(html, /class="page-toc"/, `${page} 需有页内目录`);
    assert.match(html, /aria-label="本页目录"/, `${page} 页内目录需有可访问标签`);
    const aside = html.match(/<aside class="docs-side"[\s\S]*?<\/aside>/);
    assert.ok(aside, `${page} 模块侧栏存在`);
    assert.ok(!aside[0].includes("本页目录"), `${page} 模块侧栏不得放本页目录`);
    // 生成页:页内目录为 aside,位于 detail-layout 内、detail-body 之前;
    // showcase 三页手维护,自身侧栏已含目录,只检查存在性
    if (!page.startsWith("/showcase/")) {
      const m = html.match(/<div class="detail-layout">\s*<aside class="page-toc"/);
      assert.ok(m, `${page} 页内目录须竖排在 detail-layout 左侧`);
      assert.match(html, /class="detail-body"/, `${page} 正文须在 detail-body 内`);
    }
  }
});

test("公告为独立单页:侧栏直达链接无子级,系统说明并入新模块「系统概览」", async () => {
  const announce = await readPage("/index.html");
  assert.match(announce, /<a class="side-item[^>]*>(?:<svg[\s\S]*?<\/svg>)?公告<\/a>/, "公告必须是侧栏直达链接(单页模块)");
  const 公告块 = announce.match(/<a class="side-item[^>]*>公告<\/a>\s*<details/);
  assert.equal(公告块, null, "公告之后不应再有属于公告的子级分组");
  for (const anchor of ["dashboard", "guide"]) {
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
    assert.ok(home.includes(`href="${href}"`), `公告页缺少模块入口 ${href}`);
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
  assert.equal(redirectFor("/docs/cases"), "/experiment/cases");
  assert.equal(redirectFor("/docs/cases.html"), "/experiment/cases");
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

test("公开页零后端依赖、无交互输入(全部公开页)", async () => {
  for (const page of SITE_PAGES) {
    const html = await readPage(page);
    if (page === "/ops/run-api.html") {
      assert.doesNotMatch(html, /fetch\(|XMLHttpRequest|axios/, "ops/run-api 文档页也不得发起真实后端调用");
    } else {
      assert.doesNotMatch(html, /\/api\/v1\//, `${page} 不得出现后端 API`);
    }
    assert.doesNotMatch(html, /<input|<form|<textarea/, `${page} 不得出现输入控件`);
    assert.doesNotMatch(html, /sessionStorage|localStorage/, `${page} 无会话概念`);
    assert.doesNotMatch(html, /href="\/lab/, `${page} 不得硬链接运行台(公开镜像物理排除 /lab)`);
    for (const url of [...html.matchAll(/fetch\((["'])([^"']+)\1/g)].map((m) => m[2])) {
      assert.ok(url.startsWith("/showcase-data/"), `${page} 的 fetch 只允许 /showcase-data/:${url}`);
    }
  }
});

test("题库页去硬编码:数据驱动渲染,不含题号字面量", async () => {
  const cases = await readPage("/experiment/cases.html");
  assert.match(cases, /showcase-data\/index\.json/, "题库页必须读发布产物");
  assert.match(cases, /showcase-data\/batches\//, "题库页必须读批次报告");
  assert.doesNotMatch(cases, /research-01|ctx-port-01|chat-01|miss-01/, "题库页不得硬编码题号表格");
});

test("公告页数据驱动:横幅与数字卡读发布产物", async () => {
  const announce = await readPage("/index.html");
  assert.match(announce, /对照实验数据/, "数据仪表盘需在最上部");
  assert.match(announce, /快速指引/, "快速指引紧随其后");
  assert.match(announce, /showcase-data\/index\.json/, "数字卡读发布产物");
  assert.match(announce, /renderDashboard|renderHomeBanner/, "复用仪表盘渲染函数");
});

test("工具调用明细页:读发布产物渲染按序调用链", async () => {
  const tools = await readPage("/showcase/tools.html");
  assert.match(tools, /renderToolTrace/, "明细页使用共享渲染函数");
  assert.match(tools, /showcase-data\/runs\//, "明细页读取逐运行工件");
  assert.match(tools, /按序调用|调用顺序/, "明细页说明调用顺序口径");
});

test("长上下文库页与静态导出产物一致", async () => {
  const library = await readPage("/context/library.html");
  assert.match(library, /id="libraryList"/, "库页有列表容器");
  assert.match(library, /context\/library\.js/, "库页渲染脚本外置(公开 HTML 零后端)");
  const data = JSON.parse(await readFile(new URL("../public/showcase-data/context-library.json", import.meta.url), "utf8"));
  assert.equal(data.cases.length, 6, "六套长上下文用例");
  const port = data.cases.find((c) => c.case_id === "ctx-port-01");
  assert.equal(port.item_count, 564, "组合用例条目数与 SQL 种子一致");
  assert.ok(port.token_estimate > 0, "token 估算非零");
  for (const meta of data.cases) {
    const txt = await readFile(new URL(`../public${meta.txt}`, import.meta.url), "utf8");
    assert.ok(txt.includes(meta.case_id), `${meta.case_id} 的 txt 导出存在且带标识`);
  }
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
