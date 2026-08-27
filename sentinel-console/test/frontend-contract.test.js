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
  assert.match(html, /assets\/blocks\.js/);
  assert.match(html, /id="followupChip"/);
  assert.match(html, /id="pauseBtn"/);
  assert.match(html, /id="resumeBtn"/);
  assert.match(js, /\/api\/v1\/chat\/stream/);
  assert.match(js, /method:\s*"POST"/);
  assert.match(js, /response\.body\.getReader\(\)/);
  assert.match(js, /type==="token"/);
  assert.match(js, /type==="done"/);
  assert.match(js, /type==="clarification"/);
  assert.match(js, /type==="tool.step"/);
  assert.match(js, /type==="response.final"/);
  assert.match(js, /params\.get\("followup"\)/);
  assert.match(js, /params\.get\("sessionId"\)/);
  assert.match(js, /enabledSkillIds/);
  assert.doesNotMatch(js, /new EventSource\(/);
  assert.doesNotMatch(js, /chat\/stream\?userId=/);
  assert.doesNotMatch(js, /agent-runs\?userId=/);
  assert.doesNotMatch(js, /guest-analysis-quota/);
  assert.doesNotMatch(js, /GUEST_ANALYSIS_LIMIT/);
  assert.doesNotMatch(js, /params\.get\("mode"\)/);
});

/**
 * 验证公共导航只保留正式入口；/skills 为开发遗留。
 */
