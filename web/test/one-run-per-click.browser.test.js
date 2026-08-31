/**
 * 浏览器级验收(P0-1):一次用户点击最多创建一个 Agent 运行。
 *
 * 用 playwright(可选依赖)+ dev-server(纯 Node,无外部依赖)做真实页面验证:
 * 页面 JS 全部真实执行,API 层用路由拦截打桩(不启动 engine,不调用任何模型):
 *  1. 发起页点击一次「提交批次」→ /experiment-series 恰好 1 次 POST,
 *     /experiment-series/{id}/runs 的 POST 为 0(第一个样本由用户在实验组页点击创建),
 *     且页面跳转到 /experiment/series/{id};
 *  2. 实验组页统计「先成功、后失败」→ 旧快照立即失效,
 *     不再参与推荐,运行按钮保持禁用(P1-1)。
 *
 * playwright 或 chromium 未安装时跳过(可选能力,与 visual-smoke 同策略):
 *   启用:cd web && npm install && npx playwright install chromium
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { test } from "node:test";
import assert from "node:assert/strict";

// 浏览器二进制位置:与 visual-smoke 同约定——优先 env,其次仓库同级 playwright-browsers/。
// 必须在 import playwright 之前设置:playwright-core 在模块加载时读取该环境变量。
if (!process.env.PLAYWRIGHT_BROWSERS_PATH) {
  const sibling = path.resolve(
    path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")),
    "..", "..", "..", "playwright-browsers",
  );
  if (existsSync(sibling)) process.env.PLAYWRIGHT_BROWSERS_PATH = sibling;
}

let playwright = null;
try {
  playwright = await import("playwright");
} catch {
  console.log("[one-run-per-click] playwright 未安装,浏览器级测试跳过(可选能力)。");
}

const OWNER_TEMPLATE = {
  template_id: "governance-on-off",
  version: 1,
  purpose: "工具调用治理的有效性验证",
  classification: "formal",
  independent_variable: ["governance_profile"],
  variants: [{ label: "off" }, { label: "standard" }],
  allowed_test_types: ["COMPARISON_CASE"],
  anonymous_allowed: false,
  owner_allowed: true,
  repeat_count_range: [1, 5],
  formal_min_repeat_count: 3,
  advanced_allowed_paths: [],
  frozen_conditions: {},
};

const SERIES_ID = "series-e2e-0001";

function templatePayload() {
  return { templates: [OWNER_TEMPLATE] };
}

function seriesDetail(totalRuns, activeRun = null) {
  return {
    series_id: SERIES_ID,
    template_id: OWNER_TEMPLATE.template_id,
    template_version: 1,
    case_id: "cmp-series-01",
    title: "实验组",
    status: "active",
    definition_hash: "sha256:def",
    variant_labels: ["off", "standard"],
    formal_min_repeat_count: 3,
    expected_config_hashes: { off: "sha256:cfg-off", standard: "sha256:cfg-standard" },
    completed_counts_by_variant: { off: totalRuns, standard: 0 },
    total_runs: totalRuns,
    active_run: activeRun,
    created_at: "2026-08-29T00:00:00+00:00",
  };
}

function statisticsSnapshot(offIncluded) {
  const variant = (label, included) => ({
    variant_id: label,
    included_run_ids: included ? ["run-1"] : [],
    included_count: included ? 1 : 0,
    excluded_count: 0,
    completed_count: included ? 1 : 0,
    failed_count: 0,
    sample_level: included
      ? { level: "single-observation", label: "单次观察" }
      : { level: "no-data", label: "无数据" },
  });
  return {
    series_id: SERIES_ID,
    statistics_version: "experiment-stats-v2",
    formal_min_repeat_count: 3,
    config_hash_mode: "expected",
    included_run_count: offIncluded ? 1 : 0,
    excluded_run_count: 0,
    by_variant: { off: variant("off", offIncluded), standard: variant("standard", false) },
    comparison: { available: false, formal_available: false, reason: "至少两个变体需要有效样本" },
    sample_sufficiency: { by_variant: {}, overall_level: "single-observation", overall_label: "单次观察" },
    data_quality_warnings: [],
    notes: [],
    excluded_runs: [],
    generated_at: "2026-08-29T00:00:00+00:00",
  };
}

/** 启动 dev-server(纯 Node):返回 { base, close }。 */
async function startDevServer() {
  const port = 18000 + Math.floor(Math.random() * 2000);
  const webDir = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
  const child = spawn(process.execPath, ["dev-server.js"], {
    cwd: webDir,
    env: { ...process.env, HOST: "127.0.0.1", PORT: String(port), RUN_API_PROXY: "off" },
    stdio: "ignore",
  });
  const base = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 50; i++) {
    try {
      const res = await fetch(base + "/experiment/run.html");
      if (res.ok) return { base, close: () => child.kill() };
    } catch {
      /* 未就绪,重试 */
    }
    await delay(100);
  }
  child.kill();
  throw new Error("dev-server 未能在 5s 内就绪");
}

