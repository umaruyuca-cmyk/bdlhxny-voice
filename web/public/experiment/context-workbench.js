(function () {
  "use strict";

  var view = document.body.getAttribute("data-context-view");
  var PHASE_LABELS = {
    LOAD_HISTORY: "读取历史",
    CLASSIFY_AND_SELECT: "分类与选择",
    SUMMARIZE_HISTORY: "LLM 总结",
    VALIDATE_AND_PERSIST: "校验入库",
    ASSEMBLE_CONTEXT: "组装上下文",
    COMPLETED: "已完成",
  };
  var CLASS_LABELS = {
    required: "必须保留",
    compressible: "可压缩",
    reference_only: "仅引用",
    distractor: "干扰/过期",
  };
  var ACTION_LABELS = {
    kept: "保留",
    compressed: "压缩",
    referenced: "引用",
    omitted: "忽略",
    isolated: "隔离",
  };

  function esc(value) { return EXP.esc(value); }
  function metric(label, value) {
    return '<div class="context-metric"><span>' + esc(label) + "</span><b>" + esc(value == null ? "—" : value) + "</b></div>";
  }
  function excerpt(value, limit) {
    var text = String(value || "");
    return text.length > limit ? text.slice(0, limit) + "…" : text;
  }
  function uuid() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return "ctx-" + Date.now() + "-" + Math.random().toString(16).slice(2);
  }
  function errorDetail(error) {
    return error && error.detail && typeof error.detail === "object" ? error.detail : {};
  }

  function renderEvents(target, events, currentId, includedIds, highlightIds) {
    var included = new Set(includedIds || []);
    var highlight = new Set(highlightIds || []);
    if (!events.length) {
      target.innerHTML = '<div class="placeholder-block">没有历史事件。</div>';
      return;
    }
    target.innerHTML = events.map(function (event) {
      var classes = ["context-event"];
      if (event.event_id === currentId) classes.push("current");
      if (included.has(event.event_id)) classes.push("included");
      if (highlight.size && highlight.has(event.event_id)) classes.push("source-hit");
      var tags = [event.turn_id, event.event_type, event.event_id];
      if (event.event_id === currentId) tags.push("当前请求");
      if (included.has(event.event_id)) tags.push("进入历史构建");
      if (highlight.size && highlight.has(event.event_id)) tags.push("来源事件");
      return '<article class="' + classes.join(" ") + '"><div class="context-event-head">'
        + tags.map(function (tag) { return "<span>" + esc(tag) + "</span>"; }).join("")
        + "</div><pre>" + esc(excerpt(event.content || (event.tool_name ? "调用 " + event.tool_name : ""), 1200)) + "</pre></article>";
    }).join("");
  }

  // 分页条:已显示计数 + 继续加载按钮;计数为真实数值,不是进度条(需求 §22.3/§22.4)
  function renderPager(target, shown, total, hasMore, label, onMore) {
    if (!target) return;
    if (!hasMore) {
      target.hidden = true;
      target.innerHTML = "";
      return;
    }
    target.hidden = false;
    target.innerHTML = '<span class="pager-note">已显示 ' + esc(shown) + " / " + esc(total)
      + ' 条</span><button type="button" class="filter-btn pager-more">' + esc(label) + "</button>";
    target.querySelector(".pager-more").onclick = onMore;
  }

  function initWorkbench() {
    var sessionSelect = document.getElementById("sessionSelect");
    var requestSelect = document.getElementById("requestSelect");
    var buildButton = document.getElementById("buildButton");
    var hint = document.getElementById("buildHint");
    if (!EXP.isOwner()) {
      document.getElementById("authNotice").hidden = false;
      buildButton.disabled = true;
    }

  function renderSegmentLibrary(payload, turnByEvent) {
    var target = document.getElementById("segmentLibrary");
    if (!target) return;
    if (payload && payload.unavailable) {
      target.innerHTML = '<div class="placeholder-block">历史摘要库暂不可用,不影响会话读取与构建。</div>';
      return;
    }
    if (!payload || payload.enabled === false) {
      target.innerHTML = '<div class="placeholder-block">当前模式未启用历史摘要复用(legacy 只读冻结 Session)。</div>';
      return;
    }
    var rows = payload.segments || [];
    if (!rows.length) {
      target.innerHTML = '<div class="placeholder-block">该会话还没有冻结的历史摘要段;发起一次构建后,超出最近原文窗口的旧轮会生成并冻结摘要。</div>';
      return;
    }
    target.innerHTML = rows.map(function (row) {
      var turn = turnByEvent[row.start_event_id] || "";
      return '<article class="context-card"><div class="context-card-head"><b>'
        + esc(turn || row.start_event_id) + "</b><span>"
        + esc(row.start_event_id + " → " + row.end_event_id + " · " + (row.event_count || 0) + " 事件") + "</span><span>"
        + esc("hash " + (row.source_hash_short || "")) + "</span><span>"
        + esc(row.status + " · " + row.generation_mode) + "</span><span>"
        + esc((row.source_tokens || 0) + " → " + (row.summary_tokens || 0) + " token")
        + "</span></div><pre>" + esc(row.summary_excerpt || "") + "</pre></article>";
    }).join("");
  }

  // P2 分析区块:跨构建趋势 + 摘要质量抽检;会话切换时各自重新加载,失败保持隐藏
  function renderTrendAndQuality(sessionId) {
    var trendPanel = document.getElementById("trendPanel");
    var qualityPanel = document.getElementById("qualityPanel");
    if (trendPanel) trendPanel.hidden = true;
    if (qualityPanel) qualityPanel.hidden = true;
    EXP.get("/api/v1/context/sessions/" + encodeURIComponent(sessionId) + "/build-trend?limit=20")
      .then(function (payload) {
        var rows = payload.trends || [];
        if (!trendPanel || !rows.length) return;
        trendPanel.hidden = false;
        document.getElementById("buildTrend").innerHTML = rows.map(function (row) {
          var rate = row.compression_rate == null ? "—"
            : Math.round(row.compression_rate * 1000) / 10 + "%";
          return '<article class="context-event"><div class="context-event-head"><span>'
            + esc(row.build_id || "—") + '</span><span>' + esc(row.status || "—") + '</span><span>'
            + esc(row.created_at || "") + '</span></div><div class="context-metrics">'
            + metric("原始 Token", row.raw_tokens != null ? row.raw_tokens : "—")
            + metric("最终 Token", row.final_tokens != null ? row.final_tokens : "—")
            + metric("压缩率", rate)
            + metric("摘要调用/缓存命中", (row.summary_calls || 0) + "/" + (row.cache_hits || 0))
            + metric("Agent 调用/工具调用", (row.agent_calls || 0) + "/" + (row.agent_tool_calls || 0))
            + '</div></article>';
        }).join("");
      }).catch(function () { /* 趋势不可用:区块保持隐藏 */ });
    EXP.get("/api/v1/context/sessions/" + encodeURIComponent(sessionId) + "/segment-quality?limit=20")
      .then(function (payload) {
        if (!qualityPanel || !payload || payload.enabled !== true) return;
        qualityPanel.hidden = false;
        var rows = payload.rows || [];
        var head = '<div class="context-metrics">'
          + metric("抽检段数", payload.checked != null ? payload.checked : "—")
          + metric("规则通过", payload.passed != null ? payload.passed : "—")
          + metric("规则问题", (payload.issues || []).length)
          + '</div>';
        var body = rows.length ? rows.map(function (row) {
          var problems = (row.problems || []).length
            ? ' · <b>问题:' + esc(row.problems.join(", ")) + "</b>"
            : " · 通过";
          return '<article class="context-event"><div class="context-event-head"><span>'
            + esc(row.segment_id || "—") + '</span><span>' + esc((row.event_count || 0) + " 事件") + '</span><span>'
            + esc((row.source_tokens || 0) + " → " + (row.summary_tokens || 0) + " token")
            + '</span><span>' + esc(row.status + " · " + row.generation_mode) + "</span>"
            + problems + "</div></article>";
        }).join("") : '<div class="placeholder-block">该会话还没有可抽检的冻结摘要段。</div>';
        // 语义抽检(定时分析任务产出,页面只读持久化结果,不触发 LLM)
        var semantic = payload.semantic;
        if (semantic && semantic.length) {
          body += '<h3 class="structure-subhead">语义评审(评审模型对比摘要与原文)</h3>'
            + semantic.map(function (row) {
              var verdictLabel = row.verdict === "PASS" ? "通过"
                : row.verdict === "WARN" ? "警告" : row.verdict === "FAIL" ? "不通过"
                : "评审失败(" + esc(row.error_code || "—") + ")";
              var details = [];
              (row.missing_facts || []).forEach(function (fact) { details.push("遗漏:" + fact); });
              (row.hallucinations || []).forEach(function (fact) { details.push("编造:" + fact); });
              return '<article class="context-event"><div class="context-event-head"><span>'
                + esc(row.segment_id || "—") + '</span><span><b>' + esc(verdictLabel) + '</b></span><span>'
                + esc(row.checked_at || "") + '</span></div>'
                + (details.length ? "<pre>" + esc(details.join("\n")) + "</pre>" : "")
                + "</article>";
            }).join("");
        } else if (semantic) {
          body += '<div class="budget-note">语义抽检还没有覆盖该会话的记录(由后台定时分析任务产出)。</div>';
        }
        document.getElementById("segmentQuality").innerHTML = head + body;
      }).catch(function () { /* 抽检不可用:区块保持隐藏 */ });
  }

  // 工作台事件分页状态:首页只取一页,长会话按游标续载(需求 §22.4 首屏不拉全长会话)
  var EVENT_PAGE_SIZE = 100;
  var eventPage = { sessionId: null, events: [], nextCursor: null, total: 0 };

  function eventsUrl(sessionId, cursor) {
    return "/api/v1/context/sessions/" + encodeURIComponent(sessionId)
      + "/events?limit=" + EVENT_PAGE_SIZE + "&cursor=" + cursor;
  }

  function renderWorkbenchEvents() {
    renderEvents(document.getElementById("eventList"), eventPage.events, requestSelect.value, [], []);
    renderPager(document.getElementById("eventPager"), eventPage.events.length, eventPage.total,
      eventPage.nextCursor != null, "加载更多事件", function () { loadMoreEvents(eventPage.sessionId); });
  }

  function loadMoreEvents(sessionId) {
    if (eventPage.sessionId !== sessionId || eventPage.nextCursor == null) return;
    var cursor = eventPage.nextCursor;
    EXP.get(eventsUrl(sessionId, cursor)).then(function (payload) {
      if (eventPage.sessionId !== sessionId) return; // 会话已切换,丢弃过期页
      eventPage.events = eventPage.events.concat(payload.events || []);
      eventPage.nextCursor = payload.next_cursor == null ? null : payload.next_cursor;
      renderWorkbenchEvents();
    }).catch(function (error) {
      hint.textContent = "加载更多事件失败：" + error.message;
    });
  }

  function loadSession(sessionId) {
    eventPage = { sessionId: sessionId, events: [], nextCursor: null, total: 0 };
    renderTrendAndQuality(sessionId);
    // 摘要库读取单独兜底:仓库故障不阻塞会话概览与事件
    var segmentsPromise = EXP.get(
      "/api/v1/context/sessions/" + encodeURIComponent(sessionId) + "/segments"
    ).catch(function () { return { enabled: false, unavailable: true }; });
    Promise.all([
      EXP.get("/api/v1/context/sessions/" + encodeURIComponent(sessionId) + "/overview"),
      EXP.get(eventsUrl(sessionId, 0)),
      segmentsPromise,
    ]).then(function (values) {
      var overview = values[0];
      eventPage.events = values[1].events || [];
      eventPage.nextCursor = values[1].next_cursor == null ? null : values[1].next_cursor;
      eventPage.total = values[1].total || eventPage.events.length;
      var latest = overview.latest_build;
      var turnByEvent = {};
      eventPage.events.forEach(function (event) { turnByEvent[event.event_id] = event.turn_id; });
      renderSegmentLibrary(values[2], turnByEvent);
        document.getElementById("overviewMetrics").innerHTML = [
          metric("来源类型", overview.source_type),
          metric("原始事件", overview.event_count),
          metric("完整对话轮", overview.turn_count),
          metric("用户消息", overview.user_message_count),
          metric("工具调用对", overview.tool_pair_count),
          metric("算法版本", overview.algorithm_version),
          metric("已冻结摘要段", overview.frozen_segment_count == null ? "—" : overview.frozen_segment_count),
          metric("最近原文轮", overview.recent_raw_turns == null ? "—" : overview.recent_raw_turns),
          metric("最近一次构建", latest ? latest.status : "尚无构建"),
        ].join("");
        var latestLink = document.getElementById("latestBuildLink");
        if (latest && latest.build_id) {
          latestLink.hidden = false;
          latestLink.href = "/experiment/context-builds/" + encodeURIComponent(latest.build_id);
          latestLink.textContent = "查看最近构建(" + latest.status + ")";
        } else {
          latestLink.hidden = true;
        }
        requestSelect.innerHTML = (overview.current_request_candidates || []).map(function (row) {
          var selected = row.event_id === overview.default_current_request_event_id ? " selected" : "";
          return '<option value="' + esc(row.event_id) + '"' + selected + '>'
            + esc(row.event_id + " · " + excerpt(row.excerpt, 90)) + "</option>";
        }).join("");
        renderWorkbenchEvents();
        requestSelect.onchange = renderWorkbenchEvents;
      }).catch(function (error) {
        hint.textContent = "读取会话失败：" + error.message;
      });
    }

    EXP.get("/api/v1/context/sessions").then(function (payload) {
      var sessions = payload.sessions || [];
      if (!sessions.length) throw new Error("没有可用上下文来源");
      var wanted = new URLSearchParams(location.search).get("session_id");
      sessionSelect.innerHTML = sessions.map(function (row) {
        return '<option value="' + esc(row.session_id) + '"' + (row.session_id === wanted ? " selected" : "") + ">"
          + esc(row.title || row.session_id) + " · " + esc(row.source_type) + "</option>";
      }).join("");
      sessionSelect.onchange = function () { loadSession(sessionSelect.value); };
      loadSession(sessionSelect.value);
    }).catch(function (error) {
      sessionSelect.innerHTML = "<option>来源读取失败</option>";
      hint.textContent = "需要登录且运行服务可达：" + error.message;
    });

    buildButton.onclick = function () {
      if (!sessionSelect.value || !requestSelect.value) return;
      buildButton.disabled = true;
      hint.textContent = "正在创建构建；不会运行 Agent…";
      EXP.post("/api/v1/context/sessions/" + encodeURIComponent(sessionSelect.value) + "/builds", {
        current_request_event_id: requestSelect.value,
        algorithm: "budgeted-hybrid-v1",
        idempotency_key: uuid(),
      }).then(function (build) {
        location.href = "/experiment/context-builds/" + encodeURIComponent(build.build_id);
      }).catch(function (error) {
        var detail = errorDetail(error);
        if (error.status === 409 && detail.active_build_id) {
          hint.innerHTML = '该 Session 已有活跃构建。<a href="/experiment/context-builds/'
            + esc(detail.active_build_id) + '">查看正在进行的构建 →</a>';
        } else {
          hint.textContent = "构建创建失败：" + error.message;
        }
        buildButton.disabled = false;
      });
    };

    // 访问审计(本人)与运维脱敏视图:403/未登录时保持隐藏,不阻塞页面
    if (EXP.isOwner()) {
      EXP.get("/api/v1/context/audit?limit=20").then(function (payload) {
        var rows = payload.events || [];
        if (!rows.length) return;
        document.getElementById("auditPanel").hidden = false;
        document.getElementById("ownerAuditList").innerHTML = rows.map(function (row) {
          return '<article class="context-event"><div class="context-event-head"><span>'
            + esc(row.action || "—") + '</span><span>' + esc(row.succeeded ? "成功" : "失败") + '</span><span>'
            + esc(row.created_at || "") + '</span></div></article>';
        }).join("");
      }).catch(function () { /* 审计不可用:区块保持隐藏 */ });
      EXP.get("/api/v1/context/ops/builds?limit=20").then(function (payload) {
        var rows = payload.builds || [];
        if (!rows.length) return;
        document.getElementById("opsPanel").hidden = false;
        document.getElementById("opsBuilds").innerHTML = rows.map(function (row) {
          return '<article class="context-event"><div class="context-event-head"><span>'
            + esc(row.build_id || "—") + '</span><span>所有者 ' + esc(row.owner_ref || "—") + '</span><span>'
            + esc(row.status || "—") + '</span><span>' + esc(row.current_phase || "") + '</span><span>'
            + esc(row.algorithm_version || "") + '</span></div>'
            + '<pre>' + esc(JSON.stringify({
              budget: row.budget || {}, llm_usage: row.llm_usage || {}, agent_run: row.agent_run || {}
            }, null, 2)) + '</pre></article>';
        }).join("");
      }).catch(function () { /* 非运维账号:区块保持隐藏 */ });
      loadOpsAnalysis();
    }

  // 定时分析报告(运维):只读最近运行与报告;手动触发会产生评审 LLM 调用
  function loadOpsAnalysis() {
    var panel = document.getElementById("opsAnalysisPanel");
    var target = document.getElementById("opsAnalysis");
    if (!panel || !target) return;
    EXP.get("/api/v1/context/ops/analysis?limit=3").then(function (payload) {
      var runs = payload.runs || [];
      if (!runs.length) return;
      panel.hidden = false;
      target.innerHTML = runs.map(function (run) {
        var report = typeof run.report === "string" ? JSON.parse(run.report || "{}") : (run.report || {});
        var quality = report.quality_sampling || {};
        var counts = quality.verdict_counts || {};
        var cost = report.cost_benefit || {};
        var corr = report.correlation || {};
        var groups = report.threshold_groups || [];
        var head = '<div class="context-event-head"><span>' + esc(run.run_id || "—") + '</span><span>'
          + esc(run.status || "—") + '</span><span>' + esc(run.trigger_source === "MANUAL" ? "手动" : "定时") + '</span><span>'
          + esc((run.sampled_segments != null ? run.sampled_segments : "—") + " 段采样 · "
            + (run.judge_errors != null ? run.judge_errors : "—") + " 评审失败") + '</span></div>';
        var metrics = '<div class="context-metrics">'
          + metric("语义评审(通过/警告/不通过/失败)",
              (counts.PASS || 0) + "/" + (counts.WARN || 0) + "/" + (counts.FAIL || 0) + "/" + (counts.ERROR || 0))
          + metric("完成构建", cost.completed_builds != null ? cost.completed_builds : "—")
          + metric("Token 净节省", cost.token_savings != null ? cost.token_savings : "—")
          + metric("压缩 LLM 调用", cost.generation_llm_calls != null ? cost.generation_llm_calls : "—")
          + metric("每次调用节省 Token", cost.token_savings_per_generation_call != null
              ? cost.token_savings_per_generation_call : "—")
          + metric("压缩率×Agent 步数相关", corr.correlation != null
              ? corr.correlation + "(n=" + (corr.sample_count || 0) + ")"
              : "样本不足(n=" + (corr.sample_count || 0) + ")")
          + '</div>';
        var groupRows = groups.length
          ? '<h3 class="structure-subhead">阈值/预算分组对照</h3>' + groups.map(function (row) {
            return '<article class="context-event"><div class="context-event-head"><span>'
              + esc("原文轮数 " + (row.recent_raw_turns != null ? row.recent_raw_turns : "—")) + '</span><span>'
              + esc("段预算 " + (row.segment_max_tokens != null ? row.segment_max_tokens : "—")) + '</span><span>'
              + esc(row.build_count + " 构建 / 完成 " + row.completed_count) + '</span><span>'
              + esc("平均压缩率 " + (row.avg_compression_rate != null
                ? Math.round(row.avg_compression_rate * 1000) / 10 + "%" : "—")) + '</span><span>'
              + esc(row.avg_final_tokens != null ? "平均最终 " + row.avg_final_tokens + " token" : "")
              + '</span></div></article>';
          }).join("")
          : "";
        var errorNote = run.error_code
          ? '<div class="budget-note">错误码:' + esc(run.error_code) + "</div>"
          : "";
        return '<article class="context-event">' + head + metrics + groupRows + errorNote + "</article>";
      }).join("");
      var button = document.getElementById("analysisRunButton");
      var hint = document.getElementById("analysisRunHint");
      if (button) {
        button.onclick = function () {
          button.disabled = true;
          hint.textContent = "已提交分析任务(评审模型逐段对比摘要与原文,完成后此处刷新)…";
          EXP.post("/api/v1/context/ops/analysis/run", {}).then(function () {
            window.setTimeout(loadOpsAnalysis, 2000);
            button.disabled = false;
          }).catch(function (error) {
            hint.textContent = "提交失败:" + error.message;
            button.disabled = false;
          });
        };
      }
    }).catch(function () { /* 非运维或不可用:区块保持隐藏 */ });
  }
  }

  function renderSteps(build) {
    document.getElementById("stepList").innerHTML = (build.steps || []).map(function (step) {
      return '<article class="context-step" data-status="' + esc(step.status) + '"><b>'
        + esc(PHASE_LABELS[step.phase] || step.phase) + "</b><span>" + esc(step.status) + "</span><span>"
        + esc(step.duration_ms == null ? "—" : step.duration_ms + " ms") + "</span><span>"
        + esc(step.detail_code || "—") + "</span></article>";
    }).join("");
  }

  function renderBuildMetrics(build) {
    var budget = build.budget || {};
    var usage = build.llm_usage || {};
    document.getElementById("buildMetrics").innerHTML = [
      metric("构建状态", build.status),
      metric("算法", build.algorithm_version),
      metric("历史输入 Token", budget.history_input_tokens),
      metric("最终上下文 Token", budget.final_context_tokens),
      metric("分类 LLM 调用", usage.classification_calls || 0),
      metric("摘要 LLM 调用", usage.summary_calls || 0),
      metric("摘要缓存命中", usage.cache_hits || 0),
      metric("Agent 调用", usage.agent_calls || 0),
    ].join("");
  }

  function renderDecisions(decisions, page) {
    var target = document.getElementById("decisionList");
    if (!decisions.length) { target.innerHTML = '<div class="placeholder-block">尚无决策。</div>'; return; }
    target.innerHTML = decisions.map(function (row) {
      return '<article class="context-card"><div class="context-card-head"><b>' + esc(row.item_id) + "</b><span>"
        + esc(CLASS_LABELS[row.classification] || row.classification) + "</span><span>"
        + esc(ACTION_LABELS[row.action] || row.action) + "</span><span>"
        + esc(row.input_tokens + " → " + row.output_tokens + " token")
        + "</span></div><pre>" + esc(row.reason) + "</pre></article>";
    }).join("");

    var summaries = decisions.filter(function (row) { return row.action === "compressed"; });
    var summaryTarget = document.getElementById("summaryList");
    if (!summaries.length) {
      summaryTarget.innerHTML = '<div class="placeholder-block">本次没有生成压缩表示，可能未达到阈值、命中缓存或全部保留原文。</div>';
      return;
    }
    summaryTarget.innerHTML = summaries.map(function (row) {
      var ids = page ? page.expandIds([row.item_id]).join(",") : row.item_id;
      return '<article class="context-card"><div class="context-card-head"><b>' + esc(row.item_id)
        + "</b><span>来源 " + esc(row.source_id || row.item_id) + "</span><span>"
        + esc(row.input_tokens + " → " + row.output_tokens + " token")
        + '</span><button type="button" class="link-btn" data-source-ids="' + esc(ids) + '">查看来源</button>'
        + "</div><pre>" + esc(row.output_content || "摘要正文未记录") + "</pre></article>";
    }).join("");
  }

  function renderArtifact(build, artifact, page) {
    if (page) {
      page.artifact = artifact;
      page.renderEvents();
      page.renderMessages();
    } else {
      renderEvents(
        document.getElementById("buildEvents"),
        artifact.events || [],
        artifact.current_request_event_id,
        artifact.source_event_ids || []
      );
      document.getElementById("messageList").innerHTML = (artifact.messages || []).map(function (message) {
        return '<article class="context-message"><span class="role">#' + esc(message.order) + " · "
          + esc(message.role) + "</span><pre>" + esc(message.content) + "</pre></article>";
      }).join("") || '<div class="placeholder-block">工件没有消息。</div>';
    }
    document.getElementById("buildIdentity").textContent = "构建 " + build.build_id + " · Session "
      + build.session_id + " · 当前请求 " + build.current_request_event_id + " · 来源 " + build.source_type;
  }

  function renderSegments(build, artifact) {
    var panel = document.getElementById("segmentPanel");
    if (!panel) return;
    var usage = build.llm_usage || {};
    var rows = (artifact && artifact.memory_segments) || [];
    var enabled = usage.segment_cache_hits != null || rows.length > 0;
    if (!enabled) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    document.getElementById("segmentMetrics").innerHTML = [
      metric("旧历史轮数", usage.old_history_turns),
      metric("最近原文轮数", usage.recent_raw_turns),
      metric("Segment 命中", usage.segment_cache_hits || 0),
      metric("本次新生成", usage.segment_generated || 0),
      metric("失效数", usage.segment_invalidated || 0),
      metric("真实摘要 LLM 调用", usage.summary_calls || 0),
      metric("抽取式回退", usage.segment_fallbacks || 0),
      metric("Segment 节省 Token", usage.segment_saved_tokens || 0),
    ].join("");
    var target = document.getElementById("segmentList");
    if (!rows.length) {
      target.innerHTML = '<div class="placeholder-block">本次构建没有可复用的历史摘要 Segment。</div>';
      return;
    }
    target.innerHTML = rows.map(function (row) {
      var ids = (row.source_event_ids || []).join(",");
      return '<article class="context-card"><div class="context-card-head"><b>'
        + esc(row.turn_id || row.start_event_id) + "</b><span>"
        + esc(row.start_event_id + " → " + row.end_event_id + " · " + (row.event_count || 0) + " 事件") + "</span><span>"
        + esc("hash " + (row.source_hash_short || "")) + "</span><span>"
        + esc(row.status + " · " + row.generation_mode) + "</span><span>"
        + esc((row.cache_hit ? "缓存命中" : "本次生成") + " · " + (row.source_tokens || 0) + " → "
          + (row.summary_tokens || 0) + " token")
        + '</span><button type="button" class="link-btn" data-source-ids="' + esc(ids) + '">查看来源</button>'
        + "</div><pre>" + esc(row.summary_excerpt || "") + "</pre></article>";
    }).join("");
  }

  function renderBudgetComposition(build, decisions, events) {
    var target = document.getElementById("budgetComposition");
    var ratios = document.getElementById("buildRatios");
    if (!target || !ratios) return;
    var budget = build.budget || {};
    var counts = build.item_counts || {};
    var rows = decisions || [];

    // 各段 Token 均来自真实决策数据:保留项取输入 Token,压缩/引用项取输出 Token
    var parts = [
      { key: "system", label: "系统规则", tokens: 0 },
      { key: "request", label: "当前请求", tokens: 0 },
      { key: "kept", label: "保留原文", tokens: 0 },
      { key: "compressed", label: "压缩摘要", tokens: 0 },
      { key: "referenced", label: "引用", tokens: 0 },
    ];
    var requiredTotal = 0;
    var requiredKept = 0;
    var traceTotal = 0;
    var traceHit = 0;
    var eventIds = new Set((events || []).map(function (row) { return row.event_id; }));
    rows.forEach(function (row) {
      var action = row.action;
      var input = Number(row.input_tokens) || 0;
      var output = Number(row.output_tokens) || 0;
      var part = parts.find(function (item) { return item.key === action; });
      if (row.item_id === "system-prompt") {
        parts[0].tokens += input;
      } else if (row.item_id === "current-question") {
        parts[1].tokens += input;
      } else if (part) {
        part.tokens += action === "kept" ? input : output;
      }
      if (row.classification === "required") {
        requiredTotal += 1;
        if (action === "kept") requiredKept += 1;
      }
      if (action === "compressed" || action === "referenced") {
        traceTotal += 1;
        if (eventIds.has(row.item_id) || String(row.item_id || "").indexOf("memory-segment:") === 0) traceHit += 1;
      }
    });
    if (budget.current_request_tokens && !parts[1].tokens) parts[1].tokens = budget.current_request_tokens;

    var finalTokens = budget.final_context_tokens;
    var historyInput = budget.history_input_tokens;
    var cap = budget.context_budget_tokens;
    var total = parts.reduce(function (sum, item) { return sum + item.tokens; }, 0);
    var denominator = finalTokens || total;
    var bar = parts.filter(function (item) { return item.tokens > 0; }).map(function (item) {
      var width = denominator ? Math.max(1, Math.round(item.tokens * 100 / denominator)) : 0;
      return '<span class="budget-seg budget-' + item.key + '" style="width:' + width + '%" title="'
        + esc(item.label + " " + item.tokens + " token") + '"></span>';
    }).join("");
    var legend = parts.map(function (item) {
      return '<span class="budget-legend"><i class="budget-dot budget-' + item.key + '"></i>'
        + esc(item.label) + " <b>" + esc(item.tokens || "—") + "</b> token</span>";
    }).join("");
    var margin = cap != null && finalTokens != null ? Math.max(0, cap - finalTokens) : null;
    target.innerHTML = (bar ? '<div class="budget-bar" role="img" aria-label="最终上下文 Token 构成">'
      + bar + "</div>" : '<div class="placeholder-block">暂无决策数据。</div>')
      + '<div class="budget-legend-row">' + legend + "</div>"
      + '<div class="budget-note">最终 ' + esc(finalTokens != null ? finalTokens : "—") + " / 预算上限 "
      + esc(cap != null ? cap : "—") + " token · 余量 " + esc(margin != null ? margin : "—") + "</div>";

    var compression = historyInput > 0 && finalTokens != null
      ? Math.round((1 - finalTokens / historyInput) * 100) : null;
    var requiredRate = requiredTotal > 0 ? Math.round(requiredKept * 100 / requiredTotal) : null;
    var traceRate = traceTotal > 0 ? Math.round(traceHit * 100 / traceTotal) : null;
    ratios.innerHTML = [
      metric("压缩率", compression == null ? "—" : compression + "%"),
      metric("必须项保留率", requiredRate == null ? "—" : requiredRate + "%"),
      metric("来源可追溯率", traceRate == null ? "—" : traceRate + "%"),
      metric("分类(必留/可压/引用/干扰)", (counts.required || 0) + "/" + (counts.compressible || 0)
        + "/" + (counts.reference_only || 0) + "/" + (counts.distractor || 0)),
      metric("动作(保留/压缩/引用/忽略)", (counts.retained || 0) + "/" + (counts.compressed || 0)
        + "/" + (counts.referenced || 0) + "/" + (counts.omitted || 0)),
    ].join("");
  }

  function renderAgentRun(page, build) {
    var panel = document.getElementById("agentPanel");
    var button = document.getElementById("agentRunButton");
    var hint = document.getElementById("agentRunHint");
    var target = document.getElementById("agentRunResult");
    if (!panel || !button) return;
    var run = build.agent_run;
    var runnable = build.status === "COMPLETED" && !(run && (run.status === "RUNNING" || run.status === "COMPLETED"));
    button.disabled = !runnable;
    if (run && run.status === "RUNNING") {
      hint.textContent = "Agent 正在运行,不可重复提交…";
    } else if (run) {
      hint.textContent = run.status === "COMPLETED" ? "已运行完成;同一构建不会重复运行。" : "上次运行失败;同一构建不会重复运行。";
    } else {
      hint.textContent = "";
    }
    if (!run) {
      target.innerHTML = '<div class="placeholder-block">尚未运行。</div>';
      return;
    }
    var usage = build.llm_usage || {};
    var rows = [
      metric("运行状态", run.status),
      metric("模型", run.model || usage.agent_model || "—"),
      metric("Agent 输入 Token", run.input_tokens != null ? run.input_tokens : (usage.agent_input_tokens != null ? usage.agent_input_tokens : "—")),
      metric("Agent 输出 Token", run.output_tokens != null ? run.output_tokens : (usage.agent_output_tokens != null ? usage.agent_output_tokens : "—")),
      metric("模型往返步数", run.steps != null && run.steps > 0 ? run.steps : (usage.agent_calls != null ? usage.agent_calls : "—")),
      metric("工具调用", (run.tool_calls || []).length || (usage.agent_tool_calls != null ? usage.agent_tool_calls : 0)),
      metric("耗时", run.duration_ms != null ? run.duration_ms + " ms" : "—"),
      metric("发送内容哈希", run.message_hash_at_run ? String(run.message_hash_at_run).slice(0, 19) : "—"),
    ];
    if (run.estimated) {
      rows.push(metric("用量口径", "估算(模型未返回 usage,按字符保守估算)"));
    }
    var stopReasons = {
      FINAL_ANSWER: "模型给出最终回答",
      MAX_AGENT_STEPS: "达到单次运行步数上限,保留已有证据停止",
      CONTEXT_ERROR: "上下文错误,诚实停止"
    };
    var toolRows = (run.tool_calls || []).map(function (call, index) {
      return '<li>' + esc('#' + (index + 1) + ' ' + (call.tool || "—")
        + ' · ' + esc(call.status || "—")
        + (call.audit_code ? ' · 审计码 ' + esc(call.audit_code) : '')) + '</li>';
    });
    var toolBlock = toolRows.length
      ? '<article class="context-card"><div class="context-card-head"><b>工具调用记录</b><span>'
        + toolRows.length + ' 次</span></div><ul class="context-tool-calls">' + toolRows.join("") + '</ul></article>'
      : "";
    var stopNote = run.stop_reason
      ? '<div class="note">停止原因:' + esc(stopReasons[run.stop_reason] || run.stop_reason) + '</div>'
      : "";
    var body = run.status === "FAILED"
      ? '<pre>' + esc("错误码 " + (run.error_code || "—") + " · " + (run.error_message || "")) + '</pre>'
      : '<pre>' + esc(run.output || "模型未返回内容") + '</pre>';
    target.innerHTML = '<div class="context-metrics">' + rows.join("") + '</div>' + stopNote
      + '<article class="context-card"><div class="context-card-head"><b>模型输出</b><span>'
      + esc(run.status) + '</span></div>' + body + '</article>' + toolBlock;
    if (run.status === "RUNNING") {
      window.setTimeout(function () { page.reloadBuild(); }, 1500);
    }
  }

  // 工件下载/复制(需求 §11.2):必须经权限校验并记录审计——下载重新走服务端
  // 工件接口(服务端审计后返回),复制在剪贴板写入成功后申报 CONTEXT_CONTENT_COPY
  function renderArtifactActions(buildId, page) {
    var target = document.getElementById("artifactActions");
    if (!target) return;
    var messages = (page.artifact && page.artifact.messages) || [];
    if (!messages.length) {
      target.innerHTML = "";
      return;
    }
    target.innerHTML = '<button type="button" class="filter-btn" id="artifactDownload">下载冻结工件</button>'
      + '<button type="button" class="filter-btn" id="artifactCopy">复制消息序列</button>'
      + '<span class="pager-note" id="artifactActionsNote">下载与复制均记录访问审计</span>';
    var note = document.getElementById("artifactActionsNote");
    document.getElementById("artifactDownload").onclick = function () {
      note.textContent = "正在下载…";
      EXP.get("/api/v1/context/builds/" + encodeURIComponent(buildId) + "/artifact")
        .then(function (artifact) {
          var blob = new Blob([JSON.stringify(artifact, null, 2)], { type: "application/json" });
          var url = URL.createObjectURL(blob);
          var link = document.createElement("a");
          link.href = url;
          link.download = "context-artifact-" + buildId + ".json";
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          URL.revokeObjectURL(url);
          note.textContent = "已下载(访问已记录审计)";
        })
        .catch(function (error) { note.textContent = "下载失败:" + error.message; });
    };
    document.getElementById("artifactCopy").onclick = function () {
      var text = messages.map(function (message) {
        return message.role + ": " + (message.content || "");
      }).join("\n\n");
      if (!(navigator.clipboard && navigator.clipboard.writeText)) {
        note.textContent = "当前浏览器不支持剪贴板 API,请手动选择复制";
        return;
      }
      navigator.clipboard.writeText(text).then(function () {
        note.textContent = "已复制 " + messages.length + " 条消息(已记录审计)";
        EXP.post("/api/v1/context/builds/" + encodeURIComponent(buildId) + "/access-audit", {
          action: "CONTEXT_CONTENT_COPY",
        }).catch(function () { note.textContent = "已复制,但审计申报失败"; });
      }, function () {
        note.textContent = "复制失败:浏览器拒绝了剪贴板写入";
      });
    };
  }

  function initBuild() {
    var buildId = decodeURIComponent(location.pathname.split("/").filter(Boolean).pop() || "");
    var errorBox = document.getElementById("buildError");

    // 构建页状态:筛选/高亮/视图均为纯前端展示,不影响后端数据;
    // 事件为工件冻结快照,长会话按窗口分批展示(需求 §22.4)
    var page = {
      events: [],
      decisions: [],
      artifact: null,
      filter: "all",
      view: "raw",
      highlight: new Set(),
      eventLimit: 50,

      // 工具对是原子单元:命中 call 时连带其紧邻 result 一起高亮;
      // memory-segment:<id> 条目经 artifact.memory_segments 映射回原始事件
      expandIds: function (ids) {
        var result = [];
        var byId = {};
        page.events.forEach(function (event, index) { byId[event.event_id] = index; });
        (ids || []).forEach(function (id) {
          if (String(id).indexOf("memory-segment:") === 0) {
            var segmentId = String(id).slice("memory-segment:".length);
            ((page.artifact && page.artifact.memory_segments) || []).forEach(function (row) {
              if (row.segment_id === segmentId) {
                (row.source_event_ids || []).forEach(function (eventId) {
                  if (result.indexOf(eventId) < 0) result.push(eventId);
                });
              }
            });
            return;
          }
          if (byId[id] == null || result.indexOf(id) >= 0) return;
          result.push(id);
          var event = page.events[byId[id]];
          var next = page.events[byId[id] + 1];
          if (event.event_type === "tool_call" && next && next.event_type === "tool_result") {
            result.push(next.event_id);
          }
        });
        return result;
      },

      filterSets: function () {
        var artifact = page.artifact || {};
        var history = new Set(artifact.source_event_ids || []);
        var segmented = new Set();
        ((artifact.memory_segments || []).forEach(function (row) {
          (row.source_event_ids || []).forEach(function (id) { segmented.add(id); });
        }));
        var compressed = new Set();
        (page.decisions || []).forEach(function (row) {
          if (row.action === "compressed") page.expandIds([row.item_id]).forEach(function (id) { compressed.add(id); });
        });
        var tools = new Set(page.events.filter(function (event) {
          return event.event_type === "tool_call" || event.event_type === "tool_result";
        }).map(function (event) { return event.event_id; }));
        var raw = new Set(Array.from(history).filter(function (id) { return !segmented.has(id); }));
        return { all: null, raw: raw, segmented: segmented, compressed: compressed, tools: tools };
      },

      renderFilterBar: function () {
        var bar = document.getElementById("eventFilters");
        if (!bar) return;
        var sets = page.filterSets();
        var definitions = [
          { key: "all", label: "全部", set: null },
          { key: "raw", label: "保留原文", set: sets.raw },
          { key: "segmented", label: "已摘要", set: sets.segmented },
          { key: "compressed", label: "被压缩", set: sets.compressed },
          { key: "tools", label: "工具记录", set: sets.tools },
        ];
        bar.innerHTML = definitions.map(function (item) {
          var count = item.set ? item.set.size : page.events.length;
          return '<button type="button" class="filter-btn" data-filter="' + item.key + '"'
            + (page.filter === item.key ? ' aria-pressed="true"' : ' aria-pressed="false"') + ">"
            + esc(item.label) + " · " + count + "</button>";
        }).join("");
        bar.onclick = function (event) {
          var button = event.target.closest ? event.target.closest("[data-filter]") : null;
          if (!button) return;
          page.filter = button.getAttribute("data-filter");
          page.renderFilterBar();
          page.renderEvents();
        };
      },

      visibleEvents: function () {
        var active = this.filterSets()[this.filter];
        var events = active
          ? this.events.filter(function (event) { return active.has(event.event_id); })
          : this.events;
        return events;
      },

      // 高亮目标若落在窗口之外,扩窗保证联动可见(来源追溯不因分页失效)
      ensureEventWindow: function (ids) {
        if (!ids.length) return;
        var events = this.visibleEvents();
        var maxIndex = -1;
        events.forEach(function (event, index) {
          if (ids.indexOf(event.event_id) >= 0 && index > maxIndex) maxIndex = index;
        });
        if (maxIndex >= this.eventLimit) this.eventLimit = maxIndex + 1;
      },

      renderEvents: function () {
        var artifact = this.artifact || {};
        var sets = this.filterSets();
        var active = sets[this.filter];
        var events = this.visibleEvents();
        var visible = events.slice(0, this.eventLimit);
        var highlight = this.highlight.size ? Array.from(this.highlight) : [];
        renderEvents(
          document.getElementById("buildEvents"),
          visible,
          artifact.current_request_event_id,
          active ? Array.from(active) : (artifact.source_event_ids || []),
          highlight
        );
        renderPager(document.getElementById("eventPager"), visible.length, events.length,
          visible.length < events.length, "显示更多事件", function () {
            page.eventLimit += 100;
            page.renderEvents();
          });
      },

      renderViewToggle: function () {
        var bar = document.getElementById("messageViews");
        if (!bar) return;
        var views = [
          { key: "raw", label: "原始消息" },
          { key: "structure", label: "结构视图" },
          { key: "token", label: "Token 视图" },
        ];
        bar.innerHTML = views.map(function (item) {
          return '<button type="button" class="filter-btn" data-view="' + item.key + '"'
            + (page.view === item.key ? ' aria-pressed="true"' : ' aria-pressed="false"') + ">"
            + esc(item.label) + "</button>";
        }).join("");
        bar.onclick = function (event) {
          var button = event.target.closest ? event.target.closest("[data-view]") : null;
          if (!button) return;
          page.view = button.getAttribute("data-view");
          page.renderViewToggle();
          page.renderMessages();
        };
      },

      renderMessages: function () {
        var target = document.getElementById("messageList");
        var messages = (page.artifact && page.artifact.messages) || [];
        if (!messages.length) {
          target.innerHTML = '<div class="placeholder-block">工件没有消息。</div>';
          return;
        }
        if (page.view === "token") {
          var hasTokens = messages.some(function (message) { return message.tokens != null; });
          if (!hasTokens) {
            target.innerHTML = '<div class="placeholder-block">该工件生成于逐消息 Token 记录上线之前,无法展示 Token 视图;请重新构建获得真实计数。</div>';
            return;
          }
          var totalTokens = messages.reduce(function (sum, message) { return sum + (Number(message.tokens) || 0); }, 0);
          target.innerHTML = messages.map(function (message) {
            var tokens = Number(message.tokens) || 0;
            var width = totalTokens ? Math.max(1, Math.round(tokens * 100 / totalTokens)) : 0;
            return '<article class="context-message"><span class="role">#' + esc(message.order) + " · "
              + esc(message.role) + " · " + esc(tokens) + " token</span>"
              + '<span class="token-bar"><i style="width:' + width + '%"></i></span>'
              + "<pre>" + esc(excerpt(message.content, 200)) + "</pre></article>";
          }).join("") + '<div class="budget-note">合计 ' + esc(totalTokens) + " token(逐消息真实计数)</div>";
          return;
        }
        if (page.view === "structure") {
          var groups = [];
          messages.forEach(function (message) {
            var kind = message.role === "system" ? "系统规则"
              : String(message.content || "").indexOf("memory-segment:") >= 0 ? "冻结摘要段" : "对话与数据";
            var group = groups[groups.length - 1];
            if (!group || group.kind !== kind) {
              group = { kind: kind, messages: [], tokens: 0 };
              groups.push(group);
            }
            group.messages.push(message);
            group.tokens += Number(message.tokens) || 0;
          });
          target.innerHTML = groups.map(function (group) {
            return '<div class="structure-group"><h3>' + esc(group.kind)
              + " <span>" + group.messages.length + " 条 · " + esc(group.tokens) + " token</span></h3>"
              + group.messages.map(function (message) {
                return '<article class="context-message"><span class="role">#' + esc(message.order) + " · "
                  + esc(message.role) + "</span><pre>" + esc(excerpt(message.content, 400)) + "</pre></article>";
              }).join("") + "</div>";
          }).join("");
          return;
        }
        target.innerHTML = messages.map(function (message) {
          return '<article class="context-message"><span class="role">#' + esc(message.order) + " · "
            + esc(message.role) + "</span><pre>" + esc(message.content) + "</pre></article>";
        }).join("");
      },

      reloadBuild: function () {
        EXP.get("/api/v1/context/builds/" + encodeURIComponent(buildId)).then(function (build) {
          renderSteps(build);
          renderBuildMetrics(build);
          renderAgentRun(page, build);
          if (build.status === "PENDING" || build.status === "RUNNING") {
            window.setTimeout(load, 1500);
          }
        }).catch(function () { /* 轮询失败静默,下一轮重试 */ });
      },
    };

    // 来源联动:摘要卡/Segment 卡的"查看来源"→ 高亮原始事件并滚动定位;再次点击取消
    document.addEventListener("click", function (event) {
      var button = event.target.closest ? event.target.closest("[data-source-ids]") : null;
      if (!button) return;
      var ids = (button.getAttribute("data-source-ids") || "").split(",").filter(Boolean);
      var expanded = page.expandIds(ids);
      page.highlight = sameSet(page.highlight, expanded) ? new Set() : new Set(expanded);
      page.ensureEventWindow(Array.from(page.highlight));
      page.renderEvents();
      if (page.highlight.size) {
        var first = document.querySelector("#buildEvents .source-hit");
        if (first && first.scrollIntoView) first.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    });

    function sameSet(left, right) {
      if (left.size !== right.length) return false;
      return right.every(function (id) { return left.has(id); });
    }

    // Agent 运行:一次构建一次运行;提交后轮询构建记录直到运行终态
    var agentButton = document.getElementById("agentRunButton");
    if (agentButton) {
      agentButton.addEventListener("click", function () {
        agentButton.disabled = true;
        document.getElementById("agentRunHint").textContent = "正在提交 Agent 运行…";
        EXP.post("/api/v1/context/builds/" + encodeURIComponent(buildId) + "/agent-runs", {})
          .then(function () { page.reloadBuild(); })
          .catch(function (error) {
            var detail = errorDetail(error);
            agentButton.disabled = false;
            document.getElementById("agentRunHint").textContent = "运行提交失败:"
              + (detail.error_code || error.message);
          });
      });
    }

    function load() {
      EXP.get("/api/v1/context/builds/" + encodeURIComponent(buildId)).then(function (build) {
        renderSteps(build);
        renderBuildMetrics(build);
        document.getElementById("buildIdentity").textContent = "构建 " + build.build_id + " · Session "
          + build.session_id + " · 当前阶段 " + (PHASE_LABELS[build.current_phase] || build.current_phase);
        if (build.status === "PENDING" || build.status === "RUNNING") {
          window.setTimeout(load, 1500);
          return;
        }
        if (build.status === "FAILED" || build.status === "CANCELLED") {
          errorBox.hidden = false;
          errorBox.textContent = "构建未完成：" + (build.error_code || build.status) + " · " + (build.error_message || "");
          renderAgentRun(page, build);
          return;
        }
        renderAgentRun(page, build);
        Promise.all([
          EXP.get("/api/v1/context/builds/" + encodeURIComponent(buildId) + "/decisions"),
          EXP.get("/api/v1/context/builds/" + encodeURIComponent(buildId) + "/artifact"),
        ]).then(function (values) {
          page.decisions = values[0].decisions || [];
          page.artifact = values[1];
          page.events = values[1].events || [];
          renderDecisions(page.decisions, page);
          renderArtifact(build, values[1], page);
          renderSegments(build, values[1]);
          renderBudgetComposition(build, page.decisions, page.events);
          page.renderFilterBar();
          page.renderViewToggle();
          page.renderMessages();
          renderArtifactActions(buildId, page);
        });
      }).catch(function (error) {
        errorBox.hidden = false;
        errorBox.textContent = "构建读取失败：" + error.message;
      });
    }
    load();
  }

  if (view === "workbench") initWorkbench();
  if (view === "build") initBuild();
})();
