import { readFile } from "node:fs/promises";
import { test } from "node:test";
import assert from "node:assert/strict";

/**
 * /lab 私有侧契约：页面存在且可调用运行 API；但公开镜像物理排除 lab/，
 * 公开页面（/showcase、/docs）不得链接 /lab、不得出现后端调用。
 */

const PUBLIC_PAGES = [
  ["", "index"],
  ["about", "index"], ["about", "banks"], ["about", "repo"],
  ["showcase", "index"], ["showcase", "results"], ["showcase", "tools"], ["showcase", "runs"],
  ["experiment", "index"], ["experiment", "cases"], ["experiment", "reproduce"],
  ["context", "index"], ["context", "library"], ["context", "design"], ["context", "results"],
  ["judging", "index"], ["judging", "metrics"], ["judging", "judge"], ["judging", "invalid"],
  ["engine", "index"], ["engine", "loading"], ["engine", "catalog"],
  ["engine", "governance"], ["engine", "guardrail"], ["engine", "tools"],
  ["ops", "index"], ["ops", "run-api"], ["ops", "artifacts"], ["ops", "deploy"], ["ops", "roadmap"],
];

async function readPublicPage(dir, page) {
  const rel = dir ? `../public/${dir}/${page}.html` : `../public/${page}.html`;
  return readFile(new URL(rel, import.meta.url), "utf8");
}

test("/lab 批次页存在，只在此处允许表单与运行 API 调用；登录统一为公开页弹窗", async () => {
  await assert.rejects(
    () => readFile(new URL("../public/lab/login.html", import.meta.url)),
    "独立登录页已删除——登录唯一入口是公开页右上角弹窗",
  );
  const index = await readFile(new URL("../public/lab/index.html", import.meta.url), "utf8");
  assert.match(index, /\/api\/v1\//, "lab 页面需要调用运行 API");
  assert.match(index, /sessionStorage/, "登录令牌只进 sessionStorage");
  // 未登录/会话失效/退出登录都回公告首页(/),那里有弹窗登录
  assert.ok(index.includes('location.href = "/"'), "未登录与退出均应回到公告首页");
  assert.ok(index.includes('href="/"'), "运行台需提供首页入口");
  assert.match(index, /case_ids/, "批次页只提交题号与实验配置");
  // 提交体只允许八个键（与 EvalBatchRequest 对齐，GT-2/GT-4/GT-8 增
  // fixture_set_id/visible_tools/search_top_k），不得夹带问题正文
  const literal = index.match(/payload = \{([^}]*)\}/);
  const literalKeys = literal ? [...literal[1].matchAll(/\b([a-z_]+)\s*:/g)].map((m) => m[1]) : [];
  const assignKeys = [...index.matchAll(/payload\.([a-z_]+)\s*=/g)].map((m) => m[1]);
  assert.deepEqual(
    [...new Set([...literalKeys, ...assignKeys])].sort(),
    ["case_ids", "fixture_set_id", "include_react", "max_total_tokens", "model", "runs", "search_top_k", "visible_tools"],
  );
  assert.doesNotMatch(index, /payload\.?(message|prompt|system_prompt|tools)/, "不得提交问题正文、提示词或自定义工具");
});

