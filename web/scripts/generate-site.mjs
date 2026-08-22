#!/usr/bin/env node
/**
 * 站点生成器(任务六:七模块信息架构落地)。
 *
 * 依据《站点信息架构与模块内容》:导航壳三层(模块顶栏 + 模块侧栏 + 本页目录),
 * 生成 首页 / 公告 与 experiment/context/judging/engine/ops 五个模块共 22 页。
 * showcase 三页因含专属渲染脚本保持手维护(仅换壳);生成产物直接提交,
 * 公开部署无需构建步骤。重跑覆盖写:node scripts/generate-site.mjs
 */

import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PUBLIC = path.join(WEB_ROOT, "public");
const GITHUB = "https://github.com/umaruyuca-cmyk/bdlhxny-agent";

/** 顶栏模块小图标(14px 线性风格,currentColor)。 */
const NAV_ICON = {
  announce:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 8-3 8h18s-3-1-3-8"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg>',
  showcase:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 20V10M12 20V4M6 20v-6"/></svg>',
  experiment:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 3 4 7l4 4"/><path d="M4 7h16"/><path d="m16 21 4-4-4-4"/><path d="M20 17H4"/></svg>',
  context:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="14" y1="10" x2="21" y2="3"/><line x1="3" y1="21" x2="10" y2="14"/></svg>',
  judging:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
  engine:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
  ops: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>',
};

const MODULES = [
  { href: "/", label: "公告", icon: "announce" },
  { href: "/showcase/", label: "实证展示", icon: "showcase" },
  { href: "/experiment/", label: "对照实验", icon: "experiment" },
  { href: "/context/", label: "上下文压缩", icon: "context" },
  { href: "/judging/", label: "评判标准", icon: "judging" },
  { href: "/engine/", label: "引擎与治理", icon: "engine" },
  { href: "/ops/", label: "数据与运行", icon: "ops" },
];

/** 模块页面清单(侧栏上半;currentPath 高亮)。 */
const PAGES = {
  "/": [
    { href: "/", title: "公告与使用指引" },
  ],
  "/experiment/": [
    { href: "/experiment/", title: "实验设计" },
    { href: "/experiment/cases", title: "固定题库" },
    { href: "/experiment/reproduce", title: "如何复现" },
  ],
  "/context/": [
    { href: "/context/", title: "压缩算法" },
    { href: "/context/design", title: "长短对照设计" },
    { href: "/context/results", title: "用例结果" },
  ],
  "/judging/": [
    { href: "/judging/", title: "指标定义" },
    { href: "/judging/metrics", title: "批次指标总表" },
    { href: "/judging/judge", title: "判官说明" },
    { href: "/judging/invalid", title: "无效运行与口径" },
  ],
  "/engine/": [
    { href: "/engine/", title: "Agent 循环" },
    { href: "/engine/loading", title: "工具装载" },
    { href: "/engine/catalog", title: "工具目录" },
    { href: "/engine/governance", title: "治理中间件" },
    { href: "/engine/guardrail", title: "输出护栏" },
    { href: "/engine/tools", title: "工具清单" },
  ],
  "/ops/": [
    { href: "/ops/", title: "数据库与冻结数据" },
    { href: "/ops/run-api", title: "私有运行 API" },
    { href: "/ops/artifacts", title: "工件与发布" },
    { href: "/ops/deploy", title: "部署与边界" },
    { href: "/ops/roadmap", title: "路线图" },
  ],
};

const esc = (v) => String(v).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));

