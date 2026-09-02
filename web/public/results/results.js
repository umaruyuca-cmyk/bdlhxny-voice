/* 实验结果页(全站第一核心页)。
 * 只消费 SHOWCASE 适配层发布的公开快照;所有比例标注分母与口径;
 * 汇总数字可下钻到组成它的单次运行(/evidence/);成功与失败同样展示;
 * 无发布数据时整页保持真实空状态。 */
(function () {
  "use strict";

  var S = window.SITE;
  var SC = window.SHOWCASE;
  var state = { batch: "", variant: "", scene: "", status: "" };
  var data = []; // [{batch, runs, publishedAt}]
  var sel = null; // 当前选中的已发布批次

  function el(id) { return document.getElementById(id); }

  function experimentLabel(batch) {
    if (batch.experiment_type === "context-strategy") return "上下文策略对照";
    return zh(batch.experiment_name || batch.experiment_type);
  }

  function selectedRuns() {
    if (!sel) return [];
    return sel.runs.filter(function (run) {
      var v = SC.runView(run, sel.batch);
      if (state.variant && v.variant !== state.variant) return false;
      if (state.scene && (v.scene || "") !== state.scene) return false;
      if (state.status) {
        var isInvalid = v.validity === "INVALID" || v.status === "INVALID";
        var key = isInvalid ? "invalid" : String(v.status).toLowerCase();
        if (key !== state.status) return false;
      }
      return true;
    });
  }

  /* ── 筛选 ─────────────────────────────────────────────────────────── */

  function fillSelect(select, values, current, allLabel, zhFn) {
    var html = '<option value="">' + allLabel + "</option>";
    values.forEach(function (v) {
      var text = zhFn ? zhFn(v) : v;
      html += '<option value="' + S.esc(v) + '"' + (v === current ? " selected" : "") + ">" + S.esc(text) + "</option>";
    });
    select.innerHTML = html;
  }

  function zh(value) { return SC.zh ? SC.zh(value) : value; }

  function unique(list) {
    var seen = {};
    var out = [];
    list.forEach(function (v) {
      if (v && !seen[v]) { seen[v] = 1; out.push(v); }
    });
    return out;
  }

  function initFilters() {
    fillSelect(el("fBatch"), data.map(function (d) { return d.batch.batch_id; }), state.batch, "全部批次(默认最新)");
    var types = unique(data.map(function (d) { return experimentLabel(d.batch); }));
    fillSelect(el("fExperiment"), types, "", "全部实验");
    refreshDynamicFilters();
    ["fBatch", "fVariant", "fScene", "fStatus"].forEach(function (id) {
      el(id).addEventListener("change", function () {
        state.batch = el("fBatch").value;
        state.variant = el("fVariant").value;
        state.scene = el("fScene").value;
        state.status = el("fStatus").value;
        refreshDynamicFilters();
        syncQuery();
        render();
      });
    });
    el("fExperiment").addEventListener("change", function () {
      // 实验类型当前与批次一一对应:选中后定位到对应批次
      var label = el("fExperiment").value;
      var hit = data.filter(function (d) { return experimentLabel(d.batch) === label; })[0];
      if (hit) {
        state.batch = hit.batch.batch_id;
        el("fBatch").value = state.batch;
        refreshDynamicFilters();
        syncQuery();
        render();
      }
    });
  }

  function refreshDynamicFilters() {
    // 默认选中最新发布批次(发布时间倒序);URL 指定批次时以其为准
    var latest = data.slice().sort(function (a, b) { return String(b.publishedAt || "").localeCompare(String(a.publishedAt || "")); })[0];
    sel = data.filter(function (d) { return d.batch.batch_id === state.batch; })[0] || latest || null;
    if (sel && !state.batch) state.batch = sel.batch.batch_id;
    var variants = [];
    var scenes = [];
    if (sel) {
      variants = unique((sel.batch.groups || []).map(function (g) { return g.key; }));
      scenes = unique(sel.runs.map(function (r) { return SC.runView(r, sel.batch).scene; }));
    }
    fillSelect(el("fVariant"), variants, state.variant, "全部变体", zh);
    fillSelect(el("fScene"), scenes, state.scene, "全部场景");
    fillSelect(el("fStatus"),
      [["complete", "完成"], ["failed", "失败"], ["invalid", "无效"], ["cancelled", "已取消"], ["pending_judgment", "待评测"], ["not_run", "未运行"]],
      state.status, "全部状态");
  }

  function syncQuery() {
    var params = new URLSearchParams();
    if (state.batch) params.set("batch", state.batch);
    if (state.variant) params.set("variant", state.variant);
    if (state.scene) params.set("scene", state.scene);
    if (state.status) params.set("status", state.status);
    var q = params.toString();
    history.replaceState(null, "", q ? "?" + q : location.pathname);
  }

  /* ── 区块渲染 ─────────────────────────────────────────────────────── */

  /* 实验总览:全部已发布正式批次一行一个(与单批视图同源数据),点击下钻。
     概要列只呈现该批最有区分度的一项已发布事实(压缩率/最快变体/成功率)。 */
  function renderOverview() {
    if (data.length === 0) {
      el("overviewBlock").innerHTML = '<div class="placeholder-block">尚无正式批次。</div>';
      return;
    }
    var ordered = data.slice().sort(function (a, b) { return String(b.publishedAt || "").localeCompare(String(a.publishedAt || "")); });
    var head = "<thead><tr><th>实验(批次)</th><th class=\"num\">变体</th><th class=\"num\">有效样本</th><th>一句话概要</th><th></th></tr></thead>";
    var rows = ordered.map(function (d) {
      var b = d.batch;
      var groups = b.groups || [];
      var valid = groups.reduce(function (s, g) { return s + g.valid_runs; }, 0);
      var invalid = groups.reduce(function (s, g) { return s + g.invalid_runs; }, 0);
      var note = '<span class="txt-muted">详见单批视图</span>';
      var tokGroups = groups.filter(function (g) { return g.metrics && g.metrics.raw_tokens > 0 && g.metrics.working_tokens != null; });
      if (tokGroups.length >= 2) {
        var minWork = tokGroups.reduce(function (a, g) { return g.metrics.working_tokens < a.metrics.working_tokens ? g : a; }, tokGroups[0]);
        note = "最紧变体 <strong>" + S.esc(zh(minWork.key)) + "</strong> 压缩至原始 " +
          (100 * minWork.metrics.working_tokens / minWork.metrics.raw_tokens).toFixed(1) + "%";
      } else {
        var durGroups = groups.filter(function (g) { return g.metrics && g.metrics.median_duration_ms != null; });
        if (durGroups.length >= 2) {
          var fastest = durGroups.reduce(function (a, g) { return g.metrics.median_duration_ms < a.metrics.median_duration_ms ? g : a; }, durGroups[0]);
          note = "最快变体 <strong>" + S.esc(zh(fastest.key)) + "</strong>(" + SC.metricCell(fastest.metrics, "median_duration_ms").text + ")";
        } else {
          var succ = groups.filter(function (g) { return g.metrics && g.metrics.task_success_rate != null; });
          if (succ.length > 0) note = "任务成功率 " + succ.map(function (g) { return S.esc(zh(g.key)) + " " + SC.metricCell(g.metrics, "task_success_rate").text; }).join(" · ");
        }
      }
      var current = sel && sel.batch.batch_id === b.batch_id;
      return "<tr" + (current ? ' class="row-on"' : "") + "><td>" + S.esc(experimentLabel(b)) +
        '<br><span class="txt-muted">' + S.fmtTime(b.generated_at) + " 发布</span></td>" +
        '<td class="num">' + S.fmtInt(groups.length) + "</td>" +
        '<td class="num txt-ok">' + S.fmtInt(valid) + (invalid > 0 ? ' <span class="txt-warn">+' + S.fmtInt(invalid) + " 无效</span>" : "") + "</td>" +
        "<td>" + note + "</td>" +
        '<td><a href="/results/?batch=' + encodeURIComponent(b.batch_id) + '">查看 →</a></td></tr>';
    }).join("");
    el("overviewBlock").innerHTML =
      '<div class="tbl-scroll"><table class="tbl">' + head + "<tbody>" + rows + "</tbody></table></div>" +
      '<p class="note">总览与单批视图同源(发布校验后的公开快照);概要只取各批最有区分度的一项已发布事实,完整指标进入单批视图查看。</p>';
  }

  /* 结论摘要:全部由本页已发布数字推导(组表/指标表同源),不另立口径;
     字段缺失时逐条降级为「未记录」,不推断。 */
  function renderSummary() {
    var b = sel.batch;
    var groups = b.groups || [];
    var fc = b.fixed_conditions || {};
    if (groups.length === 0) {
      el("summaryBlock").innerHTML = '<div class="placeholder-block">本批次无组级数据,无法生成摘要。</div>';
      return;
    }
    var totalValid = groups.reduce(function (s, g) { return s + g.valid_runs; }, 0);
    var totalInvalid = groups.reduce(function (s, g) { return s + g.invalid_runs; }, 0);
    var total = totalValid + totalInvalid;
    var rows = [];

    // 设计一句话
    rows.push(["实验设计", (Array.isArray(fc.case_ids) ? S.fmtInt(fc.case_ids.length) : "?") + " 个用例 × " + groups.length + " 个变体" +
      (fc.runs_per_case != null ? " × 每变体 " + S.fmtInt(fc.runs_per_case) + " 次" : "") +
      " · 唯一自变量 <code>" + S.esc(zh(fc.variable || "未记录")) + "</code> · 模型 " + S.esc(b.model)]);

    // 样本有效性
    rows.push(["有效样本", "<strong>" + S.fmtInt(totalValid) + "/" + S.fmtInt(total) + "</strong>(" + (total ? (100 * totalValid / total).toFixed(1) : "0") + "%)。" +
      (totalInvalid > 0 ? "另有 <strong>" + S.fmtInt(totalInvalid) + "</strong> 次无效运行(限流/服务不可用等),单列不计入分母。" : "无无效运行。")]);

    // 压缩效果(存在 token 遥测时):报告最大对比
    var tokGroups = groups.filter(function (g) { return g.metrics && g.metrics.raw_tokens != null && g.metrics.working_tokens != null && g.metrics.raw_tokens > 0; });
    if (tokGroups.length >= 1) {
      var parts = tokGroups.map(function (g) {
        var cut = Math.max(0, 1 - g.metrics.working_tokens / g.metrics.raw_tokens);
        return S.esc(zh(g.key)) + ":" + S.fmtInt(g.metrics.raw_tokens) + " → <strong>" + S.fmtInt(g.metrics.working_tokens) + "</strong>(" + (cut * 100).toFixed(1) + "% 缩减)";
      });
      rows.push(["上下文 token(均值)", parts.join(" · ")]);
    }

    // 运行开销(实验组批次携带时):轮次与平均 token
    var roundGroups = groups.filter(function (g) { return g.metrics && g.metrics.mean_rounds != null; });
    if (roundGroups.length > 0) {
      rows.push(["平均轮次", roundGroups.map(function (g) { return S.esc(zh(g.key)) + " " + SC.metricCell(g.metrics, "mean_rounds").text; }).join(" · ")]);
    }
    var tokenMeanGroups = groups.filter(function (g) { return g.metrics && g.metrics.mean_tokens != null && (g.metrics.raw_tokens == null) });
    if (tokenMeanGroups.length > 0) {
      rows.push(["平均 token(轮均)", tokenMeanGroups.map(function (g) { return S.esc(zh(g.key)) + " " + SC.metricCell(g.metrics, "mean_tokens").text; }).join(" · ")]);
    }

    // 质量断言:全变体一致达标的项归纳为一行,未达标项逐个列出
    var qualityKeys = [
      { key: "constraint_retention_rate", label: "强制项保留率", pass: function (v) { return v >= 1; } },
      { key: "fact_recall_rate", label: "关键事实出现率", pass: function (v) { return v >= 1; } },
      { key: "injection_isolated_rate", label: "注入隔离率", pass: function (v) { return v >= 1; } },
      { key: "forbidden_fact_leak_rate", label: "禁用事实泄漏率", pass: function (v) { return v <= 0; } },
    ];
    var held = [];
    var broken = [];
    qualityKeys.forEach(function (q) {
      var vals = groups.map(function (g) { return g.metrics ? g.metrics[q.key] : null; });
      if (vals.every(function (v) { return v == null; })) return;
      if (vals.every(function (v) { return v != null && q.pass(v); })) held.push(q.label);
      else broken.push(q.label + "(" + groups.map(function (g) { return S.esc(zh(g.key)) + " " + SC.metricCell(g.metrics, q.key).text; }).join("、") + ")");
    });
    if (held.length > 0) rows.push(["质量断言(全变体一致)", "<strong class=\"txt-ok\">" + held.join(" / ") + " 全部达标</strong>" + (broken.length ? ";<br>未达标:" + broken.join(";") : "")]);
    else if (broken.length) rows.push(["质量断言", broken.join(";")]);

    // 工具选择(存在该指标时)
    var toolGroups = groups.filter(function (g) { return g.metrics && g.metrics.tool_selection_rate != null; });
    if (toolGroups.length > 0) {
      var best = toolGroups.reduce(function (a, g) { return g.metrics.tool_selection_rate > a.metrics.tool_selection_rate ? g : a; }, toolGroups[0]);
      rows.push(["工具选择准确率", toolGroups.map(function (g) { return S.esc(zh(g.key)) + " " + SC.metricCell(g.metrics, "tool_selection_rate").text; }).join(" · ") +
        (best.metrics.tool_selection_rate > 0 ? "(最高:" + S.esc(zh(best.key)) + ")" : "(各变体均未通过)")]);
    }

    // 时长
    var durGroups = groups.filter(function (g) { return g.metrics && g.metrics.median_duration_ms != null; });
    if (durGroups.length > 1) {
      var fastest = durGroups.reduce(function (a, g) { return g.metrics.median_duration_ms < a.metrics.median_duration_ms ? g : a; }, durGroups[0]);
      rows.push(["时长中位数", durGroups.map(function (g) { return S.esc(zh(g.key)) + " " + SC.metricCell(g.metrics, "median_duration_ms").text; }).join(" · ") +
        "(最快:" + S.esc(zh(fastest.key)) + ")"]);
    }

    // 变体对比结论:按可用指标归纳差异(无差异维度不提,只描述已发布数据)
    var compareNotes = [];
    if (durGroups.length > 1) {
      var fastest2 = durGroups.reduce(function (a, g) { return g.metrics.median_duration_ms < a.metrics.median_duration_ms ? g : a; }, durGroups[0]);
      var slowest = durGroups.reduce(function (a, g) { return g.metrics.median_duration_ms > a.metrics.median_duration_ms ? g : a; }, durGroups[0]);
      if (fastest2.key !== slowest.key && slowest.metrics.median_duration_ms > 0) {
        var speedup = slowest.metrics.median_duration_ms / fastest2.metrics.median_duration_ms;
        compareNotes.push("<strong>" + S.esc(zh(fastest2.key)) + "</strong> 比 " + S.esc(zh(slowest.key)) + " 快约 " + speedup.toFixed(1) + " 倍");
      }
    }
    if (toolGroups.length > 1) {
      var sortedTool = toolGroups.slice().sort(function (a, b) { return (b.metrics.tool_selection_rate || 0) - (a.metrics.tool_selection_rate || 0); });
      var top = sortedTool[0], bottom = sortedTool[sortedTool.length - 1];
      if (top.key !== bottom.key && (top.metrics.tool_selection_rate || 0) > (bottom.metrics.tool_selection_rate || 0)) {
        compareNotes.push("工具选择 <strong>" + S.esc(zh(top.key)) + "</strong> 最高(" + SC.metricCell(top.metrics, "tool_selection_rate").text + ")");
      }
    }
    if (tokGroups.length > 1) {
      var minWork = tokGroups.reduce(function (a, g) { return g.metrics.working_tokens < a.metrics.working_tokens ? g : a; }, tokGroups[0]);
      if (minWork.metrics.raw_tokens > 0) {
        compareNotes.push("<strong>" + S.esc(zh(minWork.key)) + "</strong> 工作上下文最小(" + (100 * minWork.metrics.working_tokens / minWork.metrics.raw_tokens).toFixed(1) + "% of 原始)");
      }
    }
    if (compareNotes.length > 0) rows.push(["变体对比结论", compareNotes.join(" · ")]);

    el("summaryBlock").innerHTML =
      '<table class="kv"><tbody>' +
      rows.map(function (r) { return "<tr><th>" + r[0] + "</th><td>" + r[1] + "</td></tr>"; }).join("") +
      "</tbody></table>" +
      '<p class="note">摘要数字全部来自下方表格(同源推导);结论性判断只描述已发布数据,不外推。</p>';
  }

  function renderDesign() {
    var b = sel.batch;
    var fc = b.fixed_conditions || {};
    var rows = [
      ["批次编号", '<span class="hash">' + S.esc(b.batch_id) + "</span>"],
      ["实验", experimentLabel(b)],
      ["实验目的", b.purpose ? S.esc(b.purpose) : '<span class="txt-muted">未记录</span>'],
      ["唯一自变量", fc.variable ? "<code>" + S.esc(fc.variable) + "</code>" : '<span class="txt-muted">未记录</span>'],
      ["固定用例", Array.isArray(fc.case_ids) ? S.fmtInt(fc.case_ids.length) + " 个(" + fc.case_ids.map(function (c) { return S.esc(zh(c)); }).join("、") + ")" : '<span class="txt-muted">未记录</span>'],
      ["每用例重复", fc.runs_per_case != null ? S.fmtInt(fc.runs_per_case) + " 次" : '<span class="txt-muted">未记录</span>'],
      ["工具数据", fc.tool_data === "frozen" ? "冻结 Mock(fixture)" : fc.tool_data === "live" ? "实时" : '<span class="txt-muted">未记录</span>'],
      ["模型", S.esc(b.model)],
      ["批次生成时间", S.fmtTime(b.generated_at)],
      ["代码版本", '<span class="hash">' + S.esc(b.git_commit) + "</span>"],
    ];
    el("designBlock").innerHTML =
      '<table class="kv"><tbody>' +
      rows.map(function (r) { return "<tr><th>" + r[0] + "</th><td>" + r[1] + "</td></tr>"; }).join("") +
      "</tbody></table>" +
      '<p class="note">固定条件写入运行配置快照(同配置必同哈希);变体由实验模板定义,任何角色不可编辑。</p>';
  }

  function renderSamples() {
    var b = sel.batch;
    var groups = b.groups || [];
    var head = "<thead><tr><th>变体</th><th class=\"num\">有效运行<br>(进指标分母)</th><th class=\"num\">无效运行</th><th>运行证据</th></tr></thead>";
    var rows = groups.map(function (g) {
      return "<tr><td>" + S.esc(zh(g.label)) + "</td>" +
        '<td class="num txt-ok">' + S.fmtInt(g.valid_runs) + "</td>" +
        '<td class="num ' + (g.invalid_runs > 0 ? "txt-warn" : "") + '">' + S.fmtInt(g.invalid_runs) + "</td>" +
        '<td><a href="/evidence/?batch=' + encodeURIComponent(b.batch_id) + "&variant=" + encodeURIComponent(g.key) + '">查看 ' + S.fmtInt(g.valid_runs + g.invalid_runs) + " 次运行</a></td></tr>";
    }).join("");
    var totalValid = groups.reduce(function (s, g) { return s + g.valid_runs; }, 0);
    var totalInvalid = groups.reduce(function (s, g) { return s + g.invalid_runs; }, 0);
    el("sampleBlock").innerHTML =
      '<div class="tbl-scroll"><table class="tbl">' + head + "<tbody>" + rows + "</tbody></table></div>" +
      '<p>合计:<strong class="txt-ok">' + S.fmtInt(totalValid) + " 次有效</strong> · <strong>" + S.fmtInt(totalInvalid) + " 次无效</strong> · 共 " + S.fmtInt(totalValid + totalInvalid) + " 次。发布门槛要求每组有效运行 ≥ 5;无效运行(限流/服务不可用等)单列,不冒充失败样本。</p>";
  }

  function renderMetrics() {
    var groups = (sel.batch.groups || []).filter(function (g) { return g.valid_runs > 0 || g.invalid_runs > 0; });
    var keys = SC.METRICS.filter(function (m) {
      return groups.some(function (g) { return g.metrics && g.metrics[m.key] != null; });
    });
    if (keys.length === 0) {
      el("metricsBlock").innerHTML = '<div class="placeholder-block">本批次报告没有可展示的指标数值(全部为「未运行」)。</div>';
      return;
    }
    var head = "<thead><tr><th>指标(口径)</th>" +
      groups.map(function (g) { return "<th class=\"num\">" + S.esc(zh(g.label)) + "<br><span class=\"txt-muted\">分母 " + S.fmtInt(g.valid_runs) + " 次有效</span></th>"; }).join("") +
      "</tr></thead>";
    var rows = keys.map(function (m) {
      var cells = groups.map(function (g) {
        var cell = SC.metricCell(g.metrics, m.key);
        if (cell.value == null) return '<td class="num txt-muted">未记录</td>';
        return '<td class="num">' + cell.text + "</td>";
      }).join("");
      var dirLabel = m.dir === "up" ? "越高越好" : m.dir === "down" ? "越低越好" : "遥测";
      return "<tr><td>" + S.esc(m.label) + '<br><span class="txt-muted">' + S.esc(dirLabel) + " · " + S.esc(m.note) + "</span></td>" + cells + "</tr>";
    }).join("");
    var drill = '<p class="note">指标在逐次运行上计算后聚合;每个数字的支持运行可在「原始证据」页按 <a href="/evidence/?batch=' +
      encodeURIComponent(sel.batch.batch_id) + '">批次</a> 或变体筛选核对。</p>';
    el("metricsBlock").innerHTML = '<div class="tbl-scroll"><table class="tbl">' + head + "<tbody>" + rows + "</tbody></table></div>" + drill;
  }

  function renderCompare() {
    var groups = sel.batch.groups || [];
    var pctMetrics = SC.METRICS.filter(function (m) {
      return m.kind === "pct" && groups.some(function (g) { return g.metrics && g.metrics[m.key] != null; });
    });
    if (pctMetrics.length === 0) {
      el("compareBlock").innerHTML = '<div class="placeholder-block">本批次无比率型指标可比(全部未记录)。</div>';
      return;
    }
    var metric = pctMetrics[0];
    var rows = groups.map(function (g) {
      var cell = SC.metricCell(g.metrics, metric.key);
      var pct = cell.value == null ? 0 : Math.max(0, Math.min(1, cell.value)) * 100;
      var fillClass = metric.dir === "down" ? "fill-bad" : cell.value == null ? "fill-muted" : "fill-ok";
      return '<div class="bar-row">' +
        '<span class="bar-label">' + S.esc(zh(g.label)) + "</span>" +
        '<span class="bar-track"><span class="bar-fill ' + fillClass + '" style="width:' + pct.toFixed(1) + '%"></span></span>' +
        '<span class="bar-value">' + cell.text + "(有效 " + S.fmtInt(g.valid_runs) + ")</span>" +
        "</div>";
    }).join("");
    el("compareBlock").innerHTML =
      '<p class="filter-row"><label>指标<select id="cmpMetric">' +
      pctMetrics.map(function (m) {
        return '<option value="' + m.key + '"' + (m.key === metric.key ? " selected" : "") + ">" + S.esc(m.label) + (m.dir === "down" ? "(越低越好)" : m.dir === "up" ? "(越高越好)" : "") + "</option>";
      }).join("") + "</select></label></p>" +
      '<div class="bars" id="cmpBars">' + rows + "</div>" +
      '<p class="note">朴素对比柱:长度为该组指标值;有效运行数为该组分母。' + S.esc(metric.note) + "。</p>";
    el("cmpMetric").addEventListener("change", function () {
      var key = el("cmpMetric").value;
      var m = SC.METRIC_MAP[key];
      el("cmpBars").innerHTML = groups.map(function (g) {
        var cell = SC.metricCell(g.metrics, key);
        var pct = cell.value == null ? 0 : Math.max(0, Math.min(1, cell.value)) * 100;
        var fillClass = m.dir === "down" ? "fill-bad" : cell.value == null ? "fill-muted" : "fill-ok";
        return '<div class="bar-row"><span class="bar-label">' + S.esc(zh(g.label)) + "</span>" +
          '<span class="bar-track"><span class="bar-fill ' + fillClass + '" style="width:' + pct.toFixed(1) + '%"></span></span>' +
          '<span class="bar-value">' + cell.text + "(有效 " + S.fmtInt(g.valid_runs) + ")</span></div>";
      }).join("");
    });
  }

  function renderScenes() {
    var cases = sel.batch.cases || [];
    var groupKeys = (sel.batch.groups || []).map(function (g) { return g.key; });
    if (cases.length === 0) {
      el("sceneBlock").innerHTML = '<div class="placeholder-block">本批次报告未含分用例结果。</div>';
      return;
    }
    var head = "<thead><tr><th>用例</th>" + groupKeys.map(function (k) { return '<th class="num">' + S.esc(zh(k)) + "</th>"; }).join("") + "<th>用例输入</th></tr></thead>";
    var rows = cases.map(function (c) {
      var cells = groupKeys.map(function (k) {
        var g = (c.groups || {})[k];
        if (!g) return '<td class="num txt-muted">未记录</td>';
        var ok = g.correct || 0;
        var total = g.total || 0;
        var cls = total === 0 ? "txt-muted" : ok === total ? "txt-ok" : "txt-bad";
        return '<td class="num ' + cls + '">' + ok + "/" + total + "</td>";
      }).join("");
      var runs = [];
      groupKeys.forEach(function (k) {
        ((c.run_ids || {})[k] || []).forEach(function (id) { runs.push(id); });
      });
      var link = runs.length
        ? ' · <a href="/evidence/?batch=' + encodeURIComponent(sel.batch.batch_id) + "&case=" + encodeURIComponent(c.id) + '">' + runs.length + " 次运行</a>"
        : "";
      return "<tr><td><code>" + S.esc(c.id) + "</code>" + (c.category ? '<br><span class="txt-muted">' + S.esc(c.category) + "</span>" : "") + "</td>" + cells +
        '<td><span class="txt-muted">' + S.esc(String(c.message || "").slice(0, 60)) + (String(c.message || "").length > 60 ? "…" : "") + "</span>" + link + "</td></tr>";
    }).join("");
    el("sceneBlock").innerHTML =
      '<div class="tbl-scroll"><table class="tbl">' + head + "<tbody>" + rows + "</tbody></table></div>" +
      '<p class="note">单元格为「通过/总次数」(口径:工具选择正确);0 次总量的格显示未记录,不以 0% 冒充实测。</p>';
  }

  function renderFailures() {
    var runs = sel.runs.map(function (r) { return SC.runView(r, sel.batch); });
    var valid = runs.filter(function (r) { return !(r.validity === "INVALID" || r.status === "INVALID"); });
    var invalid = runs.filter(function (r) { return r.validity === "INVALID" || r.status === "INVALID"; });
    var failed = valid.filter(function (r) { return r.success === false || r.status === "FAILED"; });
    var byReason = {};
    failed.forEach(function (r) {
      var key = r.failure || "未记录";
      byReason[key] = (byReason[key] || 0) + 1;
    });
    var checkFails = {};
    sel.runs.forEach(function (run) {
      ((run.sections && run.sections.output_checks) || []).forEach(function (c) {
        if (c.passed === false) checkFails[c.check] = (checkFails[c.check] || 0) + 1;
      });
    });
    var reasonRows = Object.keys(byReason).sort(function (a, b) { return byReason[b] - byReason[a]; }).map(function (k) {
      return "<tr><td>" + S.esc(k) + "</td><td class=\"num\">" + S.fmtInt(byReason[k]) + "</td>" +
        '<td><a href="/evidence/?batch=' + encodeURIComponent(sel.batch.batch_id) + '&status=failed">查看失败运行</a></td></tr>';
    }).join("");
    var checkRows = Object.keys(checkFails).map(function (k) {
      return "<tr><td>" + S.esc(k) + "</td><td class=\"num\">" + S.fmtInt(checkFails[k]) + "</td></tr>";
    }).join("");
    el("failureBlock").innerHTML =
      "<p>本批次 " + S.fmtInt(runs.length) + " 次发布运行:有效 " + S.fmtInt(valid.length) + " · 其中任务失败 " + S.fmtInt(failed.length) + " · 无效 " + S.fmtInt(invalid.length) + "。" +
      (failed.length === 0 && invalid.length === 0 ? " 本批次无失败样本(如实说明,不以占位代替)。" : "") + "</p>" +
      (reasonRows ? '<div class="tbl-scroll"><table class="tbl"><thead><tr><th>失败原因(按断言归纳)</th><th class="num">次数</th><th>证据</th></tr></thead><tbody>' + reasonRows + "</tbody></table></div>" : "") +
      (checkRows ? '<h3>断言失败项计数(逐运行)</h3><div class="tbl-scroll"><table class="tbl"><thead><tr><th>断言</th><th class="num">未通过次数</th></tr></thead><tbody>' + checkRows + "</tbody></table></div>" : '<p class="note">无断言失败记录。</p>');
  }

  function renderCases() {
    var runs = selectedRuns();
    var views = runs.map(function (r) { return { run: r, v: SC.runView(r, sel.batch) }; });
    var success = views.filter(function (x) { return x.v.success === true; })[0];
    var failure = views.filter(function (x) { return x.v.success === false || x.v.status === "FAILED"; })[0];
    var anyInvalid = views.filter(function (x) { return x.v.validity === "INVALID" || x.v.status === "INVALID"; })[0];
    function card(x, kind) {
      if (!x) return '<div class="placeholder-block">暂无' + kind + "样本</div>";
      var v = x.v;
      return '<div class="panel" style="margin:10px 0">' +
        '<p>' + S.statusChip(v.status, v.validity) + " <strong>" + S.esc(v.variant || "未记录变体") + "</strong> · 用例 <code>" + S.esc(v.caseId) + "</code> · " + S.fmtInt(v.stepCount) + " 步 · " + S.fmtMs(v.durationMs) + "</p>" +
        '<p class="txt-muted">任务输入:' + S.esc(String(v.message).slice(0, 80)) + (String(v.message).length > 80 ? "…" : "") + "</p>" +
        (v.failure ? '<p><span class="st st-bad">失败原因</span> ' + S.esc(v.failure) + "</p>" : "") +
        '<p><a href="/evidence/run/?id=' + encodeURIComponent(v.runId) + '">查看完整证据链 →</a></p>' +
        "</div>";
    }
    el("caseBlock").innerHTML =
      "<p>同一批次中成功与失败各展示一个代表运行(受当前筛选影响);完整清单见证据索引。</p>" +
      "<h3>成功代表</h3>" + card(success, "成功") +
      "<h3>失败代表</h3>" + card(failure, "失败") +
      (anyInvalid ? "<h3>无效示例</h3>" + card(anyInvalid, "无效") : "");
  }

  function render() {
    if (!sel) return;
    renderOverview();
    renderSummary();
    renderDesign();
    renderSamples();
    renderMetrics();
    renderCompare();
    renderScenes();
    renderFailures();
    renderCases();
  }

  async function init() {
    var params = new URLSearchParams(location.search);
    state.batch = params.get("batch") || "";
    state.variant = params.get("variant") || "";
    state.scene = params.get("scene") || "";
    state.status = (params.get("status") || "").toLowerCase();
    data = await SC.loadPublished();
    if (data.length === 0) {
      el("resultsEmpty").hidden = false;
      el("resultsApp").hidden = true;
      return;
    }
    el("resultsEmpty").hidden = true;
    el("resultsApp").hidden = false;
    initFilters();
    render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
