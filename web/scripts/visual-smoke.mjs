#!/usr/bin/env node
/**
 * 响应式视觉冒烟(P2-3):在 390 / 768 / 1440 三档视口打开关键页面,
 * 断言无整页横向溢出(scrollWidth ≤ clientWidth + 1px 容差)。
 *
 * 依赖 playwright(可选):未安装时打印说明并以退出码 0 结束——
 * 本脚本不进入 npm test 默认链路,手动执行:npm run test:visual
 * CI 环境装好 playwright + chromium 后即可作为截图回归的基础。
 *
 * 浏览器二进制位置:优先读 PLAYWRIGHT_BROWSERS_PATH 环境变量;未设置且
 * 仓库同级存在 playwright-browsers/ 目录时使用它(本机约定:装在 D 盘,
 * 不占 C 盘缓存)。CI 上两个条件都不成立,走 playwright 默认缓存路径。
 */
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

if (!process.env.PLAYWRIGHT_BROWSERS_PATH) {
  const sibling = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "playwright-browsers",
  );
  if (existsSync(sibling)) process.env.PLAYWRIGHT_BROWSERS_PATH = sibling;
}

const BASE = process.env.SMOKE_BASE_URL || "http://127.0.0.1:8082";
const WIDTHS = [390, 768, 1440];
const PAGES = [
  "/",
  "/experiment/",
  "/experiment/run?template=governance-on-off",
  "/cases/",
  "/test/",
  "/assets/",
  "/docs/",
  "/context/",
];

let chromium;
try {
  ({ chromium } = await import("playwright"));
} catch {
  console.log(
    "[visual-smoke] playwright 未安装,跳过(可选能力)。\n" +
      "  启用:npm i -D playwright && npx playwright install chromium\n" +
      "  运行:先 npm run dev,再 npm run test:visual",
  );
  process.exit(0);
}

const browser = await chromium.launch();
let failures = 0;
for (const width of WIDTHS) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  for (const path of PAGES) {
    await page.goto(BASE + path, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(300); // 等 JS 渲染(目录表/模板卡)
    const overflow = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    const ok = overflow.scroll <= overflow.client + 1;
    if (!ok) {
      failures += 1;
      console.error(`✖ ${width}px ${path}: 横向溢出 scroll=${overflow.scroll} client=${overflow.client}`);
    } else {
      console.log(`✔ ${width}px ${path}`);
    }
  }
  await page.close();
}
await browser.close();
if (failures) {
  console.error(`visual-smoke: ${failures} 处溢出`);
  process.exit(1);
}
console.log("visual-smoke: 全部通过(3 档宽度 × " + PAGES.length + " 页)");
