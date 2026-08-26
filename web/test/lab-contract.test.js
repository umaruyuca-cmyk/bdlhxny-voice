import { readFile } from "node:fs/promises";
import { test } from "node:test";
import assert from "node:assert/strict";

/**
 * /lab 私有侧契约：页面存在且可调用运行 API；但公开镜像物理排除 lab/，
 * 公开页面（/showcase、/docs）不得链接 /lab、不得出现后端调用。
 * 例外(前后端对接契约 v1)：实验模块页面(模板中心/发起/批次列表/批次详情/压缩用例/我的测试)
 * 允许 /api/v1/public/* 匿名测试接口与同源所有者通道白名单
 * (login/logout/experiment-templates/template-batches/batches/jobs/runs)。
 */

const PUBLIC_PAGES = [
  ["", "index"],
  ["about", "index"], ["about", "banks"], ["about", "repo"],
  ["showcase", "index"], ["showcase", "results"], ["showcase", "tools"], ["showcase", "runs"],
  ["experiment", "index"], ["experiment", "compression"], ["experiment", "run"],
  ["experiment", "batches"], ["experiment", "batch"],
  ["test", "index"],
  ["context", "index"], ["context", "library"], ["context", "design"], ["context", "results"],
  ["judging", "index"], ["judging", "metrics"], ["judging", "judge"], ["judging", "invalid"],
  ["engine", "index"], ["engine", "loading"], ["engine", "catalog"],
  ["engine", "governance"], ["engine", "guardrail"], ["engine", "tools"],
  ["ops", "index"], ["ops", "run-api"], ["ops", "artifacts"], ["ops", "deploy"], ["ops", "roadmap"],
];

