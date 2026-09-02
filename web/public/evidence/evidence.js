/* 原始证据页(全站第二核心页):索引 + 单次运行 11 段证据链。
 * 索引支持批次/实验/用例/变体/结果/失败原因六维筛选与分页;
 * 详情按实际发生顺序展示公开证据链,缺失字段显示「未记录」;
 * 只有复制按钮,没有下载、复现或重新运行入口;不展示模型内部思维链。 */
(function () {
  "use strict";

  var S = window.SITE;
  var SC = window.SHOWCASE;
  var PAGE_SIZE = 20;

  function el(id) { return document.getElementById(id); }

  /* 机器键 → 中文显示(适配层 SC.zh;未知键原样) */
  function zh(v) { return SC.zh ? SC.zh(v) : v; }
  function chip(ok) {
    if (ok === true) return '<span class="st st-ok">通过</span>';
    if (ok === false) return '<span class="st st-bad">未通过</span>';
    return '<span class="st st-muted">未记录</span>';
  }
  function orUnset(v) { return v == null || v === "" ? '<span class="txt-muted">未记录</span>' : S.esc(v); }

  /* ── 索引页 ───────────────────────────────────────────────────────── */

  var rows = [];        // 视图行(SC.runView + 批次信息)
  var filters = { batch: "", experiment: "", case: "", variant: "", result: "", failure: "" };
  var page = 1;

  function resultKey(v) {
    if (v.validity === "INVALID" || v.status === "INVALID") return "invalid";
    if (v.success === true) return "success";
    if (v.success === false || v.status === "FAILED") return "failed";
    return "other";
  }
  var RESULT_LABELS = { success: "成功", failed: "失败", invalid: "无效", other: "未判定/其他" };

  function filtered() {
    return rows.filter(function (v) {
      if (filters.batch && v.batchId !== filters.batch) return false;
      if (filters.experiment && v.experiment !== filters.experiment) return false;
      if (filters.case && v.caseId !== filters.case) return false;
      if (filters.variant && v.variant !== filters.variant) return false;
      if (filters.result && resultKey(v) !== filters.result) return false;
      if (filters.failure && (v.failure || "") !== filters.failure) return false;
      return true;
    });
  }

  function fillSelect(select, values, current, allLabel, zhFn) {
    var html = '<option value="">' + allLabel + "</option>";
    values.forEach(function (v) {
      var text = zhFn ? zhFn(v) : v;
      html += '<option value="' + S.esc(v) + '"' + (v === current ? " selected" : "") + ">" + S.esc(text) + "</option>";
    });
    select.innerHTML = html;
  }
  function unique(list) {
    var seen = {};
    var out = [];
    list.forEach(function (v) {
      if (v && !seen[v]) { seen[v] = 1; out.push(v); }
    });
    return out;
  }

  function syncQuery() {
    var params = new URLSearchParams();
    for (var k in filters) {
      if (filters[k]) params.set(k, filters[k]);
    }
    if (page > 1) params.set("page", String(page));
    var q = params.toString();
    history.replaceState(null, "", q ? "?" + q : location.pathname);
  }

  function renderTable() {
    var list = filtered();
    var pages = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
    if (page > pages) page = pages;
    var slice = list.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
    var head = "<thead><tr><th>运行编号</th><th>用例</th><th>实验变体</th><th>状态</th><th>判定</th><th class=\"num\">步骤数</th><th class=\"num\">耗时</th><th>发生时间</th><th></th></tr></thead>";
    var body = slice.map(function (v) {
      var judged = v.success === true ? '<span class="st st-ok">成功</span>'
        : v.success === false ? '<span class="st st-bad">失败</span>'
        : '<span class="st st-muted">未记录</span>';
      return "<tr>" +
        '<td class="code"><span class="hash">' + S.esc(v.runId) + "</span></td>" +
        "<td><code>" + S.esc(zh(v.caseId)) + "</code></td>" +
        "<td>" + orUnset(zh(v.variant)) + "</td>" +
        "<td>" + S.statusChip(v.status, v.validity) + "</td>" +
        "<td>" + judged + "</td>" +
        '<td class="num">' + S.fmtInt(v.stepCount) + "</td>" +
        '<td class="num">' + S.fmtMs(v.durationMs) + "</td>" +
        "<td>" + S.fmtTime(v.startedAt) + "</td>" +
        '<td><a href="/evidence/run/?id=' + encodeURIComponent(v.runId) + '">查看证据链</a></td>' +
        "</tr>";
    }).join("");
    el("evidenceTable").innerHTML =
      '<div class="tbl-scroll"><table class="tbl">' + head + "<tbody>" + body + "</tbody></table></div>" +
      '<p class="note">共 ' + S.fmtInt(list.length) + " 条(全部公开发布运行 " + S.fmtInt(rows.length) + " 条);步骤数 = 模型步 + 工具步;发生时间字段缺失时显示「未记录」。</p>";
    el("evidencePager").innerHTML =
      '<button type="button" id="pgPrev"' + (page <= 1 ? " disabled" : "") + ">上一页</button>" +
      "<span>第 " + page + " / " + pages + " 页</span>" +
      '<button type="button" id="pgNext"' + (page >= pages ? " disabled" : "") + ">下一页</button>";
    var prev = el("pgPrev");
    var next = el("pgNext");
    if (prev) prev.addEventListener("click", function () { page -= 1; syncQuery(); renderTable(); });
    if (next) next.addEventListener("click", function () { page += 1; syncQuery(); renderTable(); });
  }

  function initFiltersSelects() {
    fillSelect(el("eBatch"), unique(rows.map(function (v) { return v.batchId; })), filters.batch, "全部批次");
    fillSelect(el("eExperiment"), unique(rows.map(function (v) { return v.experiment; })), filters.experiment, "全部实验");
    fillSelect(el("eCase"), unique(rows.map(function (v) { return v.caseId; })), filters.case, "全部用例", zh);
    fillSelect(el("eVariant"), unique(rows.map(function (v) { return v.variant; })), filters.variant, "全部变体", zh);
    fillSelect(el("eResult"), Object.keys(RESULT_LABELS).map(function (k) { return k; }), filters.result, "全部结果");
    fillSelect(el("eFailure"), unique(rows.map(function (v) { return v.failure; })), filters.failure, "全部/无失败");
    var resultSel = el("eResult");
    var map = {};
    for (var k in RESULT_LABELS) map[k] = RESULT_LABELS[k];
    Array.prototype.forEach.call(resultSel.options, function (opt) {
      if (opt.value) opt.textContent = map[opt.value];
    });
    ["eBatch", "eExperiment", "eCase", "eVariant", "eResult", "eFailure"].forEach(function (id) {
      el(id).addEventListener("change", function () {
        filters.batch = el("eBatch").value;
        filters.experiment = el("eExperiment").value;
        filters.case = el("eCase").value;
        filters.variant = el("eVariant").value;
        filters.result = el("eResult").value;
        filters.failure = el("eFailure").value;
        page = 1;
        syncQuery();
        renderTable();
      });
    });
  }

  async function initIndex() {
    var params = new URLSearchParams(location.search);
    filters.batch = params.get("batch") || "";
    filters.case = params.get("case") || "";
    filters.variant = params.get("variant") || "";
    if (params.get("status")) filters.result = params.get("status") === "invalid" ? "invalid" : params.get("status") === "failed" ? "failed" : "";
    page = Math.max(1, parseInt(params.get("page") || "1", 10) || 1);
    var published = await SC.loadPublished();
    published.forEach(function (d) {
      var zh = function (v) { return SC.zh ? SC.zh(v) : v; };
      var experiment = d.batch.experiment_type === "context-strategy" ? "上下文策略对照" : zh(d.batch.experiment_name || d.batch.experiment_type);
      d.runs.forEach(function (run) {
        var v = SC.runView(run, d.batch);
        v.experiment = experiment;
        rows.push(v);
      });
    });
    if (rows.length === 0) {
      el("evidenceEmpty").hidden = false;
      el("evidenceApp").hidden = true;
      return;
    }
    el("evidenceEmpty").hidden = true;
    el("evidenceApp").hidden = false;
    initFiltersSelects();
    renderTable();
  }

  /* ── 单次运行证据链(11 段,按实际发生顺序) ──────────────────────── */

  function section(no, title, bodyHtml, open) {
    return '<details class="chain-section"' + (open ? " open" : "") + ">" +
      '<summary><span class="chain-no">' + no + "</span>" + S.esc(title) + "</summary>" +
      '<div class="chain-body">' + bodyHtml + "</div></details>";
  }

  function kvTable(pairs) {
    return '<table class="kv"><tbody>' +
      pairs.map(function (p) { return "<tr><th>" + p[0] + "</th><td>" + p[1] + "</td></tr>"; }).join("") +
      "</tbody></table>";
  }

  function timelineHtml(run) {
    var s = run.sections || {};
    var items = []
      .concat((s.model_steps || []).map(function (m) { return { kind: "model", seq: m.seq, m: m }; }))
      .concat((s.tool_results || []).map(function (t) { return { kind: "tool", seq: t.seq, t: t }; }))
      .sort(function (a, b) { return (a.seq || 0) - (b.seq || 0); });
    if (items.length === 0) return '<div class="placeholder-block">未记录任何模型或工具步骤。</div>';
    return '<ul class="timeline">' + items.map(function (it) {
      if (it.kind === "model") {
        return '<li class="tl-model"><div class="tl-head"><span class="tl-seq">#' + it.seq + "</span>" +
          '<span class="tl-title">模型决策</span>' +
          '<span class="tl-meta">' + S.esc(it.m.decision || "未记录") + (it.m.latency_ms != null ? " · " + S.fmtMs(it.m.latency_ms) : "") + "</span></div>" +
          '<div class="tl-body">决策依据摘要:仅记录可观察行为(是否调用工具/最终回答),不含模型内部思维链。</div></li>';
      }
      var t = it.t;
      var bad = t.status && t.status !== "SUCCESS";
      return '<li class="tl-tool' + (bad ? " tl-bad" : "") + '"><div class="tl-head"><span class="tl-seq">#' + it.seq + "</span>" +
        '<span class="tl-title">工具调用 <code>' + S.esc(t.name) + "</code></span>" +
        '<span class="tl-meta">' + S.esc(t.status || "未记录") + (t.audit_code ? " · 审计码 " + S.esc(t.audit_code) : "") + (t.duration_ms != null ? " · " + S.fmtMs(t.duration_ms) : "") + "</span></div>" +
        '<div class="tl-body">返回摘要:' + (t.summary ? S.esc(JSON.stringify(t.summary).slice(0, 200)) : "未记录") +
        (t.source ? " · 数据来源 " + S.esc(t.source) : "") + "</div></li>";
    }).join("") + "</ul>";
  }

  function toolTableHtml(run) {
    var tools = (run.sections && run.sections.tool_results) || [];
    if (tools.length === 0) return '<div class="placeholder-block">本运行无工具调用记录。</div>';
    var head = "<thead><tr><th>序号</th><th>工具名</th><th>参数</th><th>状态</th><th>审计码</th><th class=\"num\">耗时</th><th>返回摘要</th><th>数据来源</th><th>数据时点</th></tr></thead>";
    var body = tools.map(function (t) {
      return "<tr><td>" + S.fmtInt(t.seq) + "</td><td><code>" + S.esc(t.name) + "</code></td>" +
        "<td>" + (t.arguments != null ? "<code>" + S.esc(JSON.stringify(t.arguments)) + "</code>" : '<span class="txt-muted">未记录</span>') + "</td>" +
        "<td>" + (t.status === "SUCCESS" ? '<span class="txt-ok">' + S.esc(t.status) + "</span>" : '<span class="txt-bad">' + S.esc(t.status || "未记录") + "</span>") + "</td>" +
        "<td>" + orUnset(t.audit_code) + "</td>" +
        '<td class="num">' + (t.duration_ms != null ? S.fmtMs(t.duration_ms) : "未记录") + "</td>" +
        "<td>" + (t.summary ? S.esc(JSON.stringify(t.summary).slice(0, 160)) : '<span class="txt-muted">未记录</span>') + "</td>" +
        "<td>" + orUnset(t.source) + "</td>" +
        "<td>" + S.fmtTime(t.data_time) + "</td></tr>";
    }).join("");
    return '<div class="tbl-scroll"><table class="tbl">' + head + "<tbody>" + body + "</tbody></table></div>";
  }

  function governanceHtml(run) {
    var checks = (run.sections && run.sections.code_decisions) || [];
    var codes = (run.sections && run.sections.final_result && run.sections.final_result.audit_codes) || [];
    var body = checks.length
      ? checks.map(function (c) {
        return "<tr><td>" + S.fmtInt(c.seq) + "</td><td>" + (c.allowed ? '<span class="st st-ok">放行</span>' : '<span class="st st-bad">拦截</span>') + "</td><td>" + orUnset(c.audit_code) + "</td></tr>";
      }).join("")
      : "<tr><td colspan=\"3\" class=\"txt-muted\">未记录治理检查(旧版工件可能未投影此段)。</td></tr>";
    return '<div class="tbl-scroll"><table class="tbl"><thead><tr><th>序号</th><th>判定</th><th>审计码</th></tr></thead><tbody>' + body + "</tbody></table></div>" +
      (codes.length ? "<p>最终输出携带的审计码:" + codes.map(function (c) { return "<code>" + S.esc(c) + "</code>"; }).join(" ") + "</p>" : "");
  }

  function judgmentHtml(run) {
    var s = run.sections || {};
    var checks = s.output_checks || [];
    var j = (s.final_result && s.final_result.judgment) || null;
    var checkRows = checks.length
      ? checks.map(function (c) {
        var labelMap = { tool_correct: "工具选择", number_grounding: "数字接地", c1_compliance: "高危操作合规(C-1)", c2_compliance: "专业建议合规(C-2)" };
        return "<tr><td>" + S.esc(labelMap[c.check] || c.check) + "</td><td>" + chip(c.passed) + "</td><td>" + (c.detail ? S.esc(c.detail) : '<span class="txt-muted">—</span>') + "</td></tr>";
      }).join("")
      : "<tr><td colspan=\"3\" class=\"txt-muted\">未记录断言明细。</td></tr>";
    var summary = j
      ? kvTable([
        ["任务成功", chip(j.task_success)],
        ["工具选择正确", chip(j.tool_correct)],
        ["数字接地", chip(j.number_grounded)],
      ])
      : '<p class="txt-muted">判定汇总未记录。</p>';
    return summary + '<div class="tbl-scroll"><table class="tbl"><thead><tr><th>断言</th><th>结果</th><th>失败原因/明细</th></tr></thead><tbody>' + checkRows + "</tbody></table></div>" +
      '<p class="note">断言由机械判官(fixed-rules-v1,代码断言)产生,无 LLM 判官;指标口径见「测试逻辑」页。</p>';
  }

  function configHtml(run) {
    var e = run.experiment || {};
    var base = kvTable([
      ["执行底座", orUnset(e.agent_mode)],
      ["上下文策略", e.context_strategy ? "<code>" + S.esc(e.context_strategy) + "</code>" : '<span class="txt-muted">未记录</span>'],
      ["模型", orUnset(e.model)],
      ["重复序号", e.repeat_index != null ? S.fmtInt(e.repeat_index) : "未记录"],
    ]);
    var c = run.config;
    if (!c) {
      return base + '<p class="note">完整运行配置快照未随本工件发布(旧版工件);配置以批次报告的固定条件为准。</p>';
    }
    var rows = [];
    if (c.model) {
      ["provider", "model_id", "temperature_requested", "temperature_effective", "top_p_requested", "top_p_effective", "max_output_tokens", "tool_choice", "parallel_tool_calls"].forEach(function (k) {
        if (c.model[k] != null) rows.push([k, S.esc(String(c.model[k]))]);
      });
    }
    if (c.limits) {
      ["max_agent_steps", "max_tool_calls", "max_calls_per_tool", "agent_timeout_seconds", "tool_timeout_seconds"].forEach(function (k) {
        if (c.limits[k] != null) rows.push(["limits." + k, S.esc(String(c.limits[k])) + (k === "agent_timeout_seconds" && Number(c.limits[k]) === 0 ? "(0 = 不限时)" : "")]);
      });
    }
    ["execution_engine", "tool_delivery", "governance_profile", "fixture_version", "prompt_version", "judge_version"].forEach(function (k) {
      if (c[k] != null) rows.push([k, S.esc(String(c[k]))]);
    });
    return base + (rows.length ? kvTable(rows) : "") +
      (run.config_hash ? '<p class="note">配置哈希(config_hash):<span class="hash">' + S.esc(run.config_hash) + "</span>;同配置必同哈希。</p>" : "");
  }

  function contextHtml(run) {
    var c = (run.sections && run.sections.context) || null;
    if (!c) return '<div class="placeholder-block">本运行未记录上下文构建摘要(非上下文实验或旧版工件)。</div>';
    var counts = c.item_counts || {};
    return kvTable([
      ["策略", orUnset(c.strategy)],
      ["原始 token", c.raw_tokens != null ? S.fmtInt(c.raw_tokens) : "未记录"],
      ["工作 token", c.working_tokens != null ? S.fmtInt(c.working_tokens) : "未记录"],
      ["强制项全保留", c.required_retained == null ? '<span class="st st-muted">未记录</span>' : chip(c.required_retained)],
      ["条目计数", counts && (counts.retained != null || counts.compressed != null)
        ? "保留 " + S.fmtInt(counts.retained) + " · 压缩 " + S.fmtInt(counts.compressed) + " · 引用 " + S.fmtInt(counts.referenced) + " · 隔离 " + S.fmtInt(counts.isolated) + " · 省略 " + S.fmtInt(counts.omitted)
        : "未记录"],
    ]);
  }

  function renderRun(run) {
    var s = run.sections || {};
    var input = s.fixed_input || {};
    var cost = s.cost || {};
    var html =
      '<p class="page-lead">以下为该运行的公开证据链,按实际发生顺序排列。展示的是可审计执行记录与决策依据摘要,不含模型内部思维链;敏感字段经发布白名单脱敏。</p>' +
      section("01", "运行身份与来源",
        kvTable([
          ["运行编号", '<span class="hash">' + S.esc(run.run_id) + '</span> <button type="button" class="copy-btn" id="copyRunId">复制</button>'],
          ["所属批次", '<a href="/results/?batch=' + encodeURIComponent(run.batch_id) + '"><span class="hash">' + S.esc(run.batch_id) + "</span></a>(结果页)"],
          ["用例", "<code>" + S.esc(run.case_id) + "</code>"],
          ["运行状态", S.statusChip(run.status, run.validity)],
          ["发生时间", S.fmtTime(run.started_at)],
        ]) +
        '<p class="note">来源:发布校验后的公开快照(runs/' + S.esc(run.run_id) + '.json);工件哈希在发布时复算通过。</p>', true) +
      section("02", "固定任务输入",
        kvTable([
          ["任务消息", S.esc(input.message || "") || '<span class="txt-muted">未记录</span>'],
          ["场景", orUnset(input.scene)],
          ["登录态", input.authenticated == null ? "未记录" : input.authenticated ? "已登录" : "未登录"],
          ["历史轮数", input.history_count != null ? S.fmtInt(input.history_count) : "未记录"],
          ["标准工具范围", Array.isArray(input.allowed_tools) && input.allowed_tools.length ? input.allowed_tools.map(function (t) { return "<code>" + S.esc(t) + "</code>"; }).join(" ") : "未记录(按发布口径隐藏)"],
        ]), true) +
      section("03", "实际生效的运行配置", configHtml(run), true) +
      section("04", "上下文构建摘要", contextHtml(run), true) +
      section("05", "Agent 执行时间线", timelineHtml(run), true) +
      section("06", "逐次工具调用", toolTableHtml(run), true) +
      section("07", "治理判定与拦截", governanceHtml(run), true) +
      section("08", "最终输出",
        (s.final_result && s.final_result.answer_excerpt)
          ? "<blockquote style=\"margin:8px 0;padding:10px 16px;border-left:3px solid var(--line);background:var(--bg-soft)\">" + S.esc(s.final_result.answer_excerpt) + "</blockquote><p class=\"note\">输出摘录(护栏修正后);完整答案不随公开工件发布。</p>"
          : '<div class="placeholder-block">未记录最终输出。</div>', true) +
      section("09", "评测断言", judgmentHtml(run), true) +
      section("10", "遥测(token / 耗时)",
        kvTable([
          ["总耗时", cost.duration_ms != null ? S.fmtMs(cost.duration_ms) : "未记录"],
          ["上下文构建", cost.context_ms != null ? S.fmtMs(cost.context_ms) : "未记录"],
          ["模型调用累计", cost.llm_ms != null ? S.fmtMs(cost.llm_ms) : "未记录"],
          ["工具执行累计", cost.tool_ms != null ? S.fmtMs(cost.tool_ms) : "未记录"],
          ["prompt token", cost.prompt_tokens != null ? S.fmtInt(cost.prompt_tokens) : "未记录"],
          ["completion token", cost.completion_tokens != null ? S.fmtInt(cost.completion_tokens) : "未记录"],
          ["压缩 token", cost.compression_tokens != null ? S.fmtInt(cost.compression_tokens) : "未记录"],
          ["token 口径", cost.tokens_estimated == null ? "未记录" : cost.tokens_estimated ? "估算" : "实测"],
        ]) +
        '<p class="note">遥测字段只如实记录,不参与对错判定。</p>', true) +
      section("11", "原始 JSON(公开白名单投影)",
        '<p><button type="button" class="copy-btn" id="copyJson">复制完整 JSON</button>' +
        ' <span class="txt-muted">仅复制;不提供下载或重新运行。</span></p>' +
        "<pre><code>" + S.esc(JSON.stringify(run, null, 2)) + "</code></pre>" +
        '<p class="note">以上 JSON 即本页数据的唯一来源;系统提示词、密钥、私有账户数据与金标答案不在公开字段白名单内。</p>', false);
    el("runDetail").innerHTML = html;
    var copyRun = el("copyRunId");
    if (copyRun) copyRun.addEventListener("click", function () { S.copyText(run.run_id, copyRun); });
    var copyJson = el("copyJson");
    if (copyJson) copyJson.addEventListener("click", function () { S.copyText(JSON.stringify(run, null, 2), copyJson); });
    document.title = "运行 " + run.run_id.slice(0, 8) + " · 证据链 · Touchstone";
  }

  async function initRun() {
    var params = new URLSearchParams(location.search);
    var id = params.get("id") || "";
    var box = el("runDetail");
    var run = id ? await SC.loadRun(id) : null;
    if (!run) {
      box.innerHTML = '<div class="empty-state panel"><h2>未找到该运行的公开证据</h2>' +
        "<p>运行编号无效,或该运行不属于任何已发布的正式批次(调试与匿名运行不公开发布)。</p>" +
        '<p><a href="/evidence/">← 返回证据索引</a></p></div>';
      return;
    }
    renderRun(run);
  }

  async function init() {
    if (el("evidenceTable")) await initIndex();
    else if (el("runDetail")) await initRun();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