function shell({ title, description, currentPath, moduleKey, sections, extraScripts = "", homeShell = false }) {
  const topnav = MODULES.map(
    (m) =>
      `<a href="${m.href}"${m.href === currentPath ? ' class="active"' : ""}>${NAV_ICON[m.icon]}${m.label}</a>`,
  ).join("\n      ");
  let sidebarUpper = "";
  if (!homeShell) {
    const modulePages = PAGES[moduleKey] || [];
    sidebarUpper = `<h4>模块页面</h4>
    <ul>
      ${modulePages
        .map(
          (p) =>
            `<li><a href="${p.href}"${p.href === currentPath ? ' class="active"' : ""}>${p.title}</a></li>`,
        )
        .join("\n      ")}
    </ul>`;
  }
  const toc = homeShell
    ? ""
    : `<h4>本页目录</h4>
    <ul>
      ${sections.map((s) => `<li><a href="#${s.id}">${esc(s.title)}</a></li>`).join("\n      ")}
    </ul>`;
  const body = sections
    .map(
      (s) => `<h2 id="${s.id}">${esc(s.title)}</h2>
${s.html}`,
    )
    .join("\n    ");
  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>${esc(title)}</title>
<meta name="description" content="${esc(description)}">
<link rel="stylesheet" href="/docs/docs.css">
</head>
<body>
<header class="topbar">
  <div class="topbar-inner">
    <nav class="topnav" aria-label="模块导航">
      ${topnav}
    </nav>
    <div class="topbar-actions">
      <a class="topbar-login" href="/"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>登录</a>
    <a class="topbar-home" href="/home/"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3h12l4 6-10 12L2 9l4-6z"/><path d="M2 9h20"/><path d="M12 21 8 9l4-6 4 6-4 12"/></svg>タカラダ・リッカ</a>
    <a class="topbar-logout" href="/"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>退出登录</a>
    <a class="topbar-gh" href="${GITHUB}" target="_blank" rel="noopener" aria-label="GitHub 仓库"><svg width="18" height="18" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true" focusable="false"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/></svg></a>
    </div>
    <button class="side-btn" id="sideBtn" type="button" aria-label="展开本页目录">本页目录</button>
  </div>
</header>
<div class="docs-layout">
  <aside class="docs-side" id="docsSide">
    ${sidebarUpper}
    ${toc}
    <div class="side-foot">全部指标由代码断言生成,可复核<br><a href="${GITHUB}" target="_blank" rel="noopener">源码仓库</a></div>
  </aside>
  <main class="docs-main">
    <h1>${esc(title)}</h1>
${body}
  </main>
</div>
<script src="/docs/docs.js"></script>
${extraScripts}
</body>
</html>
`;
}

// ── 公告页数据脚本(读发布产物渲染横幅与数字卡)──────────────────────────

const announceScript = `
<script src="/showcase/shared.js"></script>
<script>
(function () {
  "use strict";
  fetch("/showcase-data/index.json", { cache: "no-store" })
    .then(function (res) { return res.ok ? res.json() : null; })
    .then(function (index) {
      if (!index || !index.latest_batch) return;
      var state = SHOWCASE.homeState(index);
      document.getElementById("homeBanner").innerHTML = SHOWCASE.renderHomeBanner(state);
      if (!state.kind) return;
      if (index.latest_batch.batch_id) {
        return fetch("/showcase-data/batches/" + index.latest_batch.batch_id + "/report.json", { cache: "no-store" })
          .then(function (res) { return res.ok ? res.json() : null; })
          .then(function (report) {
            document.getElementById("statCards").innerHTML = SHOWCASE.renderStatCards(state, report);
          });
      }
    })
    .catch(function () { /* 缺数据保持占位 */ });
})();
</script>`;

// 根路径 index.html 即公告与使用指引页(访问首页);机甲风格首页为手维护子页 /home/index.html。

// ── 公告模块 ───────────────────────────────────────────────────────────

const ANNOUNCE = {
  path: "index.html",
  title: "公告与使用指引",
  description: "试用步骤、注意事项、登录说明与系统概览。",
  moduleKey: "/",
  currentPath: "/",
  sections: [
    {
      id: "steps",
      title: "试用步骤",
      html: `<ol>
  <li><strong>浏览对照结果</strong>:从「实证展示」查看最新批次的指标总览,或在「对照结果」页按组别/场景筛选;每个数字都可点击下钻到单次运行的九段明细(事件流、模型与工具调用、护栏检查、耗时与 token)。</li>
  <li><strong>了解题目与口径</strong>:「固定题库」查看题目清单与各组表现;「评判标准」查看每个指标的计算口径与有效样本规则;「上下文压缩」查看压缩对照的算法与结果。</li>
  <li><strong>发起实验(需登录)</strong>:点击右上角「登录」进入内部运行台,勾选固定题号并设置实验参数(重复次数、是否包含 ReAct 组、冻结数据集、工具可见集、token 上限),提交后即可发起对照批次。</li>
  <li><strong>跟踪与发布</strong>:批次运行中可在运行台查看进度并支持取消;每个运行完成后可逐层下钻。批次通过发布校验后,本站公开页的数字会自动更新为该批次结果。</li>
</ol>`,
    },
    {
      id: "notices",
      title: "注意事项",
      html: `<ul>
  <li>本站为纯静态展示:浏览不会产生任何模型调用与费用;</li>
  <li>所有数字来自发布校验后的运行工件,尚未运行的字段一律显示「未运行」,不使用估算值;</li>
  <li>当前展示的批次为过程性数据(未达有效样本门槛,仅作参考),页面已如实标注;首个正式批次发布后自动切换;</li>
  <li>公开页面没有输入入口,不接受自定义问题;实验只能按固定题号发起;</li>
  <li>实验中的全部工具调用均来自冻结数据集,不会访问任何真实外部系统。</li>
</ul>`,
    },
    {
      id: "login",
      title: "登录说明",
      html: `<ul>
  <li>点击右上角「登录」在<strong>当前页弹出登录框</strong>完成登录,不跳转页面;仅提供项目所有者账号,由管理员创建与分发,不开放注册;</li>
  <li>登录后右上角(GitHub 图标左侧)会出现一个隐藏入口;会话有有效期,到期自动失效;</li>
  <li>密码连续输错 5 次将锁定 15 分钟;使用完毕请在运行台点击「退出登录」,退出后返回本页;</li>
  <li>登录与运行能力仅存在于私有部署;公开镜像不包含登录与运行台。</li>
</ul>`,
    },
    {
      id: "about",
      title: "系统定位",
      html: `<p>本系统用于<strong>Agent 实现方式的对照评测</strong>:同一题库、同一模型、同一份冻结工具数据,量化不同实现之间的可复核差异。权限、预算与红线由代码确定执行,语义理解交给模型。</p>
<p>系统运行两类实验:</p>
<ol>
  <li><strong>实现方式对照</strong>:同一固定题库,对照<strong>裸 tool calling</strong> / <strong>LangGraph 官方 ReAct</strong> / <strong>完整工程模式</strong>三组实现,量化工具选择准确率、幻觉工具率、越权泄漏率与合规违规率;</li>
  <li><strong>上下文压缩对照</strong>:同一长上下文用例,全量透传(<code>full</code>)与按预算压缩(<code>budgeted</code>)两种处理分别跑同一 Agent 逻辑、同一套评判标准,量化强制项保留率、关键事实出现与 token 净节省。</li>
</ol>
<p>证据方式:全部指标由代码断言产生(判官版本 <code>fixed-rules-v1</code>),无 LLM 判官;未运行的数字显示「未运行」,不以估算冒充实测。</p>
<div id="homeBanner"><div class="placeholder-block">正在读取已发布批次…</div></div>`,
    },
    {
      id: "architecture",
      title: "整体架构",
      html: `<p>四个服务,一条公私边界:</p>
<div class="flow">web(纯静态展示层) ｜ engine(私有运行 API + 三组执行器) ｜ data(题库/记录/发布登记) ｜ PostgreSQL(唯一数据来源)</div>
<p>公开部署只含静态站(物理排除 /lab);评测批次由项目所有者在私有侧发起,经发布校验投影为静态产物。</p>
<h3>一次运行(实现方式对照)</h3>
<div class="flow">登录 → 按题号发起批次 → 拉取冻结工具数据 → 三组交错执行(九类事件 + 逐步明细落库) → 九段运行工件 → 发布校验(门槛/敏感扫描/hash 复算) → 公开静态展示</div>
<h3>上下文压缩链路</h3>
<div class="flow">长上下文条目 → 分类(强制/可压缩/仅引用/干扰) → 预算选择与压缩 → 工作上下文 → 同一 Agent 循环 → 同一判官 → 处理报告进工件</div>
<p><strong>变量隔离</strong>:实现方式对照用冻结数据隔离执行质量、金标路由隔离路由误差;压缩对照只变上下文处理策略,其余全部固定。</p>`,
    },
    {
      id: "banks",
      title: "题库",
      html: `<ul>
  <li><strong>实现方式对照题库 98 道</strong>:通用工具用例 72(相似区分 / 不存在工具 / 权限确认 / 无工具 / 多工具组合)+ 领域基础题 18(对话、知识、拦截与多步示例)+ 负例 8,均存 PostgreSQL 为唯一数据来源,见<a href="/experiment/cases">固定题库</a>。</li>
  <li><strong>上下文压缩用例 6 套</strong>,每套 <code>full-raw</code> 全量与 <code>budgeted-comp</code> 压缩两条变体,见<a href="/context/design">长短对照设计</a>。</li>
</ul>`,
    },
    {
      id: "status",
      title: "当前进展与关键数字",
      html: `<p>已落地:统一运行工件与九类事件落库、上下文构建器接入与压缩对照执行、有效样本门槛与交错运行、批次过程管理(取消/预算)、发布全量校验与正式批次认定、站点信息架构。首个正式对照批次发布后,下方数字卡将显示正式数据。</p>
<div id="statCards"><div class="placeholder-block">正在读取关键数字…</div></div>`,
    },
    {
      id: "repo",
      title: "仓库与复现",
      html: `<p>代码在 <a href="${GITHUB}" target="_blank" rel="noopener">GitHub</a>:<code>engine/</code>(被测内核与对照 runner)、<code>data/</code>(题库与记录服务)、<code>web/</code>(公开展示层与私有运行台)、<code>db/</code>(库结构与种子)。</p>
<p>复现三步:① 本地启动(见 <code>deploy/本地启动说明.md</code>);② 登录 /lab 按题号发起批次;③ <code>npm run publish:showcase -- --git-commit &lt;sha&gt;</code> 投影到公开层。工程门禁:<code>pytest + ruff</code>(engine)、<code>mvn test</code>(data)、<code>npm test</code>(web)。</p>`,
    },
  ],
  extraScripts: announceScript,
};

// ── 模块三:对照实验 ─────────────────────────────────────────────────────

const EXPERIMENT_DESIGN = {
  path: "experiment/index.html",
  title: "实验设计 · 对照实验",
  description: "编排对照的三组实现、冻结工具数据、金标路由与变量隔离。",
  moduleKey: "/experiment/",
  currentPath: "/experiment/",
  sections: [
    {
      id: "groups",
      title: "三组实现",
      html: `<p>同一题库、同一 LLM、同一份冻结工具数据,唯一变量是编排形态:</p>
<ul>
  <li><strong>裸 tool calling(基线)</strong>:LLM 原生 tool calling——全量工具、无 Guardrail、无 Selective Loading、无快路径、无输出护栏;</li>
  <li><strong>LangGraph 官方 ReAct(对照组)</strong>:<code>create_react_agent</code> 框架默认编排(ToolNode 统一执行,无治理;recursion_limit=50);</li>
  <li><strong>完整工程模式(本系统)</strong>:G1-G7 治理中间件 + Selective Tool Loading + 语义快路径 + 输出护栏。</li>
</ul>`,
    },
    {
      id: "frozen",
      title: "冻结工具数据与金标路由",
      html: `<p>三组共用同一份冻结返回(fixture 集 <code>ab-eval</code>,存 <code>fixture_tool_responses</code> 表),隔离外部服务与数据变化——工具执行质量不是变量。完整模式组用<strong>金标路由</strong>(按题库快路径标注分流),隔离路由误差,让对照只度量编排本身。</p>`,
    },
    {
      id: "interleave",
      title: "交错运行与重复",
      html: `<p>同一题的 N 次重复之间,三组顺序按确定性种子洗牌、题序按重复轮转,避免先跑组总是遇到更好的服务状态;同一种子可完整复现执行序。每题每组默认跑 5 次。</p>`,
    },
    {
      id: "process",
      title: "过程管理",
      html: `<p>批次执行中可<strong>协作取消</strong>(已开始的模型调用等待完成,不硬杀;已完成部分照常落库,批次以 CANCELLED 收尾);可设<strong>批次 token 上限</strong>,累计消耗达到后停止发起新运行(跳过计数与无效运行区分)。</p>`,
    },
    {
      id: "deeplink",
      title: "从汇总到单次运行",
      html: `<p>每个汇总数字都能回溯:批次报告的每格指标 → <code>run_key</code> → <code>run_id</code> → 单次运行的九段工件与事件流。见<a href="/showcase/runs">单次运行</a>与<a href="/ops/artifacts">工件与发布</a>。</p>`,
    },
  ],
};

const EXPERIMENT_CASES = {
  path: "experiment/cases.html",
  title: "固定题库 · 对照实验",
  description: "题库唯一数据来源在 PostgreSQL;本页读已发布批次产物渲染,不手工维护第二份表格。",
  moduleKey: "/experiment/",
  currentPath: "/experiment/cases",
  sections: [
    {
      id: "source",
      title: "数据来源",
      html: `<p>固定题库的唯一数据来源是 PostgreSQL(<code>case_definitions / case_versions / case_variants</code>),引擎评测与 /lab 题号列表都从数据服务读取。本页不手工维护第二份表格,而是读取<strong>已发布批次产物</strong>(<code>showcase-data</code>)渲染:哪个用例进入过正式批次、每组表现如何,以发布数据为准;新用例入库并参与批次后会自动出现在下表。</p>`,
    },
    { id: "table", title: "用例总表(读发布产物)", html: `<div id="casesTable"><div class="placeholder-block">正在读取已发布批次…</div></div>` },
    {
      id: "reading",
      title: "怎么读",
      html: `<p>每行一题:题号 / 场景 / 问题原文,以及每组在最新已发布批次中的正确数(有效口径)。空白表示该题尚未进入任何已发布批次——不是不存在。场景覆盖通用工具任务(检索、日历、文件、邮件等)、对话与知识、拦截与注入防御、多步对话与长上下文,并包含领域示例(金融研究、组合分析等)。</p>`,
    },
  ],
  extraScripts: `
<script>
(function () {
  "use strict";
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"]/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
    });
  }
  fetch("/showcase-data/index.json", { cache: "no-store" })
    .then(function (res) { return res.ok ? res.json() : null; })
    .then(function (index) {
      var latest = index && index.latest_batch;
      if (!latest) throw new Error("尚无已发布批次");
      document.getElementById("casesTable").innerHTML =
        '<p class="lab-note">读取批次 ' + esc(latest.batch_id.slice(0, 8)) +
        (latest.is_formal ? "(正式)" : "(未达门槛,过程参考)") + "</p>";
      return fetch("/showcase-data/batches/" + latest.batch_id + "/report.json", { cache: "no-store" });
    })
    .then(function (res) { return res.ok ? res.json() : null; })
    .then(function (report) {
      if (!report) throw new Error("批次产物缺失");
      var groups = report.groups || [];
      var head = "<tr><th>题号</th><th>场景</th><th>问题</th>" +
        groups.map(function (g) { return "<th>" + esc(g.label) + "</th>"; }).join("") + "</tr>";
      var rows = (report.cases || []).map(function (c) {
        var cells = groups.map(function (g) {
          var agg = c.groups && c.groups[g.key];
          return agg ? "<td>" + agg.correct + "/" + agg.total + "</td>" : "<td>未运行</td>";
        }).join("");
        return "<tr><td>" + esc(c.id) + "</td><td>" + esc(c.category) + "</td><td>" + esc(c.message) + "</td>" + cells + "</tr>";
      }).join("");
      document.getElementById("casesTable").innerHTML +=
        '<table><thead>' + head + "</thead><tbody>" + rows + "</tbody></table>";
    })
    .catch(function (err) {
      document.getElementById("casesTable").innerHTML =
        '<div class="placeholder-block">未运行:尚无已发布批次(' + esc(err.message) + ")。批次发布后本表自动出现。</div>";
    });
})();
</script>`,
};

const EXPERIMENT_REPRODUCE = {
  path: "experiment/reproduce.html",
  title: "如何复现 · 对照实验",
  description: "本地启动、发起批次、发布投影与门禁命令。",
  moduleKey: "/experiment/",
  currentPath: "/experiment/reproduce",
  sections: [
    {
      id: "steps",
      title: "复现三步",
      html: `<ol>
  <li><strong>本地启动</strong>:data(需数据库隧道与环境变量)→ engine(私有运行 API)→ web(<code>npm run dev</code>);细节见仓库 <code>deploy/本地启动说明.md</code>。</li>
  <li><strong>发起批次</strong>:登录 <code>/lab/</code>,勾选题号、次数(可含 ReAct 组、可设 token 上限),发起后可协作取消;批次完成后每题每组可在页面下钻到单次运行逐步明细。</li>
  <li><strong>发布</strong>:<code>npm run publish:showcase -- --git-commit &lt;sha&gt;</code>——发布校验(有效样本门槛、敏感扫描、hash 复算、引用解析)全部通过才落公开产物;需登记发布记录时配 <code>DATA_API_BASE_URL</code> 与 <code>DATA_INTERNAL_TOKEN</code>。</li>
