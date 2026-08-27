import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

async function readPublic(rel) {
  return readFile(new URL("../public/" + rel, import.meta.url), "utf8");
}

test("看护首页四区、骨架屏、空态与 ECharts 单脚本", async () => {
  const html = await readPublic("dashboard.html");
  const css = await readPublic("assets/dashboard.css");
  const echarts = [...html.matchAll(/<script[^>]+src="([^"]+)"/g)].map((item) => item[1]);

  assert.match(html, /id="overviewPanel"/);
  assert.match(html, /id="holdingsList"/);
  assert.match(html, /id="timelinePanel"/);
  assert.match(html, /id="watchBar"/);
  assert.match(html, /id="overviewSkeleton"/);
  assert.match(html, /id="timelineSkeleton"/);
  assert.match(html, /id="timelineEmpty"/);
  assert.match(html, /id="followupDrawer"/);
  assert.match(html, /id="drawerFrame"/);
  assert.match(html, /id="eventChip"/);
  assert.match(html, /演示数据/);
  assert.doesNotMatch(html, /id="userChip"/);
  assert.doesNotMatch(html, />登录</);
  assert.match(html, /assets\/badges\.js/);
  assert.match(html, /assets\/dashboard\.js/);
  assert.equal(echarts.filter((src) => src.includes("echarts")).length, 1);
  assert.match(css, /\.skeleton/);
  assert.match(css, /\.badge-demo/);
  assert.match(css, /\.badge-severity-critical/);
});

test("徽标组件覆盖审计码、证据编号、演示水印与严重度条", async () => {
  const source = await readPublic("assets/badges.js");
  const context = { globalThis: {} };
  context.window = context.globalThis;
  vm.runInNewContext(source, context);
  const badges = context.globalThis.SentinelBadges;
  assert.ok(badges);
  assert.match(badges.audit("RO-OK"), /badge-audit/);
  assert.match(badges.audit("RO-OK"), /RO-OK/);
  assert.match(badges.evidence(["行情快照"]), /\[1\]/);
  assert.match(badges.demoWatermark(), /演示注入/);
  assert.match(badges.severityBar("critical"), /badge-severity-critical/);
  assert.equal(badges.isDemoSource("demo_inject", {}), true);
  assert.equal(badges.isDemoSource("market_poll", { demo: true }), true);
});

test("dashboard 绑定持仓 / 通知 / 监视 / ready，SSE 优先并 30s 轮询回退", async () => {
  const js = await readPublic("assets/dashboard.js");
  assert.match(js, /\/api\/portfolio\/positions/);
  assert.match(js, /\/api\/v1\/notifications/);
  assert.match(js, /\/api\/v1\/notifications\?unread=count/);
  assert.match(js, /\/api\/v1\/watch-rules/);
  assert.match(js, /\/api\/v1\/ready/);
  assert.match(js, /\/api\/v1\/notifications\/stream/);
  assert.match(js, /POLL_MS = 30000/);
  assert.match(js, /method: "POST"/);
  assert.match(js, /\/followup/);
  assert.match(js, /followupDrawer/);
  assert.match(js, /eventChip/);
  assert.match(js, /drawerFrame/);
  assert.doesNotMatch(js, /new EventSource\(/);
  assert.doesNotMatch(js, /\/api\/v1\/auth\//);
  assert.doesNotMatch(js, /Authorization/);
});

test("公开入口收敛为文档页，看护与用例台保留直连", async () => {
  const [nginx, server, index, dash] = await Promise.all([
    readFile(new URL("../nginx.conf", import.meta.url), "utf8"),
    readFile(new URL("../dev-server.js", import.meta.url), "utf8"),
    readPublic("index.html"),
    readPublic("dashboard.html"),
  ]);
  assert.match(nginx, /try_files \/docs\/index\.html =404;/);
  assert.match(nginx, /location = \/dashboard/);
  assert.match(nginx, /try_files \/dashboard\.html =404;/);
  assert.match(nginx, /location \^~ \/api\/v1\/notifications/);
  assert.match(nginx, /location \^~ \/api\/v1\/watch-rules/);
  assert.match(server, /requestPath === "\/"/);
  assert.match(server, /target = "\/docs\/index\.html"/);
  assert.match(server, /target = "\/dashboard\.html"/);
  assert.match(server, /target = "\/lab\.html"/);
  assert.match(server, /pathname.startsWith\("\/api\/v1\/notifications"\)/);
  assert.match(index, /href="\/dashboard"/);
  assert.match(index, />进入<|>台</);
  assert.match(dash, /href="\/"/);
});
