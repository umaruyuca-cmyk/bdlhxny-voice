#!/usr/bin/env node
/**
 * 响应式视觉冒烟(信息架构 v3):在 390 / 768 / 1440 三档视口打开五页,
 * 断言无整页横向溢出(scrollWidth ≤ clientWidth + 1px 容差),
 * 且无页面错误(pageerror)与控制台 error 输出(公开站零脚本故障)。
 *
 * 依赖 playwright(可选):未安装时打印说明并以退出码 0 结束——
 * 本脚本不进入 npm test 默认链路,手动执行:npm run test:visual
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
  "/results/",
  "/evidence/",
  "/evidence/run/?id=smoke-missing-run",
  "/system/",
  "/methodology/",
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
  const consoleErrors = [];
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(`console.error: ${message.text()}`);
  });
  for (const path of PAGES) {
    consoleErrors.length = 0;
    await page.goto(BASE + path, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(300); // 等 JS 渲染(空状态/筛选)
    // 负路径页(不存在的运行编号):适配层探测 runs/<id>.json 的 404 资源日志属预期,
    // 页面必须渲染「未找到」空态;除此之外不得有任何控制台错误。
    const expectedProbe404 = path.includes("smoke-missing-run");
    const blocking = consoleErrors.filter((e) =>
      !(expectedProbe404 && /404 \(Not Found\)/.test(e) && e.includes("Failed to load resource")));
    let ok = blocking.length === 0;
    if (expectedProbe404) {
      const emptyState = await page.evaluate(() =>
        document.body.innerText.includes("未找到该运行的公开证据"));
      if (!emptyState) { ok = false; blocking.push("missing-run 空状态未渲染"); }
    }
    const overflow = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    if (overflow.scroll > overflow.client + 1) {
      ok = false;
      blocking.push(`横向溢出 scroll=${overflow.scroll} client=${overflow.client}`);
    }
    if (!ok) {
      failures += 1;
      console.error(`✖ ${width}px ${path}: ${blocking.join(" | ")}`);
    } else {
      console.log(`✔ ${width}px ${path}`);
    }
  }
  await page.close();
}
await browser.close();
if (failures) {
  console.error(`visual-smoke: ${failures} 处失败`);
  process.exit(1);
}
console.log("visual-smoke: 全部通过(3 档宽度 × " + PAGES.length + " 页,含控制台无错误检查)");
