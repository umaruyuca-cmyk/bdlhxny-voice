/* 展示层共享渲染函数（纯函数，无 DOM 依赖，可被 Node 测试加载）。
 * 约定：null 一律渲染为「未运行」；未过有效门槛的批次不做结论性文案。 */
(function (global) {
  "use strict";

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"]/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
    });
  }

  function pct(value) {
    return value == null ? "未运行" : Math.round(value * 100) + "%";
  }

  function num(value, suffix) {
    return value == null ? "未运行" : String(value) + (suffix || "");
  }

  /** 首页状态：无数据 / 最新批次未达门槛 / 正式批次。 */
  function homeState(index) {
    if (!index || !index.latest_batch) return { kind: "nodata" };
    var latest = index.latest_batch;
    if (latest.is_formal && index.formal_batches && index.formal_batches.length > 0) {
      return { kind: "formal", batch: latest };
    }
    return { kind: "gated", batch: latest };
  }

  function renderHomeBanner(state) {
    if (state.kind === "nodata") {
      return '<div class="placeholder-block">等待发布数据：尚无批次发布。发布流程见<a href="/docs/">架构讲解</a>——项目所有者运行对照批次后经发布脚本投影到 showcase-data。</div>';
    }
    if (state.kind === "formal") {
      return '<div class="note"><strong>最新正式批次</strong>：' + esc(state.batch.batch_id.slice(0, 8)) +
        " · " + esc(state.batch.model) + " · " + esc(state.batch.generated_at) + " · commit " + esc(state.batch.git_commit) + "</div>";
    }
    var b = state.batch;
    return '<div class="note"><strong>最新批次未达有效样本门槛（非正式）</strong>：' + esc(b.validity_gate && b.validity_gate.reason || "有效性未分类") +
      '。批次为 ' + esc(b.model) + " · " + esc(b.generated_at) + " · commit " + esc(b.git_commit) +
      '，可前往<a href="/showcase/results">对照结果</a>查看过程数据。</div>';
  }

  function renderStatCards(state, report) {
    // 上下文压缩对照批次:渲染策略摘要卡(工作 token 与强制项保留)
    if (state.kind === "formal" && isContextBatch(report)) {
      var ctxRows = (report.groups || []).map(function (g) {
        var m = g.metrics || {};
        return '<div class="stat-val-row">' + esc(g.label) + "：工作上下文 " + num(m.working_tokens) +
          " token · 强制项保留 " + pct(m.constraint_retention_rate) + " · 事实召回 " + pct(m.fact_recall_rate) + "</div>";
      }).join("");
      return '<div class="stat-card"><div class="stat-label">上下文压缩对照（最新正式批次）</div><div class="stat-vals">' +
        (ctxRows || '<span class="stat-now">未运行</span>') +
        '</div><div class="stat-hint">策略逐项对比见<a href="/context/results">用例结果</a></div></div>';
    }
    var cards = [
      { label: "工具选择准确率", group: "full-system", field: "tool_selection_rate", better: "high" },
      { label: "数字幻觉率", group: "full-system", field: "number_hallucination_rate", better: "low" },
      { label: "无效运行数", value: null, hint: "无效运行(限流/余额/服务不可用)单列,不进分母" }
    ];
    if (state.kind !== "formal" || !report) {
      return cards.map(function (c) {
        return '<div class="stat-card"><div class="stat-label">' + c.label + '</div><div class="stat-vals"><span class="stat-now">未运行</span></div><div class="stat-hint">正式批次发布后展示</div></div>';
      }).join("");
    }
    var byKey = {};
    (report.groups || []).forEach(function (g) { byKey[g.key] = g; });
    var base = byKey["baseline-tool-calling"], full = byKey["full-system"];
    var invalidTotal = (report.groups || []).reduce(function (sum, g) { return sum + (g.invalid_runs || 0); }, 0);
    return cards.map(function (c) {
      var html = '<div class="stat-card"><div class="stat-label">' + c.label + "</div>";
      if (c.group) {
        var b = base && base.metrics[c.field], t = full && full.metrics[c.field];
        html += '<div class="stat-vals"><span class="stat-base">基线 ' + pct(b) + '</span><span class="stat-arrow">→</span><span class="stat-now">' + pct(t) + "</span></div>";
      } else {
        html += '<div class="stat-vals"><span class="stat-now">' + num(invalidTotal) + "</span></div>";
      }
      html += '<div class="stat-hint">' + esc(c.hint || "完整工程模式 vs 裸 tool calling") + "</div></div>";
      return html;
    }).join("");
  }

  /** 指标定义（评测文档 §7），表头 <details> 就地展开。 */
  var METRIC_DEFS = [
    { field: "tool_selection_rate", label: "工具选择准确率", def: "实际成功工具集合与期望工具集合一致的比例", fmt: pct },
    { field: "hallucination_rate", label: "幻觉工具率", def: "调用了当次工具目录中不存在名称的比例", fmt: pct },
    { field: "invisible_tool_rate", label: "不可见工具调用率", def: "调用了当次不可见(被可见集收窄排除)工具名称的比例", fmt: pct },
    { field: "forbidden_leak_rate", label: "越权泄漏率", def: "未授权运行成功访问受限工具或数据的比例", fmt: pct },
    { field: "number_hallucination_rate", label: "数字幻觉率", def: "答案中的事实性数字无法在工具结果或数据快照中找到的比例", fmt: pct },
    { field: "c1_violation_rate", label: "C-1 违规率", def: "违反交易边界语义（C-1）的比例", fmt: pct },
    { field: "c2_violation_rate", label: "C-2 违规率", def: "违反适当性结论口径（C-2）的比例", fmt: pct },
    { field: "mean_rounds", label: "平均轮次", def: "每个有效运行的模型调用轮次均值", fmt: function (v) { return num(v == null ? null : Number(v).toFixed(1)); } },
    { field: "mean_tokens", label: "平均 token", def: "prompt + completion 的均值（估算口径运行数见分场景明细）", fmt: function (v) { return num(v); } },
    { field: "median_duration_ms", label: "p50 时长", def: "总时长中位数", fmt: function (v) { return num(v, "ms"); } },
    { field: "p95_duration_ms", label: "p95 时长", def: "总时长 95 分位", fmt: function (v) { return num(v, "ms"); } },
    { group: "通用目录专项（GT-7；「未运行」=该组无对应金标或调用，不进分母）" },
    { field: "selection_precision_mean", label: "选择精确率", def: "成功调用集合中命中金标的比例(均值)", fmt: pct },
    { field: "selection_recall_mean", label: "选择召回率", def: "金标工具被成功调用的比例(均值)", fmt: pct },
    { field: "missed_rate", label: "漏选率", def: "存在金标工具未被调用的运行比例", fmt: pct },
    { field: "extra_call_rate", label: "多余调用率", def: "成功调用了金标之外工具的运行比例", fmt: pct },
    { field: "forbidden_attempt_rate", label: "禁止尝试率", def: "尝试调用题目标注不存在工具的运行比例", fmt: pct },
    { field: "params_complete_rate", label: "参数完整率", def: "调用实参覆盖 schema 必填项的比例", fmt: pct },
    { field: "params_type_valid_rate", label: "参数类型正确率", def: "调用实参通过 schema 校验的比例", fmt: pct },
    { field: "params_factual_rate", label: "参数事实一致率", def: "实参与金标期望参数值一致的比例", fmt: pct },
    { field: "duplicate_call_rate", label: "重复调用率", def: "存在同工具同参数重复调用的运行比例", fmt: pct },
    { field: "order_correct_rate", label: "调用顺序正确率", def: "金标调用序完全一致的比例", fmt: pct },
    { field: "unconfirmed_write_rate", label: "未确认写入率", def: "题面未给确认仍调用写入类工具的运行比例(只判不拦)", fmt: pct },
    { field: "write_for_query_rate", label: "查询误用写入率", def: "查询类问题调用了写入类工具的运行比例", fmt: pct },
    { field: "search_hit_rate", label: "检索命中率", def: "检索后调齐金标工具的比例(v1 按调用记录近似)", fmt: pct },
    { field: "invalid_search_rate", label: "无效检索率", def: "不必要时仍调用 search_tools 的运行比例", fmt: pct },
    { field: "duplicate_search_rate", label: "重复检索率", def: "多次调用 search_tools 的运行比例", fmt: pct },
    { field: "search_then_correct_rate", label: "检索后选择准确率", def: "发生检索且工具选择正确的比例", fmt: pct },
    { field: "mean_tools_schema_tokens", label: "工具定义 token(均值)", def: "当轮可见工具 schema 序列化后的 token 估算均值", fmt: function (v) { return num(v); } }
  ];

  var OUTCOME_DEFS = [
    { key: "win", label: "获胜", def: "完整模式正确且基线错误的题数" },
    { key: "regress", label: "退化", def: "基线正确且完整模式错误的题数" },
    { key: "tie", label: "平局", def: "双方都正确的题数" },
    { key: "both_fail", label: "双方失败", def: "双方都错误的题数" },
    { key: "invalid", label: "无效", def: "有效性分类未实现（P3-1）前的诚实占位", def2: null }
  ];

  /** 组指标总表：只列各组实测值，不做组间结论（有效性未分类时尤甚）。 */
  function renderGroupTable(report) {
    if (!report || !report.groups || report.groups.length === 0) {
      return '<div class="placeholder-block">未运行。</div>';
    }
    var head = '<tr><th>指标</th>' + report.groups.map(function (g) {
      return "<th>" + esc(g.label) + '<details class="metric-def"><summary>定义</summary><p>' +
        "组键 " + esc(g.key) + "；有效 " + g.valid_runs + " / 无效 " + g.invalid_runs + " 次运行</p></details></th>";
    }).join("") + "</tr>";
    var rows = METRIC_DEFS.map(function (m) {
      if (m.group) {
        return '<tr class="metric-group-row"><td colspan="' + (report.groups.length + 1) + '">' + esc(m.group) + "</td></tr>";
      }
      return "<tr><td>" + esc(m.label) + '<details class="metric-def"><summary>定义</summary><p>' + esc(m.def) +
        "</p></details></td>" + report.groups.map(function (g) {
          return "<td>" + m.fmt(g.metrics ? g.metrics[m.field] : null) + "</td>";
        }).join("") + "</tr>";
    }).join("");
    return "<table><thead>" + head + "</thead><tbody>" + rows + "</tbody></table>";
  }

  function renderOutcomeBadges(report) {
    if (!report || !report.outcome_counts) return '<div class="placeholder-block">未运行。</div>';
    return OUTCOME_DEFS.map(function (o) {
      var v = report.outcome_counts[o.key];
      return '<span class="outcome-badge outcome-' + o.key + '" title="' + esc(o.def) + '">' +
        esc(o.label) + " <strong>" + num(v) + "</strong></span>";
    }).join(" ");
  }

  /** 分场景明细：每题每组的 correct/total，可筛场景。 */
  function renderCaseRows(report, categoryFilter) {
    var cases = (report && report.cases) || [];
    var groups = (report && report.groups) || [];
    var rows = cases
      .filter(function (c) { return !categoryFilter || c.category === categoryFilter; })
      .map(function (c) {
        var cells = groups.map(function (g) {
          var agg = c.groups && c.groups[g.key];
          if (!agg) return "<td>未运行</td>";
          var est = agg.estimated_token_runs > 0 ? ' <span class="est-flag" title="其中含 chars/4 估算口径的运行数">≈' + agg.estimated_token_runs + "</span>" : "";
          return "<td>" + agg.correct + "/" + agg.total + est + "</td>";
        }).join("");
        return "<tr><td>" + esc(c.id) + "</td><td>" + esc(c.category) + "</td><td>" + esc(c.message) + "</td>" + cells + "</tr>";
      }).join("");
    if (!rows) return '<tr><td colspan="' + (groups.length + 3) + '">该场景下没有已发布用例。</td></tr>';
    return rows;
  }

  function renderCaseTable(report, categoryFilter) {
    if (!report || !report.cases || report.cases.length === 0) return '<div class="placeholder-block">未运行。</div>';
    var groups = report.groups || [];
    var head = "<tr><th>题号</th><th>场景</th><th>问题</th>" +
      groups.map(function (g) { return "<th>" + esc(g.label) + "</th>"; }).join("") + "</tr>";
    return "<table><thead>" + head + "</thead><tbody>" + renderCaseRows(report, categoryFilter) + "</tbody></table>";
  }

  function categories(report) {
    var seen = {};
    ((report && report.cases) || []).forEach(function (c) { seen[c.category] = true; });
    return Object.keys(seen).sort();
  }

  var RUN_SECTION_TITLES = [
    ["fixed_input", "固定输入和受控变量"],
    ["context", "原始上下文与压缩结果"],
    ["visible_tools", "当次可见工具"],
    ["model_steps", "模型决策"],
    ["code_decisions", "代码允许或拒绝"],
    ["tool_results", "工具结果及来源"],
    ["output_checks", "输出检查"],
    ["final_result", "最终结果和评测"],
    ["cost", "时长、token 和成本"]
  ];

  var VALIDITY_LABELS = { VALID: "有效", INVALID: "无效", UNCLASSIFIED: "有效性未分类" };
  var STATUS_LABELS = {
    COMPLETE: "完成", FAILED: "失败", INVALID: "无效运行", CANCELLED: "已取消",
    PENDING_JUDGMENT: "待评测", NOT_RUN: "未运行"
  };

  function kv(pairs) {
    return '<dl class="run-kv">' + pairs.map(function (p) {
      return "<dt>" + p[0] + "</dt><dd>" + p[1] + "</dd>";
    }).join("") + "</dl>";
  }

  function listOrPending(items, render) {
    if (!items || items.length === 0) return '<p class="pending">未运行</p>';
    return '<ol class="run-steps">' + items.map(render).join("") + "</ol>";
  }

  /** 九段固定顺序渲染（评测文档 §11.3）；null 段渲染未运行。 */
  function renderRunDetail(run) {
    if (!run) return '<div class="placeholder-block">该运行尚未发布。</div>';
    var s = run.sections || {};
    var head = '<div class="run-head"><span class="run-badge status-' + esc(run.status) + '">' +
      esc(STATUS_LABELS[run.status] || run.status) + "</span>" +
      '<span class="run-badge validity-' + esc(run.validity) + '">' + esc(VALIDITY_LABELS[run.validity] || run.validity) + "</span>" +
      '<span class="run-meta">' + esc(run.experiment.agent_mode) + " · " + esc(run.experiment.model) +
      " · 第 " + esc(run.experiment.repeat_index) + " 次 · run " + esc(run.run_id) + "</span></div>";

    var body = RUN_SECTION_TITLES.map(function (pair) {
      var key = pair[0], title = pair[1], sec = s[key];
      var inner;
      if (key === "fixed_input" && sec) {
        inner = kv([
          ["问题", esc(sec.message)],
          ["场景", esc(sec.scene)],
          ["登录态", sec.authenticated ? "已登录用户" : "游客"],
          ["历史轮数", num(sec.history_count)],
          ["允许工具", sec.allowed_tools ? esc(sec.allowed_tools.join("、")) : "未运行"]
        ]);
      } else if (key === "context") {
        inner = !sec ? '<p class="pending">未运行</p>' : kv([
          ["策略", esc(sec.strategy)],
          ["原始 token", num(sec.raw_tokens)],
          ["工作 token", num(sec.working_tokens)],
          ["强制项保留", sec.required_retained == null ? "未运行" : sec.required_retained ? "是" : "否（本运行应判失败）"],
          ["条目计数", sec.item_counts ? "保留 " + num(sec.item_counts.retained) + " / 压缩 " + num(sec.item_counts.compressed) +
            " / 引用 " + num(sec.item_counts.referenced) + " / 隔离 " + num(sec.item_counts.isolated) +
            " / 省略 " + num(sec.item_counts.omitted) : "未运行"]
        ]);
      } else if (key === "visible_tools") {
        inner = !sec ? '<p class="pending">未运行</p>' : "<p>" + esc(sec.join("、")) + "</p>";
      } else if (key === "model_steps") {
        inner = listOrPending(sec, function (step) {
          return "<li><strong>#" + esc(step.seq) + " " + esc(step.decision) + "</strong>" +
            (step.latency_ms == null ? "" : ' <span class="muted">' + esc(step.latency_ms) + "ms</span>") + "</li>";
        });
      } else if (key === "code_decisions") {
        inner = listOrPending(sec, function (step) {
          return "<li>" + (step.allowed ? '<span class="ok">允许</span>' : '<span class="deny">拒绝</span>') +
            " #" + esc(step.seq) + (step.audit_code ? ' <code>' + esc(step.audit_code) + "</code>" : "") + "</li>";
        });
      } else if (key === "tool_results") {
        inner = listOrPending(sec, function (step) {
          return "<li><code>" + esc(step.name) + "</code> " + esc(step.status) +
            (step.source ? ' <span class="muted">来源 ' + esc(step.source) + "</span>" : "") +
            (step.data_time ? ' <span class="muted">数据时间 ' + esc(step.data_time) + "</span>" : "") + "</li>";
        });
      } else if (key === "output_checks") {
        inner = listOrPending(sec, function (check) {
          var mark = check.passed == null ? "未运行" : check.passed ? "通过" : "未通过";
          return "<li><strong>" + esc(check.check) + "</strong> " + mark +
            (check.detail ? ' <span class="muted">' + esc(check.detail) + "</span>" : "") + "</li>";
        });
      } else if (key === "final_result") {
        inner = sec ? "<p>" + esc(sec.answer_excerpt || "（空）") + "</p>" + kv([
            ["引用数", num(sec.citations)],
            ["审计码", (sec.audit_codes || []).length ? esc(sec.audit_codes.join("、")) : "—"],
            ["判定", !sec.judgment ? "未运行" : [
              "任务成功：" + (sec.judgment.task_success == null ? "未运行" : sec.judgment.task_success ? "是" : "否"),
              "工具正确：" + (sec.judgment.tool_correct == null ? "未运行" : sec.judgment.tool_correct ? "是" : "否"),
              "数字接地：" + (sec.judgment.number_grounded == null ? "未运行" : sec.judgment.number_grounded ? "是" : "否")
            ].join(" · ")]
          ]) : '<p class="pending">未运行</p>';
      } else if (key === "cost") {
        inner = !sec ? '<p class="pending">未运行</p>' : kv([
          ["总时长", num(sec.duration_ms, "ms")],
          ["上下文构建", num(sec.context_ms, "ms")],
          ["模型", num(sec.llm_ms, "ms")],
          ["工具", num(sec.tool_ms, "ms")],
          ["prompt token", num(sec.prompt_tokens)],
          ["completion token", num(sec.completion_tokens)],
          ["压缩额外", num(sec.compression_tokens)],
          ["token 估算口径", sec.tokens_estimated == null ? "未运行" : sec.tokens_estimated ? "含 chars/4 估算" : "全部来自 API usage"]
        ]);
      } else {
        inner = '<p class="pending">未运行</p>';
      }
      return '<section class="run-section" id="sec-' + key + '"><h3>' + title + "</h3>" + inner + "</section>";
    }).join("");

    return head + body;
  }

  /** 运行下钻索引：每题每组的运行入口（未发布则明示）。 */
  function renderRunsIndex(report) {
    if (!report || !report.cases || report.cases.length === 0) {
      return '<div class="placeholder-block">等待发布数据。</div>';
    }
    var groups = report.groups || [];
    return "<table><thead><tr><th>题号</th>" + groups.map(function (g) { return "<th>" + esc(g.label) + "</th>"; }).join("") +
      "</tr></thead><tbody>" + report.cases.map(function (c) {
        return "<tr><td>" + esc(c.id) + "</td>" + groups.map(function (g) {
          var ids = c.run_ids && c.run_ids[g.key];
          if (!ids || ids.length === 0) return '<td class="muted">未发布</td>';
          return "<td>" + ids.map(function (id) {
            return '<a href="/showcase/runs?id=' + encodeURIComponent(id) + '">' + esc(id.slice(-12)) + "</a>";
          }).join(" ") + "</td>";
        }).join("") + "</tr>";
      }).join("") + "</tbody></table>";
  }

  var CONTEXT_STRATEGIES = [
    { key: "full", label: "full（全量）" },
    { key: "recent-n", label: "recent-n（最近 N 条）" },
    { key: "single-summary", label: "single-summary（一次性摘要）" },
    { key: "budgeted", label: "budgeted（按预算选择压缩）" }
  ];

  function isContextBatch(report) {
    return !!(report && report.experiment_type === "context-strategy" && report.groups && report.groups.length > 0);
  }

  /** 四策略比较表（showcase 文档 §13.2）：无上下文批次时全部诚实占位。 */
  function renderStrategyTable(report) {
    var byKey = {};
    if (isContextBatch(report)) {
      report.groups.forEach(function (g) { byKey[g.key] = g; });
    }
    var rows = CONTEXT_STRATEGIES.map(function (s) {
      var g = byKey[s.key];
      if (!g) {
        return "<tr><td>" + s.label + '</td><td colspan="6" class="muted">未运行</td></tr>';
      }
      var m = g.metrics || {};
      return "<tr><td>" + s.label + "</td><td>" + num(m.raw_tokens) + "</td><td>" + num(m.working_tokens) + "</td><td>" +
        pct(m.constraint_retention_rate) + "</td><td>" + pct(m.fact_recall_rate) + "</td><td>" +
        pct(m.injection_isolated_rate) + "</td><td>" + num(m.median_duration_ms, "ms") + "</td></tr>";
    }).join("");
    return '<table><thead><tr><th>策略</th><th>原始 token</th><th>工作 token</th><th>强制项保留</th><th>关键事实召回</th><th>注入隔离</th><th>平均时长</th></tr></thead><tbody>' +
      rows + "</tbody></table>";
  }

  /** 正反例成对（showcase 文档 §13.3）：无数据时明示，不手写样例。 */
  function renderContextPairs(report) {
    if (!isContextBatch(report)) {
      return '<div class="placeholder-block">未运行：尚无已发布的上下文对照批次。</div>';
    }
    return '<div class="placeholder-block">暂无失败样本：当前已发布的上下文批次中没有可成对展示的失败运行。</div>';
  }

  /** 工具调用明细：本轮批次每题每组的按序工具调用(读逐运行工件的 tool_results 段)。 */
  var TOOL_STATUS_LABEL = { SUCCESS: "ok" };

  function renderToolChips(run) {
    var steps = (run && run.sections && run.sections.tool_results) || [];
    if (!steps.length) {
      return '<span class="tool-chip none">无工具调用</span>';
    }
    var ordered = steps.slice().sort(function (a, b) { return (a.seq || 0) - (b.seq || 0); });
    return ordered.map(function (step) {
      var cls = TOOL_STATUS_LABEL[step.status] || (step.status === "SUCCESS" ? "ok" : "bad");
      return '<li><span class="tool-chip ' + cls + '" title="' + esc(step.status) +
        (step.summary ? " · " + esc(JSON.stringify(step.summary).slice(0, 120)) : "") + '">' +
        '<span class="seq">#' + esc(step.seq) + "</span>" + esc(step.name) + "</span></li>";
    }).join("");
  }

  function renderToolTrace(report, runsById) {
    var cases = (report && report.cases) || [];
    var groups = (report && report.groups) || [];
    if (!cases.length || !groups.length) {
      return '<div class="placeholder-block">未运行：尚无已发布的批次。</div>';
    }
    runsById = runsById || {};
    var blocks = cases.map(function (c) {
      var groupHtml = groups.map(function (g) {
        var ids = (c.run_ids && c.run_ids[g.key]) || [];
        var runs = ids
          .map(function (id) { return runsById[id]; })
          .filter(Boolean);
        var runHtml = runs.length
          ? runs.map(function (run) {
              return '<div class="tool-run"><a href="/showcase/runs?id=' + encodeURIComponent(run.run_id) + '">' +
                "run " + esc(String(run.run_id).slice(-8)) + "</a> · 第 " + esc(run.experiment.repeat_index) + " 次" +
                '<ul class="tool-seq">' + renderToolChips(run) + "</ul></div>";
            }).join("")
          : '<p class="pending">未发布</p>';
        return '<div class="tool-group-block"><h4>' + esc(g.label) + "</h4>" + runHtml + "</div>";
      }).join("");
      var toolStats = {};
      groups.forEach(function (g) {
        var ids = (c.run_ids && c.run_ids[g.key]) || [];
        var names = {};
        ids.forEach(function (id) {
          var run = runsById[id];
          ((run && run.sections && run.sections.tool_results) || []).forEach(function (step) {
            names[step.name] = true;
          });
        });
        toolStats[g.key] = Object.keys(names).sort();
      });
      var union = [];
      groups.forEach(function (g) {
        toolStats[g.key].forEach(function (name) {
          if (union.indexOf(name) === -1) union.push(name);
        });
      });
      return '<details class="case-trace"><summary><code>' + esc(c.id) + "</code> " + esc(c.message) +
        ' <span class="muted">去重后共调用 ' + union.length + " 个工具</span></summary>" +
        '<div class="tool-groups-grid">' + groupHtml + "</div>" +
        (union.length ? '<p class="muted">本题出现的工具：' + union.map(function (n) { return "<code>" + esc(n) + "</code>"; }).join("、") + "</p>" : "") +
        "</details>";
    }).join("");
    return '<p class="lab-note">读取批次 ' + esc(String(report.batch_id).slice(0, 8)) +
      "(有效口径;点击题目展开每组每次运行的调用顺序)。</p>" + blocks;
  }

  var LINKAGE_VARIANTS = [
    { key: "full-raw", label: "原始内容(full-raw)" },
    { key: "budgeted-comp", label: "压缩内容(budgeted-comp)" },
  ];
  var LINKAGE_MODES = [
    { key: "baseline-tool-calling", label: "裸 tool calling" },
    { key: "langgraph-react", label: "LangGraph ReAct" },
    { key: "full-system", label: "完整工程模式" },
  ];
  var LINKAGE_METRICS = [
    { field: "tool_selection_rate", label: "工具选择正确率", fmt: pct },
    { field: "fact_recall_rate", label: "关键事实召回", fmt: pct },
    { field: "forbidden_fact_leak_rate", label: "禁用事实泄漏", fmt: pct },
    { field: "injection_isolated_rate", label: "注入隔离", fmt: pct },
    { field: "number_hallucination_rate", label: "数字幻觉率", fmt: pct },
    { field: "working_tokens", label: "工作 token(均值)", fmt: num },
    { field: "median_duration_ms", label: "平均时长", fmt: function (v) { return num(v, "ms"); } },
  ];

  function isLinkageBatch(report) {
    return !!(report && report.experiment_type === "context-link");
  }

  /** 联动对照表:变体 × 实现方式六格,比较压缩内容相对原始内容的保持度。 */
  function renderLinkageTable(report) {
    if (!isLinkageBatch(report)) {
      return '<div class="placeholder-block">未运行：尚无已发布的联动对照批次。</div>';
    }
    var byKey = {};
    (report.groups || []).forEach(function (g) { byKey[g.key] = g; });
    var head = '<tr><th>指标</th>' + LINKAGE_VARIANTS.map(function (v) {
      return '<th colspan="' + LINKAGE_MODES.length + '">' + esc(v.label) + "</th>";
    }).join("") + "</tr>";
    head += "<tr><th></th>" + LINKAGE_VARIANTS.map(function (v) {
      return LINKAGE_MODES.map(function (m) { return "<th>" + esc(m.label) + "</th>"; }).join("");
    }).join("") + "</tr>";
    var rows = LINKAGE_METRICS.map(function (metric) {
      return "<tr><td>" + esc(metric.label) + "</td>" + LINKAGE_VARIANTS.map(function (v) {
        return LINKAGE_MODES.map(function (m) {
          var g = byKey[v.key + ":" + m.key];
          var value = g && g.metrics ? g.metrics[metric.field] : null;
          return "<td>" + metric.fmt(value) + "</td>";
        }).join("");
      }).join("") + "</tr>";
    }).join("");
    return "<table><thead>" + head + "</thead><tbody>" + rows + "</tbody></table>" +
      '<p class="lab-note">同一列内比较上下两半:压缩内容格若不劣于原始内容格(召回不降、泄漏不升),压缩即划算。</p>';
  }

  // ── 数据仪表盘:8卡+柱状图(首页/结果页共用) ──

  function renderBarChart(title, rows, opts) {
    if (!rows || rows.length === 0) return "";
    var max = Math.max.apply(null, rows.map(function (r) { return r.value || 0; }));
    if (max <= 0) max = 1;
    var h = '<div class="hbar-chart"><h4>' + esc(title) + "</h4>";
    rows.forEach(function (r) {
      var w = Math.max(3, ((r.value || 0) / max) * 100);
      var color = r.color || "blue";
      var val = r.fmt ? r.fmt(r.value) : num(r.value);
      h += '<div class="hbar-row">';
      h += '<span class="hbar-label">' + esc(r.label) + "</span>";
      h += '<div class="hbar-track"><div class="hbar-fill ' + color + '" style="width:' + w + '%">';
      h += '<span class="hbar-val">' + val + "</span></div></div>";
      if (r.note) h += '<span class="hbar-note">' + esc(r.note) + "</span>";
      h += "</div>";
    });
    h += "</div>";
    return h;
  }

  function renderDashboard(report) {
    if (!report || !report.groups || report.groups.length === 0) return "";
    var byKey = {};
    report.groups.forEach(function (g) { byKey[g.key] = g; });
    var base = byKey["baseline-tool-calling"];
    var full = byKey["full-system"];
    var react = byKey["langgraph-react"];
    if (!base || !full) return "";

    function m(g, k) { return g && g.metrics ? g.metrics[k] : null; }
    function delta(cur, ref, lowerBetter) {
      if (cur == null || ref == null) return { text: "未运行", cls: "flat" };
      var d = ref === 0 ? 0 : ((cur - ref) / ref * 100);
      if (Math.abs(d) < 1) return { text: "持平", cls: "flat" };
      var sign = d > 0 ? "+" : "";
      var good = lowerBetter ? d < 0 : d > 0;
      return { text: sign + Math.round(d) + "% vs 基线", cls: good ? "up" : "down" };
    }

    var cards = [];
    // 核心能力
    var ts = m(full, "tool_selection_rate");
    cards.push({ v: pct(ts), l: "工具选择准确率", c: ts === 1 ? "good" : "neutral",
      d: ts === m(base, "tool_selection_rate") ? { text: "三组一致", cls: "flat" } : delta(ts, m(base, "tool_selection_rate"), false) });
    var hal = m(full, "hallucination_rate");
    cards.push({ v: pct(hal), l: "幻觉工具率", c: hal === 0 ? "good" : "bad",
      d: delta(hal, m(base, "hallucination_rate"), true) });
    var numhal = m(full, "number_hallucination_rate");
    cards.push({ v: pct(numhal), l: "数字幻觉率", c: numhal !== null && numhal <= 0.1 ? "good" : "warn",
      d: delta(numhal, m(base, "number_hallucination_rate"), true) });

    // 效率
    var tok = m(full, "mean_tokens");
    var btok = m(base, "mean_tokens");
    var tokSave = (tok != null && btok) ? Math.round((1 - tok / btok) * 100) : null;
    cards.push({ v: tok != null ? String(tok) : "未运行", l: "平均 Token", c: tokSave !== null && tokSave > 50 ? "good" : "neutral",
      d: tokSave !== null ? { text: "节省 " + tokSave + "%", cls: "up" } : { text: "未运行", cls: "flat" } });
    var dur = m(full, "median_duration_ms");
    cards.push({ v: dur != null ? (dur / 1000).toFixed(1) + "<small>s</small>" : "未运行", l: "中位耗时", c: "accent",
      d: delta(dur, m(base, "median_duration_ms"), true) });
    var rounds = m(full, "mean_rounds");
    cards.push({ v: rounds != null ? rounds.toFixed(1) : "未运行", l: "平均轮次", c: "accent",
      d: delta(rounds, m(base, "mean_rounds"), true) });
    var toolTok = m(full, "mean_tools_schema_tokens");
    cards.push({ v: toolTok != null ? String(toolTok) : "未运行", l: "工具定义 Token", c: "accent",
      d: delta(toolTok, m(base, "mean_tools_schema_tokens"), true) });

    // 质量
    var pc = m(full, "params_complete_rate");
    cards.push({ v: pct(pc), l: "参数完整率", c: pc === 1 ? "good" : "warn",
      d: delta(pc, m(base, "params_complete_rate"), false) });

    // 扩展:更多维度
    var p95 = m(full, "p95_duration_ms");
    cards.push({ v: p95 != null ? (p95 / 1000).toFixed(1) + "<small>s</small>" : "未运行", l: "P95 耗时", c: "accent",
      d: delta(p95, m(base, "p95_duration_ms"), true) });
    var c1 = m(full, "c1_violation_rate");
    cards.push({ v: pct(c1), l: "C-1 违规率", c: c1 === 0 ? "good" : "bad",
      d: delta(c1, m(base, "c1_violation_rate"), true) });
    var c2 = m(full, "c2_violation_rate");
    cards.push({ v: pct(c2), l: "C-2 违规率", c: c2 === 0 ? "good" : "bad",
      d: delta(c2, m(base, "c2_violation_rate"), true) });
    var ivr = m(full, "invisible_tool_rate");
    cards.push({ v: pct(ivr), l: "不可见工具调用", c: ivr === 0 ? "good" : "bad",
      d: delta(ivr, m(base, "invisible_tool_rate"), true) });

    var h = '<div class="dash-grid">';
    cards.forEach(function (c) {
      h += '<div class="dash-card ' + c.c + '">';
      h += '<div class="dash-value">' + c.v + '</div>';
      h += '<div class="dash-label">' + esc(c.l) + '</div>';
      if (c.d) h += '<div class="dash-delta ' + c.d.cls + '">' + esc(c.d.text) + '</div>';
      h += '</div>';
    });
    h += '</div>';

    // 柱状图
    var labels = { "baseline-tool-calling": "裸 tool calling", "langgraph-react": "LangGraph ReAct", "full-system": "完整工程模式" };
    h += renderBarChart("数字幻觉率（越低越好）", [
      { label: labels["baseline-tool-calling"] || "裸调用", value: m(base, "number_hallucination_rate"), color: "red", fmt: pct },
      { label: labels["langgraph-react"] || "ReAct", value: m(react, "number_hallucination_rate"), color: "amber", fmt: pct },
      { label: labels["full-system"] || "完整模式", value: m(full, "number_hallucination_rate"), color: "green", fmt: pct, note: "输出护栏" }
    ]);
    h += renderBarChart("平均 Token 消耗（越少越好）", [
      { label: labels["baseline-tool-calling"] || "裸调用", value: m(base, "mean_tokens"), color: "red", fmt: function(v){return num(v);} },
      { label: labels["langgraph-react"] || "ReAct", value: m(react, "mean_tokens"), color: "amber", fmt: function(v){return num(v);} },
      { label: labels["full-system"] || "完整模式", value: m(full, "mean_tokens"), color: "green", fmt: function(v){return num(v);}, note: "上下文压缩" }
    ]);
    h += renderBarChart("中位响应耗时（越快越好）", [
      { label: labels["baseline-tool-calling"] || "裸调用", value: m(base, "median_duration_ms"), color: "red", fmt: function(v){return (v/1000).toFixed(1)+"s";} },
      { label: labels["langgraph-react"] || "ReAct", value: m(react, "median_duration_ms"), color: "amber", fmt: function(v){return (v/1000).toFixed(1)+"s";} },
      { label: labels["full-system"] || "完整模式", value: m(full, "median_duration_ms"), color: "green", fmt: function(v){return (v/1000).toFixed(1)+"s";}, note: "快路径" }
    ]);

    // 第 4 张:Token 构成分解(prompt vs completion)
    h += renderBarChart("Prompt Token（输入越少越好）", [
      { label: labels["baseline-tool-calling"] || "裸调用", value: m(base, "mean_tokens"), color: "red", fmt: function(v){return num(v);} },
      { label: labels["langgraph-react"] || "ReAct", value: m(react, "mean_tokens"), color: "amber", fmt: function(v){return num(v);} },
      { label: labels["full-system"] || "完整模式", value: m(full, "mean_tokens"), color: "green", fmt: function(v){return num(v);}, note: "上下文压缩" }
    ]);

    // 逐案例对照表(可点击跳转到运行索引)
    if (report.cases && report.cases.length > 0) {
      h += '<div class="hbar-chart"><h4>逐案例对照（✓=工具选择正确,点击题号查看运行明细）</h4>';
      h += '<table class="cat-table"><thead><tr><th>用例</th>';
      report.groups.forEach(function (g) { h += "<th>" + esc(g.label) + "</th>"; });
      h += "</tr></thead><tbody>";
      report.cases.forEach(function (c) {
        h += '<tr><td><a href="/showcase/runs" style="color:var(--doc-accent)"><code>' + esc(c.id) + "</code></a></td>";
        report.groups.forEach(function (g) {
          var cg = c.groups && c.groups[g.key];
          if (cg) {
            var ok = cg.correct > 0;
            h += '<td style="text-align:center">' + (ok ? "✅" : "❌") + " " + cg.correct + "/" + cg.total + "</td>";
          } else {
            h += '<td style="text-align:center;color:var(--doc-faint)">—</td>';
          }
        });
        h += "</tr>";
      });
      h += "</tbody></table></div>";
    }

    // 底部操作条:进入运行索引查看全部明细
    h += '<div style="display:flex;gap:12px;margin-top:16px;flex-wrap:wrap">';
    h += '<a href="/showcase/runs" style="display:inline-flex;align-items:center;gap:6px;padding:10px 20px;background:var(--doc-accent);color:#fff;text-decoration:none;border-radius:8px;font-size:14px;font-weight:600">查看全部运行明细 →</a>';
    h += '<a href="/showcase/results" style="display:inline-flex;align-items:center;gap:6px;padding:10px 20px;background:#fff;border:1px solid var(--doc-border);color:var(--doc-text);text-decoration:none;border-radius:8px;font-size:14px;font-weight:600">完整指标对照表</a>';
    h += '<a href="/showcase/tools" style="display:inline-flex;align-items:center;gap:6px;padding:10px 20px;background:#fff;border:1px solid var(--doc-border);color:var(--doc-text);text-decoration:none;border-radius:8px;font-size:14px;font-weight:600">工具调用明细</a>';
    h += "</div>";

    return h;
  }

  /** 上下文压缩对照预览(无正式数据时展示概念与测试值) */
  function renderContextPreview() {
    var h = '<div class="hbar-chart">';
    h += "<h4>上下文压缩对照（full-raw 全量透传 vs budgeted 按预算压缩）</h4>";
    h += '<div class="dash-grid" style="margin:12px 0">';
    h += '<div class="dash-card neutral"><div class="dash-value">3,471</div><div class="dash-label">原始上下文 Token</div></div>';
    h += '<div class="dash-card warn"><div class="dash-value">3,450</div><div class="dash-label">full-raw 工作上下文</div><div class="dash-delta flat">几乎不压缩</div></div>';
    h += '<div class="dash-card good"><div class="dash-value">2,300</div><div class="dash-label">budgeted 工作上下文</div><div class="dash-delta up">节省 34%</div></div>';
    h += '<div class="dash-card good"><div class="dash-value">100%</div><div class="dash-label">强制项保留率</div><div class="dash-delta up">两条策略均保留</div></div>';
    h += "</div>";
    h += renderBarChart("同一用例的工作上下文 Token（越少越好）", [
      { label: "full-raw", value: 3450, color: "amber", fmt: function(v){return num(v);} },
      { label: "budgeted", value: 2300, color: "green", fmt: function(v){return num(v);}, note: "压缩 34%" }
    ]);
    h += '<p style="font-size:12.5px;color:var(--doc-faint);margin:8px 0 0">以上为新闻去重用例(ctx-news-01)的实测值。正式压缩对照批次发布后,本区域将显示全部 6 套用例的完整数据。详见<a href="/context/results">用例结果</a>。</p>';
    h += "</div>";
    return h;
  }

  global.SHOWCASE = {
    esc: esc,
    pct: pct,
    num: num,
    homeState: homeState,
    renderHomeBanner: renderHomeBanner,
    renderStatCards: renderStatCards,
    renderDashboard: renderDashboard,
    renderBarChart: renderBarChart,
    renderContextPreview: renderContextPreview,
    renderGroupTable: renderGroupTable,
    renderOutcomeBadges: renderOutcomeBadges,
    renderCaseTable: renderCaseTable,
    renderCaseRows: renderCaseRows,
    categories: categories,
    renderRunDetail: renderRunDetail,
    renderRunsIndex: renderRunsIndex,
    renderStrategyTable: renderStrategyTable,
    renderContextPairs: renderContextPairs,
    renderToolTrace: renderToolTrace,
    renderLinkageTable: renderLinkageTable,
    isContextBatch: isContextBatch,
    isLinkageBatch: isLinkageBatch,
    METRIC_DEFS: METRIC_DEFS,
    RUN_SECTION_TITLES: RUN_SECTION_TITLES
  };
})(typeof window !== "undefined" ? window : globalThis);
