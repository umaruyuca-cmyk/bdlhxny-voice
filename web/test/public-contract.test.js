import { readFile, access } from "node:fs/promises";
import { test } from "node:test";
import assert from "node:assert/strict";

/**
 * 公开镜像契约:公开页面零后端调用与零输入控件(实验模块页允许契约 API);
 * 登录遮罩与令牌存储收敛在共享脚本;私有运行台(/lab)已退役——物理不存在,
 * 旧地址 301 到实验中心。
 */

const PUBLIC_PAGES = [
  ["", "index"],
  ["about", "index"], ["about", "banks"], ["about", "repo"],
  ["showcase", "index"], ["showcase", "results"], ["showcase", "tools"], ["showcase", "runs"],
  ["experiment", "index"], ["experiment", "compression"], ["experiment", "run"],
  ["experiment", "batches"], ["experiment", "batch"], ["experiment", "series"],
  ["experiment", "context-workbench"], ["experiment", "context-build"],
  ["test", "index"],
  ["context", "index"], ["context", "library"], ["context", "design"], ["context", "results"],
  ["judging", "index"], ["judging", "metrics"], ["judging", "judge"], ["judging", "invalid"],
  ["engine", "index"], ["engine", "loading"], ["engine", "catalog"],
  ["engine", "governance"], ["engine", "guardrail"], ["engine", "tools"],
  ["ops", "index"], ["ops", "run-api"], ["ops", "artifacts"], ["ops", "deploy"], ["ops", "roadmap"],
];

/** 实验模块页:允许匿名公开接口 + 同源所有者通道白名单(与 nginx/dev-server 反代同口径)。 */
const PUBLIC_API_PAGES = new Set([
  "experiment/index", "experiment/compression", "experiment/run",
  "experiment/batches", "experiment/batch", "experiment/series", "test/index",
  "experiment/context-workbench", "experiment/context-build",
]);
/** 同源所有者通道白名单(前后端对接契约 §2);llm-config/test 供发起页连接检测;
 * experiment-series 供发起页创建实验组与单次运行;statistics 供实验组页统计快照
 * (与 scripts/owner-api-allowlist.mjs、site-structure 同一清单)。 */
