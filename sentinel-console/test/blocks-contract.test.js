import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

async function loadBlocks() {
  const source = await readFile(new URL("../public/assets/blocks.js", import.meta.url), "utf8");
  const context = { globalThis: {} };
  context.window = context.globalThis;
  vm.runInNewContext(source, context);
  return context.globalThis.SentinelBlocks;
}

test("Block 渲染器按类型分发，未知类型折叠 JSON", async () => {
  const Blocks = await loadBlocks();
  const score = Blocks.render({
    type: "ScoreCard",
    payload: {
      symbol: "300750",
      name: "宁德时代",
      overall: 72,
      scale: 100,
      rating: "中性偏强",
      dimensions: [{ name: "技术面", score: 78, trend: "up" }],
    },
  });
  assert.match(score, /data-block-type="ScoreCard"/);
  assert.match(score, /72/);
  assert.match(score, /前端不重算/);
  assert.doesNotMatch(score, /73/);

  const unknown = Blocks.render({ type: "FutureBlock", payload: { x: 1 } });
  assert.match(unknown, /<details/);
  assert.match(unknown, /FutureBlock/);
  assert.match(unknown, /&quot;x&quot;: 1/);
});

test("SuitabilityDraft 守 C-2：匹配+风险成组、无适合/推荐买入、披露固定", async () => {
  const Blocks = await loadBlocks();
  const html = Blocks.render({
    type: "SuitabilityDraft",
    payload: {
      matches: ["风险等级 R3 ↔ 画像稳健型"],
      risks: ["单日波动超画像容忍带 1.8σ"],
      conclusion: "适合买入",
    },
  });
  assert.match(html, /匹配项/);
  assert.match(html, /风险项/);
  assert.match(html, /本结果仅为风险匹配筛查草稿，不构成投资建议。/);
  assert.doesNotMatch(html, /适合买入/);
  assert.doesNotMatch(html, /推荐买入/);
});

test("QuoteTable / PortfolioHealth / AnalysisReport 渲染事实层 payload", async () => {
  const Blocks = await loadBlocks();
  const quote = Blocks.render({
    type: "QuoteTable",
    payload: { columns: ["symbol", "change_pct"], rows: [{ symbol: "300750", change_pct: -5.2 }] },
  });
  assert.match(quote, /300750/);
  assert.match(quote, /num-down/);

  const port = Blocks.render({
    type: "PortfolioHealth",
    payload: { hhi: 0.18, top3_weight: 0.62, sectors: [{ name: "新能源", weight: 0.41 }], risks: ["集中度偏高"] },
  });
  assert.match(port, /0\.18/);
  assert.match(port, /新能源/);

  const report = Blocks.render({
    type: "AnalysisReport",
    payload: { dimensions: [{ name: "基本面", findings: ["营收同比 +12%"], metrics: { pe: 18.4 } }] },
  });
  assert.match(report, /open/);
  assert.match(report, /18\.4/);
});

test("会话页接入 blocks 脚本、追问 chip 与运行控制", async () => {
  const html = await readFile(new URL("../public/chat.html", import.meta.url), "utf8");
  const scripts = [...html.matchAll(/<script[^>]+src="([^"]+)"/g)].map((item) => item[1]);
  assert.equal(scripts.filter((src) => src.includes("echarts")).length, 1);
  assert.match(html, /assets\/blocks\.js/);
  assert.match(html, /id="followupChip"/);
  assert.match(html, /id="runControls"/);
  assert.match(html, /id="clarifyTray"/);
  assert.match(html, /id="degradeBar"/);
});
