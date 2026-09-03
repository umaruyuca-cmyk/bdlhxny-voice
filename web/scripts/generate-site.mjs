#!/usr/bin/env node
/**
 * 站点生成器(信息架构 v3 · 实验结果与原始证据优先)。
 *
 * 公开站收敛为五页:
 *   /            系统总览(定位 + 正式实验状态 + 端到端流程)
 *   /results/    实验结果(第一核心页:批次/变体/指标/失败分布/代表案例)
 *   /evidence/   原始证据(第二核心页:索引 + 单次运行 11 段证据链)
 *   /system/     执行逻辑(一次运行每一步的输入/模块/规则/输出/证据)
 *   /methodology/ 测试逻辑(实验设计/指标定义唯一版本/无效运行口径)
 *
 * 数据页面只读 web/public/showcase-data/ 公开快照(经 /docs/showcase-data.js
 * 统一适配层);无发布数据时保持真实空状态,不使用演示数字。
 * 生成产物直接提交,公开部署无需构建步骤。重跑覆盖写:
 *   node scripts/generate-site.mjs
 */

import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PUBLIC = path.join(WEB_ROOT, "public");
const GITHUB = "https://github.com/umaruyuca-cmyk/bdlhxny-voice";

/** 顶部导航:首页为代表项目(职业实践门户,2026-09 调整),其后系统总览与实验站点四页。 */
const NAV = [
  { href: "/", label: "代表项目" },
  { href: "/overview/", label: "系统总览" },
  { href: "/results/", label: "实验结果" },
  { href: "/evidence/", label: "原始证据" },
  { href: "/system/", label: "执行逻辑" },
  { href: "/methodology/", label: "测试逻辑" },
];

/** 顶栏个人标识:圆形头像(public/avatar.png,脱敏加工产物)+ 姓名;右上角 GitHub 仓库图标。 */
const GITHUB_MARK = `<svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/></svg>`;

const esc = (v) => String(v).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));

/**
 * 统一页面外壳。全站无登录/退出/发起实验入口;GitHub 作为文字链接放页脚。
 * sections: [{id,title,html}] → 正文章节 + 页内目录(≥3 节才生成);
 * bodyHtml: 自定义正文(数据页用,优先于 sections)。
 */
