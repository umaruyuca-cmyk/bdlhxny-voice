import { readFile } from "node:fs/promises";
import { test } from "node:test";
import assert from "node:assert/strict";

/**
 * /showcase 实证层契约(七模块版):三页共享壳、与全站模块互链、纯静态零后端。
 */

const SHOWCASE_PAGES = ["index", "tools"];
const REDIRECT_PAGES = ["results", "runs"];

async function readShowcase(page) {
  return readFile(new URL(`../public/showcase/${page}.html`, import.meta.url), "utf8");
}

test("旧地址 results/runs 保留跳转", async () => {
  for (const page of REDIRECT_PAGES) {
    const html = await readShowcase(page);
    assert.match(html, /http-equiv="refresh"/, `${page}.html 需为跳转页`);
  }
});

test("实证层页面共享级联导航壳", async () => {
  for (const page of SHOWCASE_PAGES) {
    const html = await readShowcase(page);
    assert.match(html, /docs\.css/, `${page}.html 必须引用 docs.css`);
    assert.match(html, /docs\.js/, `${page}.html 必须引入共享导航脚本`);
    assert.match(html, /class="brand"/, `${page}.html 顶栏必须有品牌行`);
    assert.match(html, /class="side-tree"/, `${page}.html 侧栏必须有级联模块树`);
    for (const href of ["/", "/about/", "/experiment/", "/context/", "/judging/", "/engine/", "/ops/"]) {
      // 实验模块一级只有压缩/对比两个入口,模块根以子链接前缀出现
      const probe = href === "/experiment/" ? 'href="/experiment/' : `href="${href}"`;
      assert.ok(html.includes(probe), `${page}.html 侧栏树缺少模块 ${href}`);
    }
    assert.match(html, /side-group here" open/, `${page}.html 当前模块(实证展示)必须默认展开`);
    assert.doesNotMatch(html, /\/showcase\/context/, `${page}.html 不得再链接已迁移的旧上下文页`);
  }
});

test("实证层零后端依赖、无交互输入", async () => {
  for (const page of [...SHOWCASE_PAGES, ...REDIRECT_PAGES]) {
    const html = await readShowcase(page);
    assert.doesNotMatch(html, /\/api\/v1\//, `${page}.html 不得出现后端 API 调用`);
    assert.doesNotMatch(html, /<form|<textarea/, `${page}.html 不得出现表单或文本域`);
    assert.doesNotMatch(html, /<input(?![^>]*disabled)/, `${page}.html 的 input 只能是 disabled 占位`);
  }
});

test("实证层数据只读 showcase-data", async () => {
  for (const page of [...SHOWCASE_PAGES, ...REDIRECT_PAGES]) {
    const html = await readShowcase(page);
    const fetches = [...html.matchAll(/fetch\((["'])([^"']+)\1/g)].map((m) => m[2]);
    for (const url of fetches) {
      assert.ok(url.startsWith("/showcase-data/"), `${page}.html 的 fetch 只允许 /showcase-data/ 路径：${url}`);
    }
  }
});

test("未运行数据渲染为诚实占位而非估算值", async () => {
  const results = await readShowcase("results");
  assert.match(results, /公告页/, "结果页收敛到公告页(未发布时统一空状态)");
  const context = await readFile(new URL("../public/context/results.html", import.meta.url), "utf8");
  assert.match(context, /尚未发布/, "上下文结果页未发布时显示「尚未发布」空状态");
  assert.match(context, /publications\/index\.json/, "上下文结果页只读正式发布索引");
  assert.doesNotMatch(context, /showcase-data\/index\.json/, "上下文结果页不得读旧批次索引");
  assert.doesNotMatch(context, /showcase-data\/batches\//, "上下文结果页不得加载批次产物");
});


test("指标定义与总表页:纯定义文档,不 fetch 批次数据(P1-2 合并后)", async () => {
  const page = await readFile(new URL("../public/judging/index.html", import.meta.url), "utf8");
  assert.doesNotMatch(page, /fetch\(/, "指标定义页不发起任何数据请求(纯文档)");
  assert.match(page, /指标定义与总表|全部指标/, "页面承载指标定义与总表");
  assert.match(page, /公告页/, "指标数字入口指向公告页");
  assert.doesNotMatch(page, /批次指标总表/, "旧「批次指标总表」命名不得残留");
  // 旧 /judging/metrics 已并入本页,保留跳转兼容
  const legacy = await readFile(new URL("../public/judging/metrics.html", import.meta.url), "utf8");
  assert.match(legacy, /http-equiv="refresh"/, "旧 metrics 地址为跳转页");
});

test("压缩实验页不与长上下文库重复展示压缩前后明细", async () => {
  const page = await readFile(new URL("../public/experiment/compression.html", import.meta.url), "utf8");
  assert.doesNotMatch(page, /压缩前 Token<\/th>/, "实验页不再渲染逐策略压缩前后明细表");
  assert.match(page, /完整压缩前后对照见长上下文库|长上下文库<\/a>/, "实验页链接到文库查看完整对照");
  assert.match(page, /data-select-session/, "Session 原地选中逻辑保留");
});