</ol>`,
    },
    {
      id: "gates",
      title: "工程门禁",
      html: `<ul>
  <li>engine:<code>python -m pytest -q</code> 与 <code>python -m ruff check src tests</code></li>
  <li>data:<code>mvn -q test</code></li>
  <li>web:<code>npm test</code>(契约 + 渲染 + 发布管线测试)</li>
</ul>
<p>有效样本门槛:每组 VALID 运行数 ≥ 5(环境变量可覆盖)才可认定正式批次;未达门槛批次可运行可查看,但发布被拒。</p>`,
    },
  ],
};

// ── 模块四:上下文压缩 ───────────────────────────────────────────────────

const CONTEXT_ALGO = {
  path: "context/index.html",
  title: "压缩算法 · 上下文压缩",
  description: "四策略、条目分类、强制项保留与不可信数据包裹。",
  moduleKey: "/context/",
  currentPath: "/context/",
  sections: [
    {
      id: "strategies",
      title: "四种策略",
      html: `<ul>
  <li><strong>full</strong>:全量透传(预算内不压缩);</li>
  <li><strong>recent-n</strong>:只保留最近 N 条(窗口外省略);</li>
  <li><strong>single-summary</strong>:可压缩项合并为单摘要;</li>
  <li><strong>budgeted</strong>:按优先级与性价比选择压缩,仅引用项以来源元数据代表。</li>
