import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

/**
 * 验证灵动版原型具备完整主路径、未选标的状态、响应式规则和可编译交互脚本。
 */
test("灵动版原型结构与交互脚本完整", async () => {
  const html = await readFile(
    new URL("../prototypes/agent-chat-v2.html", import.meta.url),
    "utf8",
  );
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];

  assert.equal(scripts.length, 1);
  assert.doesNotThrow(() => new Function(scripts[0][1]));
  assert.match(html, /<html lang="zh-CN">/);
  assert.match(html, /name="viewport"/);
  assert.match(html, /name="color-scheme" content="light"/);
  assert.match(html, /--bg:#f3f7f4/);
  assert.match(html, /浅色主题：暖白纸面/);
  assert.match(html, /prefers-reduced-motion/);
  assert.match(html, /:focus-visible/);
  assert.match(html, /role="dialog"/);
  assert.match(html, /aria-live="polite"/);
  assert.match(html, /暂不选择，进入普通问答/);
  assert.match(html, /Route → Skill → 校验 → 回答/);
  assert.match(html, /界面原型 · 模拟数据/);
});
