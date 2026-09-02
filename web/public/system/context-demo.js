/* 真实运行演示页(只读):读取系统演示账号的执行数据,零提交操作。 */
(function () {
  "use strict";

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"]/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
    });
  }
  function fmt(n) { return n == null ? "—" : Number(n).toLocaleString("zh-CN"); }
  function metric(label, value) {
    return '<div class="context-metric"><span>' + esc(label) + "</span><b>" + esc(value == null ? "—" : value) + "</b></div>";
  }

  var PHASE_LABELS = {
    LOAD_HISTORY: "读取历史",
    CLASSIFY_AND_SELECT: "分类与选择",
    SUMMARIZE_HISTORY: "LLM 总结",
    VALIDATE_AND_PERSIST: "校验入库",
    ASSEMBLE_CONTEXT: "组装上下文",
    COMPLETED: "已完成",
  };

  function renderBuilds(builds) {
    var box = document.getElementById("demoBuilds");
    if (!builds.length) {
      document.getElementById("demoEmpty").hidden = false;
      box.innerHTML = "";
      return;
    }
    box.innerHTML = builds.map(function (b) {
      var cls = b.classification || {};
      var stats = cls.stats || {};
      var agent = b.agent_run || {};
      return '<button type="button" class="context-metric" data-build="' + esc(b.build_id) + '" style="cursor:pointer;text-align:left" aria-pressed="false">'
        + "<span>" + esc(b.session_title) + (b.session_title && b.session_title.indexOf("· 当前") < 0 ? "" : "") + "</span>"
        + "<b>构建 " + esc(b.status) + " · Agent " + esc(agent.status || "—") + "</b>"
        + "<span>分类 " + esc(cls.source || "—") + " " + fmt(cls.llm_calls) + " 次 · 摘要 " + fmt((b.llm_usage || {}).summary_calls)
        + " 次 · 缓存命中 " + fmt((b.llm_usage || {}).cache_hits) + "</span>"
        + "<span>必留 " + fmt(stats.required) + " · 可压 " + fmt(stats.compressible)
        + " · 引用 " + fmt(stats.reference_only) + " · 干扰 " + fmt(stats.distractor) + "</span>"
        + "</button>";
    }).join("");
    Array.prototype.forEach.call(box.querySelectorAll("[data-build]"), function (btn) {
      btn.addEventListener("click", function () {
        Array.prototype.forEach.call(box.querySelectorAll("[data-build]"), function (other) {
          other.setAttribute("aria-pressed", "false");
        });
        btn.setAttribute("aria-pressed", "true");
        loadDetail(btn.getAttribute("data-build"));
      });
    });
    var first = box.querySelector("[data-build]");
    if (first) first.click();
  }

  function renderSteps(steps) {
    document.getElementById("demoSteps").innerHTML = (steps || []).map(function (step) {
      return '<div class="context-step" data-status="' + esc(step.status) + '"><b>'
        + esc(PHASE_LABELS[step.phase] || step.phase) + "</b><span>"
        + esc(step.status) + (step.duration_ms != null ? " · " + step.duration_ms + "ms" : "")
        + (step.detail_code ? " · " + esc(step.detail_code) : "") + "</span></div>";
    }).join("");
  }

  function ledgerRow(label, calls, inputTokens, outputTokens, extra) {
    return "<tr><td>" + esc(label) + "</td><td>" + esc(calls) + "</td><td>" + esc(inputTokens)
      + "</td><td>" + esc(outputTokens) + "</td><td>" + esc(extra || "—") + "</td></tr>";
  }

  function renderLedger(usage, agent) {
    var rows = "";
    rows += ledgerRow(
      "① LLM 辅助分类(四分类判定)",
      usage.classification_calls,
      usage.classification_input_tokens,
      usage.classification_output_tokens,
      "来源 " + (usage.classification_source || "—") + ";上限 1 次/构建"
    );
    rows += ledgerRow(
      "② Segment 分段摘要(较早历史)",
      usage.segment_model_calls != null ? usage.segment_model_calls : 0,
      "—", "—",
      "生成 " + (usage.segment_generated != null ? usage.segment_generated : "—")
        + " · 命中复用 " + (usage.segment_cache_hits != null ? usage.segment_cache_hits : "—")
        + " · 节省 " + (usage.segment_saved_tokens != null ? usage.segment_saved_tokens : "—") + " token"
    );
    rows += ledgerRow(
      "③ 选中候选摘要(预算内)",
      usage.summary_calls,
      "—", "—",
      "缓存命中 " + (usage.cache_hits != null ? usage.cache_hits : "—") + " · 上限 " + (usage.summary_call_cap != null ? usage.summary_call_cap : "—") + " 次/构建"
    );
    rows += ledgerRow(
      "④ Agent 运行(工具循环往返)",
      usage.agent_calls != null ? usage.agent_calls : (agent && agent.steps) || 0,
      usage.agent_input_tokens, usage.agent_output_tokens,
      "工具调用 " + (usage.agent_tool_calls != null ? usage.agent_tool_calls : 0) + " 次 · " + (agent && agent.stop_reason ? agent.stop_reason : "—")
    );
    document.getElementById("demoLedger").innerHTML =
      '<table style="width:100%;border-collapse:collapse;font-size:13px;background:#fff">'
      + '<thead><tr><th style="text-align:left;padding:8px;border:1px solid #dbe3ee">环节</th>'
      + '<th style="padding:8px;border:1px solid #dbe3ee">调用次数</th>'
      + '<th style="padding:8px;border:1px solid #dbe3ee">输入 token</th>'
      + '<th style="padding:8px;border:1px solid #dbe3ee">输出 token</th>'
      + '<th style="text-align:left;padding:8px;border:1px solid #dbe3ee">说明</th></tr></thead>'
      + "<tbody>" + rows + "</tbody></table>"
      + '<p class="budget-note">压缩环节(①②③)与 Agent 执行(④)分开计量;缓存命中不计入调用次数。</p>';
  }

  function renderDetail(build, artifact) {
    document.getElementById("demoDetail").hidden = false;
    document.getElementById("demoIdentity").textContent =
      "构建 " + build.build_id + " · 算法 " + (build.algorithm_version || "—")
      + " · 来源 " + (build.source_type || "—") + "(冻结会话原文不变)";
    renderSteps(build.steps);

    var usage = build.llm_usage || {};
    renderLedger(usage, build.agent_run || {});

    var cls = (artifact && artifact.classification) || {};
    var stats = cls.stats || {};
    document.getElementById("demoClassMetrics").innerHTML =
      metric("分类来源", cls.source || usage.classification_source || "—")
      + metric("必须保留", stats.required)
      + metric("可压缩", stats.compressible)
      + metric("仅引用", stats.reference_only)
      + metric("干扰/过期", stats.distractor)
      + metric("LLM 判定条数", stats.llm_assist)
      + metric("代码预规则条数", stats.code_rules);

    var budget = build.budget || {};
    document.getElementById("demoBudget").innerHTML =
      '<div class="context-metrics">'
      + metric("原始历史 token", budget.history_input_tokens)
      + metric("最终上下文 token", budget.final_context_tokens)
      + metric("当前请求 token", budget.current_request_tokens)
      + metric("压缩率", budget.history_input_tokens
        ? Math.round((1 - budget.final_context_tokens / budget.history_input_tokens) * 1000) / 10 + "%"
        : "—")
      + "</div>";

    var segBox = document.getElementById("demoSegments");
    var segments = (artifact && artifact.memory_segments) || [];
    segBox.innerHTML = segments.length
      ? segments.map(function (seg) {
        return '<article class="context-event"><div class="context-event-head"><span>'
          + esc(seg.segment_id) + "</span><span>" + esc((seg.event_count || 0) + " 事件") + "</span><span>"
          + esc((seg.source_tokens || 0) + " → " + (seg.summary_tokens || 0) + " token") + "</span><span>"
          + esc(seg.generation_mode || "") + "</span></div><pre>"
          + esc(String(seg.summary_excerpt || "").slice(0, 300)) + "</pre></article>";
      }).join("")
      : '<div class="placeholder-block">本次构建没有注入分段摘要(历史未超阈值)。</div>';

    var agent = build.agent_run || {};
    var agentBox = document.getElementById("demoAgent");
    if (agent.status) {
      var toolRows = (agent.tool_calls || []).map(function (call, i) {
        return "<li>" + esc("#" + (i + 1) + " " + (call.tool || "—") + " · " + (call.status || "—")) + "</li>";
      }).join("");
      agentBox.innerHTML = '<div class="context-metrics">'
        + metric("运行状态", agent.status)
        + metric("模型往返步数", agent.steps)
        + metric("停止原因", agent.stop_reason || "—")
        + metric("耗时", agent.duration_ms != null ? agent.duration_ms + " ms" : "—")
        + '</div><article class="context-card"><div class="context-card-head"><b>模型输出</b><span>'
        + esc(agent.status) + '</span></div><pre>' + esc(agent.output || "(无输出)") + "</pre></article>"
        + (toolRows
          ? '<article class="context-card"><div class="context-card-head"><b>工具调用</b><span>'
            + (agent.tool_calls || []).length + ' 次</span></div><ul class="context-tool-calls">' + toolRows + "</ul></article>"
          : "")
        + (agent.error_code ? '<div class="budget-note">错误码:' + esc(agent.error_code) + "</div>" : "");
    } else {
      agentBox.innerHTML = '<div class="placeholder-block">该构建还没有 Agent 运行记录。</div>';
    }

    var messages = (artifact && artifact.messages) || [];
    document.getElementById("demoMessages").innerHTML = messages.length
      ? messages.map(function (m) {
        return '<article class="context-message"><span class="role">#' + esc(m.order) + " · "
          + esc(m.role) + (m.tokens != null ? " · " + esc(m.tokens) + " token" : "")
          + "</span><pre>" + esc(String(m.content || "").slice(0, 600)) + "</pre></article>";
      }).join("")
      : '<div class="placeholder-block">工件没有消息。</div>';
  }

  function loadDetail(buildId) {
    Promise.all([
      EXP.get("/api/v1/public/context-demo/builds/" + encodeURIComponent(buildId)),
      EXP.get("/api/v1/public/context-demo/builds/" + encodeURIComponent(buildId) + "/artifact")
        .catch(function () { return null; }),
    ]).then(function (values) {
      renderDetail(values[0], values[1]);
    }).catch(function (error) {
      var box = document.getElementById("demoError");
      box.hidden = false;
      box.textContent = "构建详情读取失败:" + error.message;
    });
  }

  EXP.get("/api/v1/public/context-demo").then(function (payload) {
    if (!payload || payload.enabled === false) {
      document.getElementById("demoError").hidden = false;
      document.getElementById("demoError").textContent = "演示数据仅在引擎本地文件存储模式下提供。";
      document.getElementById("demoBuilds").innerHTML = "";
      return;
    }
    renderBuilds(payload.builds || []);
  }).catch(function (error) {
    var box = document.getElementById("demoError");
    box.hidden = false;
    box.textContent = "演示数据读取失败:" + error.message;
    document.getElementById("demoBuilds").innerHTML = "";
  });
})();
