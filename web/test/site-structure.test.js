import { readFile, access, readdir } from "node:fs/promises";
import { test } from "node:test";
import assert from "node:assert/strict";
import { REDIRECTS, redirectFor } from "../scripts/redirect-map.mjs";

/**
 * 站点结构契约(信息架构 v3 · 实验结果与原始证据优先):
 * 五页导航(系统总览 / 实验结果 / 原始证据 / 执行逻辑 / 测试逻辑),顺序固定;
 * 全站无登录/运行/试用入口;结果与证据为第一、二核心页;
 * 旧地址按内容唯一归属 301,站内无死链。
 */

const NAV_HREFS = ["/", "/results/", "/evidence/", "/system/", "/methodology/"];
const NAV_LABELS = ["系统总览", "实验结果", "原始证据", "执行逻辑", "测试逻辑"];

const SITE_PAGES = [
  "/index.html",
  "/results/index.html",
  "/evidence/index.html",
  "/evidence/run.html",
  "/system/index.html",
  "/methodology/index.html",
];

async function readPage(page) {
  return readFile(new URL(`../public${page}`, import.meta.url), "utf8");
}

test("五页齐备,共享外壳(静态五导航 + 页脚 GitHub 文字链接)", async () => {
  for (const page of SITE_PAGES) {
    const html = await readPage(page);
    assert.match(html, /docs\.css/, `${page} 必须引用 docs.css`);
    assert.match(html, /docs\.js/, `${page} 必须引入共享脚本`);
    assert.match(html, /class="brand"/, `${page} 顶栏必须有品牌行`);
    assert.match(html, /<nav class="site-nav"/, `${page} 顶栏含静态五导航`);
    const navStart = html.indexOf('<nav class="site-nav"');
    for (const href of NAV_HREFS) {
      assert.ok(html.includes(`href="${href}"`), `${page} 静态导航缺少 ${href}`);
    }
    // 导航顺序与验收标准一致(首页 → 结果 → 证据 → 执行 → 测试)
    const positions = NAV_HREFS.map((href) => html.indexOf(`href="${href}"`, navStart));
    assert.deepEqual([...positions].sort((a, b) => a - b), positions, `${page} 导航顺序必须固定`);
    assert.match(html, /site-foot/, `${page} 有页脚`);
    assert.match(html, /GitHub · bdlhxny-agent/, `${page} 页脚含 GitHub 文字链接`);
  }
  const sharedJs = await readFile(new URL("../public/docs/docs.js", import.meta.url), "utf8");
  for (const label of NAV_LABELS) {
    // docs.js 只做高亮增强,不再注入导航;高亮映射需覆盖五个前缀
    assert.ok(sharedJs.includes(`"${href(label)}"`), `docs.js 高亮映射缺少 ${label}`);
  }
  // 生成器锁定的导航顺序
  const generator = await readFile(new URL("../scripts/generate-site.mjs", import.meta.url), "utf8");
  assert.match(generator, /const NAV = \[[\s\S]*?"\/results\/"[\s\S]*?"\/evidence\/"[\s\S]*?"\/system\/"[\s\S]*?"\/methodology\/"[\s\S]*?\];/, "生成器导航顺序锁定为五页");
});

function href(label) {
  return NAV_HREFS[NAV_LABELS.indexOf(label)];
}

test("全站无登录/运行/试用/我的测试入口", async () => {
  // 禁止 UI 入口:按钮/链接形态的登录、发起、试用,以及历史动作区类名。
  // 「不提供登录入口」之类的否定性说明与「登录态」数据字段不受此限。
  const forbidden = [
    />(\s*)登录(\s*)</, />(\s*)退出登录(\s*)</, />(\s*)我的测试(\s*)</, />(\s*)立即体验(\s*)</,
    />(\s*)开始测试(\s*)</, />(\s*)发起实验(\s*)</, />(\s*)运行 Agent(\s*)</, />(\s*)匿名测试(\s*)</,
    />(\s*)试试看(\s*)</, />(\s*)实验中心(\s*)</, />(\s*)运行台(\s*)</,
    /topbar-login/, /topbar-lab/, /topbar-logout/, /topbar-mytests/,
  ];
  const files = [
    ...SITE_PAGES,
    "/docs/docs.js", "/docs/home.js", "/docs/showcase-data.js",
    "/results/results.js", "/evidence/evidence.js",
  ];
  for (const file of files) {
    const text = await readFile(new URL(`../public${file}`, import.meta.url), "utf8");
    for (const pattern of forbidden) {
      assert.ok(!pattern.test(text), `${file} 不得出现公开试用/登录入口文案:${pattern}`);
    }
  }
  // 顶栏动作区整体移除:外壳不再渲染 topbar-actions
  for (const page of SITE_PAGES) {
    const html = await readPage(page);
    assert.ok(!html.includes("topbar-actions"), `${page} 顶栏不再有登录/实验中心动作区`);
  }
});