test("公共入口与 Skill 目录边界完整", async () => {
  const [index, consolePage, registry, skillsPage, docsPage, chatHtml, server] = await Promise.all([
    readFile(new URL("../public/index.html", import.meta.url), "utf8"),
    readFile(new URL("../public/api-console.html", import.meta.url), "utf8"),
    readFile(new URL("../public/skills/registry.json", import.meta.url), "utf8"),
    readFile(new URL("../public/skills/index.html", import.meta.url), "utf8"),
    readFile(new URL("../public/docs/index.html", import.meta.url), "utf8"),
    readFile(new URL("../public/chat.html", import.meta.url), "utf8"),
    readFile(new URL("../dev-server.js", import.meta.url), "utf8"),
  ]);

  assert.match(index, /href="\/dashboard"/);
  assert.match(index, /href="\/lab"/);
  assert.match(index, /href="\/docs\/"/);
  assert.match(index, /title="看护首页"/);
  assert.match(index, />护</);
  assert.match(index, /title="固定问题"/);
  assert.match(index, />问</);
  assert.match(index, /title="文档"/);
  assert.match(index, />记</);
  assert.match(index, /title="收藏"/);
  assert.match(index, />藏</);
  assert.doesNotMatch(index, />聊</);
  assert.doesNotMatch(index, />环</);
  assert.doesNotMatch(index, />台</);
  assert.match(index, /ただいま|STANDBY|ONLINE/);
  assert.doesNotMatch(index, /href="\/skills\/"/);
  assert.doesNotMatch(index, /WATCH-FIRST|持仓看护 Agent|Finance Domain Runtime|领域分析|打开据点|個人研究拠点/);
  assert.doesNotMatch(index, /api-console\.html|agent-chat-soft|agent-chat\.html|skill-dashboard\.html/);
  assert.doesNotMatch(consolePage, /旧版聊天|柔版/);
  assert.match(consolePage, /开发工具/);
  assert.match(consolePage, /enabledSkillIds/);
  assert.doesNotMatch(consolePage, /\bmode:\$\("mode"\)|id="mode"|instrument/);
  assert.doesNotMatch(consolePage, /skill-dashboard\.html/);
  assert.match(consolePage, /href="\/skills\/"/);
  assert.match(consolePage, /开发遗留/);
  assert.match(registry, /"id": "stock"/);
  assert.match(registry, /"id": "web-search"/);
  assert.doesNotMatch(registry, /"status": "planned"/);
  assert.match(skillsPage, /开发遗留/);
  assert.match(skillsPage, /href="\/docs\/docs\.css"/);
  assert.match(docsPage, /业务模块/);
  assert.match(docsPage, /整体架构/);
  assert.match(docsPage, /ToolCard|sentinel-engine|双通道/);
  assert.doesNotMatch(docsPage, /Finance Domain Runtime|Domain Dispatcher/);
  assert.match(docsPage, /href="\/docs\/docs\.css"/);
  assert.match(docsPage, /href="\/docs\/comparison"/);
  assert.match(docsPage, /href="\/docs\/eval"/);
  assert.match(docsPage, /href="\/docs\/cases"/);
  assert.match(docsPage, /href="\/docs\/results"/);
  assert.match(docsPage, /href="\/docs\/tools"/);
  assert.doesNotMatch(docsPage, /href="\/dashboard"/);
  assert.doesNotMatch(docsPage, /href="\/lab"/);
  assert.match(chatHtml, /Sentinel/);
  assert.match(chatHtml, /看护首页/);
  assert.doesNotMatch(chatHtml, /管理插件|viewPlugins|pluginTray/);
  assert.match(server, /\/skills\//);
  assert.match(server, /target = "\/docs\/index\.html"/);
});

/**
 * 验证 /workspace 与 /agent 已退役为重定向到 /lab。
 */
test("工作站入口重定向到统一助手", async () => {
  const server = await readFile(new URL("../dev-server.js", import.meta.url), "utf8");
  const nginx = await readFile(new URL("../nginx.conf", import.meta.url), "utf8");

  assert.match(server, /requestPath === "\/workspace"/);
  assert.match(server, /Location: "\/lab"/);
  assert.match(server, /writeHead\(301/);
  assert.doesNotMatch(server, /target = "\/workspace\.html"/);
  assert.doesNotMatch(server, /target = "\/chat\.html"/);
  assert.match(nginx, /return 301 \/lab;/);
  assert.doesNotMatch(nginx, /try_files \/workspace\.html/);
  assert.doesNotMatch(nginx, /try_files \/chat\.html =404;/);
});

/**
 * 对接文档必须描述 SSE 契约 v2，不得再带「现行实现 / 待 T3 切换」状态头。
 */
test("对接文档已切到 SSE 契约 v2 且删除现行实现状态头", async () => {
  const [chatDoc, apiDoc] = await Promise.all([
    readFile(new URL("../CHAT_INTEGRATION.md", import.meta.url), "utf8"),
    readFile(new URL("../API_INTEGRATION.md", import.meta.url), "utf8"),
  ]);

  for (const doc of [chatDoc, apiDoc]) {
    assert.doesNotMatch(doc, /现行实现/);
    assert.doesNotMatch(doc, /届时本文档按设计文档/);
  }
  assert.match(chatDoc, /tool\.step/);
  assert.match(chatDoc, /response\.final/);
  assert.match(chatDoc, /NEED_CLARIFICATION/);
  assert.match(chatDoc, /ScoreCard/);
  assert.match(chatDoc, /SuitabilityDraft/);
  assert.match(apiDoc, /\/api\/v1\/notifications\/\{id\}\/followup/);
  assert.match(apiDoc, /\/api\/v1\/watch-rules/);
  assert.match(apiDoc, /notification/);
});

/**
 * 抽查三个 SSE 事件与一个 Block 类型：文档表述与 chat.js / blocks.js 一致。
 */
test("文档与实现抽查：token / tool.step / response.final 与 ScoreCard", async () => {
  const [chatDoc, chatJs, blocksJs] = await Promise.all([
    readFile(new URL("../CHAT_INTEGRATION.md", import.meta.url), "utf8"),
    readFile(new URL("../public/assets/chat.js", import.meta.url), "utf8"),
    readFile(new URL("../public/assets/blocks.js", import.meta.url), "utf8"),
  ]);

  for (const event of ["token", "tool.step", "response.final"]) {
    assert.match(chatDoc, new RegExp(event.replace(".", "\\.")));
    assert.match(chatJs, new RegExp(`type==="${event.replace(".", "\\.")}"`));
  }
  assert.match(chatJs, /function applyToolStep/);
  assert.match(chatJs, /function applyFinal/);
  assert.match(chatJs, /search_tools/);
  assert.match(chatDoc, /search_tools/);
  assert.match(chatDoc, /ScoreCard/);
  assert.match(blocksJs, /ScoreCard: renderScoreCard/);
  assert.match(blocksJs, /未知结果块/);
});
