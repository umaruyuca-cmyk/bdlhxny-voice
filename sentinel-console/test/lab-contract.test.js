import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("固定话术测试页无自由输入、走 POST 流", async () => {
  const html = await readFile(new URL("../public/lab.html", import.meta.url), "utf8");
  const js = await readFile(new URL("../public/assets/lab.js", import.meta.url), "utf8");
  assert.match(html, /assets\/lab\.js/);
  assert.match(html, /assets\/lab\.css/);
  assert.match(html, /id="scripts"/);
  assert.match(html, /真实 LLM/);
  assert.doesNotMatch(html, /<textarea/);
  assert.doesNotMatch(html, /id="trialForm"|id="trialInput"|id="sessionList"|id="newChat"/);
  assert.match(js, /data-case/);
  assert.match(js, /\/api\/v1\/chat\/stream/);
  assert.match(js, /method: "POST"/);
  assert.match(js, /对我的换房计划有影响吗/);
  assert.match(js, /Authorization/);
  assert.match(js, /LLM_UNAVAILABLE/);
  assert.doesNotMatch(js, /new EventSource\(/);
  assert.doesNotMatch(js, /\?mock=1|MOCK_ANSWERS/);
});

test("追问抽屉与开发入口指向 /lab", async () => {
  const [dashJs, dashHtml, nginx, server, consolePage] = await Promise.all([
    readFile(new URL("../public/assets/dashboard.js", import.meta.url), "utf8"),
    readFile(new URL("../public/dashboard.html", import.meta.url), "utf8"),
    readFile(new URL("../nginx.conf", import.meta.url), "utf8"),
    readFile(new URL("../dev-server.js", import.meta.url), "utf8"),
    readFile(new URL("../public/api-console.html", import.meta.url), "utf8"),
  ]);
  assert.match(dashJs, /\/lab\?/);
  assert.match(dashHtml, /href="\/lab"/);
  assert.match(nginx, /location = \/lab/);
  assert.match(nginx, /try_files \/lab\.html =404;/);
  assert.match(server, /target = "\/lab\.html"/);
  assert.match(consolePage, /href="\/lab"/);
});
