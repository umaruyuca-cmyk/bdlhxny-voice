import { readFile, access, readdir } from "node:fs/promises";
import { test } from "node:test";
import assert from "node:assert/strict";

/**
 * 公开镜像契约(信息架构 v3):
 * 公开站收敛为五页(/ /results/ /evidence/ /system/ /methodology/)+ 静态资产。
 * 零后端调用:public/ 下任何 HTML/JS 不得出现 /api/v1/ 与任何外部运行入口;
 * 服务器(dev-server 与 nginx)不再反代任何 API;
 * 数据页面允许 select 筛选,全站禁止 input/textarea/form;
 * 会话读写(登录态)整体移除。
 */

const PUBLIC_PAGES = [
  ["", "index"],
  ["results", "index"],
  ["evidence", "index"], ["evidence", "run"],
  ["system", "index"],
  ["methodology", "index"],
];

async function readPublicPage(dir, page) {
  const rel = dir ? `../public/${dir}/${page}.html` : `../public/${page}.html`;
  return readFile(new URL(rel, import.meta.url), "utf8");
}

test("公开页面零后端调用、零输入控件(筛选仅 select)", async () => {
  for (const [dir, page] of PUBLIC_PAGES) {
    const html = await readPublicPage(dir, page);
    const key = dir ? `${dir}/${page}` : page;
    assert.ok(!html.includes('href="/lab'), `${key} 不得链接已退役运行台`);
    assert.doesNotMatch(html, /\/api\/v1\//, `${key} 不得出现后端 API`);
    assert.doesNotMatch(html, /<textarea/, `${key} 不得出现文本域`);
    assert.doesNotMatch(html, /<input/, `${key} 不得出现输入控件`);
    assert.doesNotMatch(html, /<form/, `${key} 不得出现表单`);
    assert.doesNotMatch(html, /sessionStorage|localStorage/, `${key} 无会话读写`);
    for (const url of [...html.matchAll(/fetch\((["'])([^"']+)\1/g)].map((m) => m[2])) {
      assert.ok(url.startsWith("/showcase-data/"), `${key} 的 fetch 只允许 /showcase-data/:${url}`);
    }
  }
});

test("公开 JS 资产零后端调用:全部脚本不出现 /api/v1/ 与外站请求", async () => {
  const jsRoot = new URL("../public/docs/", import.meta.url);
  const jsFiles = [
    ...(await readdir(jsRoot)).filter((n) => n.endsWith(".js")).map((n) => `public/docs/${n}`),
    "public/results/results.js",
    "public/evidence/evidence.js",
  ];
  for (const rel of jsFiles) {
    const text = await readFile(new URL(`../${rel}`, import.meta.url), "utf8");
    assert.doesNotMatch(text, /\/api\/v1\//, `${rel} 不得出现后端 API`);
    for (const url of [...text.matchAll(/fetch\((["'])([^"']+)\1/g)].map((m) => m[2])) {
      assert.ok(url.startsWith("/showcase-data/"), `${rel} 的 fetch 只允许 /showcase-data/:${url}`);
    }
    assert.doesNotMatch(text, /sessionStorage|localStorage/, `${rel} 无会话读写`);
  }
});

test("私有运行台(/lab)已退役:目录不存在,旧地址 301 到执行逻辑页", async () => {
  await assert.rejects(() => access(new URL("../public/lab/", import.meta.url)), "lab 目录应已删除");
  const { redirectFor } = await import("../scripts/redirect-map.mjs");
  assert.equal(redirectFor("/lab"), "/system/");
  assert.equal(redirectFor("/lab/"), "/system/");
  assert.equal(redirectFor("/lab/index.html"), "/system/");
});

test("dev-server 与 nginx 均无 API 反代(公开镜像无私有通道)", async () => {
  const devServer = await readFile(new URL("../dev-server.js", import.meta.url), "utf8");
  assert.doesNotMatch(devServer, /\/api\/v1/, "dev-server 不再反代任何 API");
  assert.doesNotMatch(devServer, /RUN_API_PROXY/, "dev-server 移除运行服务代理开关");
  assert.doesNotMatch(devServer, /proxy/i, "dev-server 无代理逻辑");
  const nginx = await readFile(new URL("../nginx.conf", import.meta.url), "utf8");
  assert.doesNotMatch(nginx, /proxy_pass/, "nginx 不再反代任何 API");
  assert.doesNotMatch(nginx, /\/api\/v1/, "nginx 不含 API 路由");
  for (const prefix of ["/results/", "/evidence/", "/system/", "/methodology/"]) {
    assert.ok(nginx.includes(`location ${prefix}`), `nginx 需服务五页模块 ${prefix}`);
  }
});

test("旧所有者通道白名单已随公开入口一并退役", async () => {
  await assert.rejects(
    () => access(new URL("../scripts/owner-api-allowlist.mjs", import.meta.url)),
    "owner-api-allowlist.mjs 应已删除(页面不再调用所有者通道)",
  );
});

test("公开镜像构建:public/ 已无私有运行台目录", async () => {
  const dockerfilePublic = await readFile(new URL("../Dockerfile.public", import.meta.url), "utf8");
  assert.doesNotMatch(dockerfilePublic, /rm -rf/, "lab 已物理移除,公开构建无需删除步骤");
  const dockerfilePrivate = await readFile(new URL("../Dockerfile", import.meta.url), "utf8");
  assert.match(dockerfilePrivate, /COPY public\//, "私有镜像照常复制 public/");

  const publicCompose = await readFile(new URL("../../deploy/docker-compose.public.yml", import.meta.url), "utf8");
  assert.match(publicCompose, /Dockerfile\.public/, "公开 compose 必须使用公开版 Dockerfile");
});