test("站内无死链:五页全部内部链接可解析", async () => {
  const publicRoot = new URL("../public/", import.meta.url);
  const exists = async (pathname) => {
    try {
      await access(new URL(pathname.replace(/^\//, ""), publicRoot));
      return true;
    } catch {
      return false;
    }
  };
  for (const page of SITE_PAGES) {
    const html = await readPage(page);
    const hrefs = [...html.matchAll(/href="([^"]+)"/g)].map((m) => m[1]);
    for (const raw of hrefs) {
      if (/^(https?:|mailto:)/.test(raw)) continue;
      const [pathname, hash] = raw.split("#");
      if (!pathname) continue; // 纯页内锚点
      if (await exists(resolvePath(pathname))) {
        if (hash) {
          // 跨页/页内锚点必须在目标文件中存在
          const targetHtml = pathname === page ? html : await readPage(resolvePath(pathname));
          assert.ok(targetHtml.includes(`id="${hash}"`), `${page} 链接 ${raw} 的锚点 #${hash} 不存在`);
        }
        continue;
      }
      // 允许由服务器路由的查询型详情页(/evidence/run/?id=…)
      if (pathname === "/evidence/run/") { await assertRunRoute(); continue; }
      assert.fail(`${page} 链接无法解析:${raw}`);
    }
  }
});

function resolvePath(pathname) {
  let p = pathname.split("?")[0];
  if (p.endsWith("/")) p += "index.html";
  else if (!/\.[a-z]+$/.test(p)) p += ".html";
  return p;
}

let runRouteChecked = false;
async function assertRunRoute() {
  if (runRouteChecked) return;
  runRouteChecked = true;
  const devServer = await readFile(new URL("../dev-server.js", import.meta.url), "utf8");
  assert.match(devServer, /\/evidence\/run/, "dev-server 需路由 /evidence/run/ → run.html");
  const nginx = await readFile(new URL("../nginx.conf", import.meta.url), "utf8");
  assert.match(nginx, /location ~ \^\/evidence\/run\/ \{[\s\S]*?try_files \/evidence\/run\.html/, "nginx 需路由 /evidence/run/ → run.html");
}

test("公开页零后端依赖、零文本输入;筛选只允许 select", async () => {
  for (const page of SITE_PAGES) {
    const html = await readPage(page);
    assert.doesNotMatch(html, /\/api\/v1\//, `${page} 不得出现后端 API`);
    assert.doesNotMatch(html, /<textarea/, `${page} 不得出现文本域`);
    assert.doesNotMatch(html, /type="text"/, `${page} 不得出现任意文本输入`);
    assert.doesNotMatch(html, /<input|<form/, `${page} 不得出现输入控件或表单`);
    assert.doesNotMatch(html, /sessionStorage|localStorage/, `${page} 无会话读写`);
    assert.doesNotMatch(html, /href="\/lab/, `${page} 不得链接运行台`);
    for (const url of [...html.matchAll(/fetch\((["'])([^"']+)\1/g)].map((m) => m[2])) {
      assert.ok(url.startsWith("/showcase-data/"), `${page} 的 fetch 只允许 /showcase-data/:${url}`);
    }
  }
  // 数据页面允许 select 筛选(浏览操作);说明页不得出现任何控件
  for (const page of ["/system/index.html", "/methodology/index.html", "/index.html"]) {
    const html = await readPage(page);
    assert.doesNotMatch(html, /<select/, `${page} 说明页不得出现筛选控件`);
  }
  for (const page of ["/results/index.html", "/evidence/index.html"]) {
    const html = await readPage(page);
    assert.match(html, /<select/, `${page} 数据页应提供筛选`);
  }
});

test("前端数据适配层唯一:页面经 SHOWCASE(loadIndex/loadBatch/loadRun)读 showcase-data", async () => {
  const adapter = await readFile(new URL("../public/docs/showcase-data.js", import.meta.url), "utf8");
  assert.match(adapter, /loadIndex\s*:/, "适配层提供 loadIndex");
  assert.match(adapter, /loadBatch\s*:/, "适配层提供 loadBatch");
  assert.match(adapter, /loadRun\s*:/, "适配层提供 loadRun");
  assert.match(adapter, /\/showcase-data\/index\.json/, "loadIndex 读发布器索引");
  assert.match(adapter, /\/showcase-data\/batches\//, "loadBatch 读批次报告");
  assert.match(adapter, /\/showcase-data\/runs\//, "loadRun 读逐运行工件");
  assert.match(adapter, /未记录/, "适配层统一缺失字段口径");
  // 页面脚本不绕过适配层自行 fetch
  for (const js of ["/results/results.js", "/evidence/evidence.js", "/docs/home.js"]) {
    const text = await readFile(new URL(`../public${js}`, import.meta.url), "utf8");
    assert.doesNotMatch(text, /fetch\(/, `${js} 不得绕过适配层直接 fetch`);
    assert.match(text, /SHOWCASE/, `${js} 必须消费统一适配层`);
  }
});

test("结果页:筛选五维 + 指标分母 + 下钻证据 + 成败并展 + 朴素柱状图", async () => {
  const page = await readPage("/results/index.html");
  for (const id of ["fExperiment", "fCase", "fBatch", "fVariant", "fStatus"]) {
    assert.ok(page.includes(`id="${id}"`), `结果页筛选缺少 ${id}`);
  }
  assert.match(page, /尚无正式实验结果/, "无数据时使用统一空状态");
  const js = await readFile(new URL("../public/results/results.js", import.meta.url), "utf8");
  assert.match(js, /分母/, "指标必须展示分母");
  assert.match(js, /loadPublished|SC\.loadBatch/, "结果页消费发布快照");
  assert.match(js, /\/evidence\/\?batch=/, "样本规模下钻到证据索引");
  assert.match(js, /\/evidence\/run\/\?id=/, "代表案例下钻到单次运行证据链");
  assert.match(js, /成功代表/, "展示成功代表");
  assert.match(js, /失败代表/, "展示失败代表");
  assert.match(js, /bar-fill/, "变体对比使用朴素柱状图");
  assert.match(js, /未记录/, "缺失字段显示未记录");
});

test("证据页:六维筛选 + 分页 + 11 段证据链 + 只有复制无下载重跑", async () => {
  const page = await readPage("/evidence/index.html");
  for (const id of ["eBatch", "eExperiment", "eCase", "eVariant", "eResult", "eFailure"]) {
    assert.ok(page.includes(`id="${id}"`), `证据索引筛选缺少 ${id}`);
  }
  assert.match(page, /尚无公开发布的运行/, "无数据时使用统一空状态");
  const js = await readFile(new URL("../public/evidence/evidence.js", import.meta.url), "utf8");
  for (let no = 1; no <= 11; no += 1) {
    const label = String(no).padStart(2, "0");
    assert.ok(js.includes(`"${label}"`), `证据链缺少第 ${label} 段`);
  }
  // 11 段语义齐备(身份/输入/配置/上下文/时间线/工具/治理/输出/断言/遥测/原始JSON)
  for (const part of ["运行身份与来源", "固定任务输入", "实际生效的运行配置", "上下文构建摘要", "Agent 执行时间线", "逐次工具调用", "治理判定与拦截", "最终输出", "评测断言", "遥测", "原始 JSON"]) {
    assert.ok(js.includes(part), `证据链缺少段落:${part}`);
  }
  assert.match(js, /copy-btn/, "提供复制按钮");
  assert.match(js, /不提供下载或重新运行/, "明确不做下载/重跑");
  assert.doesNotMatch(js, /download|重新运行\(|rerun/, "不得出现下载或重跑实现");
  assert.match(js, /未找到该运行的公开证据/, "无效运行编号有明确空状态");
  assert.match(js, /不含模型内部思维链/, "声明不展示思维链");
});

test("首页事实卡数字与数据真源一致(防硬编码脱节)", async () => {
  const home = await readPage("/index.html");
  const nums = [...home.matchAll(/<div class="fact"><b>(\d+)<\/b>/g)].map((m) => Number(m[1]));
  assert.equal(nums.length, 4, "首页应有四张构成事实卡(工具/用例/Session/模板)");
  const [tools, cases, sessions, templates] = nums;
  const toolsData = JSON.parse(await readFile(new URL("../public/showcase-data/tools.json", import.meta.url), "utf8"));
  assert.equal(tools, toolsData.total, "工具目录数与 tools.json 一致");
  const casesData = JSON.parse(await readFile(new URL("../public/showcase-data/cases.json", import.meta.url), "utf8"));
  assert.equal(cases, casesData.total, "对比用例数与 cases.json 一致");
  const libraryData = JSON.parse(await readFile(new URL("../public/showcase-data/context-library.json", import.meta.url), "utf8"));
  assert.equal(sessions, libraryData.entries.length, "压缩 Session 数与 context-library.json 一致");
  const templatesPy = await readFile(
    new URL("../../engine/src/bdlh_runtime/experiments/templates.py", import.meta.url),
    "utf8",
  );
  const registered = (templatesPy.match(/^_register\(/gm) || []).length;
  assert.equal(templates, registered, `实验模板数与 templates.py 注册数一致(当前注册 ${registered} 个)`);
  // 构成事实明确标注为非成绩
  assert.match(home, /非实验成绩/, "构成事实卡必须声明非实验成绩");
});

test("测试逻辑页承载指标定义唯一版本,执行逻辑页引用不复制", async () => {
  const methodology = await readPage("/methodology/index.html");
  assert.match(methodology, /id="metrics"/, "指标定义在测试逻辑页(锚点 metrics)");
  assert.match(methodology, /全站唯一版本/, "声明为唯一版本");
  const system = await readPage("/system/index.html");
  assert.match(system, /href="\/methodology\/#metrics"/, "执行逻辑页引用指标定义锚点");
  assert.doesNotMatch(system, /<table[^>]*>[\s\S]*?指标定义[\s\S]*?<\/table>/, "执行逻辑页不复制指标定义表");
});

test("实验模板清单与引擎注册表同步", async () => {
  const methodology = await readPage("/methodology/index.html");
  const templatesPy = await readFile(
    new URL("../../engine/src/bdlh_runtime/experiments/templates.py", import.meta.url),
    "utf8",
  );
  const registered = [...templatesPy.matchAll(/template_id="([a-z0-9-]+)"/g)].map((m) => m[1]);
  for (const id of registered) {
    assert.ok(methodology.includes(id), `测试逻辑页实验清单缺少模板 ${id}`);
  }
  assert.match(methodology, /模板存在不代表已有正式结果/, "区分模板存在与已有结果");
});

test("旧地址 301:redirect-map 与 nginx 一致,按内容唯一归属", async () => {
  // 关键归属抽查(不机械跳首页)
  assert.equal(redirectFor("/experiment"), "/methodology/");
  assert.equal(redirectFor("/experiment/batch"), "/evidence/");
  assert.equal(redirectFor("/test"), "/evidence/");
  assert.equal(redirectFor("/showcase/results"), "/results/");
  assert.equal(redirectFor("/showcase/runs"), "/evidence/");
  assert.equal(redirectFor("/showcase/tools"), "/evidence/");
  assert.equal(redirectFor("/context"), "/system/");
  assert.equal(redirectFor("/context/library"), "/methodology/");
  assert.equal(redirectFor("/context/results"), "/results/");
  assert.equal(redirectFor("/judging"), "/methodology/");
  assert.equal(redirectFor("/judging/metrics"), "/methodology/");
  assert.equal(redirectFor("/engine"), "/system/");
  assert.equal(redirectFor("/engine/catalog"), "/system/");
  assert.equal(redirectFor("/ops"), "/system/");
  assert.equal(redirectFor("/tools"), "/system/");
  assert.equal(redirectFor("/cases"), "/methodology/");
  assert.equal(redirectFor("/assets"), "/methodology/");
  assert.equal(redirectFor("/docs"), "/system/");
  assert.equal(redirectFor("/docs/results"), "/results/");
  assert.equal(redirectFor("/lab"), "/system/");
  // 目录斜杠/扩展名归一化
  assert.equal(redirectFor("/experiment/"), "/methodology/");
  assert.equal(redirectFor("/judging/metrics.html"), "/methodology/");
  // 带路径参数的旧详情地址
  assert.equal(redirectFor("/experiment/batch/01234567-89ab"), "/evidence/");
  assert.equal(redirectFor("/lab/anything"), "/system/");
  // 静态资产不重定向
  assert.equal(redirectFor("/docs/docs.css"), null);
  assert.equal(redirectFor("/showcase-data/cases.json"), null);

  const nginx = await readFile(new URL("../nginx.conf", import.meta.url), "utf8");
  for (const [from, to] of REDIRECTS) {
    assert.ok(
      nginx.includes(`location = ${from} { return 301 ${to}; }`),
      `nginx 缺少 301:${from} → ${to}`,
    );
  }
  assert.match(nginx, /location ~ \^\/experiment\/batch\/ \{ return 301 \/evidence\/; \}/, "批次详情旧前缀 301 到证据");
  // dev-server 与 nginx 同口径
  const devServer = await readFile(new URL("../dev-server.js", import.meta.url), "utf8");
  assert.match(devServer, /redirectFor/, "dev-server 需接入 301 映射");
  assert.match(devServer, /301/, "dev-server 需以 301 重定向");
  assert.ok(
    devServer.includes('"/results", "/evidence", "/system", "/methodology"'),
    "dev-server 服务五页模块前缀",
  );
});

test("五页之外的旧模块目录已物理删除(不留页面壳)", async () => {
  for (const dir of ["about", "assets", "cases", "catalog", "context", "engine", "experiment", "judging", "ops", "showcase", "test", "tools"]) {
    await assert.rejects(
      () => access(new URL(`../public/${dir}/`, import.meta.url)),
      `public/${dir}/ 应已删除`,
    );
  }
  await assert.rejects(() => access(new URL("../public/docs/index.html", import.meta.url)), "docs/index.html 应已删除(静态资产目录无索引页)");
  await assert.rejects(() => access(new URL("../public/docs/experiment.js", import.meta.url)), "experiment.js 应已删除");
  // docs 目录只保留静态资产
  const docsFiles = await readdir(new URL("../public/docs/", import.meta.url));
  for (const name of docsFiles) {
    assert.match(name, /\.(css|js)$/, `docs 目录只允许静态资产,发现:${name}`);
  }
});

test("静态站生成不发起实验:生成器只读 showcase-data 静态产物", async () => {
  const generator = await readFile(new URL("../scripts/generate-site.mjs", import.meta.url), "utf8");
  const imports = [...generator.matchAll(/^import[^\n]*$/gm)].map((m) => m[0]);
  assert.ok(imports.length > 0, "生成器应显式 import(空 import 面无法白名单校验)");
  for (const line of imports) {
    assert.match(line, /from "node:(fs|path|url)/, `生成器 import 只允许 node:fs/path/url:${line}`);
  }
  assert.doesNotMatch(generator, /urllib|require\("https?"\)|from "(node:)?(http|https|net|undici|axios|node-fetch)/, "生成器不得引入网络请求模块");
});

test("静态产物与生成器同源:重跑 generate:site 不产生差异", async () => {
  const { generateSite } = await import("../scripts/generate-site.mjs");
  const before = [];
  for (const page of SITE_PAGES) before.push(await readPage(page));
  await generateSite();
  for (let i = 0; i < SITE_PAGES.length; i += 1) {
    const after = await readPage(SITE_PAGES[i]);
    assert.equal(after, before[i], `${SITE_PAGES[i]} 与生成器输出不一致(需重跑生成)`);
  }
});

test("showcase-data JSON 无 BOM(浏览器 JSON.parse 可直接解析)", async () => {
  const root = new URL("../public/showcase-data/", import.meta.url);
  const files = ["cases.json", "tools.json", "index.json", "context-library.json", "publications/index.json"];
  for (const name of files) {
    const buf = await readFile(new URL(name, root)).catch(() => null);
    if (!buf) continue;
    assert.ok(!(buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf), `${name} 不得带 UTF-8 BOM`);
  }
});

test("正式发布索引初始为空(空状态真实,无手填成绩)", async () => {
  // 发布器索引以明确空状态随仓库携带:formal_batches 为空、latest_batch 为 null;
  // 本任务不创建正式数据,禁止向此处手填批次条目
  const index = JSON.parse(await readFile(new URL("../public/showcase-data/index.json", import.meta.url), "utf8"));
  assert.deepEqual(index.formal_batches, []);
  assert.equal(index.latest_batch, null);
  const publications = JSON.parse(await readFile(new URL("../public/showcase-data/publications/index.json", import.meta.url), "utf8"));
  assert.deepEqual(publications.formal_publications, [], "发布登记索引为空属预期");
});
