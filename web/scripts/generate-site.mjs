#!/usr/bin/env node
/**
 * 站点生成器(信息架构 v2)。
 *
 * 变更要点(2026-08-23):
 * - 公告收敛为独立单页(侧栏无子级);试用指引外的系统说明统一进新模块「系统概览」;
 * - 全站去品牌化:顶栏不再出现项目代号,登录后入口改为「运行台」(/lab);
 * - 实例展示只保留「用例详情 / 用例调用明细 / Session 交叉验证」三个实例页面;
 * - 上下文压缩新增「长上下文库」页(条目元信息 + txt 下载 + 登录后压缩测试);
 * - 压缩算法页补齐公式口径(token 计数 / 预算分配 / 压缩函数)。
 *
 * showcase 页面为空框架/跳转页,由本脚本换壳后手维护内容;生成产物直接提交,
 * 公开部署无需构建步骤。重跑覆盖写:node scripts/generate-site.mjs
 */

import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PUBLIC = path.join(WEB_ROOT, "public");
const GITHUB = "https://github.com/umaruyuca-cmyk/bdlhxny-agent";

/** 顶栏/侧栏模块小图标(15px 线性风格,currentColor)。 */
const NAV_ICON = {
  announce:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 8-3 8h18s-3-1-3-8"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg>',
  about:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
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
  tools: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
  mytests:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>',
  cases: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>',
};

const MODULES = [
  { href: "/", label: "公告", icon: "announce" },
  { href: "/about/", label: "系统概览", icon: "about" },
  { href: "/showcase/", label: "实例展示", icon: "showcase" },
  { href: "/experiment/", label: "实验", icon: "experiment" },
  { href: "/test/", label: "我的测试", icon: "mytests" },
  { href: "/context/", label: "上下文压缩", icon: "context" },
  { href: "/judging/", label: "评判标准", icon: "judging" },
  { href: "/tools/", label: "工具目录", icon: "tools" },
  { href: "/cases/", label: "用例库", icon: "cases" },
  { href: "/engine/", label: "引擎与治理", icon: "engine" },
  { href: "/ops/", label: "数据与运行", icon: "ops" },
];

