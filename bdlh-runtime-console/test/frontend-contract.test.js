import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

/**
 * 验证统一助手页（chat.html + chat.js）使用 POST 流式协议，且不把身份塞进 URL。
 */
test("统一助手页使用同源 POST 流并遵守身份边界", async () => {
  const html = await readFile(new URL("../public/chat.html", import.meta.url), "utf8");
  const js = await readFile(new URL("../public/assets/chat.js", import.meta.url), "utf8");

  assert.match(html, /assets\/chat\.js/);
  assert.match(js, /\/api\/v1\/chat\/stream/);
  assert.match(js, /method:\s*"POST"/);
  assert.match(js, /response\.body\.getReader\(\)/);
  assert.match(js, /type==="token"/);
  assert.match(js, /type==="done"/);
  assert.match(js, /type==="clarification"/);
  assert.match(js, /enabledSkillIds/);
  assert.doesNotMatch(js, /new EventSource\(/);
  assert.doesNotMatch(js, /chat\/stream\?userId=/);
  assert.doesNotMatch(js, /agent-runs\?userId=/);
  assert.doesNotMatch(js, /guest-analysis-quota/);
  assert.doesNotMatch(js, /GUEST_ANALYSIS_LIMIT/);
  assert.doesNotMatch(js, /params\.get\("mode"\)/);
});

/**
 * 验证公共导航只保留正式入口，Skill 目录可以通过注册清单扩展。
 */
test("公共入口与 Skill 目录边界完整", async () => {
  const [index, consolePage, registry, skillsPage, docsPage, server] = await Promise.all([
    readFile(new URL("../public/index.html", import.meta.url), "utf8"),
    readFile(new URL("../public/api-console.html", import.meta.url), "utf8"),
    readFile(new URL("../public/skills/registry.json", import.meta.url), "utf8"),
    readFile(new URL("../public/skills/index.html", import.meta.url), "utf8"),
    readFile(new URL("../public/docs/index.html", import.meta.url), "utf8"),
    readFile(new URL("../dev-server.js", import.meta.url), "utf8"),
  ]);

  assert.match(index, /href="\/skills\/"/);
  assert.match(index, /href="\/docs\/"/);
  assert.match(index, /DeepSearch/);
  assert.match(index, /Stock Skill/);
  assert.doesNotMatch(index, /api-console\.html|agent-chat-soft|agent-chat\.html|skill-dashboard\.html/);
  assert.doesNotMatch(consolePage, /旧版聊天|柔版/);
  assert.match(consolePage, /开发工具/);
  assert.match(consolePage, /enabledSkillIds/);
  assert.doesNotMatch(consolePage, /\bmode:\$\("mode"\)|id="mode"|instrument/);
  assert.doesNotMatch(consolePage, /skill-dashboard\.html/);
  assert.match(consolePage, /href="\/skills\/"/);
  assert.match(registry, /"id": "stock"/);
  assert.match(registry, /"id": "web-search"/);
  assert.doesNotMatch(registry, /"status": "planned"/);
  assert.match(skillsPage, /Stock Skill/);
  assert.match(skillsPage, /DeepSearch/);
  assert.match(skillsPage, /href="\/docs\/docs\.css"/);
  assert.match(docsPage, /业务模块/);
  assert.match(docsPage, /整体架构/);
  assert.match(docsPage, /href="\/docs\/docs\.css"/);
  assert.match(server, /\/skills\//);
});

/**
 * 验证 /workspace 已退役为重定向到 /agent，不再作为产品入口。
 */
test("工作站入口重定向到统一助手", async () => {
  const server = await readFile(new URL("../dev-server.js", import.meta.url), "utf8");
  const nginx = await readFile(new URL("../nginx.conf", import.meta.url), "utf8");

  assert.match(server, /requestPath === "\/workspace" \|\| requestPath === "\/workspace\/"/);
  assert.match(server, /Location: "\/agent"/);
  assert.match(server, /writeHead\(301/);
  assert.doesNotMatch(server, /target = "\/workspace\.html"/);
  assert.match(nginx, /return 301 \/agent;/);
  assert.doesNotMatch(nginx, /try_files \/workspace\.html/);
});