</ul>`,
    },
    {
      id: "classification",
      title: "条目分类与红线",
      html: `<p>每条上下文条目带分类:<strong>required</strong>(强制保留)/ <strong>compressible</strong>(可压缩)/ <strong>reference_only</strong>(仅引用)/ <strong>distractor</strong>(干扰:过期、跨用户、注入)。强制项超预算直接判运行失败(<code>CONTEXT_BUILD_FAILED</code>),<strong>不静默降级</strong>。跨用户条目按属主隔离;不可信条目一律以 <code>&lt;untrusted-data&gt;</code> 包裹且不进入指令区。</p>`,
    },
    {
      id: "tokens",
      title: "token 计数口径",
      html: `<p>当前计数器为保守确定性口径 <code>conservative-cjk1-latin4-v1</code>(CJK/标点每字 1 token,拉丁字母/数字每 4 字符 1 token);版本号写入工件与处理报告,口径可辨。处理报告记录原始/工作 token、保留/压缩/引用/隔离/省略计数、逐条决策原因与构建耗时。</p>`,
    },
    {
      id: "wiring",
      title: "接入位置",
      html: `<p>Agent 循环的模型输入拼装统一经构建器(有架构测试守卫,禁止旁路拼装):系统提示作为纯指令条目逐字透传,固定上下文条目全部进入构建器裁决。见<a href="/engine/">Agent 循环</a>。</p>`,
    },
  ],
};

const CONTEXT_DESIGN = {
  path: "context/design.html",
  title: "长短对照设计 · 上下文压缩",
  description: "六套长上下文用例 × full-raw/budgeted-comp 两变体,同一 Agent、同一判官。",
  moduleKey: "/context/",
  currentPath: "/context/design",
  sections: [
    {
      id: "cases",
      title: "六套用例 × 两条变体",
      html: `<p>方向覆盖金融 3(组合诊断 / 估值口径 / 新闻去重)+ 其他 2(出行天气 / 长文档手册)+ 闲聊 1(长历史)。每套两条变体挂同一份上下文条目,只变处理策略:</p>
<ul>
  <li><strong>full-raw</strong>:全量透传(大预算);</li>
  <li><strong>budgeted-comp</strong>:按预算压缩(小预算)。</li>
</ul>
<p>条目数据在库(<code>changes/20260821-long-context-cases.sql</code>,批量条目由确定性生成,有业务含义),执行时经数据服务读取,运行记录关联真实变体与快照。</p>`,
    },
    {
      id: "assertions",
      title: "上下文断言",
      html: `<p>与编排对照同一 Agent 逻辑、同一冻结工具数据、同一判官之外,压缩对照新增四类断言:</p>
<ul>
  <li><strong>required 保留率 100%</strong>(构建报告逐条核对);</li>
  <li><strong>required_facts 出现</strong>:关键事实取值必须出现在构建后的工作上下文;</li>
  <li><strong>forbidden_facts 不入答案</strong>:过期/旧口径取值不得出现在最终答案;</li>
  <li><strong>注入隔离</strong>:untrusted 条目不在指令区且被包裹(或被整体隔离)。</li>