/** 各模块页面清单(侧栏级联树子项;currentPath 高亮)。公告为单页模块,不设子级。 */
const PAGES = {
  "/": [],
  "/test/": [],
  "/about/": [
    { href: "/about/", title: "系统定位与架构" },
    { href: "/about/banks", title: "题库与数据" },
    { href: "/about/repo", title: "仓库与复现" },
  ],
  "/showcase/": [
    { href: "/showcase/", title: "用例详情" },
    { href: "/showcase/tools", title: "用例调用明细" },
  ],
  "/experiment/": [
    { href: "/experiment/", title: "模板中心" },
    { href: "/experiment/batches", title: "批次列表" },
    { href: "/experiment/compression", title: "压缩用例" },
  ],
  "/context/": [
    { href: "/context/", title: "压缩算法" },
    { href: "/context/library", title: "长上下文库" },
    { href: "/context/design", title: "长短对照设计" },
    { href: "/context/results", title: "用例结果" },
  ],
  "/judging/": [
    { href: "/judging/", title: "指标定义" },
    { href: "/judging/metrics", title: "指标定义总表" },
    { href: "/judging/judge", title: "判官说明" },
    { href: "/judging/invalid", title: "无效运行与口径" },
  ],
  "/tools/": [
    { href: "/tools/", title: "全部工具" },
  ],
  "/cases/": [
    { href: "/cases/", title: "全部用例" },
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

/** 侧栏级联模块树:父级手风琴(带箭头)+ 子级缩进嵌套;当前模块默认展开。 */
function sideTree(currentPath, moduleKey) {
  const items = MODULES.map((m) => {
    const pages = PAGES[m.href] || [];
    const here = m.href === moduleKey;
    const icon = NAV_ICON[m.icon];
    if (pages.length === 0) {
      // 单页模块(公告)渲染为直达链接:无子集、不带箭头
      return `<a class="side-item${here ? " active" : ""}" href="${m.href}">${icon}${m.label}</a>`;
    }
    const lis = pages
      .map(
        (p) =>
          `<li><a href="${p.href}"${p.href === currentPath ? ' class="active"' : ""}>${p.title}</a></li>`,
      )
      .join("\n          ");
    return `<details class="side-group${here ? " here" : ""}"${here ? " open" : ""}>
        <summary>${icon}${m.label}</summary>
        <ul>
          ${lis}
        </ul>
      </details>`;
  }).join("\n    ");
  return `<nav class="side-tree" aria-label="站点模块导航">
    ${items}
  </nav>`;
}

function shell({ title, description, currentPath, moduleKey, sections, extraScripts = "", homeShell = false, bodyHtml = "", pageClass = "", pageToc = true }) {
  // 页内目录与正文保持同一详情区,具体视觉位置由页面类型的 CSS 决定。
  const hasDetailLayout = !homeShell && sections.length > 0;
  const hasToc = hasDetailLayout && pageToc;
  const toc = hasToc
    ? `<aside class="page-toc" aria-label="本页目录">
      <h4 class="page-toc-title">本页目录</h4>
      <ul>
        ${sections.map((s) => `<li><a href="#${s.id}">${esc(s.title)}</a></li>`).join("\n        ")}
      </ul>
    </aside>`
    : "";
  const body = bodyHtml
    ? bodyHtml
    : sections
        .map(
          (s) => `<h2 id="${s.id}">${esc(s.title)}</h2>
${s.html}`,
        )
        .join("\n    ");
  const inner = hasDetailLayout
    ? `<div class="detail-layout${hasToc ? "" : " detail-layout-full"}">
      ${toc}
      <div class="detail-body">
        ${bodyHtml ? "" : `<h1>${esc(title)}</h1>`}
${body}
      </div>
    </div>`
    : `    ${bodyHtml ? "" : `<h1>${esc(title)}</h1>`}
${body}`;
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
<body${pageClass ? ` class="${esc(pageClass)}"` : ""}>
<header class="topbar">
  <div class="topbar-inner">
    <a class="brand" href="/"><span class="brand-mark">◆</span>Agent 对照评测<span class="brand-sub">实现方式 · 上下文压缩 · 可复核指标</span></a>
    <div class="topbar-actions">
      <a class="topbar-mytests" href="/test/">我的测试</a>
      <a class="topbar-login" href="/"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>登录</a>
    <a class="topbar-lab" title="进入运行台发起实验"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>运行台</a>
    <a class="topbar-logout" href="/"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>退出登录</a>
    <a class="topbar-gh" href="${GITHUB}" target="_blank" rel="noopener" aria-label="GitHub 仓库"><svg width="18" height="18" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true" focusable="false"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/></svg></a>
    </div>
    <button class="side-btn" id="sideBtn" type="button" aria-label="展开导航">导航</button>
  </div>
</header>
<div class="docs-layout">
  <aside class="docs-side" id="docsSide">
    ${sideTree(currentPath, moduleKey)}
    <div class="side-foot">全部指标由代码断言生成,可复核<br><a href="${GITHUB}" target="_blank" rel="noopener">源码仓库</a></div>
  </aside>
  <main class="docs-main">
${inner}
  </main>
</div>
<script src="/docs/docs.js"></script>
${extraScripts}
</body>
</html>
`;
}

// ── 公告页数据脚本(只读正式发布索引;无发布数据时保持真实空状态)────────
// 公告页(public/index.html)与实验模板中心(public/experiment/index.html)
// 为手工维护页面,不在 ALL_PAGES 内:重跑生成器不会覆盖这两页。

// 根路径 index.html 即公告页(独立单页,侧栏无子级);系统说明见「系统概览」模块。

// ── 系统概览模块 ────────────────────────────────────────────────────────

const ABOUT_SYSTEM = {
  path: "about/index.html",
  title: "系统定位与架构 · 系统概览",
  description: "本系统做什么、跑哪两类实验、四个服务如何协作。",
  moduleKey: "/about/",
  currentPath: "/about/",
  sections: [
    {
      id: "about",
      title: "系统定位",
      html: `<p>本系统用于<strong>Agent 的对照评测</strong>:同一题库、同一模型、同一份冻结工具数据,量化不同实验条件之间的可复核差异。权限、预算与红线由代码确定执行,语义理解交给模型。</p>
<p><strong>新正式实验以「实验模板 + 唯一自变量」定义</strong>,统一运行在原生 Tool Calling 底座上:</p>
<ul>
  <li><strong>治理开关对照</strong>(governance-on-off):同一循环、同一模型、同一完整工具目录与 Mock,只改变治理档位(off/standard),量化应拦截召回率、误拦截率、未确认写入与旁路事件;</li>
  <li><strong>工具提供方式对照</strong>(tool-delivery-comparison):同一完整目录与排除项下比较 all / search,错误归因分检索/选择/调用/最终回答四段;</li>
  <li><strong>工具可用性降级</strong>:版本化排除预设下观察首选路径、替代路径与诚实说明限制;</li>
  <li><strong>温度稳定性 / 步数稳定性</strong>:逐运行独立模型客户端,请求值与实际生效参数分别记录;</li>
  <li><strong>上下文实验</strong>:默认 4 种上下文方式 × 1 种固定原生配置(4×1),唯一自变量是上下文方式。</li>
</ul>
<p><strong>上下文压缩对照</strong>:同一长上下文用例,全量透传与按预算压缩两种处理分别跑同一 Agent 逻辑、同一套评判标准,量化强制项保留率、关键事实出现与 token 净节省。</p>
<p>证据方式:全部指标由代码断言产生(判官版本 <code>fixed-rules-v1</code>),无 LLM 判官;未运行的数字显示「未运行」,不以估算冒充实测。</p>`,
    },
    {
      id: "architecture",
      title: "整体架构",
      html: `<p>四个服务,一条公私边界:</p>
<div class="flow">web(纯静态展示层) ｜ engine(私有运行 API + 统一原生底座与模板执行器) ｜ data(题库/记录/发布登记) ｜ PostgreSQL(唯一数据来源)</div>
<p>公开部署只含静态站(物理排除 /lab);评测批次由项目所有者在私有侧发起,经发布校验投影为静态产物。</p>
<h3>一次运行(模板批次;旧实现对照为诊断入口)</h3>
<div class="flow">登录 → 运行台选模板并预估精确运行数 → 拉取冻结工具数据 → 逐运行独立模型客户端按变体执行(九类事件 + 逐步明细落库 + config_hash) → 九段运行工件 → 发布校验(门槛/敏感扫描/hash 复算) → 公开静态展示</div>
<h3>上下文压缩链路</h3>
<div class="flow">长上下文条目 → 分类(强制/可压缩/仅引用/干扰) → 预算选择与压缩 → 工作上下文 → 同一 Agent 循环 → 同一判官 → 处理报告进工件</div>
<p><strong>变量隔离</strong>:正式模板批次只动唯一自变量,其余条件冻结进运行配置快照(config_hash 同配置必同哈希),请求参数与实际生效参数分别记录;冻结数据隔离执行质量、金标路由隔离路由误差;压缩对照只变上下文处理策略。</p>`,
    },
  ],
};

const ABOUT_BANKS = {
  path: "about/banks.html",
  title: "题库与数据 · 系统概览",
  description: "两类题库的构成与数据来源。",
  moduleKey: "/about/",
  currentPath: "/about/banks",
  sections: [
    {
      id: "banks",
      title: "题库",
      html: `<ul>
  <li><strong>实现方式对照题库 98 道</strong>:通用工具用例 72(相似区分 / 不存在工具 / 权限确认 / 无工具 / 多工具组合)+ 领域基础题 18(对话、知识、拦截与多步示例)+ 负例 8,均存 PostgreSQL 为唯一数据来源,见<a href="/experiment/cases">固定题库</a>。</li>
  <li><strong>上下文压缩用例 6 套</strong>,每套 <code>full-raw</code> 全量与 <code>budgeted-comp</code> 压缩两条变体;条目构成与元信息见<a href="/context/library">长上下文库</a>,设计口径见<a href="/context/design">长短对照设计</a>。</li>
</ul>`,
    },
    {
      id: "data",
      title: "数据来源与冻结",
      html: `<p>题库、工具目录、冻结工具返回与变体上下文的唯一数据来源都是 PostgreSQL;引擎不直连库,全部经 data 服务 internal 接口读取。冻结工具返回存 <code>fixture_tool_responses</code>(fixture 集 <code>ab-eval</code> / <code>ab-eval-negative-v1</code> / <code>mock-eval-v1</code>),隔离执行质量差异。详见<a href="/ops/">数据库与冻结数据</a>。</p>`,
    },
  ],
};

const ABOUT_REPO = {
  path: "about/repo.html",
  title: "仓库与复现 · 系统概览",
  description: "代码构成、复现三步与工程门禁。",
  moduleKey: "/about/",
  currentPath: "/about/repo",
  sections: [
    {
      id: "repo",
      title: "仓库构成",
      html: `<p>代码在 <a href="${GITHUB}" target="_blank" rel="noopener">GitHub</a>:<code>engine/</code>(被测内核与对照 runner)、<code>data/</code>(题库与记录服务)、<code>web/</code>(公开展示层与私有运行台)、<code>db/</code>(库结构与种子)。</p>`,
    },
    {
      id: "reproduce",
      title: "复现三步",
      html: `<ol>
  <li>本地启动(见 <code>deploy/本地启动说明.md</code>);</li>
  <li>登录后进入运行台 <code>/lab/</code>:按模板发起正式批次,亦可发起上下文压缩对照;</li>
  <li><code>npm run publish:showcase -- --git-commit &lt;sha&gt;</code> 投影到公开层。</li>
</ol>`,
    },
    {
      id: "gates",
      title: "工程门禁",
      html: `<ul>
  <li>engine:<code>python -m pytest -q</code> 与 <code>python -m ruff check src tests</code></li>
  <li>data:<code>mvn -q test</code></li>
  <li>web:<code>npm test</code>(契约 + 渲染 + 发布管线测试)</li>
</ul>`,
    },
  ],
};

// ── 模块:我的测试(匿名任务列表/进度/取消/结果,读公开测试接口)────────

const myTestsScript = `
<script>
(function () {
  "use strict";
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"]/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
    });
  }
  var STATUS_LABEL = {
    QUEUED: "排队中", RUNNING: "运行中", COMPLETE: "完成", FAILED: "失败",
    CANCELLED: "已取消", INTERRUPTED: "已中断", PARTIAL: "部分完成",
  };
  var SCOPE_LABEL = {
    "context-only": "生成四份上下文(0 个 Agent 运行)",
    "current-combo": "运行当前组合(1 个运行)",
    "native-matrix": "原生 4×1 上下文实验(4 个运行)",
  };
  var ACTIVE = { QUEUED: 1, RUNNING: 1 };
  var listEl = document.getElementById("jobList");
  var stateEl = document.getElementById("jobLoadState");
  var openDetails = {}; // job_id -> true(展开态,重渲染后保持)

  function check(res) {
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }

  function statusBadge(status) {
    var cls = status === "COMPLETE" ? "ok" : (ACTIVE[status] ? "run" : "off");
    return '<span class="tag ' + cls + '">' + esc(STATUS_LABEL[status] || status) + "</span>";
  }

  function progressHtml(done, total) {
    var pct = total ? Math.round((done / total) * 100) : 0;
    return '<div class="prog"><div class="prog-bar" style="width:' + pct + '%"></div></div>' +
      '<small>' + done + " / " + total + " 个单元</small>";
  }

  function cardHtml(j) {
    var target = j.test_type === "COMPARISON_CASE"
      ? ("用例 " + esc(j.case_id || "—"))
      : ("Session " + esc(j.session_id || "—"));
    var custom = j.custom_conditions ? ' <span class="tag off">自定义条件</span>' : "";
    var actions = "";
    if (ACTIVE[j.status]) {
      actions += ' <button type="button" data-cancel="' + esc(j.job_id) + '">取消</button>';
    }
    actions += ' <button type="button" data-toggle="' + esc(j.job_id) + '">' +
      (openDetails[j.job_id] ? "收起结果" : "查看结果") + "</button>";
    return '<div class="job-card" id="job-' + esc(j.job_id) + '">' +
      '<div class="job-head">' + statusBadge(j.status) +
      "<b>" + esc(SCOPE_LABEL[j.execution_scope] || j.execution_scope) + "</b>" + custom +
      '<span class="job-time">' + esc(j.created_at || "") + "</span></div>" +
      '<div class="job-meta">' + target + " · 任务号 <code>" + esc(j.job_id) + "</code></div>" +
      progressHtml(j.completed_units || 0, j.total_units || 0) +
      '<div class="job-actions">' + actions + "</div>" +
      '<div class="job-detail" id="detail-' + esc(j.job_id) + '">' +
      (openDetails[j.job_id] ? '<div class="placeholder-block">读取中…</div>' : "") + "</div>" +
      "</div>";
  }

  function render(jobs) {
    if (!jobs.length) {
      stateEl.textContent = "";
      listEl.innerHTML = '<div class="placeholder-block">尚未发起任何测试。到 <a href="/experiment/compression">压缩用例</a> 实验页发起;任务在后台执行,关闭或刷新页面不会停止。</div>';
      return;
    }
    stateEl.textContent = "共 " + jobs.length + " 个任务,按创建时间倒序;运行中的任务每 5 秒自动刷新。";
    listEl.innerHTML = jobs.map(cardHtml).join("");
    Array.prototype.forEach.call(listEl.querySelectorAll("[data-cancel]"), function (btn) {
      btn.addEventListener("click", function () {
        btn.disabled = true;
        fetch("/api/v1/public/test-jobs/" + btn.getAttribute("data-cancel") + "/cancel", { method: "POST" })
          .then(load, load);
      });
    });
    Array.prototype.forEach.call(listEl.querySelectorAll("[data-toggle]"), function (btn) {
      btn.addEventListener("click", function () {
        var id = btn.getAttribute("data-toggle");
        if (openDetails[id]) delete openDetails[id]; else openDetails[id] = true;
        load();
      });
    });
    Object.keys(openDetails).forEach(function (id) { loadDetail(id); });
  }

  function load() {
    return fetch("/api/v1/public/test-jobs", { cache: "no-store" }).then(check).then(render).catch(function (err) {
      stateEl.textContent = "";
      listEl.innerHTML = '<div class="placeholder-block">运行服务不可达(' + esc(err.message) +
        ")。纯静态部署不提供任务查询;需要 engine 服务与 <code>/api/v1/public/</code> 反代。</div>";
    });
  }

  function unitRow(u, label) {
    var ok = u.task_success ? '<span class="tag ok">成功</span>' : '<span class="tag off">未成功</span>';
    var inval = u.validity === "INVALID" ? ' <span class="tag off">无效</span>' : "";
    return "<tr><td>" + esc(label || u.unit_id) + "</td><td>" + ok + inval + "</td><td>" +
      esc(u.actual_agent_steps || "—") + "</td><td>" + esc(u.stop_reason || "—") + "</td><td>" +
      esc(u.duration_ms || "—") + " ms</td></tr>";
  }

  function renderDetail(id, payload) {
    var box = document.getElementById("detail-" + id);
    if (!box) return;
    var result = payload.result || {};
    var units = payload.units || [];
    var html = '<p><small><span class="tag off">个人测试 · 非正式结果</span> 不进入公告指标;只有维护者审核发布的批次才进入公告。</small></p>';
    var def = result.fixed_conditions || {};
    if (def.experiment_definition || result.fixed_conditions_hash) {
      html += '<p><small>实验定义:' + esc(def.experiment_definition || "—") +
        (def.experiment_definition_note ? "(" + esc(def.experiment_definition_note) + ")" : "") +
        ' · 固定条件哈希 <code>' + esc(String(result.fixed_conditions_hash || "").slice(0, 16)) + "…</code></small></p>";
    }
    var rcs = result.run_configs || {};
    var rcKeys = Object.keys(rcs);
    if (rcKeys.length) {
      html += '<p><small>运行配置快照(config_hash):' + rcKeys.map(function (k) {
        return esc(k) + " → <code>" + esc(String((rcs[k] && rcs[k].config_hash) || "").slice(0, 12)) + "…</code>";
      }).join(" · ") + "</small></p>";
    }
    if (payload.test_type === "COMPARISON_CASE") {
      html += "<h4>实现结果分布</h4><table><thead><tr><th>Agent 实现</th><th>成功</th><th>有效/无效</th><th>时长 min/中位/max</th><th>离散</th></tr></thead><tbody>";
      Object.keys(result.by_agent || {}).forEach(function (mode) {
        var a = result.by_agent[mode];
        html += "<tr><td>" + esc(mode) + "</td><td>" + a.success_count + "/" + a.total_runs + "</td><td>" +
          a.valid_runs + "/" + a.invalid_runs + "</td><td>" +
          esc(a.duration_ms_min) + " / " + esc(a.duration_ms_median) + " / " + esc(a.duration_ms_max) +
          "</td><td>" + esc(a.duration_ms_stdev == null ? "—" : a.duration_ms_stdev) + "</td></tr>";
      });
      html += "</tbody></table>";
      if ((result.invalid_runs || []).length) {
        html += '<p><small>无效运行(' + result.invalid_runs.length + ",不自动补跑):" +
          result.invalid_runs.map(function (r) { return esc(r.unit_id); }).join("、") + "</small></p>";
      }
      html += "<h4>逐次运行(" + units.length + ")</h4><table><thead><tr><th>单元</th><th>结果</th><th>步数</th><th>停止原因</th><th>耗时</th></tr></thead><tbody>";
      units.forEach(function (u) { html += unitRow(u, u.agent_mode_id + " × 第" + (u.repeat_index + 1) + "次"); });
      html += "</tbody></table>";
      units.forEach(function (u) {
        html += '<details class="metric-def"><summary>' + esc(u.unit_id) + " 回答与调用</summary>" +
          "<p><small>回答:" + esc((u.answer || "").slice(0, 300)) + "</small></p>" +
          '<pre class="cat-schema">' + esc(JSON.stringify(u.tool_calls || [], null, 1)) + "</pre></details>";
      });
    } else if (payload.execution_scope === "context-only") {
      var stats = result.stats || {};
      html += "<h4>四份上下文工件</h4><table><thead><tr><th>方式</th><th>压缩前</th><th>压缩后</th></tr></thead><tbody>";
      ["full-session", "recent-window", "single-summary", "budgeted-session"].forEach(function (v) {
        html += "<tr><td>" + esc(v) + "</td><td>" + esc((stats.original_tokens || {})[v]) +
          "</td><td>" + esc((stats.working_tokens || {})[v]) + "</td></tr>";
      });
      html += "</tbody></table><p><small>本任务 0 个 Agent 运行;Agent 尚未运行,需另行发起「运行当前组合」或「原生 4×1」。</small></p>";
    } else {
      html += "<h4>矩阵单元</h4><table><thead><tr><th>上下文 × Agent</th><th>结果</th><th>步数</th><th>停止原因</th><th>耗时</th></tr></thead><tbody>";
      units.forEach(function (u) {
        html += unitRow(u, (u.context_variant || "") + " × " + u.agent_mode_id);
      });
      html += "</tbody></table>";
      var hashes = result.frozen_artifact_hashes || {};
      html += '<p><small>冻结工件哈希(各实现复用同一批):' +
        Object.keys(hashes).map(function (v) { return esc(v) + " → <code>" + String(hashes[v]).slice(0, 18) + "…</code>"; }).join(" · ") +
        "</small></p>";
    }
    if (payload.error) html += '<p><small>错误:' + esc(payload.error) + "</small></p>";
    box.innerHTML = html;
  }

  function loadDetail(id) {
    fetch("/api/v1/public/test-jobs/" + id + "/results", { cache: "no-store" }).then(check)
      .then(function (payload) { renderDetail(id, payload); })
      .catch(function (err) {
        var box = document.getElementById("detail-" + id);
        if (box) box.innerHTML = '<div class="placeholder-block">结果读取失败:' + esc(err.message) + "</div>";
      });
  }

  load();
  setInterval(load, 5000);
})();
</script>`;

const TEST_MY = {
  path: "test/index.html",
  title: "我的测试",
  description: "当前匿名身份发起的测试任务:进度、结果与取消;匿名结果不进入公告指标。",
  moduleKey: "/test/",
  currentPath: "/test/",
  sections: [
    {
      id: "notice",
      title: "匿名测试结果说明",
      html: `<div class="note"><strong>匿名测试结果</strong>:只代表本次选择的用例、工具和运行条件,不进入公告指标,也不会自动公开。任务与单元进度持久化在服务端,关闭或刷新页面不会停止任务;重新进入本页可继续查看。</div>`,
    },
    {
      id: "jobs",
      title: "任务列表",
      html: `<p id="jobLoadState" class="lab-note">正在读取…</p>