async function withPage(t, routeHandlers) {
  // chromium 缺失(未执行 playwright install)时跳过,不作为测试失败
  let browser;
  try {
    browser = await playwright.chromium.launch();
  } catch (err) {
    t.skip(`chromium 未安装,跳过浏览器级验收(${err.message.split("\n")[0]})`);
    return null;
  }
  const server = await startDevServer();
  const base = server.base;
  const context = await browser.newContext();
  // 所有者会话:页面脚本从 sessionStorage 读 ts_owner
  await context.addInitScript(() => sessionStorage.setItem("ts_owner", "e2e-owner-token"));
  const page = await context.newPage();
  let seriesPosts = 0;
  let runPosts = 0;
  await page.route("**/api/v1/**", (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    if (path === "/api/v1/experiment-series" && method === "POST") {
      seriesPosts += 1;
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          series_id: SERIES_ID,
          template_id: OWNER_TEMPLATE.template_id,
          case_id: "cmp-series-01",
          variant_labels: ["off", "standard"],
          definition_hash: "sha256:def",
          formal_min_repeat_count: 3,
          expected_config_hashes: { off: "sha256:cfg-off", standard: "sha256:cfg-standard" },
        }),
      });
    }
    if (/^\/api\/v1\/experiment-series\/[^/]+\/runs$/.test(path) && method === "POST") {
      runPosts += 1;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ run_key: "run-001" }) });
    }
    for (const handler of routeHandlers) {
      if (handler(path, method, route)) return;
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
  return {
    page,
    base,
    counters: {
      get seriesPosts() { return seriesPosts; },
      get runPosts() { return runPosts; },
    },
    close: async () => {
      await browser.close();
      server.close();
    },
  };
}

