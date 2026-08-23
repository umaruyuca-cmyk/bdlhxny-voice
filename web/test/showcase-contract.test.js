import { readFile } from "node:fs/promises";
import { test } from "node:test";
import assert from "node:assert/strict";

/**
 * /showcase 实证层契约(七模块版):三页共享壳、与全站模块互链、纯静态零后端。
 */

const SHOWCASE_PAGES = ["index", "results", "tools", "runs"];

async function readShowcase(page) {
  return readFile(new URL(`../public/showcase/${page}.html`, import.meta.url), "utf8");
}

test("实证层三页共享级联导航壳", async () => {
  for (const page of SHOWCASE_PAGES) {
    const html = await readShowcase(page);
    assert.match(html, /docs\.css/, `${page}.html 必须引用 docs.css`);
    assert.match(html, /docs\.js/, `${page}.html 必须引入共享导航脚本`);
    assert.match(html, /class="brand"/, `${page}.html 顶栏必须有品牌行`);
    assert.match(html, /class="side-tree"/, `${page}.html 侧栏必须有级联模块树`);
    for (const href of ["/", "/about/", "/experiment/", "/context/", "/judging/", "/engine/", "/ops/"]) {
      assert.ok(html.includes(`href="${href}"`), `${page}.html 侧栏树缺少模块 ${href}`);
    }
    assert.match(html, /side-group here" open/, `${page}.html 当前模块(实证展示)必须默认展开`);
    assert.doesNotMatch(html, /\/showcase\/context/, `${page}.html 不得再链接已迁移的旧上下文页`);
  }
});

test("实证层零后端依赖、无交互输入", async () => {
  for (const page of SHOWCASE_PAGES) {
    const html = await readShowcase(page);
    assert.doesNotMatch(html, /\/api\/v1\//, `${page}.html 不得出现后端 API 调用`);
    assert.doesNotMatch(html, /<input|<form|<textarea/, `${page}.html 不得出现输入控件`);
  }
});

test("实证层数据只读 showcase-data", async () => {
  for (const page of SHOWCASE_PAGES) {
    const html = await readShowcase(page);
    const fetches = [...html.matchAll(/fetch\((["'])([^"']+)\1/g)].map((m) => m[2]);
    for (const url of fetches) {
      assert.ok(url.startsWith("/showcase-data/"), `${page}.html 的 fetch 只允许 /showcase-data/ 路径：${url}`);
    }
  }
});

test("未运行数据渲染为诚实占位而非估算值", async () => {
  const results = await readShowcase("results");
  assert.match(results, /未运行/, "结果页无数据时必须显示未运行");
  const context = await readFile(new URL("../public/context/results.html", import.meta.url), "utf8");
  assert.match(context, /未运行/, "上下文结果页无数据时必须显示未运行");
});