<div id="jobList"><div class="placeholder-block">正在读取…</div></div>`,
    },
    {
      id: "reading",
      title: "口径说明",
      html: `<ul>
  <li>取消只阻止尚未开始的单元;已产生的运行与费用保留,任务显示「已取消」或「部分完成」。</li>
  <li>无效运行(服务错误、超时等)单独显示,不自动补跑。</li>
  <li>服务重启后的中断任务标记为「已中断」,已完成单元保留,可重新发起而不丢失历史。</li>
  <li>匿名身份由浏览器 HttpOnly Cookie 标识,清除浏览器数据后无法恢复这些记录。</li>
</ul>`,
    },
  ],
  extraScripts: myTestsScript,
};

// ── 模块:实验(模板中心为根,手工维护;压缩用例页由本脚本生成)──────────

// 压缩用例页内联脚本:读长上下文库渲染三个 Session 与四策略概览;
// 三个手动按钮只在点击时调用公开测试接口,页面加载不创建任何任务。
const compressionScript = `
<script>
(function () {
  "use strict";
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"]/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
    });
  }
  var MODES = ["full-session", "recent-window", "single-summary", "budgeted-session"];
  var MODE_LABEL = {
    "full-session": "完整 Session(对照)",
    "recent-window": "最近窗口(基准)",
    "single-summary": "一次摘要(基准)",
    "budgeted-session": "按预算压缩(本项目算法)",
  };
  var AGENTS = ["native-tool-calling"]; // 统一原生底座
  var selected = { session: null, mode: "budgeted-session", agent: "native-tool-calling" };

  fetch("/showcase-data/context-library.json", { cache: "no-store" })
    .then(function (res) { return res.ok ? res.json() : null; })
    .then(function (lib) {
      var list = document.getElementById("sessionList");
      var entries = (lib && lib.entries) || [];
      if (!entries.length) {
        list.innerHTML = '<div class="placeholder-block">尚未维护压缩 Session。</div>';
        return;
      }
      var wanted = new URLSearchParams(location.search).get("session_id");
      selected.session = entries.some(function (e) { return e.id === wanted; }) ? wanted : entries[0].id;

      function renderList() {
        list.innerHTML = entries.map(function (s) {
          var stats = s.stats || {};
          var picked = s.id === selected.session ? ' <small style="color:#1d4ed8">[当前选中]</small>' : "";
          return '<details class="side-group"' + (picked ? ' open' : '') + '><summary>' + esc(s.title || s.id) + picked + "</summary>" +
            '<div class="kv"><span>事件</span><b>' + esc(stats.event_count) + " 个(用户消息 " + esc(stats.user_messages) +
            " / 工具对 " + esc(stats.tool_pairs) + ")</b></div>" +
            '<div class="kv"><span>原始规模</span><b>' + (s.original_tokens == null ? "—" : esc(s.original_tokens) + " token") + "</b></div>" +
            '<div class="kv"><span>当前输入</span><b>' + esc(String(s.current_question || "").slice(0, 100)) + "…</b></div>" +
            '<p><small><button type="button" data-select-session="' + esc(s.id) + '"' +
            (picked ? ' disabled' : '') + ">选中该 Session</button>" +
            (picked ? " 三个操作按钮当前作用于它" : "") +
            ' · <a href="/context/library">完整压缩前后对照见长上下文库</a></small></p></details>';
        }).join("");
        Array.prototype.forEach.call(list.querySelectorAll("[data-select-session]"), function (btn) {
          btn.addEventListener("click", function () {
            selected.session = btn.getAttribute("data-select-session");
            renderList(); // 原地切换选中态,不重新加载页面
          });
        });
        var current = document.getElementById("currentSessionId");
        if (current) current.textContent = selected.session || "—";
      }

      renderList();
    })
    .catch(function () {
      document.getElementById("sessionList").innerHTML = '<div class="placeholder-block">长上下文库数据不可读。</div>';
    });

  var modeSel = document.getElementById("modeSelect");
  var agentSel = document.getElementById("agentSelect");
  MODES.forEach(function (m) {
    var o = document.createElement("option");
    o.value = m; o.textContent = MODE_LABEL[m];
    modeSel.appendChild(o);
  });
  AGENTS.forEach(function (a) { agentSel.appendChild(new Option(a, a)); });
  modeSel.addEventListener("change", function () { selected.mode = modeSel.value; });
  agentSel.addEventListener("change", function () { selected.agent = agentSel.value; });

  function postJob(body) {
    return fetch("/api/v1/public/test-jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    });
  }
  function note(msg, isError) { noteHtml(esc(msg), isError); }
  function noteHtml(html, isError) {
    var box = document.getElementById("compressStatus");
    box.innerHTML = html;
    box.className = isError ? "lab-note lab-note-error" : "lab-note";
  }
  function requireSession() {
    if (!selected.session) { note("没有可用的压缩 Session。", true); return null; }
    return selected.session;
  }
  document.getElementById("btnGenerate").addEventListener("click", function () {
    var sid = requireSession(); if (!sid) return;
    note("正在提交「生成四份上下文」任务…");
    postJob({ test_type: "COMPRESSION_CASE", session_id: sid, execution_scope: "context-only" })
      .then(function (r) { noteHtml('任务已创建:<code>' + r.job_id + "</code>(0 个 Agent 运行)。到 <a href=\"/test/\">我的测试</a> 查看四份工件。"); })
      .catch(function (e) { note("提交失败:" + e.message + "(公开运行服务未部署或不可达;本站静态部署不提供运行入口)", true); });
  });
  document.getElementById("btnRunCombo").addEventListener("click", function () {
    var sid = requireSession(); if (!sid) return;
    note("正在提交「运行当前组合」任务(1 个运行)…");
    postJob({ test_type: "COMPRESSION_CASE", session_id: sid, execution_scope: "current-combo", context_variant: selected.mode, agent_mode_id: selected.agent })
      .then(function (r) { noteHtml('任务已创建:<code>' + r.job_id + "</code>(1 个 Agent 运行)。到 <a href=\"/test/\">我的测试</a> 查看进度与结果。"); })
      .catch(function (e) { note("提交失败:" + e.message, true); });
  });
  document.getElementById("btnRunNative").addEventListener("click", function () {
    var sid = requireSession(); if (!sid) return;
    note("正在提交「原生 4×1」任务(4 个运行)…");
    postJob({ test_type: "COMPRESSION_CASE", session_id: sid, execution_scope: "native-matrix" })
      .then(function (r) { noteHtml('任务已创建:<code>' + r.job_id + "</code>(4 个运行:4 种上下文 × 1 种固定原生配置)。到 <a href=\"/test/\">我的测试</a> 查看结果。"); })
      .catch(function (e) { note("提交失败:" + e.message, true); });
  });
})();
</script>`;

const EXPERIMENT_COMPRESSION = {
  path: "experiment/compression.html",
  title: "压缩用例 · 实验",
  description: "三个长 Session × 四种上下文方式;默认上下文实验 4×1(原生底座);生成上下文与 Agent 运行拆开,每格单次样本。",
  moduleKey: "/experiment/",
  currentPath: "/experiment/compression",
  sections: [
    {
      id: "scope",
      title: "实验对象与数量口径",
      html: `<p>压缩用例只使用上下文压缩模块维护的<strong>三个版本化长 Session</strong>:产品演进与需求决策、上下文引擎排查、数据库与部署。<strong>默认上下文实验是 4×1</strong>:4 种上下文方式 × 1 种固定原生 Tool Calling 配置(模板 <code>context-strategy-comparison</code>,唯一自变量 = <code>context_strategy</code>,其余条件冻结),共 4 个运行、每格 1 次。</p>