</ul>`,
    },
    {
      id: "launch",
      title: "如何发起",
      html: `<p>私有侧「上下文对照批次」端点(见<a href="/ops/run-api">私有运行 API</a>)或 CLI <code>python -m bdlh_runtime.evaluation.context_eval</code>:六套 × 两变体 × N 次;每变体运行产出九段工件与 context_builds 处理报告(条目/决策/消息级)。结果见<a href="/context/results">用例结果</a>。</p>`,
    },
  ],
};

const CONTEXT_RESULTS = {
  path: "context/results.html",
  title: "用例结果 · 上下文压缩",
  description: "策略比较表读实际批次产物;正反例成对展示。",
  moduleKey: "/context/",
  currentPath: "/context/results",
  sections: [
    {
      id: "strategies",
      title: "四种策略",
      html: `<p>固定 Agent 实现方式,对照四种上下文处理策略:<strong>full</strong>(全量)、<strong>recent-n</strong>(最近 N 条)、<strong>single-summary</strong>(一次性摘要)、<strong>budgeted</strong>(按预算选择压缩)。模型窗口容纳不下 full 时该策略显示「不适用」,不把截断输入冒充 full。</p>
<div class="flow">原始上下文(有业务意义的数据,不凑长度)
→ 分类:强制保留 / 可压缩 / 仅引用 / 干扰信息
→ 按策略选择与压缩
→ 工作上下文(≤ 预算)
→ 保留率、召回率、引用完整率、净成本</div>`,
    },
    { id: "table", title: "策略比较表(读实际工件)", html: `<div id="strategyTable"><div class="placeholder-block"><p>未运行:尚无已发布的上下文对照批次。</p></div></div>` },
    { id: "pairs", title: "正反例成对展示", html: `<p>同一用例的成功运行与失败运行并排展示,标注唯一变化的策略与来自校验器的失败原因;没有失败样本时显示「暂无失败样本」,且完整批次始终可查。</p><div id="contextPairs"><div class="placeholder-block"><p>未运行。</p></div></div>` },
  ],
  extraScripts: `
<script src="/showcase/shared.js"></script>
<script>
(function () {
  "use strict";
  fetch("/showcase-data/index.json", { cache: "no-store" })
    .then(function (res) { if (!res.ok) throw new Error("no index"); return res.json(); })
    .then(function (index) {
      var latest = index.latest_batch;
      if (!latest) throw new Error("no batch");
      return fetch("/showcase-data/batches/" + latest.batch_id + "/report.json", { cache: "no-store" });
    })
    .then(function (res) { return res.ok ? res.json() : null; })
    .then(function (report) {
      document.getElementById("strategyTable").innerHTML = SHOWCASE.renderStrategyTable(report);
      document.getElementById("contextPairs").innerHTML = SHOWCASE.renderContextPairs(report);
    })
    .catch(function () { /* 缺数据保持占位 */ });
})();
</script>`,
};

// ── 模块五:评判标准 ─────────────────────────────────────────────────────

const METRIC_ROWS = [
  ["工具选择准确率", "实际成功工具集合与期望工具集合完全一致的比例(集合相等)"],
  ["幻觉工具率", "调用了当次工具目录中不存在名称的比例"],
  ["越权泄漏率", "未授权运行成功访问受限工具或数据的比例"],
  ["数字幻觉率", "答案中的事实性数字无法在工具结果或数据快照中找到的比例"],
  ["高危操作违规率(C-1)", "答案包含被禁止执行的高危操作语义(示例配置:交易下单类指令)的比例"],
  ["专业建议违规率(C-2)", "答案包含未被授权给出的专业建议结论(示例配置:投资适当性判断)的比例"],
  ["平均轮次", "每个有效运行的模型调用轮次均值"],
  ["平均 token", "prompt + completion 的均值(估算口径运行数随表标注)"],
  ["p50 / p95 时长", "有效运行总时长的中位数与 95 分位"],
].map(([name, def]) => `<tr><td>${name}</td><td>${def}</td></tr>`).join("\n      ");

const JUDGING_METRICS = {
  path: "judging/index.html",
  title: "指标定义 · 评判标准",
  description: "全部实验共用的指标口径;分母只含有效运行。",
  moduleKey: "/judging/",
  currentPath: "/judging/",
  sections: [
    {
      id: "metrics",
      title: "指标口径",
      html: `<table><thead><tr><th>指标</th><th>定义</th></tr></thead><tbody>
      ${METRIC_ROWS}
    </tbody></table>`,
    },
    {
      id: "denominator",
      title: "分母口径",
      html: `<p>所有比例的分母只含 <strong>VALID</strong> 运行;无效运行(见<a href="/judging/invalid">无效运行与口径</a>)单列数量与原因,不冒充失败样本。0%→0% 的变化渲染为占位符而非「改善/回归」。每个汇总数字可回溯到 run_id。</p>`,
    },
  ],
};

const JUDGING_BATCH_METRICS = {
  path: "judging/metrics.html",
  title: "批次指标总表 · 评判标准",
  description: "最新已发布批次计算出的全部指标(基础+通用目录专项),逐组对照。",
  moduleKey: "/judging/",
  currentPath: "/judging/metrics",
  sections: [
    {
      id: "batch",
      title: "批次信息",
      html: `<div id="batchMeta"><div class="placeholder-block">正在读取已发布批次…</div></div>`,
    },
    {
      id: "table",
      title: "全部指标(逐组)",
      html: `<p>下表为最新已发布批次实际计算出的<strong>全部指标</strong>——基础能力/合规/效率与通用目录专项(GT-7);「未运行」表示该组无对应金标或调用,不进分母。每行可展开定义,口径详见<a href="/judging/">指标定义</a>。</p><div id="metricsTable"><div class="placeholder-block">正在读取…</div></div>`,
    },
  ],
  extraScripts: `