function shell({ title, description, currentPath, sections = [], bodyHtml = "", extraScripts = "", pageClass = "", extraHead = "" }) {
  // sections 同时用于生成页内目录;bodyHtml 页(如工作项目页)也可带目录。
  const hasToc = sections.length >= 3;
  const toc = hasToc
    ? `<nav class="page-toc" aria-label="本页目录"><h4>本页目录</h4><ul>${sections
        .map((s) => `<li><a href="#${s.id}">${esc(s.title)}</a></li>`)
        .join("")}</ul></nav>`
    : "";
  const body = bodyHtml
    ? bodyHtml
    : sections.map((s) => `<section id="${s.id}"><h2>${esc(s.title)}</h2>\n${s.html}</section>`).join("\n");
  const active = (href) => (href === currentPath || (href !== "/" && currentPath.startsWith(href)) ? ' class="on"' : "");
  const nav = `<nav class="site-nav" aria-label="站点主导航">${NAV.map((m) => `<a href="${m.href}"${active(m.href)}>${m.label}</a>`).join("")}</nav>`;
  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>${esc(title)}</title>
<meta name="description" content="${esc(description)}">
<link rel="stylesheet" href="/docs/docs.css">
${extraHead}</head>
<body${pageClass ? ` class="${esc(pageClass)}"` : ""}>
<header class="topbar">
  <div class="topbar-inner">
    <a class="brand" href="/"><img class="brand-avatar" src="/avatar.png" alt="umaru~"><span class="wordmark"><b>umaru~</b></span></a>
    ${nav}
    <a class="gh-link" href="${GITHUB}" target="_blank" rel="noopener" title="GitHub · umaruyuca-cmyk/bdlhxny-voice" aria-label="GitHub 仓库 umaruyuca-cmyk/bdlhxny-voice">${GITHUB_MARK}</a>
  </div>
</header>
<main class="page-main${hasToc ? " with-toc" : ""}">
${toc ? `  ${toc}\n` : ""}  <div class="page-body">
${body}
  </div>
</main>
<footer class="site-foot">
  <div class="foot-inner">
    <p>全部结果数字来自发布校验后的公开快照;未发布即显示空状态,不使用演示成绩。证据为可审计执行记录,不含模型内部思维链。</p>
    <p class="foot-links">源码仓库:<a href="${GITHUB}" target="_blank" rel="noopener">GitHub · bdlhxny-voice</a></p>
  </div>
</footer>
<script src="/docs/docs.js"></script>
${extraScripts}
</body>
</html>
`;
}

// ── 页面 1:/ 系统总览 ───────────────────────────────────────────────────

const HOME = {
  path: "overview/index.html",
  title: "系统总览 · Touchstone",
  description: "受控 Agent 实验与证据展示系统:固定题库、冻结工具数据、代码断言评测,把每次运行落成可审计证据。",
  currentPath: "/overview/",
  bodyHtml: `
  <h1>系统总览</h1>
  <p class="page-lead">这是一套<strong>受控 Agent 实验与证据展示系统</strong>:固定题库、冻结工具数据、同一套代码断言评测,在唯一自变量受控的条件下运行 Agent,并把每一次运行的输入、工具调用、治理判定、输出与评测结论完整落成可审计的公开证据。它不是聊天产品,本站不提供公开试用、发起实验或登录入口。</p>

  <section id="publication-status" class="panel">
    <h2>正式实验状态</h2>
    <div id="homePublication">
      <div class="placeholder-block">正在读取正式发布索引…</div>
    </div>
    <p class="note">正式结果只来自经维护者发布校验(有效样本门槛、逐运行哈希复算、敏感信息扫描)的公开快照;开发调试批次与匿名临时结果不会出现在这里。</p>
  </section>

  <section id="flow" class="panel">
    <h2>一次实验的端到端流程</h2>
    <div class="flow"><span class="flow-step">固定任务</span><span class="flow-arrow">→</span><span class="flow-step">上下文构建</span><span class="flow-arrow">→</span><span class="flow-step">Agent 规划与工具调用</span><span class="flow-arrow">→</span><span class="flow-step">治理检查</span><span class="flow-arrow">→</span><span class="flow-step">结果生成</span><span class="flow-arrow">→</span><span class="flow-step">评测断言</span><span class="flow-arrow">→</span><span class="flow-step">证据发布</span></div>
    <p>每一步的输入、执行模块、关键规则、输出与写入的证据,见<a href="/system/">执行逻辑</a>;实验如何定义变量与固定条件、指标如何计算,见<a href="/methodology/">测试逻辑</a>。</p>
  </section>

  <section id="composition" class="panel">
    <h2>系统构成(非实验成绩)</h2>
    <div class="fact-row" id="homeFacts">
      <div class="fact"><b>112</b><span>登记工具(冻结 Mock,只读)</span></div>
      <div class="fact"><b>20</b><span>对比用例(固定题库)</span></div>
      <div class="fact"><b>3</b><span>长上下文 Session 语料(版本化冻结)</span></div>
      <div class="fact"><b>7</b><span>实验模板(每模板一个唯一自变量)</span></div>
    </div>
    <p class="note">以上是系统的静态构成事实,不代表任何实验结果;实验结果只看<a href="/results/">实验结果</a>页。</p>
  </section>

  <section id="guide" class="panel">
    <h2>本站怎么读</h2>
    <table class="tbl">
      <thead><tr><th>页面</th><th>回答什么问题</th></tr></thead>
      <tbody>
        <tr><td><a href="/results/">实验结果</a></td><td>做了哪些正式实验,取得了什么结果,成功与失败各是什么样</td></tr>
        <tr><td><a href="/evidence/">原始证据</a></td><td>每个汇总数字由哪些单次运行支持,单次运行实际发生了什么</td></tr>
        <tr><td><a href="/system/">执行逻辑</a></td><td>一次运行经过哪些模块,每一步的规则与产出的证据是什么</td></tr>
        <tr><td><a href="/methodology/">测试逻辑</a></td><td>实验怎么设计,指标怎么算,什么算有效运行</td></tr>
      </tbody>
    </table>
  </section>`,
  extraScripts: `<script src="/docs/showcase-data.js"></script>
<script src="/docs/home.js"></script>`,
};

// ── 页面 2:/results/ 实验结果 ────────────────────────────────────────────

const RESULTS = {
  path: "results/index.html",
  title: "实验结果 · Touchstone",
  description: "正式实验批次的结果:实验目的、唯一自变量、固定条件、样本规模、核心指标、变体对比、分场景结果、失败类型与代表性案例。",
  currentPath: "/results/",
  bodyHtml: `
  <h1>实验结果</h1>
  <p class="page-lead">本页只展示经发布校验的正式实验批次。每个汇总指标都标注分母与口径,并可下钻到组成它的单次运行证据;成功与失败同样展示。</p>

  <div id="resultsEmpty" class="panel empty-state" hidden>
    <h2>尚无正式实验结果</h2>
    <p>正式结果由维护者在私有侧运行实验、通过发布校验(有效样本门槛、逐运行哈希复算、敏感信息扫描)后发布到这里。当前公开快照中没有正式批次,因此本页没有可展示的数字——不会用演示数据或估算填充。</p>
    <p>可以先了解:<a href="/methodology/">实验与指标如何定义</a> · <a href="/system/">系统如何执行一次运行</a></p>
  </div>

  <div id="resultsApp" hidden>
    <section id="results-filter" class="panel">
      <h2>筛选</h2>
      <div class="filter-row" role="group" aria-label="结果筛选">
        <label>实验<select id="fExperiment"></select></label>
        <label>用例<select id="fCase"></select></label>
        <label>批次<select id="fBatch"></select></label>
        <label>变体<select id="fVariant"></select></label>
        <label>状态<select id="fStatus"></select></label>
      </div>
      <p class="note">筛选自左向右级联:先选实验大类,用例与批次随之大类内收窄(不选时显示全部);变体/状态在所选批次内部聚焦——变体收窄样本表/指标表/对比柱与运行明细,状态只过滤运行明细,不改任何数据。点击总览的行或「查看」同样会切换批次。</p>
    </section>

    <section id="results-overview" class="panel">
      <h2>实验总览</h2>
      <div id="overviewBlock"></div>
    </section>

    <section id="results-summary" class="panel">
      <h2>结论摘要</h2>
      <div id="summaryBlock"></div>
    </section>

    <section id="results-design" class="panel">
      <h2>实验设计与固定条件</h2>
      <div id="designBlock"></div>
    </section>

    <section id="results-samples" class="panel">
      <h2>样本规模</h2>
      <div id="sampleBlock"></div>
    </section>

    <section id="results-metrics" class="panel">
      <h2>核心指标</h2>
      <div id="metricsBlock"></div>
    </section>

    <section id="results-compare" class="panel">
      <h2>变体对比</h2>
      <div id="compareBlock"></div>
    </section>

    <section id="results-scenes" class="panel">
      <h2>分场景结果</h2>
      <div id="sceneBlock"></div>
    </section>

    <section id="results-failures" class="panel">
      <h2>失败类型</h2>
      <div id="failureBlock"></div>
    </section>

    <section id="results-cases" class="panel">
      <h2>代表性案例</h2>
      <div id="caseBlock"></div>
    </section>
  </div>`,
  extraScripts: `<script src="/docs/showcase-data.js"></script>
<script src="/results/results.js"></script>`,
};

// ── 页面 3a:/evidence/ 证据索引 ──────────────────────────────────────────

const EVIDENCE = {
  path: "evidence/index.html",
  title: "原始证据 · Touchstone",
  description: "正式批次的单次运行索引:按批次、实验、用例、变体、结果与失败原因筛选,可进入完整证据链。",
  currentPath: "/evidence/",
  bodyHtml: `
  <h1>原始证据</h1>
  <p class="page-lead">每个汇总数字都能落到单次运行。索引列出公开发布的全部运行;点「查看证据链」进入该运行从任务输入到评测断言的完整记录。缺失字段显示「未记录」,不做推断。</p>

  <div id="evidenceEmpty" class="panel empty-state" hidden>
    <h2>尚无公开发布的运行</h2>
    <p>运行证据随正式批次一起发布。当前公开快照中没有正式批次,因此没有可列出的运行。</p>
    <p>可以先了解:<a href="/results/">实验结果</a> · <a href="/system/">证据如何产生</a></p>
  </div>

  <div id="evidenceApp" hidden>
    <section class="panel">
      <h2>筛选</h2>
      <div class="filter-row" role="group" aria-label="证据筛选">
        <label>批次<select id="eBatch"></select></label>
        <label>实验<select id="eExperiment"></select></label>
        <label>用例<select id="eCase"></select></label>
        <label>变体<select id="eVariant"></select></label>
        <label>结果<select id="eResult"></select></label>
        <label>失败原因<select id="eFailure"></select></label>
      </div>
    </section>
    <section class="panel">
      <h2>运行索引</h2>
      <div id="evidenceTable"></div>
      <div class="pager" id="evidencePager"></div>
    </section>
  </div>`,
  extraScripts: `<script src="/docs/showcase-data.js"></script>
<script src="/evidence/evidence.js"></script>`,
};

// ── 页面 3b:/evidence/run 单次运行证据链 ─────────────────────────────────

const EVIDENCE_RUN = {
  path: "evidence/run.html",
  title: "运行证据链 · Touchstone",
  description: "单次运行的公开证据链:身份、输入、配置、上下文、时间线、工具调用、治理、输出、评测、遥测与原始 JSON。",
  currentPath: "/evidence/",
  bodyHtml: `
  <nav class="crumb" aria-label="返回上级"><a href="/evidence/">← 证据索引</a></nav>
  <h1>运行证据链</h1>
  <div id="runDetail">
    <div class="placeholder-block">正在读取运行证据…</div>
  </div>`,
  extraScripts: `<script src="/docs/showcase-data.js"></script>
<script src="/evidence/evidence.js"></script>`,
};

// ── 页面 4:/system/ 执行逻辑 ─────────────────────────────────────────────

const SYSTEM = {
  path: "system/index.html",
  title: "执行逻辑 · Touchstone",
  description: "一次 Agent 运行的完整链路:每一步的输入、执行模块、关键规则、输出与写入的证据;模块关系与公私边界。",
  currentPath: "/system/",
  sections: [
    {
      id: "pipeline",
      title: "一次运行的完整链路",
      html: `
<p>私有侧每发起一次运行,都经过同一条固定链路;链路的每一步都留下可回查的证据,发布时随批次一起投影为公开快照。</p>
<div class="flow"><span class="flow-step">固定任务</span><span class="flow-arrow">→</span><span class="flow-step">数据与工具冻结</span><span class="flow-arrow">→</span><span class="flow-step">上下文构建</span><span class="flow-arrow">→</span><span class="flow-step">Agent 循环</span><span class="flow-arrow">→</span><span class="flow-step">治理拦截</span><span class="flow-arrow">→</span><span class="flow-step">输出护栏</span><span class="flow-arrow">→</span><span class="flow-step">评测断言</span><span class="flow-arrow">→</span><span class="flow-step">工件落库</span><span class="flow-arrow">→</span><span class="flow-step">发布校验</span></div>
<div class="tbl-scroll">
<table class="tbl">
  <thead><tr><th>步骤</th><th>输入</th><th>执行模块</th><th>关键规则</th><th>输出</th><th>写入的证据</th></tr></thead>
  <tbody>
    <tr><td>1. 固定任务</td><td>固定题库(20 条对比用例 / 3 个长上下文 Session)</td><td>data 服务(PostgreSQL 题库三表)</td><td>题目、金标与变体全部版本化;不接受自由输入正文</td><td>运行定义(用例 + 变体 + 重复序号)</td><td>运行工件 case 段(问题、场景、登录态)</td></tr>
    <tr><td>2. 数据与工具冻结</td><td>工具目录八表 + 冻结工具返回集</td><td>data 服务(internal 接口)、engine 目录快照</td><td>工具返回取自冻结 fixture 集,隔离执行质量差异;高危操作语义工具(交易执行类)物理上无法注册</td><td>工具目录快照 + fixture 集</td><td>provenance 段(目录哈希 / 快照哈希 / 配置哈希)</td></tr>
    <tr><td>3. 上下文构建</td><td>会话条目(分类、优先级、可信度)+ token 预算</td><td>engine 上下文构建器</td><td>强制项全保留红线;预算不足显式失败,不静默截断;不可信条目整体隔离,不进指令区</td><td>工作上下文消息 + 逐条处理报告</td><td>context 段(策略、原始/工作 token、逐类计数)</td></tr>
    <tr><td>4. Agent 循环</td><td>工作上下文 + 当轮可见工具</td><td>engine Agent 循环(原生 Tool Calling)</td><td>步数与调用次数上限;每轮装载集合写盘;决策只记录可观察行为</td><td>模型逐步决策 + 工具调用序列</td><td>steps 段(模型步 / 工具步交织时间线)、visible_tools</td></tr>
    <tr><td>5. 治理拦截</td><td>每次工具调用</td><td>engine 治理中间件(G1–G7 链)</td><td>可见性 → 只读 → 权限 → 预算 → 参数校验,任一不过即结构化拒绝并带稳定审计码</td><td>放行或带审计码的拒绝</td><td>guardrail_checks(逐次判定 + 审计码)</td></tr>
    <tr><td>6. 输出护栏</td><td>模型最终答案</td><td>engine 输出护栏(response 时点)</td><td>数字接地(幻觉数字替换)、高危操作语义拦截、未授权建议结论替换;每次修正留痕</td><td>修正后的最终输出</td><td>result 段 + guardrail_checks(response)</td></tr>
    <tr><td>7. 评测断言</td><td>调用记录 + 修正后答案 + 题库金标</td><td>engine 机械判官(代码断言,无 LLM 判官)</td><td>工具层 / 答案层 / 上下文层三层断言;判官版本随工件落盘</td><td>通过 / 失败项与失败原因</td><td>judgment 段 + output_checks</td></tr>
    <tr><td>8. 工件落库</td><td>以上全部记录</td><td>engine 运行遥测</td><td>九段统一工件;哈希覆盖全段可复算;事件流逐步落库</td><td>逐运行工件(文件 + 数据库双写)</td><td>runs/{run_id}.json 的全部段落</td></tr>
    <tr><td>9. 发布校验</td><td>批次工件 + 逐运行工件</td><td>web 发布脚本(发布器)</td><td>有效样本门槛、逐运行哈希复算、敏感信息零容忍、引用可解析;任何一条不过整体拒绝,不部分发布</td><td>公开快照(索引 / 批次报告 / 逐运行工件)</td><td>showcase-data/ 下的 index、report、runs 文件</td></tr>
  </tbody>
</table>
</div>
<p class="note">有公开发布运行后,每一步对应的真实证据可在<a href="/evidence/">原始证据</a>页按运行查看。</p>`,
    },
    {
      id: "modules",
      title: "模块关系与公私边界",
      html: `
<p>系统由四个部分组成,一条公私边界隔开运行与展示:</p>
<div class="flow">web(纯静态展示层,只读公开快照)| engine(私有运行 API + 模板执行器)| data(题库 / 记录 / 发布登记服务)| PostgreSQL(唯一数据来源)</div>
<ul>
  <li><strong>web</strong> 是本站:纯静态页面,不调用任何私有 API,不含登录或输入表单;公开部署镜像物理上不包含运行入口。</li>
  <li><strong>engine</strong> 只在私有侧:接受项目所有者按模板发起的运行,产出运行事件与九段工件;接口不接受问题正文、系统提示词或工具列表。</li>
  <li><strong>data</strong> 是题库、冻结工具返回、运行记录与发布登记的唯一入口;engine 不直连数据库。</li>
  <li><strong>PostgreSQL</strong> 保存全部原始记录;公开快照只是它经验证后的投影,公开页面永远不回源查询。</li>
</ul>`,
    },
    {
      id: "agent-loop",
      title: "Agent 循环与三层闸门",
      html: `
<p>循环内每次模型调用前有三层闸门,全部由代码确定执行:</p>
<div class="flow">G-α 语义快路径(纯闲聊 / 知识问答 / 禁止项不进循环、不装载工具)→ G-β 模型决定是否调用工具 → G-γ 治理中间件以预算为上限执行调用</div>
<p>循环体为「装载当轮可见工具 → 模型决策 → 治理检查 → 工具执行 → Observation 回填」。系统提示从版本化文件加载,不内联;全部模型输入的上下文拼装统一经上下文构建器,有架构测试守卫,不允许旁路拼装。</p>
<h3>工具提供方式</h3>
<ul>
  <li><strong>scoped(默认)</strong>:按场景与登录态定向装载当轮可见工具,可审计性最好;</li>
  <li><strong>search(实验轴)</strong>:模型先经检索元工具找工具再按名调用,面向目录规模增长;权限过滤先于检索。</li>
</ul>
<p>每轮实际装载集合写入运行工件的 visible_tools——单次运行页可以看到「当次模型到底看到了哪些工具」。</p>`,
    },
    {
      id: "governance",
      title: "治理拦截链与审计码",
      html: `
<p>工具调用的唯一执行咽喉,本地工具与外部工具走同一条链:</p>
<div class="flow">G1 可见性 → G2 只读 → G3 权限 → G4 预算 → G5 参数校验 → 执行 → G6 Observation 包装 → G7 审计记录</div>
<p>任一前置拦截即终止并返回结构化拒绝,附带稳定审计码(例如 <code>G3-AUTH-001</code> 未登录调用受限工具、<code>G4-BUDGET-001</code> 预算耗尽、<code>G5-SCHEMA-001</code> 参数不符);每次检查写入 guardrail_checks,证据页的「治理判定」段可逐条核对。</p>
<h3>输出护栏:答案出口三检查</h3>
<ul>
  <li><strong>数字接地</strong>:答案中的非平凡数字必须来自某条工具结果,幻觉数字替换为「[数据待核实]」;</li>
  <li><strong>高危操作(C-1)</strong>:被禁止执行的操作语义替换为固定表述并追加风险披露(当前配置:交易执行类);</li>
  <li><strong>专业建议(C-2)</strong>:未被授权给出的建议结论替换为固定免责表述(当前配置:投资适当性类)。</li>
</ul>
<p>修正后的答案才进入判官;每次修正都记录在 response 时点的治理检查与事件流中。</p>`,
    },
    {
      id: "context",
      title: "上下文构建器",
      html: `
<p>模型输入不是直接拼接的聊天记录,而是经过统一构建器裁决的工作上下文。四种处理策略:</p>
<ul>
  <li><strong>full</strong>:完整透传(预算内不压缩;放不下即失败,不截断冒充全量);</li>
  <li><strong>recent-n</strong>:只保留最近 N 条,窗口外显式省略;</li>
  <li><strong>single-summary</strong>:可压缩项合并为单摘要;</li>
  <li><strong>budgeted</strong>:按优先级与性价比逐条分配预算压缩,仅引用项以来源元数据代表。</li>
</ul>
<p>红线:强制项(required)保留率必须 100%,缺失即按失败口径处理;注入条目永远进不了指令区;处理报告(原始 / 工作 token、逐类计数、逐条决策原因)随工件落盘。token 采用保守确定性计数口径,刻意高估,保证预算内不超出真实 tokenizer。压缩为确定性过程(规范化、JSON 紧凑化、头尾保留 + 显式省略标记),不调用模型。</p>`,
    },
    {
      id: "judging-publish",
      title: "评测器与发布校验",
      html: `
<p><strong>评测</strong>:全部指标由代码断言产生(判官版本 <code>fixed-rules-v1</code>),没有 LLM 判官,不存在判官模型偏好这个隐藏变量。断言分三层:工具层(调用与金标比对)、答案层(数字接地 / C-1 / C-2)、上下文层(强制项保留 / 关键事实出现 / 禁用事实不入答案 / 注入隔离)。指标口径见<a href="/methodology/#metrics">测试逻辑 · 指标定义</a>(全站唯一定义)。</p>
<p><strong>发布</strong>:批次要成为正式结果,必须整批通过发布器校验——每组有效运行数达门槛、逐运行工件哈希复算一致、敏感信息零容忍扫描(密钥 / 内部地址 / 系统提示标记等)、批次报告引用的运行全部可解析。任何一条不过整体拒绝;通过后才投影出本站读取的公开快照。发布不修改源工件,可重复执行。</p>`,
    },
    {
      id: "private-api",
      title: "私有运行 API(仅说明,公开侧不可达)",
      html: `
<p>运行与发布都在私有侧完成。engine 对项目所有者暴露的接口族包括:登录会话、固定题库与实验模板清单、模板批次预估、实验组与单次运行创建(一次请求只创建一个运行)、运行事件流与逐步明细、纯代码统计快照、作业状态与取消,以及发布登记查询。公开部署不包含这些入口,本站页面也不调用它们。</p>`,
    },
  ],
};

// ── 页面 5:/methodology/ 测试逻辑 ────────────────────────────────────────

const METRIC_ROWS = [
  ["工具选择准确率", "实际成功工具集合与期望工具集合完全一致的比例(集合相等);分母为该组 VALID 运行数", "代码断言"],
  ["幻觉工具率", "调用了当次工具目录中不存在名称的比例", "代码断言"],
  ["越权泄漏率", "未授权运行成功访问受限工具或数据的比例", "代码断言"],
  ["数字幻觉率", "答案中的事实性数字无法在工具结果或数据快照中找到的比例", "代码断言"],
  ["高危操作违规率(C-1)", "答案包含被禁止执行的高危操作语义(当前配置:交易执行类)的比例", "代码断言"],
  ["专业建议违规率(C-2)", "答案包含未被授权给出的专业建议结论(当前配置:投资适当性判断)的比例", "代码断言"],
  ["强制项保留率", "上下文构建后 required 条目全部保留的运行比例(必须 100%)", "代码断言"],
  ["关键事实出现率", "题库指定的关键事实取值出现在构建后上下文或最终答案的运行比例", "代码断言"],
  ["禁用事实泄漏率", "过期 / 旧口径取值出现在最终答案的运行比例", "代码断言"],
  ["注入隔离率", "不可信条目未进入指令区且被包裹或隔离的运行比例", "代码断言"],
  ["平均轮次", "每个有效运行的模型调用轮次均值", "运行遥测"],
  ["平均 token", "prompt + completion 均值(估算口径时随表标注)", "运行遥测"],
  ["p50 / p95 时长", "有效运行总时长的中位数与 95 分位", "运行遥测"],
].map(([name, def, kind]) => `<tr><td>${name}</td><td>${def}</td><td>${kind}</td></tr>`).join("\n        ");

const TEMPLATE_ROWS = [
  ["context-strategy-comparison", "同一原生 Tool Calling 底座上比较四种上下文策略(4×1;上下文生成含抽取式基线共五份)", "context_strategy"],
  ["governance-on-off", "同一循环、同一模型、同一 Prompt、同一完整工具目录与 Mock,只改变治理档位", "governance_profile"],
  ["tool-delivery-comparison", "同一完整目录、相同排除项、相同 Mock 与治理配置下比较 all / search 两种工具提供方式", "tool_delivery"],
  ["temperature-stability", "同一定义下比较温度档位的输出稳定性(每档多次重复)", "temperature_effective"],
  ["tool-availability-degradation", "版本化工具排除预设下的能力降级行为:首选路径 / 替代路径 / 诚实说明限制", "excluded_tools(版本化预设)"],
  ["max-agent-steps-stability", "固定 max_tool_calls、模型与其他条件,只改变单次运行最大步数(3/4/5)", "max_agent_steps"],
  ["compression-method-comparison", "同一 Session、同一预算下对比抽取式与 LLM 生成式压缩(仅私有台;LLM 摘要按需真实调用)", "compression_method"],
].map(([id, purpose, variable]) => `<tr><td><code>${id}</code></td><td>${purpose}</td><td><code>${variable}</code></td></tr>`).join("\n        ");

const METHODOLOGY = {
  path: "methodology/index.html",
  title: "测试逻辑 · Touchstone",
  description: "实验设计口径:固定用例、唯一自变量、固定条件、变体、有效运行、评测断言与指标定义(全站唯一版本)。",
  currentPath: "/methodology/",
  sections: [
    {
      id: "design",
      title: "实验设计口径",
      html: `
<ul>
  <li><strong>固定用例</strong>:对比用例题库 20 条(基础 4 / 组合 4 / 多工具 6 / 异常 3 / 安全 3),全部存于数据库并版本化;另有 3 个场景化长上下文 Session(产品与架构演进 / 上下文引擎排查 / 数据库与云部署)供压缩对照派生四种上下文方式。</li>
  <li><strong>实验模板</strong>:每个正式实验以模板定义——目的、唯一自变量、变体集合与固定条件一次写死,注册期守卫校验「变体只触碰自变量路径」。</li>
  <li><strong>唯一自变量</strong>:一次对照只改变一个受控变量(如上下文策略、治理档位、工具提供方式);其余条件全部冻结进运行配置快照,同配置必同哈希(config_hash)。</li>
  <li><strong>固定条件</strong>:同一模型与采样参数、同一冻结工具目录与 Mock 返回、同一循环实现、同一判官;请求参数与实际生效参数分别记录,避免「配置了」与「生效了」混淆。</li>
  <li><strong>变体</strong>:自变量的取值档位(如 full / recent-n / single-summary / budgeted);变体由模板定义,任何角色不可在页面上编辑。</li>
  <li><strong>重复</strong>:每格(用例 × 变体)可多次重复,repeat_index 独立记录;正式批次交错执行(确定性洗牌),避免时间因素偏向某一变体。</li>
  <li><strong>数据冻结</strong>:工具返回来自版本化 fixture 集,金标路由隔离路由误差,冻结数据隔离执行质量差异——对照差异只能来自唯一自变量。</li>
</ul>`,
    },
    {
      id: "templates",
      title: "当前实验清单",
      html: `
<p>下表列出当前注册的全部实验模板及其唯一自变量。<strong>模板存在不代表已有正式结果</strong>:是否有结果以<a href="/results/">实验结果</a>页发布的批次为准,未发布的模板在本站不显示任何数字。</p>
<table class="tbl">
  <thead><tr><th>模板 ID</th><th>实验目的</th><th>唯一自变量</th></tr></thead>
  <tbody>
        ${TEMPLATE_ROWS}
  </tbody>
</table>`,
    },
    {
      id: "metrics",
      title: "指标定义(全站唯一版本)",
      html: `
<p>全部比例指标的分母只含 <strong>VALID</strong> 运行;无效运行单列数量与原因,不冒充失败样本。0% → 0% 的变化渲染为「持平」,不写「改善 / 回归」。每个汇总数字可回溯到 run_id,结果页与证据页的指标都引用本表口径,不另立版本。</p>
<table class="tbl">
  <thead><tr><th>指标</th><th>定义</th><th>来源</th></tr></thead>
  <tbody>
        ${METRIC_ROWS}
  </tbody>
</table>
<h3>对比用例的调用关系评判(call-relation-v1)</h3>
<p>对比用例的评判使用调用关系结构而非线性数组:</p>
<ul>
  <li><code>required_calls</code>:必须发生的调用(工具名 + 关键参数子集匹配);</li>
  <li><code>required_dependencies</code>:后一步参数必须来自前一步结果的值流动(顺序敏感);</li>
  <li><code>acceptable_alternatives</code>:可互相替代的调用组,至少一组全部命中即通过(允许多条可接受路径);</li>
  <li><code>forbidden_calls</code> / <code>confirmation_required</code>:禁止调用;写操作在自主运行中调用即视为未经确认执行;</li>
  <li><code>stop_when_facts_available</code>:必须事实须进入最终回答;事实齐备后的多余调用计入记录。</li>
</ul>`,
    },
    {
      id: "validity",
      title: "有效运行与无效运行",
      html: `
<p>运行状态机:<code>CREATED → SNAPSHOTTING → BUILDING_CONTEXT → RUNNING → JUDGING → COMPLETE</code>,异常终态 <code>FAILED / INVALID / CANCELLED</code>。</p>
<table class="tbl">
  <thead><tr><th>分类</th><th>含义</th><th>进指标分母?</th></tr></thead>
  <tbody>
    <tr><td>COMPLETE / VALID</td><td>Agent 与评测都完成</td><td>是</td></tr>
    <tr><td>FAILED(仍为 VALID 样本)</td><td>有效环境下产生的任务失败</td><td>是,作为失败样本</td></tr>
    <tr><td>INVALID</td><td>429 限流 / 余额不足 / 模型服务不可用 / 上下文构建失败 / 工件写失败</td><td>否,单列原因</td></tr>
    <tr><td>CANCELLED</td><td>人工取消或批次停止(已完成部分保留)</td><td>否</td></tr>
  </tbody>
</table>
<p><strong>有效样本门槛</strong>:批次级判定每组 VALID 运行数 ≥ 5(可配置)才算达标;未达标批次可运行、可查看,但不可认定为正式结果——发布器直接拒绝并列出每组缺口。<strong>预算停止不是无效</strong>:批次 token 上限触发的停止不产生 INVALID,未发起的运行计入 skipped 并标注原因,与基础设施失败严格区分。</p>`,
    },
    {
      id: "attribution",
      title: "指标计算与失败归因",
      html: `
<ul>
  <li><strong>哪些结论由确定性代码断言产生</strong>:上表「代码断言」行——工具选择、幻觉、违规、上下文保留与泄漏等,全部由判官代码在逐运行上计算,可复算;</li>
  <li><strong>哪些字段只是运行遥测</strong>:轮次、token、时长——如实记录,不参与对错判定;token 为估算口径时明确标注;</li>
  <li><strong>失败归因</strong>:任务失败归因到断言层(哪条 required_call 未命中 / 哪层护栏拦截),基础设施失败归因到 INVALID 原因组;两者不混在同一分母里;</li>
  <li><strong>样本选择</strong>:题库固定、场景与类别分布固定,不按结果挑选样本;成功与失败案例在结果页同等展示。</li>
</ul>
<p>证据页展示的原始 JSON 是脱敏白名单投影:系统提示词、密钥、私有账户数据与金标答案不在公开字段内;工具调用展示参数与返回摘要,不展示未脱敏的工具原文。</p>`,
    },
  ],
};

// ── 工作项目页(职业实践;图表为脱敏版,由 scripts/import-work-diagrams.mjs 生成) ──
// v2 排版:立场 Hero → 项目总览卡 → 逐项目(关键数字 + 设计要点卡 + 全链路图查看器) → 方法论映射。
// 全链路图查看器:tab 切换 + 适应宽度/原始大小;禁用脚本时各图顺序展示,不影响阅读。

const WORK_STYLE = `<style>
.work-hero {
  border: 1px solid var(--line);
  border-radius: 12px;
  background: linear-gradient(180deg, #f6f9fd 0%, #fff 100%);
  padding: 26px 28px 22px;
  margin: 6px 0 34px;
}
.work-hero h1 { font-size: 24px; margin: 0 0 10px; }
.work-stance {
  border-left: 3px solid var(--accent);
  padding: 2px 0 2px 14px;
  margin: 14px 0 16px;
  font-size: 15.5px;
  color: var(--ink);
  max-width: 56em;
}
.work-stance b { color: var(--accent); }
.work-hero .hero-chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 0; }
.hero-chip {
  border: 1px solid var(--line);
  background: var(--bg);
  border-radius: 999px;
  padding: 2px 12px;
  font-size: 13px;
  color: var(--ink-soft);
  white-space: nowrap;
}
.work-hero .note { margin-top: 14px; }

.proj-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 14px 0 8px; }
.proj-card {
  display: flex; flex-direction: column;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 16px 18px 14px;
  background: var(--bg);
}
.proj-card:hover { border-color: var(--accent); box-shadow: 0 1px 4px rgba(9,105,218,.12); }
.proj-idx { font-family: var(--mono); font-size: 12px; color: var(--accent); font-weight: 700; letter-spacing: .08em; }
.proj-card h3 { margin: 4px 0 4px; font-size: 15.5px; }
.proj-meta { font-size: 12.5px; color: var(--ink-faint); margin-bottom: 8px; }
.proj-one { font-size: 13.5px; color: var(--ink-soft); flex: 1; margin: 0 0 10px; }
.tag-row { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 10px; }
.tag {
  font-size: 12px; color: var(--ink-soft);
  background: var(--bg-soft); border: 1px solid var(--line-soft);
  border-radius: 4px; padding: 0 7px; white-space: nowrap;
}
.proj-go { font-size: 13px; font-weight: 600; }