<p>三个数量口径全链路分开:<code>repeat_count</code>(压缩用例每格固定 1)/ <code>max_agent_steps</code>(单次运行内模型判断+工具回传的最大步数,服务端配置)/ 实现编号(统一为原生 Tool Calling 底座一种)。</p>`,
    },
    {
      id: "sessions",
      title: "三个 Session 概览",
      html: `<div id="sessionList"><div class="placeholder-block">正在读取长上下文库…</div></div>
<p class="lab-note">当前输入 = Session 最新一条有效用户消息,只发送一次,不进入历史压缩;其之前的事件构成历史。四种方式经过相同的输入构建、Token 统计与工件冻结;只有「按预算压缩」是本项目算法,完整/最近窗口/一次摘要为对照方法。<strong>各 Session 四种方式的压缩前后 Token 明细见<a href="/context/library">长上下文库</a></strong>,本页只维护实验入口,不重复展示第二份数字。</p>`,
    },
    {
      id: "actions",
      title: "三个手动操作",
      html: `<p>三个操作互不自动触发——生成上下文完成后不会自动运行 Agent;Session、算法参数或预算变化后旧工件不能复用,需重新生成。</p>
<p class="lab-note">操作作用于:<code id="currentSessionId">—</code>(在上方 Session 列表点击「选中该 Session」切换;从长上下文库进入时按链接自动预选)</p>
<div class="lab-row">
  <label>上下文方式 <select id="modeSelect"></select></label>
  <label>Agent 实现 <select id="agentSelect"></select></label>