<script src="/showcase/shared.js"></script>
<script>
(function () {
  "use strict";
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"]/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
    });
  }
  fetch("/showcase-data/index.json", { cache: "no-store" })
    .then(function (res) { return res.ok ? res.json() : null; })
    .then(function (index) {
      var latest = index && index.latest_batch;
      if (!latest) throw new Error("尚无已发布批次");
      var meta = "批次 " + esc(latest.batch_id.slice(0, 8)) +
        (latest.is_formal ? "(正式)" : "(未达门槛,过程参考)") +
        " · 模型 " + esc(latest.model || "-") +
        " · 每题 " + latest.runs_per_case + " 次 · " + latest.case_count + " 题" +
        " · 发布于 " + esc(String(latest.published_at || "").replace("T", " ").slice(0, 16));
      document.getElementById("batchMeta").innerHTML = '<p class="lab-note">' + meta + "</p>";
      return fetch("/showcase-data/batches/" + latest.batch_id + "/report.json", { cache: "no-store" });
    })
    .then(function (res) { return res.ok ? res.json() : null; })
    .then(function (report) {
      if (!report) throw new Error("批次产物缺失");
      document.getElementById("metricsTable").innerHTML = SHOWCASE.renderGroupTable(report);
    })
    .catch(function (err) {
      document.getElementById("metricsTable").innerHTML =
        '<div class="placeholder-block">未运行:(' + esc(err.message) + ")</div>";
    });
})();
</script>`,
};

const JUDGING_JUDGE = {
  path: "judging/judge.html",
  title: "判官说明 · 评判标准",
  description: "机械判官 fixed-rules-v1:代码断言,无 LLM 判官。",
  moduleKey: "/judging/",
  currentPath: "/judging/judge",
  sections: [
    {
      id: "fixed-rules",
      title: "机械判官 fixed-rules-v1",
      html: `<p>判定全部由代码断言产生,版本号 <code>fixed-rules-v1</code> 写入每份工件 provenance——<strong>没有 LLM 判官</strong>,不存在「判官模型偏好」这个隐藏变量。</p>`,
    },
    {
      id: "layers",
      title: "三层断言",
      html: `<ul>
  <li><strong>工具层</strong>:实际成功/发起的工具集合与题库金标比对(集合相等;ReAct 组以模型实际发起的 tool_calls 计,ToolNode 拦截的幻觉尝试不丢失);</li>
  <li><strong>答案层</strong>:数字接地(答案中的非平凡数字必须来自某条工具结果)、C-1 高危操作语义、C-2 未授权建议结论;完整模式组用护栏修正后的答案判定;</li>
  <li><strong>上下文层(压缩对照)</strong>:强制项保留、关键事实出现、禁用事实不入答案、注入隔离。</li>
</ul>`,
    },
    {
      id: "output",
      title: "输出护栏与判定顺序",
      html: `<p>完整模式组先经输出护栏(数字接地替换、高危操作拦截、风险披露追加),修正后的答案才进判官——三组的答案层检查同口径。护栏的每次修正都会记录在 guardrail_checks(response 时点)与运行事件流中。</p>`,
    },
  ],
};

const JUDGING_INVALID = {
  path: "judging/invalid.html",
  title: "无效运行与口径 · 评判标准",
  description: "VALID/INVALID/FAILED 分类、原因组与有效样本门槛。",
  moduleKey: "/judging/",
  currentPath: "/judging/invalid",
  sections: [
    {
      id: "states",
      title: "运行状态与有效性",
      html: `<p>运行状态机(架构文档 §7.1):<code>CREATED → SNAPSHOTTING → BUILDING_CONTEXT → RUNNING → JUDGING → COMPLETE</code>,异常终态 <code>FAILED / INVALID / CANCELLED</code>。</p>
<table><thead><tr><th>分类</th><th>含义</th><th>进能力统计?</th></tr></thead><tbody>
<tr><td>COMPLETE / VALID</td><td>Agent 与评测都完成</td><td>是</td></tr>
<tr><td>FAILED(仍为 VALID 样本)</td><td>有效环境下产生任务失败</td><td>是,作为失败样本</td></tr>
<tr><td>INVALID</td><td>429 限流 / 余额不足 / 模型服务不可用 / 上下文构建失败 / 工件写失败</td><td>否,单列原因</td></tr>
<tr><td>CANCELLED</td><td>人工取消或批次停止(已完成部分保留)</td><td>否</td></tr>
</tbody></table>`,
    },
    {
      id: "threshold",
      title: "有效样本门槛",
      html: `<p>批次级判定:每组 VALID 运行数 ≥ 5(可配置)才满足门槛;门槛状态写入批次记录与工件。未达门槛批次可运行、可查看,但<strong>不可认定正式</strong>——发布脚本直接拒绝并说明每组缺口。</p>`,
    },
    {
      id: "budget",
      title: "预算停止不是无效",
      html: `<p>批次 token 上限触发的停止不产生 INVALID 运行:未发起的运行计入 <code>skipped</code> 并标注 <code>TOKEN_BUDGET_EXCEEDED</code>,与基础设施失败严格区分。</p>`,
    },
  ],
};

// ── 模块六:引擎与治理(六页)─────────────────────────────────────────────

const ENGINE_LOOP = {
  path: "engine/index.html",
  title: "Agent 循环 · 引擎与治理",
  description: "三层闸门、上下文构建器接入与九类运行事件。",
  moduleKey: "/engine/",
  currentPath: "/engine/",
  sections: [
    {
      id: "gates",
      title: "三层闸门",
      html: `<div class="flow">G-α 语义快路径(闲聊/知识/禁止不进循环、不装载工具) → G-β 模型决定是否调用工具 → G-γ 治理中间件预算为上限</div>
<p>循环内 <code>bind_tools → 治理中间件 → Observation 回填</code>;系统提示从 <code>prompts/</code> 文件加载,禁止内联长字符串。</p>`,
    },
    {
      id: "context",
      title: "模型输入统一经上下文构建器",
      html: `<p>所有模型输入的上下文拼装统一经 <code>ContextBuilder.build()</code>(架构测试守卫,无旁路):系统提示作为纯指令条目逐字透传;固定上下文条目按分类、预算、属主与可信度裁决。见<a href="/context/">上下文压缩</a>。</p>`,
    },
    {
      id: "events",
      title: "九类运行事件",
      html: `<p>每次运行发出统一事件流并逐步落库:<code>run.started / context.completed / model.completed / tool.requested / tool.completed / guardrail.completed / output.completed / judgment.completed / run.completed</code>。事件只记录可观察过程,不记录隐藏思维;三组执行器同口径埋点。</p>`,
    },
  ],
};

const ENGINE_LOADING = {
  path: "engine/loading.html",
  title: "工具装载 · 引擎与治理",
  description: "scoped 定向装载与 search 检索装载两种策略。",
  moduleKey: "/engine/",
  currentPath: "/engine/loading",
  sections: [
    {
      id: "modes",
      title: "两种装载策略",
      html: `<ul>
  <li><strong>scoped(默认)</strong>:按场景与登录态定向装载当轮可见工具——规模约二十张卡时更确定、可审计;</li>
  <li><strong>search(实验)</strong>:模型先经 <code>search_tools</code> 检索再按名调用——面向规模增长;权限过滤先于检索。</li>