test("/lab 工具可见集勾选区（GT-5）：加载目录、快捷操作与空集二次确认接线", async () => {
  const index = await readFile(new URL("../public/lab/index.html", import.meta.url), "utf8");
  assert.match(index, /\/api\/v1\/tools/, "勾选区目录来自工具端点");
  assert.match(index, /id="toolGroups"/, "分组勾选容器存在");
  assert.match(index, /id="toolFieldset"[^>]*disabled/, "目录加载前勾选区 disabled+骨架");
  for (const button of ["toolAll", "toolNone", "toolDefault"]) {
    assert.ok(index.includes(`id="${button}"`), `快捷操作 ${button} 需存在`);
  }
  assert.match(index, /visible_tools = visibleTools/, "显式勾选过才随批次提交 visible_tools");
  assert.match(index, /confirm\(/, "空集（能力缺口实验）提交需二次确认");
  assert.match(index, /未知工具名/, "400 被拒工具名需直接呈现");
  // 勾选区只存在于 /lab：公开 12+ 页不得出现工具勾选控件或工具端点
  for (const [dir, page] of PUBLIC_PAGES) {
    const html = await readPublicPage(dir, page);
    assert.ok(!html.includes("toolGroups"), `${dir || "root"}/${page}.html 不得出现工具勾选区`);
    assert.doesNotMatch(html, /\/api\/v1\/tools/, `${dir || "root"}/${page}.html 不得调用工具目录端点`);
  }
});

test("/lab 模型接入（模型切换）：快速切换/提供商预设/Key 选填/测试连接接线", async () => {
  const index = await readFile(new URL("../public/lab/index.html", import.meta.url), "utf8");
  assert.match(index, /\/api\/v1\/llm-config/, "需调用配置读写端点");
  assert.match(index, /\/api\/v1\/llm-config\/test/, "需接通连通性测试端点");
  assert.match(index, /id="modelQuick"/, "需提供模型快速切换下拉");
  assert.match(index, /id="llmProvider"/, "需提供提供商预设下拉");
  assert.match(index, /id="llmApiKey" type="password"/, "密钥输入必须为 password 型(不回显)");
  assert.match(index, /按当前账号绑定/, "需说明配置与账号绑定");
});

test("/lab 批次过程管理（任务四）：取消、预算与运行详情下钻均已接线", async () => {
  const index = await readFile(new URL("../public/lab/index.html", import.meta.url), "utf8");
  assert.match(index, /\/api\/v1\/jobs\/" \+ jobId \+ "\/cancel/, "取消按钮需调用协作取消端点");
  assert.match(index, /max_total_tokens/, "表单需提供批次 token 上限");
  assert.match(index, /\/api\/v1\/batches\//, "批次完成后可下钻运行列表");
  assert.match(index, /\/api\/v1\/runs\/" \+ runId \+ "\/detail/, "运行列表可下钻单次运行逐步明细");
  for (const table of ["modelCalls", "toolCalls", "guardrailChecks", "events", "measurements"]) {
    assert.ok(index.includes(table), `运行详情需渲染 ${table}`);
  }
});

test("公开页面不链接 /lab(登录唯一入口是弹窗)、不出现后端调用", async () => {
  for (const [dir, page] of PUBLIC_PAGES) {
    const html = await readPublicPage(dir, page);
    assert.ok(!html.includes('href="/lab'), `${dir || "root"}/${page}.html 不得链接运行台(登录走弹窗)`);
    if (`${dir}/${page}` === "ops/run-api") {
      // 私有 API 的文档页:正文列出端点是职责,但不得发起任何真实调用
      assert.doesNotMatch(html, /fetch\(|XMLHttpRequest|axios/, "ops/run-api 文档页不得发起真实后端调用");
    } else {
      assert.doesNotMatch(html, /\/api\/v1\//, `${dir}/${page}.html 不得出现后端 API`);
    }
    assert.doesNotMatch(html, /<input|<form|<textarea/, `${dir}/${page}.html 不得出现输入控件`);
  }
});

test("登录遮罩:公开页登录不跳转;运行台隐藏入口登录后才可见并动态赋址", async () => {
  const docsJs = await readFile(new URL("../public/docs/docs.js", import.meta.url), "utf8");
  assert.match(docsJs, /\/api\/v1\/login/, "遮罩登录需调用登录端点");
  assert.match(docsJs, /preventDefault/, "点击登录不得跳转页面");
  assert.match(docsJs, /lab_token/, "成功后写入会话令牌");
  assert.match(docsJs, /topbar-lab/, "登录后显示运行台入口");
  assert.match(docsJs, /发起对照批次/, "登录入口需写明登录后可执行的操作");
  assert.match(docsJs, /\/api\/v1\/logout/, "顶栏需提供退出登录并调用注销端点");
  assert.match(docsJs, /topbar-logout/, "登录后显示退出登录按钮");
  assert.match(docsJs, /location\.href = "\/lab\/"/, "登录成功后自动进入运行台(发起对照实验)");
  assert.match(docsJs, /labBtn\.href = logged/, "运行台链接由脚本登录态动态赋址(公开 HTML 不硬链接)");
  const css = await readFile(new URL("../public/docs/docs.css", import.meta.url), "utf8");
  assert.match(css, /\.topbar-lab\s*\{[^}]*display:\s*none/, "运行台入口默认不可见");
  // 遮罩表单由共享脚本运行时注入,公开页 HTML 源保持零输入控件
  for (const [dir, page] of PUBLIC_PAGES) {
    const html = await readPublicPage(dir, page);
    assert.doesNotMatch(html, /<input|<textarea/, `${dir || "root"}/${page}.html HTML 源不得出现输入控件`);
  }
});

test("公开镜像构建物理排除 lab/，私有镜像保留", async () => {
  const dockerfilePublic = await readFile(new URL("../Dockerfile.public", import.meta.url), "utf8");
  assert.match(dockerfilePublic, /rm -rf public\/lab/, "公开构建必须删除 lab 目录");
  const dockerfilePrivate = await readFile(new URL("../Dockerfile", import.meta.url), "utf8");
  assert.match(dockerfilePrivate, /COPY public\//, "私有镜像照常复制 public/");
  assert.doesNotMatch(dockerfilePrivate, /rm -rf/, "私有镜像不得排除 lab");

  const publicCompose = await readFile(new URL("../../deploy/docker-compose.public.yml", import.meta.url), "utf8");
  assert.match(publicCompose, /Dockerfile\.public/, "公开 compose 必须使用排除版 Dockerfile");
});

test("登录令牌不出现在公开数据契约的禁止字段清单之外的页面脚本中", async () => {
  // showcase-data 由发布脚本做 FORBIDDEN_KEYS 扫描；这里守页面侧：
  // 公开页面脚本不读 sessionStorage/localStorage（无会话概念）
  for (const [dir, page] of PUBLIC_PAGES) {
    const html = await readPublicPage(dir, page);
    assert.doesNotMatch(html, /sessionStorage|localStorage/, `${dir || "root"}/${page}.html 无会话概念`);
  }
});