</div>
<p>
  <button type="button" class="btn" id="btnGenerate">生成四份上下文(0 个 Agent 运行)</button>
  <button type="button" class="btn" id="btnRunCombo">运行当前组合(1 个运行)</button>
  <button type="button" class="btn" id="btnRunNative">运行原生 4×1(4 个运行 · 默认上下文实验)</button>
</p>
<div id="compressStatus" class="lab-note">按钮只在点击时调用公开测试接口;页面加载、静态站生成都不会创建实验任务。静态部署(无运行服务)时提交会失败并如实提示。</div>`,
    },
  ],
    extraScripts: compressionScript,
};

// 对比用例页内联脚本:读用例库公开投影;重复次数只允许 3/5;
// 开始按钮只在点击时调用公开测试接口。

// ── 模块:上下文压缩 ─────────────────────────────────────────────────────

const CONTEXT_ALGO = {
  path: "context/index.html",
  title: "压缩算法 · 上下文压缩",
  description: "token 计数公式、四种策略的决策规则、预算分配与压缩函数的精确口径。",
  moduleKey: "/context/",
  currentPath: "/context/",
  sections: [
    {
      id: "overview",
      title: "四种策略与符号",
      html: `<p>构建器输入为条目集合 <code>I = {i₁,…,iₙ}</code>(每条带分类 <code>cls(i) ∈ {required, compressible, reference_only, distractor}</code>、优先级 <code>p(i)</code>、序号 <code>seq(i)</code>)与预算 <code>B</code>;输出为工作上下文消息与逐条决策(<code>kept / compressed / referenced / omitted / isolated</code>)。四种策略:</p>
<ul>
  <li><strong>full</strong>:全量透传(预算内不压缩);</li>
  <li><strong>recent-n</strong>:只保留最近 N 条(窗口外省略);</li>
  <li><strong>single-summary</strong>:可压缩项合并为单摘要;</li>
  <li><strong>budgeted</strong>:按优先级与性价比选择压缩,仅引用项以来源元数据代表。</li>
</ul>
<p>默认参数:<code>N = 10</code>,压缩目标比例 <code>ρ = 0.35</code>,压缩条目最小 token <code>M = 32</code>。</p>`,
    },
    {
      id: "tokens",
      title: "token 计数公式",
      html: `<p>计数器为保守确定性口径 <code>conservative-cjk1-latin4-v1</code>,版本号写入工件与处理报告。对文本 <code>s</code>,设:</p>
<ul>
  <li><code>C(s)</code> = 非空白字符中属于「CJK 汉字 / 平假名 / 片假名 / 谚文 / Unicode 标点(类别 P*)」的个数;</li>
  <li><code>L(s)</code> = 其余非空白字符(拉丁字母、数字与其他文字)的个数;</li>
  <li>空白字符不计入。</li>