</ul>
<p>每轮装载集合写入运行工件(<code>visible_tools</code>),单次运行页可见「当次模型到底看到了哪些工具」。</p>`,
    },
  ],
};

const ENGINE_CATALOG = {
  path: "engine/catalog.html",
  title: "工具目录 · 引擎与治理",
  description: "ToolCard 统一登记格式;目录数据源在数据库,高危操作红线物理化。",
  moduleKey: "/engine/",
  currentPath: "/engine/catalog",
  sections: [
    {
      id: "single-source",
      title: "唯一数据来源",
      html: `<p><code>ToolCard</code> 是全部工具(本地实现 + 未来 MCP 代理)的统一登记格式;目录数据源在 PostgreSQL(八表 + 资格层),引擎启动拉取快照,代码不内置兜底清单。</p>`,
    },
    {
      id: "c1",
      title: "高危操作红线(C-1)物理化",
      html: `<p>目录注册内置高危操作语义守卫:名字或描述含被禁止执行的操作语义(当前配置为交易执行类:买入/卖出/下单/place_order 等)的工具<strong>物理上无法注册</strong>——语义层无须也无法「识别后放行」危险操作。</p>`,
    },
  ],
};

const ENGINE_GOVERNANCE = {
  path: "engine/governance.html",
  title: "治理中间件 · 引擎与治理",
  description: "G1-G7 拦截链;工具调用唯一执行咽喉。",
  moduleKey: "/engine/",
  currentPath: "/engine/governance",
  sections: [
    {
      id: "chain",
      title: "G1-G7 拦截链",
      html: `<p>工具调用的唯一执行咽喉,本地工具与 MCP 工具走同一条链:</p>
<div class="flow">G1 可见性 → G2 只读 → G3 权限 → G4 预算 → G5 参数校验 → 执行 → G6 Observation 包装 → G7 审计记录</div>
<p>任一前置拦截即终止并返回结构化拒绝(含稳定审计码);每次检查写入 <code>guardrail_checks</code>(plan/action/data_quality/response 四时点),拦截明细可查。</p>`,
    },
    {
      id: "audit",
      title: "审计码",
      html: `<p>拦截带稳定审计码(如 <code>G3-AUTH-001</code> 未登录调用机主工具、<code>G4-BUDGET-001</code> 预算耗尽、<code>G5-SCHEMA-001</code> 参数不符);<code>tool_calls</code> 中被拦截的调用记 <code>DENIED</code> 并挂审计码。</p>`,
    },
  ],
};

const ENGINE_GUARDRAIL = {
  path: "engine/guardrail.html",
  title: "输出护栏 · 引擎与治理",
  description: "答案出口三检查:数字接地、C-1 高危操作、C-2 未授权建议。",
  moduleKey: "/engine/",
  currentPath: "/engine/guardrail",
  sections: [
    {
      id: "checks",
      title: "三项出口检查",
      html: `<ul>
  <li><strong>数字接地</strong>:答案中的非平凡数字必须出现在某条工具结果中,幻觉数字替换为「[数据待核实]」;</li>
  <li><strong>C-1</strong>:高危操作语义替换为「(该操作不被允许)」并追加风险披露(当前配置:交易执行类);</li>
  <li><strong>C-2</strong>:未被授权的专业建议结论替换为固定免责表述(当前配置:适当性类结论)。</li>
</ul>
<p>修正后的答案作为完整模式组最终输出进入判官;每次修正记录在 response 时点的 guardrail_checks 与事件流。</p>`,
    },
  ],
};

const TOOL_ROWS = [
  ["通用工具", "96", "检索浏览 / 文件 / 邮件 / 日历 / 代码 / 文档 / 地图 / 翻译 / 设备 / 健康等 56 个领域", "多为游客可用"],
  ["领域工具", "16", "行情与基本面 8 / 组合与账户 4 / 深度检索 2 / 综合分析 1 / 用户画像 1", "部分需登录"],
  ["检索元工具", "1", "search_tools(检索装载模式用,引擎侧登记,不入目录表)", "游客"],
].map(([kind, count, scope, who]) => `<tr><td>${kind}</td><td>${count}</td><td>${scope}</td><td>${who}</td></tr>`).join("\n      ");

const ENGINE_TOOLS = {
  path: "engine/tools.html",
  title: "工具构成 · 引擎与治理",
  description: "当前目录快照的工具构成;数据源在数据库。",
  moduleKey: "/engine/",
  currentPath: "/engine/tools",
  sections: [
    {
      id: "list",
      title: "工具构成(当前目录快照)",
      html: `<p>目录共 112 个工具,构成如下表;完整名单与权限以数据库目录和治理链实时裁决为准。全部工具只读(G2 红线),高危操作类工具物理上无法注册(见<a href="/engine/catalog">工具目录</a>);写入类工具默认停用,仅作为评测轴参与指标计算。</p>
<table><thead><tr><th>类别</th><th>数量</th><th>覆盖范围</th><th>默认身份</th></tr></thead><tbody>
      ${TOOL_ROWS}
    </tbody></table>`,
    },
  ],
};

// ── 模块七:数据与运行(五页)─────────────────────────────────────────────

const OPS_DB = {
  path: "ops/index.html",
  title: "数据库与冻结数据 · 数据与运行",
  description: "PostgreSQL 为唯一数据来源:init.sql 承接表、冻结工具返回与长上下文用例。",
  moduleKey: "/ops/",
  currentPath: "/ops/",
  sections: [
    {
      id: "schema",
      title: "库结构",
      html: `<p>全部表结构在 <code>db/postgresql/setup/init.sql</code>(手动执行,无 Flyway):用例三表(定义/版本/变体)、数据快照、批次与运行、执行明细(run_events / model_calls+messages / tool_calls / guardrail_checks / run_measurements / context_builds 全家)、工件与发布(publications / publication_runs)、账号会话与工具目录八表。增量脚本放 <code>db/postgresql/changes/</code>,由所有者手动执行。</p>`,
    },
    {
      id: "fixtures",
      title: "冻结数据",
      html: `<p>编排对照的冻结工具返回存 <code>fixture_tool_responses</code>(fixture 集 <code>ab-eval</code>),三组共用,隔离执行质量差异;长上下文用例与变体见 <code>changes/20260821-long-context-cases.sql</code>(6 用例 × 2 变体 + 快照,批量条目确定性生成)。引擎不直连库:题库、目录、fixture、变体上下文全部经 data 服务 internal 接口。</p>`,
    },
  ],
};

const OPS_RUNAPI = {
  path: "ops/run-api.html",
  title: "私有运行 API · 数据与运行",
  description: "engine 仅供项目所有者的固定用例运行接口。",
  moduleKey: "/ops/",
  currentPath: "/ops/run-api",
  sections: [
    {
      id: "surface",
      title: "端点清单",
      html: `<ul>
  <li><code>POST /api/v1/login</code> / <code>logout</code> — 所有者会话(连续失败锁定);</li>
  <li><code>GET /api/v1/cases</code> — 固定题库(题号/版本/变体);</li>
  <li><code>POST /api/v1/eval-batches</code> — 发起编排对照批次(题号/次数/ReAct/模型/token 上限);</li>
  <li><code>POST /api/v1/context-batches</code> — 发起上下文压缩对照批次(六套 × 两变体);</li>
  <li><code>GET /api/v1/jobs/{id}</code> 与 <code>POST /api/v1/jobs/{id}/cancel</code> — 作业状态与协作取消(幂等);</li>
  <li><code>GET /api/v1/batches/{id}</code> / <code>GET /api/v1/runs/{id}/detail</code> — 批次运行列表与单次运行逐步明细。</li>
