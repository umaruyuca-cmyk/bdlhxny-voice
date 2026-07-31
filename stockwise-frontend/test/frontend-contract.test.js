import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

/**
 * 验证正式页面使用POST流式协议且不再把消息或用户ID放进URL。
 */
test("正式页面使用同源POST流并遵守身份边界", async () => {
  const html = await readFile(
    new URL("../public/stockwise-chat.html", import.meta.url),
    "utf8",
  );
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];

  assert.equal(scripts.length, 1);
  assert.doesNotThrow(() => new Function(scripts[0][1]));
  assert.match(html, /fetch\(\"\/api\/v1\/chat\/stream\"/);
  assert.match(html, /fetch\(\"\/api\/v1\/chat\/guest-analysis-quota\"/);
  assert.match(html, /method:\"POST\"/);
  assert.match(html, /response\.body\.getReader\(\)/);
  assert.match(html, /type===\"quota\"/);
  assert.match(html, /GUEST_ANALYSIS_LIMIT_REACHED/);
  assert.match(html, /游客分析 \"\+remaining\+\"\/\"\+limit/);
  assert.doesNotMatch(html, /new EventSource\(/);
  assert.doesNotMatch(html, /chat\/stream\?userId=/);
  assert.doesNotMatch(html, /agent-runs\?userId=/);
  assert.match(html, /fetch\(\"\/api\/v1\/agent-runs\?limit=20\"/);
  assert.match(html, /智能研究工作站/);
  assert.match(html, /运行追踪/);
  assert.doesNotMatch(html, />StockWise</);
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
    new URL("../public/stockwise-chat-soft.html", import.meta.url),
    "utf8",
  );
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];

  assert.equal(scripts.length, 1);
  assert.doesNotThrow(() => new Function(scripts[0][1]));
  assert.match(html, /fetch\("\/api\/v1\/chat\/stream"/);
  assert.match(html, /fetch\("\/api\/v1\/agent-runs\?limit=20"/);
  assert.match(html, /sessionId:ST\.sessionIds\[ST\.mode\]/);
  assert.match(html, /assetType:normalizeAssetType/);
  assert.match(html, /id="companionWidget"/);
  assert.match(html, /data-companion-action="follow"/);
});