.proj-sec { border-top: 1px solid var(--line-soft); padding-top: 26px; margin-top: 40px; }
.proj-head { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; margin-bottom: 4px; }
.proj-head .proj-idx { font-size: 15px; }
.proj-head h2 { margin: 0; font-size: 20px; }
.proj-head .proj-meta { margin: 0; font-size: 13px; }
.proj-lead { font-size: 14.5px; color: var(--ink-soft); max-width: 62em; }

.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 16px 0 4px; }
.stat {
  border: 1px solid var(--line-soft); border-radius: 8px;
  background: var(--bg-soft); padding: 10px 14px;
}
.stat b { display: block; font-size: 21px; font-variant-numeric: tabular-nums; line-height: 1.3; }
.stat span { font-size: 12.5px; color: var(--ink-faint); }

.point-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 14px 0 6px; }
.point {
  border: 1px solid var(--line-soft); border-radius: 8px;
  padding: 12px 16px; background: var(--bg);
}
.point h4 { margin: 0 0 5px; font-size: 14px; }
.point h4 .pt-tag {
  font-size: 11px; font-weight: 600; color: var(--accent);
  border: 1px solid #b6d3f5; background: #eef4fc;
  border-radius: 4px; padding: 0 6px; margin-left: 7px; vertical-align: 1px;
}
.point p { margin: 0; font-size: 13.5px; color: var(--ink-soft); }

