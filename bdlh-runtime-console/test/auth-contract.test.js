import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("工作站提供登录和用户名密码注册，并为 API 自动携带 JWT", async () => {
  const html = await readFile(new URL("../public/workspace.html", import.meta.url), "utf8");
  const script = await readFile(
    new URL("../public/assets/workspace-common.js", import.meta.url),
    "utf8",
  );

  assert.match(html, /id="modalAuth"/);
  assert.match(html, /id="authRegisterButton"/);
  assert.match(html, /注册账号/);
  assert.match(script, /\/api\/v1\/auth\/\$\{registering\?"register":"login"\}/);
  assert.match(script, /\/api\/v1\/auth\/me/);
  assert.match(script, /Authorization","Bearer "/);
  assert.match(script, /apiFetch\("\/api\/v1\/chat\/stream"/);
});

test("浏览器会话和标的缓存按登录用户隔离", async () => {
  const script = await readFile(
    new URL("../public/assets/workspace-common.js", import.meta.url),
    "utf8",
  );

  assert.match(script, /userStorageKey\(SESSION_STORAGE_KEY\)/);
  assert.match(script, /userStorageKey\("bdlh_runtime\.currentInstrument"\)/);
  assert.match(script, /AUTH\.user\?\.userId\|\|"anonymous"/);
  assert.doesNotMatch(script, /body:JSON\.stringify\([^)]*userId/s);
});

test("新版统一聊天页复用账号体系并按用户隔离本地会话", async () => {
  const [html, script, css, server] = await Promise.all([
    readFile(new URL("../public/chat.html", import.meta.url), "utf8"),
    readFile(new URL("../public/assets/chat.js", import.meta.url), "utf8"),
    readFile(new URL("../public/assets/chat-theme.css", import.meta.url), "utf8"),
    readFile(new URL("../dev-server.js", import.meta.url), "utf8"),
  ]);

  assert.match(html, /id="authModal"/);
  assert.match(html, /id="authRegister"/);
  assert.match(html, /注册账号/);
  assert.match(script, /\/api\/v1\/auth\/"\+\(registering\?"register":"login"\)/);
  assert.match(script, /headers\.set\("Authorization","Bearer "\+token\)/);
  assert.match(script, /STORAGE_BASE\+"\."\+\(AUTH\.user\?AUTH\.user\.userId:"anonymous"\)/);
  assert.match(script, /regenerate:!!regenerateExisting/);
  assert.match(script, /method:"DELETE"/);
  assert.match(server, /BDLH_RUNTIME_ANALYSIS_URL/);
  assert.match(server, /pathname\.startsWith\("\/api\/v1\/auth\/"\)/);
  assert.match(server, /return backendUrl/);
  assert.match(server, /pathname\.startsWith\("\/api\/v1\/chat\/"\)/);
  assert.match(server, /target = "\/chat\.html"/);
  assert.match(html, /aria-controls="sidebar" aria-expanded="true"/);
  assert.match(script, /function setSidebarCollapsed\(collapsed\)/);
  assert.match(script, /setAttribute\("aria-expanded",String\(!collapsed\)\)/);
  assert.match(css, /\.sidebar\.collapsed\{width:52px/);
  assert.doesNotMatch(css, /\.sidebar\.collapsed\{width:0/);
});
