import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

/**
 * 验证正式页面使用POST流式协议且不再把消息或用户ID放进URL。
 */
test("正式页面使用同源POST流并遵守身份边界", async () => {
  const html = await readFile(
    new URL("../public/agent-chat.html", import.meta.url),
    "utf8",
  );
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];

  assert.ok(scripts.length >= 1);
  scripts.forEach((script) => assert.doesNotThrow(() => new Function(script[1])));
  assert.match(html, /fetch\(\"\/api\/v1\/chat\/stream\"/);
  assert.match(html, /method:\"POST\"/);
  assert.match(html, /response\.body\.getReader\(\)/);
  assert.match(html, /type===\"token\"/);
  assert.match(html, /type===\"done\"/);
  assert.doesNotMatch(html, /guest-analysis-quota/);
  assert.doesNotMatch(html, /guestQuotaBadge/);
  assert.doesNotMatch(html, /GUEST_ANALYSIS_LIMIT/);
  assert.doesNotMatch(html, /new EventSource\(/);
  assert.doesNotMatch(html, /chat\/stream\?userId=/);
  assert.doesNotMatch(html, /agent-runs\?userId=/);
  assert.match(html, /fetch\(\"\/api\/v1\/agent-runs\?limit=20\"/);
  assert.match(html, /智能研究工作站/);
  assert.match(html, /运行追踪/);
  assert.doesNotMatch(html, />BDLH Agent Runtime</);
  assert.doesNotMatch(html, /问题是否已解决/);
  assert.doesNotMatch(html, /以上知识将加入知识库/);
  assert.match(html, /type===\"clarification\"/);
  assert.match(html, /选择分析口径/);
  assert.match(html, /NEED_CLARIFICATION/);
});

/**
 * 验证柔和版入口复用正式后端协议，并保留陪伴角色的快捷操作。
 */
test("柔和版入口连接后端流式协议", async () => {
  const html = await readFile(
    new URL("../public/agent-chat-soft.html", import.meta.url),
    "utf8",
  );
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];

  assert.ok(scripts.length >= 1);
  scripts.forEach((script) => assert.doesNotThrow(() => new Function(script[1])));
  assert.match(html, /fetch\("\/api\/v1\/chat\/stream"/);
  assert.match(html, /fetch\("\/api\/v1\/agent-runs\?limit=20"/);
  assert.match(html, /sessionId:ST\.sessionIds\[ST\.mode\]/);
  assert.match(html, /assetType:normalizeAssetType/);
  assert.match(html, /id="companionWidget"/);
  assert.match(html, /data-companion-action="follow"/);
});

/**
 * 验证公共导航只保留正式入口，Skill 目录可以通过注册清单扩展。
 */
test("公共入口与 Skill 目录边界完整", async () => {
  const [index, consolePage, dashboard, registry] = await Promise.all([
    readFile(new URL("../public/index.html", import.meta.url), "utf8"),
    readFile(new URL("../public/api-console.html", import.meta.url), "utf8"),
    readFile(new URL("../public/skill-dashboard.html", import.meta.url), "utf8"),
    readFile(new URL("../public/skills/registry.json", import.meta.url), "utf8"),
  ]);

  assert.match(index, /href="\/skill-dashboard\.html"/);
  assert.match(index, /href="\/docs"/);
  assert.match(index, /WebSearchSkill/);
  assert.doesNotMatch(index, /api-console\.html|agent-chat-soft|agent-chat\.html/);
  assert.doesNotMatch(consolePage, /旧版聊天|柔版/);
  assert.match(consolePage, /开发工具/);
  assert.match(dashboard, /fetch\('\/skills\/registry\.json'/);
  assert.match(dashboard, /function renderSkill/);
  assert.match(registry, /"id": "stock"/);
  assert.match(registry, /"id": "web-search"/);
  assert.doesNotMatch(registry, /"status": "planned"/);
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