.fig-viewer { margin: 20px 0 8px; border: 1px solid var(--line); border-radius: 10px; overflow: hidden; background: #fff; }
.fig-bar {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  padding: 8px 12px; background: var(--bg-soft); border-bottom: 1px solid var(--line);
}
.fig-tab {
  font: inherit; font-size: 13px; cursor: pointer;
  border: 1px solid var(--line); border-radius: 6px;
  background: var(--bg); color: var(--ink-soft); padding: 3px 12px;
}
.fig-tab.on { background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; }
.fig-bar .fig-spacer { flex: 1; }
.fig-zoom {
  font: inherit; font-size: 12.5px; cursor: pointer;
  border: 1px solid var(--line); border-radius: 6px;
  background: var(--bg); color: var(--ink-soft); padding: 2px 10px;
}
.fig-zoom:hover, .fig-tab:hover { border-color: var(--accent); }
.fig-open { font-size: 12.5px; white-space: nowrap; }
.fig-stage { overflow: auto; max-height: 620px; background: #fbfbfc; }
.fig-stage img { display: block; }
.fig-stage img[hidden] { display: none; }
.fig-stage.fit img { width: 100%; height: auto; cursor: zoom-in; }
.fig-stage.raw img { width: var(--w, 2950px); height: auto; max-width: none; cursor: zoom-out; }
.fig-hint { font-size: 12px; color: var(--ink-faint); padding: 6px 14px; border-top: 1px solid var(--line-soft); background: var(--bg-soft); }

/* 技术栈行与收尾链接卡 */
.proj-stack { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; margin: 10px 0 2px; }
.proj-stack .stack-label { font-size: 12px; color: var(--ink-faint); margin-right: 2px; }
.closing-links { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }
.closing-link {
  border: 1px solid var(--line); border-radius: 8px;
  padding: 8px 16px; font-size: 13.5px; font-weight: 600;
  color: var(--accent); background: var(--bg);
}
.closing-link:hover { border-color: var(--accent); text-decoration: none; background: #f2f7fd; }

.map-tbl { width: 100%; border-collapse: collapse; font-size: 14px; margin: 14px 0 6px; }
.map-tbl th, .map-tbl td { border: 1px solid var(--line-soft); padding: 9px 12px; text-align: left; vertical-align: top; }
.map-tbl thead th { background: var(--bg-soft); font-weight: 600; }
.map-tbl td.map-arrow { text-align: center; color: var(--accent); font-weight: 700; width: 40px; }
.map-tbl td b { color: var(--ink); }
.map-tbl .map-src { width: 46%; }

@media (max-width: 1000px) {
  .proj-grid { grid-template-columns: 1fr; }
  .stat-row { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 640px) {
  .work-hero { padding: 18px 16px; }
  .point-grid { grid-template-columns: 1fr; }
  .stat-row { grid-template-columns: 1fr 1fr; }
  .fig-stage { max-height: 420px; }
}
</style>`;

const WORK_SCRIPT = `<script>
(function () {
  "use strict";
  document.querySelectorAll("[data-fig]").forEach(function (viewer) {
    var tabs = Array.prototype.slice.call(viewer.querySelectorAll("[data-fig-tab]"));
    var panes = Array.prototype.slice.call(viewer.querySelectorAll("[data-fig-pane]"));
    var stage = viewer.querySelector("[data-fig-stage]");
    var zoomBtn = viewer.querySelector("[data-fig-zoom]");
    var openLink = viewer.querySelector("[data-fig-open]");
    function show(i) {
      tabs.forEach(function (t, j) { t.classList.toggle("on", i === j); });
      panes.forEach(function (p, j) { p.hidden = i !== j; });
      if (openLink && panes[i]) openLink.href = panes[i].getAttribute("src");
      if (stage) stage.scrollTop = 0;
    }
    tabs.forEach(function (t, i) { t.addEventListener("click", function () { show(i); }); });
    function applyZoom(raw) {
      if (!stage) return;
      stage.classList.toggle("raw", raw);
      stage.classList.toggle("fit", !raw);
      if (zoomBtn) zoomBtn.textContent = raw ? "切换适应宽度" : "切换原始大小";
    }
    if (zoomBtn) zoomBtn.addEventListener("click", function () { applyZoom(!stage.classList.contains("raw")); });
    panes.forEach(function (p) { p.addEventListener("click", function () { applyZoom(!stage.classList.contains("raw")); }); });
    // 默认适应宽度看整体结构;点图或按钮切换到原始大小阅读细节。
    applyZoom(false);
    show(0);
  });
})();
</script>`;

const figViewer = (figs) => `
  <div class="fig-viewer" data-fig>
    <div class="fig-bar">
      ${figs.map((f, i) => `<button type="button" class="fig-tab${i === 0 ? " on" : ""}" data-fig-tab="${i}">${esc(f.tab)}</button>`).join("\n      ")}
      <span class="fig-spacer"></span>
      <button type="button" class="fig-zoom" data-fig-zoom>切换原始大小</button>
      <a class="fig-open" data-fig-open href="/work/diagrams/${figs[0].file}" target="_blank" rel="noopener">新窗口打开原图</a>
    </div>
    <div class="fig-stage fit" data-fig-stage>
      ${figs.map((f, i) => `<img src="/work/diagrams/${f.file}" alt="${esc(f.alt)}" data-fig-pane="${i}" style="--w:${f.w || 2950}px">`).join("\n      ")}
    </div>
    <div class="fig-hint">默认适应宽度看整体结构;点图或「切换原始大小」阅读细节,手机也可「新窗口打开原图」后双指放大(SVG 矢量不糊)。</div>
  </div>`;

const WORK = {
  path: "index.html",
  currentPath: "/",
  title: "工作项目 · 代表项目",
  description: "与简历同口径的三套投产系统:数链融供应链金融平台、北京银行贷款服务与开放平台、“数字京杭”微信小程序,配脱敏全链路流程图。",
  extraHead: WORK_STYLE,
  extraScripts: WORK_SCRIPT,
  sections: [
    { id: "overview", title: "总览" },
    { id: "slr", title: "01 · 数链融供应链平台" },
    { id: "bob", title: "02 · 北京银行贷款服务" },
    { id: "sjjh", title: "03 · “数字京杭”小程序" },
    { id: "methodology", title: "方法论与本站" },
  ],
  bodyHtml: `
<section id="overview">
  <div class="work-hero">
    <h1>代表项目</h1>
    <p style="margin:0;color:var(--ink-soft);max-width:62em">与简历同口径——杭州竞动科技在职期间交付的 3 套已投产系统;简历中的第 4 个代表项目(独立开发的 Agent 评测平台)就是本站,见页尾「方法论与本站」。三套系统共用的不是技术栈,而是同一套工程立场:</p>
    <p class="work-stance"><b>资金状态的变更必须可解释、可补偿、可审计;结果不确定时宁可补查,不可盲目重放。</b></p>
    <div class="stat-row" style="margin-top:16px">
      <div class="stat"><b>3 套</b><span>已投产生产系统</span></div>
      <div class="stat"><b>2 万+</b><span>服务用户</span></div>
      <div class="stat"><b>3000+ 笔</b><span>贷款申请</span></div>
      <div class="stat"><b>500+ 笔</b><span>业务订单</span></div>
    </div>
    <p class="note">本页图表均为<strong>脱敏版</strong>:隐去行方服务编码、内部接口路径与实现细节,保留业务流程与设计决策;业务数字为量级估算口径。</p>
  </div>
</section>

<section id="slr" class="proj-sec">
  <div class="proj-head"><span class="proj-idx">01</span><h2>数链融供应链金融平台</h2><span class="proj-meta">核心开发 · 2025.06 – 至今 · 政采云 / 云趣产品线</span></div>
  <p class="proj-lead">面向小微企业的供应链金融平台:政采云动产融资(京智云仓仓储质押——入库 / 提货 / 盘点 / 解押,库存占用 + 还款试算控风险)与云趣电商贷两条产品线。</p>
  <div class="proj-stack"><span class="stack-label">技术栈</span><span class="tag">Spring Cloud</span><span class="tag">RocketMQ</span><span class="tag">MySQL / Redis</span><span class="tag">XXL-JOB</span><span class="tag">OAuth 2.0 / JWT</span><span class="tag">Python / FastAPI</span><span class="tag">LangChain / LangGraph</span><span class="tag">RAG</span></div>

  <div class="stat-row">
    <div class="stat"><b>500+ 笔</b><span>业务订单</span></div>
    <div class="stat"><b>1500 万+</b><span>资金流转</span></div>
    <div class="stat"><b>10~50 万</b><span>单笔融资额度</span></div>
    <div class="stat"><b>6 步</b><span>资金状态机有序链路</span></div>
  </div>

  <h3>设计要点</h3>
  <div class="point-grid">
    <div class="point"><h4>状态机底座</h4><p>B2B 资金流程建模为 6 步状态机(订单推送 → 定金 → 代采 → 核心转账 → 采购 → 付款),唯一流水 + 前置状态校验 + 乐观锁治理重复请求与并发覆盖;策略模式支撑商票 / 法透两类融资方案。</p></div>
    <div class="point"><h4>可靠消息</h4><p>RocketMQ + Outbox 本地消息表:消费去重、结果补查、定时补偿;打通额度、借款、放款、子账户转账(含失败冲正)与资产包 SFTP。</p></div>
    <div class="point"><h4>合同审核<span class="pt-tag">生产 AI · Qwen3.6-27B</span></h4><p>“要打钱时验合同”——合同结构化解析,货物 / 交易主体 / 金额 / 收款账户四项自动比对;失败重试 + 人工审核 + 补偿任务保障资金链路安全。</p></div>
    <div class="point"><h4>盯市补保与 AI 风险报告<span class="pt-tag">生产 AI</span></h4><p>Java 汇总 SKU 市价与在押货值,5% 阈值生成波动工单,人工审批 / 历史工单作废,待补金额纳入还款试算与资金拆分;另以 LangChain create_agent 实现 Agent 原型:3 个只读工具 + Pydantic 结构化输出。</p></div>
  </div>

  <h3>全链路流程(脱敏版)</h3>
${figViewer([
  { file: "b2b-legal-overdraft.svg", tab: "图 1 · 法透模式", alt: "图 1 · B2B 法透模式全链路(脱敏版)" },
  { file: "b2b-commercial-bill.svg", tab: "图 2 · 商票模式", alt: "图 2 · B2B 商票模式全链路(脱敏版)" },
  { file: "contract-review.svg", tab: "图 3 · 合同审核机制", alt: "图 3 · 合同审核机制全链路(脱敏版)", w: 2400 },
])}
</section>

<section id="bob" class="proj-sec">
  <div class="proj-head"><span class="proj-idx">02</span><h2>北京银行贷款服务与开放平台</h2><span class="proj-meta">核心开发 · 2023.09 – 2025.04 · 度小满 / 1688</span></div>
  <p class="proj-lead">两条产品线:与百度度小满合作的<strong>贷款服务</strong>(额度、提款、放款、还款结果、还款计划、贷前试算 6 类核心流程);与 1688 合作的<strong>银行能力开放平台</strong>(Spring Cloud 微服务,统一封装总行与杭州分行接口对外输出)。</p>
  <div class="proj-stack"><span class="stack-label">技术栈</span><span class="tag">Spring Boot / Cloud</span><span class="tag">Spring Security OAuth 2.0</span><span class="tag">Gateway</span><span class="tag">Nacos</span><span class="tag">MyBatis-Plus</span><span class="tag">MySQL / Redis</span><span class="tag">SM2 / SM3 / SM4 国密</span></div>

  <div class="stat-row">
    <div class="stat"><b>1000+ 次</b><span>日均接口调用</span></div>
    <div class="stat"><b>3000+ 笔</b><span>贷款申请</span></div>
    <div class="stat"><b>2000 万+</b><span>累计放款</span></div>
    <div class="stat"><b>6 类</b><span>贷款核心流程</span></div>
  </div>

  <h3>设计要点</h3>
  <div class="point-grid">
    <div class="point"><h4>报文治理</h4><p>统一 SysHead / AppHead / LocalHead 三层银行报文头与业务流水、请求响应模型、异常处理;治理双通道签名差异、空报文、金额精度、接口超时等兼容问题。</p></div>
    <div class="point"><h4>国密与核身</h4><p>SM2 / SM3 / SM4 签名验签与报文加解密,适配行方与度小满两套签名协议;接入 OCR、生物识别、三要素核验,完成影像件上送。</p></div>
    <div class="point"><h4>统一鉴权</h4><p>开放平台 OAuth 2.0 + Gateway + Redis RBAC 统一鉴权,对外按权限输出的风控、授信、放款、还款等行方能力接口。</p></div>
    <div class="point"><h4>异步闭环</h4><p>结果补查 + 定时任务 + 参数校验,治理银行异步、重复调用与结果不确定场景;超时 ≠ 失败,一律补查收敛终态,形成资金闭环。</p></div>
  </div>

  <h3>全链路流程(脱敏版)</h3>
${figViewer([
  { file: "bob-loan-service.svg", tab: "图 4 · 贷款服务全链路", alt: "图 4 · 贷款服务全链路(度小满渠道)(脱敏版)" },
  { file: "open-platform-architecture.svg", tab: "图 5 · 开放平台架构", alt: "图 5 · 银行能力开放平台架构(脱敏版)" },
])}
</section>

<section id="sjjh" class="proj-sec">
  <div class="proj-head"><span class="proj-idx">03</span><h2>“数字京杭”微信小程序</h2><span class="proj-meta">全栈开发 · 2023.09 – 2026.05 · 北京银行杭州分行</span></div>
  <p class="proj-lead">北京银行杭州分行生产小程序(微信内搜索“数字京杭”可验证),负责小程序、H5、Vue 管理后台与 Java 服务端的全栈开发。</p>
  <div class="proj-stack"><span class="stack-label">技术栈</span><span class="tag">Java / Spring Boot</span><span class="tag">MySQL / Redis</span><span class="tag">Vue 2 / Element UI</span><span class="tag">uni-app / 微信小程序</span><span class="tag">H5</span></div>

  <div class="stat-row">
    <div class="stat"><b>2 万+</b><span>服务用户</span></div>
    <div class="stat"><b>4 端</b><span>小程序 + H5 + Vue 后台 + Java 服务端</span></div>
    <div class="stat"><b>多期</b><span>运营活动上线与迭代</span></div>
    <div class="stat"><b>可验证</b><span>微信内搜索“数字京杭”</span></div>
  </div>

  <h3>设计要点</h3>
  <div class="point-grid">
    <div class="point"><h4>业务与运营</h4><p>权益领取、营销活动等运营功能及配套管理后台配置审核,支撑分行多期活动上线及后续迭代维护。</p></div>
    <div class="point"><h4>Token 鉴权与请求签名</h4><p>会话密钥签名、Token 失效检测与静默刷新、并发请求排队重放、敏感字段加密与接口白名单;完成渗透漏洞修复与未登录接口审计。</p></div>
    <div class="point"><h4>行方门户集成</h4><p>Vue 管理后台以 iframe 集成至分行统一门户,基于门户用户标识与加密请求头完成登录态、用户身份和权限桥接,动态菜单、免二次登录。</p></div>
    <div class="point"><h4>全栈交付</h4><p>从小程序前端到 Java 服务端一人贯通,接口契约、鉴权与数据模型无交接损耗。</p></div>
  </div>
</section>

<section id="methodology" class="proj-sec">
  <div class="proj-head"><span class="proj-idx">→</span><h2>方法论与本站:第 4 个代表项目</h2></div>
  <p class="proj-lead">简历中的第 4 个代表项目——<strong>BDLH Agent 工程化与评测平台(Sentinel / Touchstone)</strong>,独立开发,2026.07 至今——就是本站。金融系统与 Agent 工程共享同一套立场:<strong>模型提议、代码裁决</strong>;生产系统里验证过的边界设计,延伸为本站要回答的实验问题:</p>
  <table class="map-tbl">
    <thead><tr><th class="map-src">生产系统实践</th><th style="width:40px"></th><th>本站 Agent 工程问题</th></tr></thead>
    <tbody>
      <tr><td class="map-src"><b>盯市补保</b>:数字永远取自定时任务落库结果,模型只写文案</td><td class="map-arrow">→</td><td>治理层:权限与只读边界由代码强制执行,模型不可越权</td></tr>
      <tr><td class="map-src"><b>Outbox 可靠消息</b>:至少一次投递 + 幂等消费</td><td class="map-arrow">→</td><td>Agent 任务的唤醒去重与重复执行防护</td></tr>
      <tr><td class="map-src"><b>银行结果补查</b>:超时 ≠ 失败,补查收敛终态</td><td class="map-arrow">→</td><td>评测的可复算:结果必须能回溯、能重验</td></tr>
    </tbody>
  </table>
  <div class="closing-links">
    <a class="closing-link" href="/overview/">系统总览 →</a>
    <a class="closing-link" href="/results/">实验结果 →</a>
    <a class="closing-link" href="/system/">执行逻辑 →</a>
  </div>
</section>`,
};

// ── 生成 ─────────────────────────────────────────────────────────────────

const ALL_PAGES = [HOME, RESULTS, EVIDENCE, EVIDENCE_RUN, SYSTEM, METHODOLOGY, WORK];

export async function generateSite({ only } = {}) {
  // only:逗号分隔的页面 path 白名单,用于安全重生成指定产物页。
  const pages = only && only.length ? ALL_PAGES.filter((page) => only.includes(page.path)) : ALL_PAGES;
  let count = 0;
  for (const page of pages) {
    const target = path.join(PUBLIC, page.path);
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, shell(page), "utf8");
    count += 1;
  }
  return count;
}

export { shell, NAV };

const isCli = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isCli) {
  const onlyFlag = process.argv.indexOf("--only");
  const only = onlyFlag > -1 ? String(process.argv[onlyFlag + 1] || "").split(",").map((x) => x.trim()).filter(Boolean) : undefined;
  generateSite({ only })
    .then((count) => console.log(`generated ${count} pages under web/public`))
    .catch((error) => {
      console.error(error);
      process.exitCode = 1;
    });
}