</ul>
<p>则 <code>T(s) = C(s) + ⌈L(s) / 4⌉</code>。该口径刻意偏保守(高估),保证预算内绝不超出真实 tokenizer 计数。</p>
<p>条目渲染时附加头标:<code>render(i, c) = [context item=ID type=cls(i) source=SID] + "\\n" + c</code>;不可信条目(<code>trusted=false</code> 或角色为 <code>untrusted_data</code>)整体包裹 <code>&lt;untrusted-data&gt;…&lt;/untrusted-data&gt;</code>,且不进入指令区。系统提示为 <code>bare</code> 条目逐字透传(不加头标)。所有 token 均按渲染后文本计数。</p>`,
    },
    {
      id: "allocation",
      title: "budgeted:预算分配公式",
      html: `<p><strong>第一步(required 全保留,红线)</strong>:</p>
<div class="flow">R = Σ_{cls(i)=required} T(render(i, content(i)))　→　R &gt; B 时直接判 CONTEXT_BUILD_FAILED,不静默降级;否则剩余预算 M₁ = B − R</div>
<p><strong>第二步(候选排序)</strong>:候选集 <code>Cand = {i : cls(i) ∈ {compressible, reference_only}}</code>,按 <code>(−p(i), seq(i), id(i))</code> 字典序升序处理(优先级高者优先,同优先级按时间先后)。跨用户条目(owner 不匹配)在此之前已被整体隔离(<code>isolated</code>);干扰项(<code>distractor</code>)不进预算,直接隔离。</p>
<p><strong>第三步(逐条配额)</strong>:处理到第 <code>j</code> 条(0 起,其后还有 <code>m = max(1, |Cand| − j)</code> 条)时,设当前剩余预算为 <code>Mⱼ</code>:</p>
<div class="flow">fairⱼ = max(M_min, ⌊Mⱼ / m⌋)　(均分下限保护,M_min = 32)
targetⱼ = min( T_orig(j),　max(M_min, ⌊T_orig(j) × ρ⌋),　max(0, fairⱼ − T_header(j)) )</div>
<p>其中 <code>T_orig(j) = T(render(iⱼ, content(iⱼ)))</code> 为原始渲染 token,<code>T_header(j) = T(render(iⱼ, ""))</code> 为头标 token。三个上限分别来自「不需要压」「不许压过头」「当条配额」。<code>reference_only</code> 条目不走压缩,直接以一行元数据代表:<code>[reference source=SID original_tokens=T_orig]</code>。</p>
<p><strong>第四步(入选与否)</strong>:压缩产物渲染后 token <code>≤ Mⱼ</code> 则入选并扣减预算(<code>Mⱼ₊₁ = Mⱼ − T(render(iⱼ, value))</code>);否则整条 <code>omitted</code>(原因记录进决策)。最终选中条目按 <code>(seq, id)</code> 复原时间顺序。</p>`,
    },
    {
      id: "compress",
      title: "压缩函数 compress(i, target)",
      html: `<p>单条压缩为确定性过程,无模型调用:</p>
<ol>
  <li><strong>规范化</strong>:按连续空行分段,段内连续空白折叠为单个空格,去掉首尾空白,并<strong>丢弃重复段落</strong>(保首次出现);</li>
  <li><strong>JSON 紧凑化</strong>:内容以 <code>{</code> 或 <code>[</code> 开头且可解析为 JSON 时,重写为无空白紧凑形式(键排序),否则保留规范化文本;</li>
  <li><strong>预算内直接返回</strong>:若 <code>T(norm) ≤ target</code>,原样返回(决策记 <code>kept</code>,不算压缩);</li>
  <li><strong>头尾保留</strong>:否则构造 <code>[compressed source=SID]\\n + norm[: ⌈0.6·|norm|⌉] + \\n[content omitted]\\n + norm[−⌈0.25·|norm|⌉:]</code>,即保头部 60%、尾部 25%,中段显式标注省略;</li>
  <li><strong>收缩循环</strong>:仍超预算时,对当前较大的一侧(头或尾)长度乘 0.8(下限 1 字符)重试,直至放得下;</li>
  <li><strong>兜底二分</strong>:极端情况下(连省略标记都放不下)在「标记 + 全文」上二分查找最大前缀长度 <code>lo</code> 使 <code>T(text[:lo]) ≤ target</code>,截断返回。</li>
</ol>
<p>压缩后能复原的定位信息只有 <code>source=SID</code> 与头标——这是设计取舍:省略必须显式可辨,不允许静默截断冒充全文。</p>`,
    },
    {
      id: "other-strategies",
      title: "其余策略公式",
      html: `<ul>
  <li><strong>full</strong>:全部条目按 <code>(seq, id)</code> 顺序渲染;<code>Σ T(render(i)) &gt; B</code> 时抛 <code>ContextWindowError</code>(不截断冒充全量)。</li>
  <li><strong>recent-n</strong>:按 <code>(seq, id)</code> 排序取最后 N 条为窗口;窗口内逐条放行并扣减预算,窗口外或预算耗尽记 <code>omitted</code>。</li>
  <li><strong>single-summary</strong>:required 先全保留(同 budgeted 第一步);可选条目按序拼接为一个合成条目(优先级取各条最大值,来源为各条 source 逗号连接),摘要预算 = <code>剩余预算 − T(合成条目头标)</code>,对合成条目调用上面的 compress;放得下则全部可选条目记 <code>compressed</code>,否则全部记 <code>omitted</code>。</li>
</ul>`,
    },
    {
      id: "invariants",
      title: "校验与红线",
      html: `<ul>
  <li><strong>required 保留率 100%</strong>:决策中 action ∈ {kept, compressed, referenced} 的 required 条目集合必须等于全部 required 条目;缺失即告警并按失败口径处理;</li>
  <li><strong>工作 token 校验</strong>:最终 <code>W = Σ T(message.content) &gt; B</code> 时抛 <code>ContextWindowError</code>;</li>
  <li><strong>消息拼装</strong>:可信指令类条目(system/instruction)合并为一条 system 消息,其余合并为一条 user 消息——注入条目永远进不了指令区;</li>
  <li><strong>处理报告</strong>:记录原始/工作 token、保留/压缩/引用/隔离/省略计数、逐条决策原因与构建耗时,随九段工件落库。</li>
</ul>
<p>接入位置:Agent 循环的模型输入拼装统一经构建器(有架构测试守卫,禁止旁路拼装)。见<a href="/engine/">Agent 循环</a>。</p>`,
    },
  ],
};

const CONTEXT_LIBRARY = {
  path: "context/library.html",
  title: "长上下文库 · 上下文压缩",
  description: "三套完整的场景化冻结 Session,用于长上下文与压缩策略的可复现实验。",
  moduleKey: "/context/",
  currentPath: "/context/library",
  sections: [
    {
      id: "about",
      title: "语料设计",
      html: `<p>主文库只展示<strong>完整、连续的 Session</strong>。仓库中的文档、源码、SQL 和配置不会直接拼成顶层用例,而是作为对话过程中的冻结工具结果出现。当前三套用例分别覆盖:</p>
<ul>
  <li><strong>产品与架构演进</strong>:多轮需求澄清、误解纠正、设计文件读取和最终范围收敛;</li>
  <li><strong>上下文引擎排查</strong>:编译器、预算、评分与 Agent 循环的连续代码审查;</li>
  <li><strong>数据库与云部署</strong>:手工 SQL、data 服务、本地 5432 和云部署配置的一致性审计。</li>
</ul>
<p>三套内容都明确标注为<strong>场景化冻结 Session</strong>:对话按真实开发流程整理,工具返回取自仓库文件快照,用于稳定复现实验,不冒充未经编辑的聊天逐字稿。同一份 Session 独立派生完整透传、最近窗口、一次摘要和按预算压缩四种输入。旧的六套结构化夹具仍可供引擎回归使用,但不再属于主文库展示语料。</p>`,
    },
    { id: "list", title: "语料列表", html: `<div id="libraryList"><div class="placeholder-block">正在读取长上下文库…</div></div>` },
  ],
  extraScripts: `
<script src="/context/library.js"></script>`,
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
<p>条目数据在库(<code>changes/20260821-long-context-cases.sql</code>,批量条目由确定性生成,有业务含义),执行时经数据服务读取,运行记录关联真实变体与快照;条目元信息与原文下载见<a href="/context/library">长上下文库</a>。</p>`,
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
      html: `<p>登录后进入运行台「压缩对照批次」按钮,或 CLI <code>python -m bdlh_runtime.evaluation.context_eval</code>:六套 × 两变体 × N 次;每变体运行产出九段工件与 context_builds 处理报告(条目/决策/消息级)。结果见<a href="/context/results">用例结果</a>。</p>`,
    },
  ],
};