/** 实验模块页:允许匿名公开接口 + 所有者通道白名单(与 nginx/dev-server 反代同口径)。 */
const PUBLIC_API_PAGES = new Set([
  "experiment/index", "experiment/compression", "experiment/run",
  "experiment/batches", "experiment/batch", "test/index",
]);
/** 同源所有者通道白名单(前后端对接契约 §2);之外的维护者端点仍禁止出现在公开页。 */
const EXPERIMENT_API_OK = /\/api\/v1\/(public(\/|$)|(login|logout|experiment-templates|template-batches|batches|jobs|runs)(\/|\?|["'`]|$))/;

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
  assert.match(index, /case_ids/, "压缩对照提交所选用例编号");
  // 提交只允许编号与实验配置键,不得夹带问题正文
  const assignKeys = [...index.matchAll(/(?:body|payload)\.([a-z_]+)\s*=/g)].map((m) => m[1]);
  const literalKeys = [...index.matchAll(/body: JSON\.stringify\(\s*\{([^}]*)\}/g)]
    .flatMap((m) => [...m[1].matchAll(/\b([a-z_]+)\s*:/g)].map((x) => x[1]));
  for (const key of [...new Set([...literalKeys, ...assignKeys])]) {
    assert.ok(
      ["template_id", "repeat_count", "preset_id", "advanced", "case_id", "case_ids", "runs"].includes(key),
      "提交键越界: " + key,
    );
  }
  assert.doesNotMatch(index, /payload\.?(message|prompt|system_prompt)/, "不得提交问题正文或提示词");
});

test("公开页不得出现工具勾选区与工具端点调用", async () => {
  const index = await readFile(new URL("../public/lab/index.html", import.meta.url), "utf8");
  assert.ok(!index.includes("toolGroups"), "/lab 无工具勾选区(工具范围由模板 tool_delivery 决定)");
  for (const [dir, page] of PUBLIC_PAGES) {
    const html = await readPublicPage(dir, page);
    assert.ok(!html.includes("toolGroups"), (dir || "root") + "/" + page + ".html 不得出现工具勾选区");
    assert.doesNotMatch(html, /\/api\/v1\/tools/, (dir || "root") + "/" + page + ".html 不得调用工具目录端点");
  }
});

test("/lab 模型接入:env 唯一真源,页面无账号级配置,仅保留连通性测试", async () => {
  const index = await readFile(new URL("../public/lab/index.html", import.meta.url), "utf8");
  assert.match(index, /\/api\/v1\/llm-config\/test/, "需接通连通性测试端点");
  assert.match(index, /env 是唯一真源/, "需说明配置来自服务端环境");
  assert.match(index, /LLM_BASE_URL/, "需指明配置的环境变量名");
  // 账号级配置模块已删除:不得再有读写端点、密钥输入与提供商预设
  assert.doesNotMatch(index, /["']\/api\/v1\/llm-config["']/, "不得调用配置读写端点(已删除)");
  assert.ok(!index.includes("llmApiKey"), "不得出现密钥输入框");
  assert.ok(!index.includes("llmProvider"), "不得出现提供商预设下拉");
  assert.ok(!index.includes("modelQuick"), "不得出现模型快速切换下拉");
});

test("/lab 批次过程管理（任务四）：取消、预算与运行详情下钻均已接线", async () => {
  const index = await readFile(new URL("../public/lab/index.html", import.meta.url), "utf8");
  assert.match(index, /\/api\/v1\/jobs\/" \+ jobId \+ "\/cancel/, "取消按钮需调用协作取消端点");
  assert.match(index, /\/api\/v1\/batches\//, "批次完成后可下钻运行列表");
  assert.match(index, /\/api\/v1\/runs\/" \+ runId \+ "\/detail/, "运行列表可下钻单次运行逐步明细");
  for (const table of ["modelCalls", "toolCalls", "guardrailChecks", "events", "measurements"]) {
    assert.ok(index.includes(table), `运行详情需渲染 ${table}`);
  }
});

test("/lab 新运行台：正式模板、参数能力、长上下文选择(历史诊断入口已删除)", async () => {
  const index = await readFile(new URL("../public/lab/index.html", import.meta.url), "utf8");
  for (const section of ["overview", "formal", "capabilities", "context-workbench", "evidence"]) {
    assert.ok(index.includes(`id="${section}"`), `新版运行台需要 ${section} 工作区`);
  }
  assert.match(index, /先定义变量，再运行 Agent/, "首页需要明确先预估、后执行的操作逻辑");
  assert.match(index, /正式单变量实验/, "正式模板应成为主操作区");
  assert.match(index, /暂未支持/, "未接入的模型参数不能展示为已生效");
  assert.match(index, /templatePlanSignature/, "模板、用例或参数变化后旧预估必须失效");
  assert.doesNotMatch(index, /id="tplAdvanced"/, "高级设置使用普通表单控件，不要求手写 JSON");
  // 压缩前后正式对照:能看到并选择本次对照的长上下文用例
  assert.match(index, /id="ctxCaseList"/, "压缩对照需提供长上下文用例勾选");
  assert.match(index, /id="ctxCaseSummary"/, "压缩对照需显示已选用例摘要");
  assert.match(index, /selectedCtxCaseIds/, "提交时携带所选用的 case_ids");
  assert.match(index, /请至少勾选一套长上下文用例/, "空选择需拒绝提交");
});

test("公开页面不链接 /lab(登录唯一入口是弹窗)、不出现后端调用(实验模块页允许公开接口与所有者通道白名单)", async () => {
  for (const [dir, page] of PUBLIC_PAGES) {
    const html = await readPublicPage(dir, page);
    assert.ok(!html.includes('href="/lab'), `${dir || "root"}/${page}.html 不得链接运行台(登录走弹窗)`);
    const key = dir ? `${dir}/${page}` : page;
    if (key === "ops/run-api") {
      // 私有 API 的文档页:正文列出端点是职责,但不得发起任何真实调用
      assert.doesNotMatch(html, /fetch\(|XMLHttpRequest|axios/, "ops/run-api 文档页不得发起真实后端调用");
    } else if (PUBLIC_API_PAGES.has(key)) {
      // 实验模块页:允许匿名公开接口 + 所有者通道白名单(登录/模板/plan/批次/作业/运行)
      const offenders = [...html.matchAll(/\/api\/v1\/[a-z\-]+(\/[a-z\-]+)?/g)].map((m) => m[0]);
      for (const api of offenders) {
        assert.ok(EXPERIMENT_API_OK.test(api), `${key} 引用了白名单之外的端点:${api}`);
      }
    } else {
      assert.doesNotMatch(html, /\/api\/v1\//, `${dir || "root"}/${page}.html 不得出现后端 API`);
    }
    if (!PUBLIC_API_PAGES.has(key)) {
      if (key.startsWith("showcase/")) {
        // showcase 空框架页:允许 disabled 占位控件,禁止表单
        assert.doesNotMatch(html, /<form/, `${key} 不得出现表单提交`);
      } else {
        assert.doesNotMatch(html, /<input|<form|<textarea/, `${dir || "root"}/${page}.html 不得出现输入控件`);
      }
    }
  }
});

test("登录遮罩:公开页登录不跳转;登录后留在当前页刷新角色视图", async () => {
  const docsJs = await readFile(new URL("../public/docs/docs.js", import.meta.url), "utf8");
  assert.match(docsJs, /\/api\/v1\/login/, "遮罩登录需调用登录端点");
  assert.match(docsJs, /preventDefault/, "点击登录不得跳转页面");
  assert.match(docsJs, /lab_token/, "成功后写入会话令牌");
  assert.match(docsJs, /topbar-lab/, "登录后显示运行台入口");
  assert.match(docsJs, /发起正式批次|发起对照批次/, "登录入口需写明登录后可执行的操作");
  assert.match(docsJs, /\/api\/v1\/logout/, "顶栏需提供退出登录并调用注销端点");
  assert.match(docsJs, /topbar-logout/, "登录后显示退出登录按钮");
  assert.match(docsJs, /location\.reload\(\)/, "登录成功后留在当前页刷新角色视图(实验模块同页双角色)");
  assert.doesNotMatch(docsJs, /location\.href = "\/lab\/"/, "登录不再硬跳运行台");
  assert.match(docsJs, /labBtn\.href = logged/, "运行台链接由脚本登录态动态赋址(公开 HTML 不硬链接)");
  const css = await readFile(new URL("../public/docs/docs.css", import.meta.url), "utf8");
  assert.match(css, /\.topbar-lab\s*\{[^}]*display:\s*none/, "运行台入口默认不可见");
  // 遮罩表单由共享脚本运行时注入,公开页 HTML 源保持零输入控件
  // (实验模块页的选择/数字输入是实验配置控件;showcase 空框架页的 disabled 占位为纯展示)
  for (const [dir, page] of PUBLIC_PAGES) {
    const key = dir ? `${dir}/${page}` : page;
    if (PUBLIC_API_PAGES.has(key)) continue;
    const html = await readPublicPage(dir, page);
    const isShowcaseFrame = key.startsWith("showcase/");
    if (isShowcaseFrame) {
      assert.doesNotMatch(html, /<input(?![^>]*disabled)/, `${key} 的 input 只能是 disabled 占位`);
    } else {
      assert.doesNotMatch(html, /<input|<textarea/, `${dir || "root"}/${page}.html HTML 源不得出现输入控件`);
    }
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
  // 公开页面 HTML 不直接读写 sessionStorage/localStorage
  // (实验模块的登录态读写收敛在共享脚本 docs.js/experiment.js,令牌不落公开数据契约)
  for (const [dir, page] of PUBLIC_PAGES) {
    const html = await readPublicPage(dir, page);
    assert.doesNotMatch(html, /sessionStorage|localStorage/, `${dir || "root"}/${page}.html 无内联会话读写`);
  }
});
