import { readFile } from "node:fs/promises";
import { test } from "node:test";
import assert from "node:assert/strict";
import { REDIRECTS, redirectFor } from "../scripts/redirect-map.mjs";

/**
 * 站点结构契约:公告首页 / + 机甲风格子页 /home(1)+ 六模块。
 * 模块:公告(即访问首页)/ + 实证展示 /showcase(3)+ 对照实验 /experiment(3)+
 * 上下文压缩 /context(3)+ 评判标准 /judging(3)+ 引擎与治理 /engine(6)+
 * 数据与运行 /ops(5)。
 */

const MODULE_HREFS = ["/", "/showcase/", "/experiment/", "/context/", "/judging/", "/engine/", "/ops/"];

const SITE_PAGES = [
  "/index.html",
  "/showcase/index.html", "/showcase/results.html", "/showcase/runs.html",
  "/experiment/index.html", "/experiment/cases.html", "/experiment/reproduce.html",
  "/context/index.html", "/context/design.html", "/context/results.html",
  "/judging/index.html", "/judging/metrics.html", "/judging/judge.html", "/judging/invalid.html",
  "/engine/index.html", "/engine/loading.html", "/engine/catalog.html",
  "/engine/governance.html", "/engine/guardrail.html", "/engine/tools.html",
  "/ops/index.html", "/ops/run-api.html", "/ops/artifacts.html",
  "/ops/deploy.html", "/ops/roadmap.html",
];

async function readPage(page) {
  return readFile(new URL(`../public${page}`, import.meta.url), "utf8");
}

test("模块页齐备,共享三层导航壳(模块顶栏 + 模块侧栏 + 本页目录)", async () => {
  assert.equal(SITE_PAGES.length, 25);
  for (const page of SITE_PAGES) {
    const html = await readPage(page);
    assert.match(html, /docs\.css/, `${page} 必须引用 docs.css`);
    assert.match(html, /docs\.js/, `${page} 必须引入共享导航脚本`);
    assert.match(html, /class="topnav"/, `${page} 必须有顶栏导航`);
    for (const href of MODULE_HREFS) {
      assert.ok(html.includes(`href="${href}"`), `${page} 顶栏缺少模块 ${href}`);
    }
    assert.ok(html.includes("topbar-gh"), `${page} 顶栏需要 GitHub 外链`);
    if (page !== "/index.html") {
      assert.match(html, /模块页面/, `${page} 侧栏需要模块页面清单`);
      assert.match(html, /本页目录/, `${page} 侧栏需要本页目录`);
    }
  }
});

test("模块首页从公告首页可达(互链)", async () => {
  const home = await readPage("/index.html");
  for (const href of MODULE_HREFS.slice(1)) {
    assert.ok(home.includes(`href="${href}"`), `首页缺少模块入口 ${href}`);
  }
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
  assert.match(nginx, /location \/home\//, "nginx 需服务机甲子页前缀");
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

test("公告首页含使用指引与概览五节,数据驱动数字卡", async () => {
  const announce = await readPage("/index.html");
  for (const anchor of ["steps", "notices", "login", "about", "architecture", "banks", "status", "repo"]) {
    assert.ok(announce.includes(`id="${anchor}"`), `公告页缺少第 ${anchor} 节`);
  }
  assert.match(announce, /试用步骤/, "使用指引需在最上部");
  assert.match(announce, /showcase-data\/index\.json/, "数字卡读发布产物");
  assert.match(announce, /renderStatCards|renderHomeBanner/, "复用实证层渲染函数");
});

test("机甲风格子页 /home: 纯静态、唯一进入系统按钮、无导航堆叠", async () => {
  const home = await readPage("/home/index.html");
  assert.ok(home.includes('href="/"'), "机甲页需提供进入系统入口(指向公告首页)");
  assert.ok(home.includes("进入系统"), "右上角进入系统按钮需存在");
  assert.doesNotMatch(home, /id="navLinks"|id="menuToggle"/, "机甲页不再堆叠引/护/问/藏导航");
  assert.ok((home.match(/href="\/lab/g) || []).length <= 1, "登录入口至多一个");
  assert.doesNotMatch(home, /\/api\/v1\//, "机甲页不得出现后端 API");
  assert.doesNotMatch(home, /<input|<textarea/, "机甲页不得出现输入控件");
  assert.doesNotMatch(home, /sessionStorage|localStorage/, "机甲页无会话概念");
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