const CONTEXT_RESULTS = {
  path: "context/results.html",
  title: "用例结果 · 上下文压缩",
  description: "压缩实验结果以公告页正式发布为准;未发布时统一空状态。",
  moduleKey: "/context/",
  currentPath: "/context/results",
  sections: [
    {
      id: "strategies",
      title: "四种策略",
      html: `<p>固定 Agent 实现方式,对照四种上下文处理策略:<strong>full-session</strong>(完整透传)、<strong>recent-window</strong>(最近窗口)、<strong>single-summary</strong>(一次摘要)、<strong>budgeted-session</strong>(按预算压缩,本项目算法)。模型窗口容纳不下 full 时该策略显示「不适用」,不把截断输入冒充 full。</p>
<p>各 Session 四种方式的<strong>编译统计</strong>(压缩前后 Token、事件处理桶)见<a href="/context/library">长上下文库</a>;<strong>实验结果</strong>(默认 4×1 上下文实验)在<a href="/experiment/compression">压缩用例实验</a>发起运行,正式数字经维护者审核发布后出现在<a href="/">公告页</a>。</p>`,
    },
    {
      id: "table",
      title: "策略对照(读正式发布索引)",
      html: `<div id="strategyTable"><div class="placeholder-block">尚未发布:压缩实验结果只展示经维护者审核发布的正式批次,不展示开发调试批次。发布后此处按变体展示工具选择正确率、关键事实召回、禁用事实泄漏与注入隔离。</div></div>`,
    },
    {
      id: "pairs",
      title: "正反例成对展示",
      html: `<p>同一用例的成功运行与失败运行并排展示,标注唯一变化的策略与来自校验器的失败原因;没有失败样本时显示「暂无失败样本」,且完整批次始终可查。</p><div id="contextPairs"><div class="placeholder-block">尚未发布。</div></div>`,
    },
  ],
  extraScripts: `
<script>
(function () {
  "use strict";
  // 只读正式发布索引;为空保持空状态(不回退旧批次索引)
  fetch("/showcase-data/publications/index.json", { cache: "no-store" })
    .then(function (res) { return res.ok ? res.json() : null; })
    .then(function (index) {
      var pubs = (index && index.formal_publications) || [];
      if (!pubs.length) return;
      var box = document.getElementById("strategyTable");
      if (box) {
        box.innerHTML = '<p class="lab-note">最新正式发布:' + String(pubs[0].published_at || "") +
          "(批次 " + String(pubs[0].batch_id || "").slice(0, 8) + ")。逐项指标与实例下钻见<a href=\"/\">公告页</a>;本页不再单独维护第二份结果展示。</p>";
      }
    })
    .catch(function () { /* 缺索引保持占位 */ });
})();
</script>`,
};

// ── 模块:评判标准 ───────────────────────────────────────────────────────

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
      id: "relation",
      title: "对比用例的调用关系评判",
      html: `<p>对比用例(20 条)的评判不再使用唯一 <code>expected_tools</code> 线性数组,而是调用关系结构(<code>call-relation-v1</code>):</p>
<ul>
  <li><code>required_calls</code>:必须发生的调用(工具名+关键参数子集匹配);</li>
  <li><code>required_dependencies</code>:后一步参数必须来自前一步结果的值流动(顺序敏感);</li>
  <li><code>acceptable_alternatives</code>:可互相替代的调用组,至少一组全部命中即通过(多条可接受路径);</li>
  <li><code>forbidden_calls</code> / <code>confirmation_required</code>:禁止调用;写操作在自主运行中调用即视为未经确认执行;</li>
  <li><code>stop_when_facts_available</code>:必须事实须进入最终回答;事实齐备后的多余调用计入记录。</li>
</ul>
<p>指标在逐次运行上计算:调用覆盖率、依赖满足、替代路径命中、违规数、事实命中、多余/重复调用、实际步数与停止原因;各实现的重复分布(成功次数、最小/中位/最大、离散)只在聚合页展示;结果按模板变量分组,不再默认按旧 agent_mode 分组。</p>`,
    },
    {
      id: "denominator",
      title: "分母口径与数字入口",
      html: `<p>所有比例的分母只含 <strong>VALID</strong> 运行;无效运行(见<a href="/judging/invalid">无效运行与口径</a>)单列数量与原因,不冒充失败样本。0%→0% 的变化渲染为占位符而非「改善/回归」。每个汇总数字可回溯到 run_id。</p>
<p><strong>指标数字的唯一入口是<a href="/#agent-summary">公告页 Agent 对比汇总区</a></strong>:实验结果数据只经维护者审核发布进入公告;本模块只维护指标定义,不再单独维护第二份批次指标总表。</p>`,
    },
  ],
};