const EXPERIMENT_API_OK = /\/api\/v1\/(public(\/|$)|(login|logout|llm-config\/test|experiment-templates|template-batches|experiment-series|statistics|batches|jobs|runs|context)(\/|\?|["'`]|$))/;

async function readPublicPage(dir, page) {
  const rel = dir ? `../public/${dir}/${page}.html` : `../public/${page}.html`;
  return readFile(new URL(rel, import.meta.url), "utf8");
}

test("私有运行台(/lab)已退役:目录物理不存在,旧地址 301 到实验中心", async () => {
  await assert.rejects(() => access(new URL("../public/lab/", import.meta.url)), "lab 目录应已删除");
  const { redirectFor } = await import("../scripts/redirect-map.mjs");
  assert.equal(redirectFor("/lab"), "/experiment/");
  assert.equal(redirectFor("/lab/"), "/experiment/");
  assert.equal(redirectFor("/lab/index.html"), "/experiment/");
});

test("公开页面不链接 /lab、不出现后端调用(实验模块页允许公开接口与所有者通道白名单)", async () => {
  for (const [dir, page] of PUBLIC_PAGES) {
    const html = await readPublicPage(dir, page);
    assert.ok(!html.includes('href="/lab'), `${dir || "root"}/${page}.html 不得链接已退役运行台`);
    const key = dir ? `${dir}/${page}` : page;
    if (key === "ops/run-api") {
      // 私有 API 的文档页:正文列出端点是职责,但不得发起任何真实调用
      assert.doesNotMatch(html, /fetch\(|XMLHttpRequest|axios/, "ops/run-api 文档页不得发起真实后端调用");
    } else if (PUBLIC_API_PAGES.has(key)) {
      const offenders = [...html.matchAll(/\/api\/v1\/[a-z\-]+(\/[a-z\-]+)?/g)].map((m) => m[0]);
      for (const api of offenders) {
        assert.ok(EXPERIMENT_API_OK.test(api), `${key} 引用了白名单之外的端点:${api}`);
      }
    } else {
      assert.doesNotMatch(html, /\/api\/v1\//, `${dir || "root"}/${page}.html 不得出现后端 API`);
    }
    if (!PUBLIC_API_PAGES.has(key)) {
      if (key.startsWith("showcase/")) {
        // showcase 空框架页:允许 disabled 占位控件,禁止表单
        assert.doesNotMatch(html, /<form/, `${key} 不得出现表单提交`);
      } else {
        assert.doesNotMatch(html, /<input|<form|<textarea/, `${dir || "root"}/${page}.html 不得出现输入控件`);
      }
    }
  }
});

test("登录遮罩:公开页登录不跳转;登录后留在当前页刷新角色视图", async () => {
  const docsJs = await readFile(new URL("../public/docs/docs.js", import.meta.url), "utf8");
  assert.match(docsJs, /\/api\/v1\/login/, "遮罩登录需调用登录端点");
  assert.match(docsJs, /preventDefault/, "点击登录不得跳转页面");
  assert.match(docsJs, /ts_owner/, "成功后写入会话令牌(ts_owner)");
  assert.match(docsJs, /topbar-lab/, "登录后显示实验中心入口");
  assert.match(docsJs, /\/api\/v1\/logout/, "顶栏需提供退出登录并调用注销端点");
  assert.match(docsJs, /topbar-logout/, "登录后显示退出登录按钮");
  assert.match(docsJs, /location\.reload\(\)/, "登录成功后留在当前页刷新角色视图(实验模块同页双角色)");
  assert.match(docsJs, /labBtn\.href = logged/, "实验中心链接由脚本登录态动态赋址(公开 HTML 不硬编码)");
  const css = await readFile(new URL("../public/docs/docs.css", import.meta.url), "utf8");
  assert.match(css, /\.topbar-lab\s*\{[^}]*display:\s*none/, "实验中心入口默认不可见");
  // 遮罩表单由共享脚本运行时注入,公开页 HTML 源保持零输入控件
  // (实验模块页的选择/数字输入是实验配置控件;showcase 空框架页的 disabled 占位为纯展示)
  for (const [dir, page] of PUBLIC_PAGES) {
    const key = dir ? `${dir}/${page}` : page;
    if (PUBLIC_API_PAGES.has(key)) continue;
    const html = await readPublicPage(dir, page);
    const isShowcaseFrame = key.startsWith("showcase/");
    if (isShowcaseFrame) {
      assert.doesNotMatch(html, /<input(?![^>]*disabled)/, `${key} 的 input 只能是 disabled 占位`);
    } else {
      assert.doesNotMatch(html, /<input|<textarea/, `${dir || "root"}/${page}.html HTML 源不得出现输入控件`);
    }
  }
});

test("公开镜像构建:public/ 已无私有运行台目录", async () => {
  const dockerfilePublic = await readFile(new URL("../Dockerfile.public", import.meta.url), "utf8");
  assert.doesNotMatch(dockerfilePublic, /rm -rf/, "lab 已物理移除,公开构建无需删除步骤");
  const dockerfilePrivate = await readFile(new URL("../Dockerfile", import.meta.url), "utf8");
  assert.match(dockerfilePrivate, /COPY public\//, "私有镜像照常复制 public/");

  const publicCompose = await readFile(new URL("../../deploy/docker-compose.public.yml", import.meta.url), "utf8");
  assert.match(publicCompose, /Dockerfile\.public/, "公开 compose 必须使用公开版 Dockerfile");
});

test("登录令牌不出现在公开数据契约的禁止字段清单之外的页面脚本中", async () => {
  for (const [dir, page] of PUBLIC_PAGES) {
    const html = await readPublicPage(dir, page);
    assert.doesNotMatch(html, /sessionStorage|localStorage/, `${dir || "root"}/${page}.html 无内联会话读写`);
  }
});