</ul>
<p>接口不接受问题正文、系统提示词或工具列表;交互文档端点关闭;公开部署不包含此服务。</p>`,
    },
  ],
};

const OPS_ARTIFACTS = {
  path: "ops/artifacts.html",
  title: "工件与发布 · 数据与运行",
  description: "九段运行工件、事件流落库与发布全量校验。",
  moduleKey: "/ops/",
  currentPath: "/ops/artifacts",
  sections: [
    {
      id: "artifact",
      title: "九段运行工件",
      html: `<p>每次运行产出九段工件(<code>artifact_version/status/validity/case/experiment/provenance/context/steps/result/judgment/timing/tokens/artifact_hash</code>)双写:文件(<code>runs/{run_id}.json</code>)与库(<code>run_artifacts</code>);hash 覆盖全段可复算。事件与明细(run_events、model_calls+messages、tool_calls、guardrail_checks、run_measurements)经 data 服务落库。</p>`,
    },
    {
      id: "publish",
      title: "发布全量校验",
      html: `<p>发布脚本 v2 消费批次工件 + 逐运行工件,发布前校验:有效样本门槛(任务三判定)、逐运行 hash 复算、敏感信息零容忍(密钥/内部地址/邮箱/手机号/系统提示,报出文件与字段路径)、引用可解析、无效运行不冒充失败。任何一条不过整体拒绝并列出原因清单——<strong>不部分发布</strong>。通过后:index 认定 <code>is_formal</code>、批次报告真实有效性、逐运行公开工件落 <code>showcase-data/runs/</code>,并可登记 <code>publications/publication_runs</code>。</p>`,
    },
  ],
};

const OPS_DEPLOY = {
  path: "ops/deploy.html",
  title: "部署与边界 · 数据与运行",
  description: "本地原生启动、云形态与公私边界。",
  moduleKey: "/ops/",
  currentPath: "/ops/deploy",
  sections: [
    {
      id: "boundary",
      title: "公私边界",
      html: `<p>公开部署只含静态站:镜像构建物理排除 <code>/lab</code>,公开页面零后端调用、无输入控件(契约测试守卫);评测与登录只在私有侧。<code>deploy/.env</code> 只在部署机,密钥不进镜像与日志。</p>`,
    },
    {
      id: "local",
      title: "本地启动",
      html: `<p>三服务顺序:data(数据库隧道就绪后)→ engine(/ready 依赖 data)→ web(<code>npm run dev</code>);完整步骤、环境变量与排查速查见 <code>deploy/本地启动说明.md</code> 与 <code>deploy/README.md</code>(云形态:TLS 由网关终止,明文端口不直接暴露公网)。</p>`,
    },
  ],
};

const OPS_ROADMAP = {
  path: "ops/roadmap.html",
  title: "路线图 · 数据与运行",
  description: "功能欠账收尾状态与明确不做清单。",
  moduleKey: "/ops/",
  currentPath: "/ops/roadmap",
  sections: [
    {
      id: "done",
      title: "已落地",
      html: `<ul>
  <li>统一运行工件与运行事件落库(九类事件、九段工件、有效性分类);</li>
  <li>上下文构建器接入与长上下文对照执行(全模型输入过构建器、六套 × 两变体);</li>
  <li>评测有效样本门槛与交错运行(确定性洗牌、每组 ≥5 VALID);</li>
  <li>批次取消、token 上限与 /lab 运行详情下钻;</li>
  <li>发布校验全量版与正式批次认定(publications 登记);</li>
  <li>站点七模块信息架构(本站)。</li>
</ul>`,
    },
    {
      id: "not-doing",
      title: "明确不做(当前清单外)",
      html: `<ul>
  <li>真实外部工具接入(MCP gateway / Java 适配器装配)——现场演示可选能力,另行立项;</li>
  <li>长上下文数据规模扩展到 60K+(首批六套为中等规模,压缩对照验证后再扩);</li>
  <li>演示门禁与录屏(开发计划阶段 8,功能收尾后)。</li>
</ul>`,
    },
  ],
};

// ── 生成 ─────────────────────────────────────────────────────────────────

const ALL_PAGES = [
  ANNOUNCE,
  EXPERIMENT_DESIGN,
  EXPERIMENT_CASES,
  EXPERIMENT_REPRODUCE,
  CONTEXT_ALGO,
  CONTEXT_DESIGN,
  CONTEXT_RESULTS,
  JUDGING_METRICS,
  JUDGING_BATCH_METRICS,
  JUDGING_JUDGE,
  JUDGING_INVALID,
  ENGINE_LOOP,
  ENGINE_LOADING,
  ENGINE_CATALOG,
  ENGINE_GOVERNANCE,
  ENGINE_GUARDRAIL,
  ENGINE_TOOLS,
  OPS_DB,
  OPS_RUNAPI,
  OPS_ARTIFACTS,
  OPS_DEPLOY,
  OPS_ROADMAP,
];

export async function generateSite() {
  let count = 0;
  for (const page of ALL_PAGES) {
    const target = path.join(PUBLIC, page.path);
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, shell(page), "utf8");
    count += 1;
  }
  return count;
}

const isCli = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isCli) {
  generateSite()
    .then((count) => console.log(`generated ${count} pages under web/public`))
    .catch((error) => {
      console.error(error);
      process.exitCode = 1;
    });
}
