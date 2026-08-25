/* Session 交叉验证三视图共享渲染(纯函数,无 DOM 依赖,可被 Node 测试加载)。
 * 数据源:发布器生成的 data.js(window.SESSION_CROSS_DATA)。
 * 约定:所有工具返回展示处必须带「simulated/冻结 Mock」标记;页面不出现
 * 任何 gold 评测标注;纯前端渲染本地数据,无重运行入口、无后端调用。 */
(function (global) {
  "use strict";

  var SHOWCASE = global.SHOWCASE || {};
  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"]/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
    });
  }
  function pct(value) {
    return value == null ? "—" : Math.round(value * 100) + "%";
  }
  function num(value, suffix) {
    return value == null ? "—" : String(value) + (suffix || "");
  }
  function shortHash(hash) {
    return String(hash || "").replace(/^sha256:/, "").slice(0, 12);
  }

  var EVENT_LABELS = {
    user_message: "用户",
    assistant_message: "助手",
    tool_call: "工具调用",
    tool_result: "工具结果"
  };

  var MOCK_NOTICE = '所有工具返回均为冻结 Mock(<span class="mock-mark">simulated</span>),不代表真实第三方 API。';

  /** 原始 Session 视图:102 事件时间线;工具对折叠;错误结果显眼;无评测标注。 */
  function renderSessionTimeline(session) {
    if (!session || !session.events || !session.events.length) {
      return '<div class="placeholder-block">尚未发布 Session 数据。</div>';
    }
    var rows = [];
    var events = session.events;
    var index = 0;
    while (index < events.length) {
      var event = events[index];
      if (event.type === "tool_call") {
        var result = events[index + 1] && events[index + 1].type === "tool_result" ? events[index + 1] : null;
        rows.push(_toolPairRow(event, result));
        index += result ? 2 : 1;
        continue;
      }
      rows.push(_messageRow(event));
      index += 1;
    }
    return [
      '<div class="notice"><strong>' + esc(session.title || session.case_id) + '</strong> · '
        + session.event_count + ' 个事件 · 当前问题:' + esc(session.current_question) + '</div>',
      '<div class="session-timeline">' + rows.join("\n") + "</div>"
    ].join("\n");
  }

  function _messageRow(event) {
    var kind = event.type === "assistant_message" ? "assistant" : "user";
    return [
      '<div class="timeline-row ' + kind + '" id="' + esc(event.event_id) + '">',
      '<div class="timeline-side"><span class="seq">#' + event.seq + "</span>"
        + '<span class="tag">' + esc(EVENT_LABELS[event.type] || event.type) + "</span></div>",
      '<div class="timeline-main"><div class="timeline-meta">' + esc(event.occurred_at) + "</div>",
      '<div class="timeline-content">' + esc(event.content) + "</div></div></div>"
    ].join("");
  }

  function _toolPairRow(call, result) {
    var isError = result && result.status && result.status !== "success";
    var args = "";
    try { args = JSON.stringify(call.arguments || {}); } catch (e) { args = String(call.arguments || ""); }
    return [
      '<div class="timeline-row tool' + (isError ? " error" : "") + '" id="' + esc(call.event_id) + '">',
      '<div class="timeline-side"><span class="seq">#' + call.seq + "</span>"
        + '<span class="tag">工具对</span>' + (isError ? '<span class="tag wip">错误</span>' : "") + "</div>",
      '<div class="timeline-main"><details class="tool-details">',
      "<summary><code>" + esc(call.tool_name) + "</code>(" + esc(args) + ") "
        + '<span class="mock-mark">simulated/冻结 Mock</span>'
        + (isError ? ' <span class="tool-error">error_code=' + esc(result.error_code || "?") + "</span>" : " ✓") + "</summary>",
      '<div class="timeline-meta">tool_result(' + esc((result && result.status) || "success") + ") · "
        + esc((result && result.event_id) || "") + "</div>",
      '<div class="timeline-content mono">' + esc((result && result.content) || "") + "</div>",
      "</details></div></div>"
    ].join("");
  }

  /** 四种模型输入视图:变体摘要卡(可四列对照)。 */
  function renderVariantCards(index) {
    var variants = (index && index.variants) || [];
    if (!variants.length) return '<div class="placeholder-block">尚未发布编译工件。</div>';
    return variants.map(function (v) {
      var compression = v.original_tokens ? Math.round((1 - v.working_tokens / v.original_tokens) * 100) : null;
      return [
        '<div class="doc-card variant-card">',
        '<h3>' + esc(v.title) + ' <span class="table-meta">' + esc(v.variant_id) + "</span></h3>",
        '<div class="kv"><span>strategy_version</span><b>' + esc(v.strategy_version) + "</b></div>",
        '<div class="kv"><span>预算</span><b>' + num(v.token_budget) + " token</b></div>",
        '<div class="kv"><span>original → working</span><b>' + num(v.original_tokens) + " → " + num(v.working_tokens)
          + " token" + (compression != null ? "(压缩 " + compression + "%)" : "") + "</b></div>",
        '<div class="kv"><span>构建时长</span><b>' + num(v.build_duration_ms, " ms") + "</b></div>",
        v.uses_summary_model
          ? '<div class="kv"><span>摘要成本</span><b>' + num(v.build_model_calls) + " 次调用 · in "
            + num(v.build_input_tokens) + " / out " + num(v.build_output_tokens) + " token</b></div>"
          : "",
        '<div class="kv"><span>compiled_context_hash</span><b class="mono">' + esc(shortHash(v.compiled_context_hash)) + "</b></div>",
        v.has_scores ? '<div class="tag ok">含 v2 因子评分</div>' : "",
        '<p class="variant-notes">' + esc(v.notes || "") + "</p>",
        "</div>"
      ].join("");
    }).join("\n");
  }

  /** 事件桶:kept/compressed/referenced/omitted → 可点击跳回原始 Session 视图定位。 */
  function renderEventBuckets(artifact, session) {
    if (!artifact) return "";
    var buckets = [
      ["kept", "保留原文", artifact.kept_event_ids],
      ["compressed", "压缩", artifact.compressed_event_ids],
      ["referenced", "引用", artifact.referenced_event_ids],
      ["omitted", "省略", artifact.omitted_event_ids]
    ];
    return buckets.map(function (row) {
      var name = row[0], label = row[1], ids = row[2] || [];
      return [
        '<div class="bucket bucket-' + name + '">',
        '<h4>' + label + ' <span class="table-meta">' + ids.length + " 个事件</span></h4>",
        '<div class="bucket-chips">' + ids.map(function (id) {
          return '<a class="chip" href="index.html#' + esc(id) + '" title="在原始 Session 中定位">' + esc(id) + "</a>";
        }).join("") + "</div></div>"
      ].join("");
    }).join("\n");
  }

  /** v2 因子构成条形图(可解释性证据;仅 budgeted v2 工件有 scores)。 */
  function renderFactorBars(artifact) {
    var scores = (artifact && artifact.scores) || [];
    if (!scores.length) return "";
    var factors = ["relevance", "authority", "freshness", "source_quality", "task_impact", "citation_dependency", "failure_risk", "staleness"];
    return [
      '<h3>条目因子构成(公式五·multi-factor-v2)</h3>',
      '<p class="table-meta">priority 为八因子加权和;selection_value = priority / 选中表示 token(公式六)。</p>',
      '<div class="factor-table">'
        + scores.map(function (row) {
          var bars = factors.map(function (key) {
            var value = Number(row.factors && row.factors[key] != null ? row.factors[key] : 0);
            return '<span class="factor-cell"><i style="height:' + Math.round(Math.max(0, Math.min(1, value)) * 28) + 'px"></i><em>'
              + esc(key) + "</em><b>" + value.toFixed(2) + "</b></span>";
          }).join("");
          return '<div class="factor-row"><span class="factor-item mono" title="' + esc(row.item_id) + '">'
            + esc(row.item_id) + '</span><span class="factor-bars">' + bars
            + '</span><span class="factor-priority">p=' + Number(row.priority).toFixed(3)
            + " · " + esc(row.representation) + " · " + num(row.representation_tokens) + "tok"
            + " · sv=" + Number(row.selection_value).toFixed(5) + "</span></div>";
        }).join("\n")
        + "</div>"
    ].join("\n");
  }

  /** 编译消息预览(模型实际输入)。 */
  function renderCompiledMessages(artifact) {
    var messages = (artifact && artifact.compiled_messages) || [];
    if (!messages.length) return "";
    return [
      '<details class="messages-details"><summary>展开冻结的模型输入消息(' + messages.length + " 条)</summary>",
      messages.map(function (message, order) {
        return '<div class="compiled-message role-' + esc(message.role) + '"><div class="timeline-meta">#'
          + order + " · " + esc(message.role) + "</div><pre>" + esc(message.content) + "</pre></div>";
      }).join("\n"),
      ((artifact.warnings || []).length
        ? '<div class="note">warnings:' + (artifact.warnings || []).map(function (w) { return "<code>" + esc(w) + "</code>"; }).join(" ") + "</div>"
        : ""),
      "</details>"
    ].join("\n");
  }

  /** 实验结果视图:12 格矩阵(行=上下文策略,列=Agent 模式)。 */
  function renderResultsMatrix(report, index) {
    if (!report || report.status === "not_run") {
      return '<div class="placeholder-block">尚未运行实验。<code>report.json</code> 当前为 <code>{status:"not_run"}</code> 占位;运行 '
        + "<code>python -m bdlh_runtime.evaluation.session_cross_eval --runs 3 --publish</code> 后此处渲染 12 格矩阵。</div>";
    }
    var variants = (index && index.variants) || [];
    var modes = (index && index.agent_modes) || ["baseline-tool-calling", "langgraph-react", "full-system"];
    var cellsBy = {};
    (report.cells || []).forEach(function (cell) {
      cellsBy[cell.context_variant + "|" + cell.agent_mode] = cell;
    });
    var head = "<tr><th>上下文策略 \\ Agent 模式</th>" + modes.map(function (mode) { return "<th>" + esc(mode) + "</th>"; }).join("") + "</tr>";
    var body = variants.map(function (variant) {
      var cells = modes.map(function (mode) {
        var cell = cellsBy[variant.variant_id + "|" + mode];
        if (!cell) return '<td class="matrix-cell empty">—</td>';
        var runs = cell.runs || [];
        var valid = runs.filter(function (r) { return r.validity === "VALID"; });
        var selection = _mean(valid.map(function (r) { return (r.judgment && r.judgment.tool_plan && r.judgment.tool_plan.selection_rate); }));
        var retention = _mean(valid.map(function (r) { return r.judgment && r.judgment.constraint_retention; }));
        var misuse = valid.filter(function (r) { return r.judgment && (r.judgment.superseded_misuse || []).length; }).length;
        var duration = _mean(valid.map(function (r) { return r.duration_ms; }));
        var insufficient = valid.length < 2 && runs.length > 0 ? ' <span class="tag wip">样本不足</span>' : "";
        return '<td class="matrix-cell" data-cell="' + esc(variant.variant_id) + "|" + esc(mode) + '">'
          + '<b>' + valid.length + "/" + runs.length + "</b> 有效运行" + insufficient
          + '<div class="matrix-metrics">工具选择率 <b>' + pct(selection) + "</b><br>约束保留率 <b>"
          + pct(retention) + "</b><br>废弃误用 <b>" + misuse + "</b> 次<br>平均时长 <b>"
          + (duration == null ? "—" : Math.round(duration) + " ms") + "</b></div></td>";
      }).join("");
      return "<tr><th>" + esc(variant.title) + '<span class="table-meta">' + esc(variant.variant_id) + "</span></th>" + cells + "</tr>";
    }).join("");
    return [
      '<div class="note">' + MOCK_NOTICE + "评测器:" + esc(report.evaluator_version) + " · 模型:" + esc(report.model)
        + " · 每格重复:" + num(report.runs_per_cell) + "</div>",
      '<table class="matrix-table"><thead>' + head + "</thead><tbody>" + body + "</tbody></table>",
      '<p class="table-meta">点击任意格子展开该格运行列表与单次运行下钻;INVALID 运行保留并标注原因。</p>',
      '<div id="cellDetail"></div>'
    ].join("\n");
  }

  function _mean(values) {
    var usable = (values || []).filter(function (v) { return v != null && !isNaN(v); });
    if (!usable.length) return null;
    return usable.reduce(function (a, b) { return a + b; }, 0) / usable.length;
  }

  /** 单格下钻:运行列表(点击展开单次运行明细)。 */
  function renderCellDetail(cell) {
    if (!cell) return "";
    var runs = cell.runs || [];
    return [
      '<h3>格子:' + esc(cell.context_variant) + " × " + esc(cell.agent_mode) + "</h3>",
      '<table><thead><tr><th>run_key</th><th>有效性</th><th>时长</th><th>工具选择率</th><th>约束保留</th><th>展开</th></tr></thead><tbody>'
        + runs.map(function (run, order) {
          var judgment = run.judgment || {};
          var invalid = run.validity !== "VALID";
          return "<tr><td class=\"mono\">" + esc(run.run_key) + "</td>"
            + '<td>' + (invalid ? '<span class="tag wip">INVALID</span>' : '<span class="tag ok">VALID</span>') + "</td>"
            + "<td>" + num(run.duration_ms, " ms") + "</td>"
            + "<td>" + pct(judgment.tool_plan && judgment.tool_plan.selection_rate) + "</td>"
            + "<td>" + pct(judgment.constraint_retention) + "</td>"
            + '<td><button class="tab run-toggle" data-run="' + order + '">明细</button></td></tr>'
            + '<tr class="run-detail-row" id="run-detail-' + order + '" hidden><td colspan="6">' + renderRunDetail(run) + "</td></tr>";
        }).join("\n")
        + "</tbody></table>"
    ].join("\n");
  }

  /** 单次运行下钻:answer、工具调用序列、Mock 返回、判定明细。 */
  function renderRunDetail(run) {
    if (!run) return "";
    var judgment = run.judgment || {};
    var plan = judgment.tool_plan || {};
    return [
      '<div class="run-detail">',
      "<h4>回答</h4>",
      run.answer ? '<div class="timeline-content">' + esc(run.answer) + "</div>"
        : '<div class="timeline-content dim">（无回答' + (run.error ? ":" + esc(run.error) : "") + "）</div>",
      "<h4>工具调用序列(" + ((run.tool_calls || []).length) + " 次)</h4>",
      (run.tool_calls || []).length
        ? "<ol>" + (run.tool_calls || []).map(function (call) {
            var args = "";
            try { args = JSON.stringify(call.arguments || {}); } catch (e) { args = String(call.arguments || ""); }
            return "<li><code>" + esc(call.tool) + "</code>(" + esc(args) + ")</li>";
          }).join("") + "</ol>"
        : '<p class="dim">无工具调用。</p>',
      "<h4>Mock 返回（<span class=\"mock-mark\">simulated/冻结 Mock</span>）</h4>",
      (run.mock_records || []).length
        ? "<ol>" + (run.mock_records || []).map(function (record) {
            return "<li><code>" + esc(record.tool_name) + "</code> → " + esc(record.status)
              + (record.fixture_id ? " · fixture " + esc(record.fixture_id) : " · 未命中 fixture") + "</li>";
          }).join("") + "</ol>"
        : '<p class="dim">无 Mock 记录。</p>',
      "<h4>判定明细</h4>",
      '<div class="kv"><span>工具选择率</span><b>' + pct(plan.selection_rate) + "（命中 " + num(plan.required_hit) + "/"
        + num(plan.required_total) + "）</b></div>",
      '<div class="kv"><span>漏调用</span><b>' + esc((plan.missing_calls || []).join("、") || "无") + "</b></div>",
      '<div class="kv"><span>约束保留率</span><b>' + pct(judgment.constraint_retention) + "</b></div>",
      '<div class="kv"><span>缺失约束</span><b>' + esc((judgment.missing_constraints || []).join("、") || "无") + "</b></div>",
      '<div class="kv"><span>废弃决定误用</span><b>' + esc((judgment.superseded_misuse || []).join("、") || "无") + "</b></div>",
      '<div class="kv"><span>禁用说法</span><b>' + esc((judgment.forbidden_claims_in_answer || []).join("、") || "无") + "</b></div>",
      run.error ? '<div class="kv"><span>错误</span><b>' + esc(run.error) + "</b></div>" : "",
      "</div>"
    ].join("\n");
  }

  global.SESSION_CROSS = {
    esc: esc,
    pct: pct,
    num: num,
    MOCK_NOTICE: MOCK_NOTICE,
    renderSessionTimeline: renderSessionTimeline,
    renderVariantCards: renderVariantCards,
    renderEventBuckets: renderEventBuckets,
    renderFactorBars: renderFactorBars,
    renderCompiledMessages: renderCompiledMessages,
    renderResultsMatrix: renderResultsMatrix,
    renderCellDetail: renderCellDetail,
    renderRunDetail: renderRunDetail
  };
})(typeof window !== "undefined" ? window : globalThis);