const JUDGING_BATCH_METRICS = {
  path: "judging/metrics.html",
  title: "指标定义总表 · 评判标准",
  description: "基础能力、合规与效率指标的完整定义;指标数字以公告页发布数据为准。",
  moduleKey: "/judging/",
  currentPath: "/judging/metrics",
  sections: [
    {
      id: "table",
      title: "全部指标(逐组口径)",
      html: `<p>下表为<strong>指标定义总表</strong>——基础能力/合规/效率与通用目录专项(GT-7)的完整口径,每行说明计算方式与分母;「未运行」表示该组无对应金标或调用,不进分母。</p>
<table><thead><tr><th>指标</th><th>定义</th></tr></thead><tbody>
      ${METRIC_ROWS}
    </tbody></table>
<p class="lab-note">指标<strong>数字</strong>不再在本模块展示:实验结果只经维护者审核发布,唯一入口是<a href="/#agent-summary">公告页 Agent 对比汇总区</a>(未发布时显示「尚未发布」)。定义详见<a href="/judging/">指标定义</a>与<a href="/judging/judge">判官说明</a>。</p>`,
    },
  ],
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
  <li><strong>工具层</strong>:实际成功/发起的工具集合与题库金标比对(集合相等);</li>
  <li><strong>答案层</strong>:数字接地(答案中的非平凡数字必须来自某条工具结果)、C-1 高危操作语义、C-2 未授权建议结论;完整模式组用护栏修正后的答案判定;</li>
  <li><strong>上下文层(压缩对照)</strong>:强制项保留、关键事实出现、禁用事实不入答案、注入隔离。</li>
</ul>`,
    },
    {
      id: "output",
      title: "输出护栏与判定顺序",
      html: `<p>完整模式组先经输出护栏(数字接地替换、高危操作拦截、风险披露追加),修正后的答案才进判官——各实现的答案层检查同口径。护栏的每次修正都会记录在 guardrail_checks(response 时点)与运行事件流中。</p>`,
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

// ── 模块:引擎与治理(六页)─────────────────────────────────────────────

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
      html: `<p>每次运行发出统一事件流并逐步落库:<code>run.started / context.completed / model.completed / tool.requested / tool.completed / guardrail.completed / output.completed / judgment.completed / run.completed</code>。事件只记录可观察过程,不记录隐藏思维;全部执行器同口径埋点。</p>`,
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

// ── 模块:数据与运行(五页)─────────────────────────────────────────────

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
      html: `<p>冻结工具返回存 <code>fixture_tool_responses</code>(fixture 集 <code>ab-eval</code>),隔离执行质量差异;长上下文用例与变体见 <code>changes/20260821-long-context-cases.sql</code>(6 用例 × 2 变体 + 快照,批量条目确定性生成)。引擎不直连库:题库、目录、fixture、变体上下文全部经 data 服务 internal 接口。</p>`,
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
  <li><code>GET /api/v1/experiment-templates</code> — 实验模板清单(目的/唯一自变量/变体/冻结条件/权限与上限);</li>
  <li><code>POST /api/v1/template-batches/plan</code> — 模板批次预估(精确运行数与变体 config_hash,不创建运行);</li>
  <li><code>POST /api/v1/template-batches</code> — 按模板发起正式批次(固定用例 × 模板变体,统一原生底座);</li>
  <li><code>POST /api/v1/context-batches</code> — 发起上下文压缩对照批次(六套 × 两变体);</li>
  <li><code>GET /api/v1/jobs/{id}</code> 与 <code>POST /api/v1/jobs/{id}/cancel</code> — 作业状态与协作取消(幂等);</li>
  <li><code>GET /api/v1/batches/{id}</code> / <code>GET /api/v1/runs/{id}/detail</code> — 批次运行列表与单次运行逐步明细;</li>
  <li><code>/api/v1/public/*</code> — 匿名受限测试接口(实验页运行入口)。</li>
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
  <li>站点信息架构 v2(公告单页 + 系统概览模块 + 工具调用明细 + 长上下文库;本站)。</li>
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

// ── 工具目录与用例库(分页浏览) ─────────────────────────────────────────

const TOOLS_LIST = {
  path: "tools/index.html",
  title: "工具目录",
  description: "系统全部工具的浏览与检索(112 个,覆盖 55 个领域)。",
  moduleKey: "/tools/",
  currentPath: "/tools/",
  sections: [],
  bodyHtml: `
    <div class="cat-toolbar">
      <input class="cat-search" data-cat-search type="text" placeholder="搜索工具名 / 描述 / 领域…">
      <select class="cat-filter" data-cat-filter="domain"><option value="">全部领域</option></select>
    </div>
    <table class="cat-table">
      <thead><tr><th>工具名</th><th>描述</th><th>领域</th><th>副作用</th><th>风险</th><th>需登录</th><th>状态</th></tr></thead>
      <tbody data-cat-table><tr><td colspan="7" style="text-align:center;color:var(--doc-faint)">加载中…</td></tr></tbody>
    </table>
    <div class="cat-paginate" data-cat-pager></div>
    <div class="cat-count" data-cat-count></div>
  `,
  extraScripts: '<script src="/catalog/catalog.js"></script>\n<script>CATALOG.initToolsList();</script>',
};

const TOOLS_DETAIL = {
  path: "tools/detail.html",
  title: "工具详情",
  description: "单个工具的参数 schema、风险等级与所属工具集。",
  moduleKey: "/tools/",
  currentPath: "/tools/detail",
  sections: [],
  bodyHtml: '<div id="toolDetail"><div class="cat-detail-card"><p>加载中…</p></div></div>',
  extraScripts: '<script src="/catalog/catalog.js"></script>\n<script>CATALOG.initToolDetail();</script>',
};

const CASES_LIST = {
  path: "cases/index.html",
  title: "用例库",
  description: "对比用例的浏览与检索(20 道,5 个类别);每条用例可从详情页进入实验。",
  moduleKey: "/cases/",
  currentPath: "/cases/",
  sections: [],
  bodyHtml: `
    <div class="cat-toolbar">
      <input class="cat-search" data-cat-search type="text" placeholder="搜索题号 / 类别…">
      <select class="cat-filter" data-cat-filter="kind">
        <option value="">全部类型</option>
        <option value="basic">基础</option>
        <option value="combo">组合</option>
        <option value="multi">多工具</option>
        <option value="exception">异常</option>
        <option value="security">安全</option>
      </select>
      <select class="cat-filter" data-cat-filter="scene">
        <option value="">全部场景</option>
        <option value="general">general</option>
        <option value="portfolio">portfolio</option>
      </select>
    </div>
    <table class="cat-table">
      <thead><tr><th>题号</th><th>类别</th><th>类型</th><th>场景</th><th>工具数</th><th>进入实验</th></tr></thead>
      <tbody data-cat-table><tr><td colspan="6" style="text-align:center;color:var(--doc-faint)">加载中…</td></tr></tbody>
    </table>
    <div class="cat-paginate" data-cat-pager></div>
    <div class="cat-count" data-cat-count></div>
    <p class="lab-note">用例库只维护对比用例的浏览、筛选与详情;三个长上下文 Session 由<a href="/context/library">长上下文库</a>(上下文压缩模块)维护,不在本库重复登记。运行实验请进入<a href="/experiment/comparison">对比用例实验</a>;本页不发起运行。</p>
  `,
  extraScripts: '<script src="/catalog/catalog.js"></script>\n<script>CATALOG.initCasesList();</script>',
};

const CASES_DETAIL = {
  path: "cases/detail.html",
  title: "用例详情",
  description: "单个用例的问题、标准工具范围与实验入口(不展示评判配置)。",
  moduleKey: "/cases/",
  currentPath: "/cases/detail",
  sections: [],
  bodyHtml: '<div id="caseDetail"><div class="cat-detail-card"><p>加载中…</p></div></div>',
  extraScripts: '<script src="/catalog/catalog.js"></script>\n<script>CATALOG.initCaseDetail();</script>',
};

// ── 生成 ─────────────────────────────────────────────────────────────────

const ALL_PAGES = [
  ABOUT_SYSTEM,
  ABOUT_BANKS,
  ABOUT_REPO,
  TOOLS_LIST,
  TOOLS_DETAIL,
  CASES_LIST,
  CASES_DETAIL,
  TEST_MY,
  EXPERIMENT_COMPRESSION,
    CONTEXT_ALGO,
  CONTEXT_LIBRARY,
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

export { shell };

const isCli = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isCli) {
  generateSite()
    .then((count) => console.log(`generated ${count} pages under web/public`))
    .catch((error) => {
      console.error(error);
      process.exitCode = 1;
    });
}