if (playwright) {
  test("发起页一次点击只创建实验组,不自动创建任何 Agent 运行,并跳转实验组页", async (t) => {
    const env = await withPage(t, [
      (path, method, route) => {
        if (path === "/api/v1/experiment-templates" && method === "GET") {
          route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(templatePayload()) });
          return true;
        }
        if (path === "/api/v1/public/test-options" && method === "GET") {
          route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              comparison_cases: [{ case_id: "cmp-series-01", case_version: 1, title: "实验组用例" }],
              quota: { repeat_options: [1, 3, 5] },
              fixed_conditions: {},
              call_limits: {},
            }),
          });
          return true;
        }
        if (path === "/api/v1/template-batches/plan" && method === "POST") {
          route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              template_id: OWNER_TEMPLATE.template_id,
              run_count: 2,
              fixed_conditions: { variant_labels: ["off", "standard"] },
              runs: [],
            }),
          });
          return true;
        }
        if (path === `/api/v1/experiment-series/${SERIES_ID}` && method === "GET") {
          route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(seriesDetail(0)) });
          return true;
        }
        if (path === `/api/v1/experiment-series/${SERIES_ID}/runs` && method === "GET") {
          route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ runs: [] }) });
          return true;
        }
        if (path.startsWith("/api/v1/statistics/") && method === "GET") {
          route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(statisticsSnapshot(false)) });
          return true;
        }
        return false;
      },
    ]);
    if (!env) return;
    t.after(async () => { await env.close(); });

    await env.page.goto(`${env.base}/experiment/run?template=governance-on-off&case=cmp-series-01`, { waitUntil: "domcontentloaded" });

    const submit = env.page.locator("#submitBtn");
    await submit.waitFor({ state: "visible", timeout: 5000 });
    // 预估(plan)到达并显示精确口径后按钮可用
    for (let i = 0; i < 30 && !(await submit.isEnabled()); i++) await delay(100);

    await submit.click();
    // 一次点击 = 一次创建 + 一次跳转;不允许自动创建任何运行
    await env.page.waitForURL(new RegExp(`/experiment/series/${SERIES_ID}`), { timeout: 5000 });
    await delay(300); // 等详情页首屏查询完成
    assert.equal(env.counters.seriesPosts, 1, "一次提交只创建 1 个实验组");
    assert.equal(env.counters.runPosts, 0, "创建实验组不得自动创建任何运行(第一个样本由用户点击)");
  });

  test("实验组页统计先成功后失败:旧快照立即失效,按钮保持禁用", async (t) => {
    let statsFails = false;
    const env = await withPage(t, [
      (path, method, route) => {
        if (path === "/api/v1/experiment-templates" && method === "GET") {
          route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(templatePayload()) });
          return true;
        }
        if (path === `/api/v1/experiment-series/${SERIES_ID}` && method === "GET") {
          route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(seriesDetail(1)) });
          return true;
        }
        if (path === `/api/v1/experiment-series/${SERIES_ID}/runs` && method === "GET") {
          route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ runs: [{ run_key: "run-001", variant_id: "off", status: "done" }] }),
          });
          return true;
        }
        if (path.startsWith("/api/v1/statistics/") && method === "GET") {
          if (statsFails) {
            route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "统计服务不可用" }) });
          } else {
            route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(statisticsSnapshot(true)) });
          }
          return true;
        }
        return false;
      },
    ]);
    if (!env) return;
    t.after(async () => { await env.close(); });

    // 第一次加载:统计成功,快照可用,按钮可用
    await env.page.goto(`${env.base}/experiment/series/${SERIES_ID}`, { waitUntil: "domcontentloaded" });
    await env.page.waitForFunction(
      () => { const el = document.querySelector("#seriesBody"); return el && el.style.display === "block"; },
      null,
      { timeout: 5000 },
    );
    for (let i = 0; i < 30 && !(await env.page.locator("#nextRunBtn").isEnabled()); i++) await delay(100);
    assert.ok(await env.page.locator("#nextRunBtn").isEnabled(), "统计 ready 后运行按钮可用");

    // 第二次加载(重新载入页面):统计失败 → 旧快照失效,按钮禁用,无推荐
    statsFails = true;
    await env.page.reload({ waitUntil: "domcontentloaded" });
    await env.page.waitForFunction(
      () => { const el = document.querySelector("#seriesBody"); return el && el.style.display === "block"; },
      null,
      { timeout: 5000 },
    );
    await delay(400);
    const hint = await env.page.locator("#nextRunHint").textContent();
    assert.match(hint || "", /旧快照已失效|统计请求失败/, "失败提示明确说明旧快照失效");
    assert.doesNotMatch(hint || "", /下一建议/, "失败后不得基于旧快照给出建议");
    assert.equal(await env.page.locator("#nextRunBtn").isDisabled(), true, "统计失败后运行按钮保持禁用");
  });
} else {
  test("浏览器级验收跳过(playwright 未安装)", () => {
    assert.ok(true);
  });
}
