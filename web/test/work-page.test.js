import { readFile, access } from "node:fs/promises";
import { test } from "node:test";
import assert from "node:assert/strict";

/**
 * 工作项目页(/work/)契约:
 * 页面存在且挂入主导航;四张脱敏图表齐备并被页面引用;
 * 图表与页面不得出现内部实现标识(行方服务编码 / 内部模块与表名 / 内部通道名)——
 * 脱敏规则与 scripts/import-work-diagrams.mjs 同步维护。
 */

const DIAGRAMS = [
  "b2b-legal-overdraft.svg",
  "b2b-commercial-bill.svg",
  "contract-review.svg",
  "bob-loan-service.svg",
  "open-platform-architecture.svg",
];

/** 禁止出现在公开产物中的内部标识(脱敏防泄漏护栏) */
const FORBIDDEN_PATTERNS = [
  /MBSD/i,
  /MbsdNl/,
  /JZH-\d/,
  /bobbank/i,
  /commercial_bill/,
  /assertCan\w+/,
  /szFactory/,
  /jingloan/i,
  /ApiFunctionController/,
  /ums_resource/,
  /alreadyRepayAmt/,
  /draftNo/,
  /dueDt/,
];

test("代表项目门户页:作为首页存在、五张图表齐备", async () => {
  const html = await readFile(new URL("../public/index.html", import.meta.url), "utf8");
  assert.match(html, /工作项目 · 代表项目/, "页面标题");
  assert.match(html, /代表项目/, "导航含代表项目入口");
  for (const file of DIAGRAMS) {
    assert.ok(html.includes(`/work/diagrams/${file}`), `页面缺少图表引用 ${file}`);
    await access(new URL(`../public/work/diagrams/${file}`, import.meta.url));
  }
  assert.match(html, /脱敏版/, "页面明示图表为脱敏版");
  // 系统总览页导航同样挂入代表项目(首页)入口
  const overview = await readFile(new URL("../public/overview/index.html", import.meta.url), "utf8");
  assert.ok(overview.includes('href="/"'), "系统总览页导航缺少代表项目入口");
});

test("代表项目门户页:图表与页面无内部实现标识(脱敏护栏)", async () => {
  const html = await readFile(new URL("../public/index.html", import.meta.url), "utf8");
  for (const pattern of FORBIDDEN_PATTERNS) {
    assert.doesNotMatch(html, pattern, `页面出现内部标识 ${pattern}`);
  }
  for (const file of DIAGRAMS) {
    const svg = await readFile(new URL(`../public/work/diagrams/${file}`, import.meta.url), "utf8");
    for (const pattern of FORBIDDEN_PATTERNS) {
      assert.doesNotMatch(svg, pattern, `${file} 出现内部标识 ${pattern}`);
    }
    assert.match(svg, /<svg[\s>]/, `${file} 为合法 SVG 根元素`);
  }
});
