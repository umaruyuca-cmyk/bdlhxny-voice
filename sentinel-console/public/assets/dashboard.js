(function () {
  "use strict";

  var SOUND_KEY = "sentinel.dashboard.sound";
  var POLL_MS = 30000;
  var Badges = window.SentinelBadges || {};
  var state = {
    notifications: [],
    unread: 0,
    sound: localStorage.getItem(SOUND_KEY) !== "off",
    sseBackoff: 1000,
    pollTimer: null,
    streamAbort: null
  };

  function $(id) {
    return document.getElementById(id);
  }

  function jsonHeaders() {
    return { Accept: "application/json" };
  }

  function show(el, on) {
    if (el) el.hidden = !on;
  }

  function formatMoney(value) {
    if (value == null || Number.isNaN(Number(value))) return "—";
    return "¥" + Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  }

  function formatTime(value) {
    if (!value) return "";
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  }

  function ruleLabel(rule) {
    var config = rule.config || {};
    if (rule.type === "price_threshold") {
      var move = config.pct != null ? config.pct + "%" : config.abs_price;
      return (config.symbol || "标的") + " " + (config.direction === "up" ? ">" : "<") + (move || "");
    }
    if (rule.type === "daily_briefing") return "晨报 " + (config.time || "08:30");
    if (rule.type === "post_market_review") return "盘后复盘 " + (config.time || "16:30");
    return rule.type || "规则";
  }

  async function postJSON(url) {
    var response = await fetch(url, { method: "POST", headers: jsonHeaders() });
    var body = null;
    try {
      body = await response.json();
    } catch (err) {
      body = null;
    }
    if (!response.ok) {
      var error = new Error("HTTP " + response.status);
      error.status = response.status;
      throw error;
    }
    return body;
  }

  async function getJSON(url) {
    var response = await fetch(url, { headers: jsonHeaders() });
    var body = null;
    try {
      body = await response.json();
    } catch (err) {
      body = null;
    }
    if (!response.ok) {
      var error = new Error("HTTP " + response.status);
      error.status = response.status;
      error.body = body;
      throw error;
    }
    return body;
  }

  function setRegionError(node, message, retry) {
    if (!node) return;
    if (!message) {
      node.hidden = true;
      node.innerHTML = "";
      return;
    }
    node.hidden = false;
    node.innerHTML = Badges.esc(message) + ' <button type="button" data-retry="1">重试</button>';
    var btn = node.querySelector("button");
    if (btn && retry) btn.onclick = retry;
  }

  function renderOverview(payload) {
    show($("overviewSkeleton"), false);
    show($("overviewMetrics"), true);
    var positions = (payload && payload.positions) || [];
    var cost = 0;
    positions.forEach(function (item) {
      cost += Number(item.quantity || 0) * Number(item.cost_price || item.costPrice || 0);
    });
    $("metricCost").textContent = formatMoney(cost);
    $("metricToday").textContent = "—";
    $("metricPnl").textContent = "—";
    var list = $("holdingsList");
    list.innerHTML = positions
      .map(function (item) {
        var weight = item.target_weight != null ? item.target_weight : item.targetWeight;
        var pct = weight != null ? Math.round(Number(weight) * 1000) / 10 + "%" : "—";
        return (
          "<li><span>" +
          Badges.esc(item.symbol) +
          " " +
          Badges.esc(item.name || "") +
          "</span><span>" +
          Badges.esc(pct) +
          "</span></li>"
        );
      })
      .join("");
    renderHoldingsChart(positions);
  }

  function renderHoldingsChart(positions) {
    var el = $("holdingsChart");
    if (!el || !window.echarts) return;
    var chart = window.echarts.init(el);
    var data = (positions || [])
      .map(function (item) {
        var weight = Number(item.target_weight != null ? item.target_weight : item.targetWeight);
        return {
          name: (item.symbol || "") + " " + (item.name || ""),
          value: Number.isFinite(weight) ? weight : 0
        };
      })
      .filter(function (item) {
        return item.value > 0;
      });
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "item" },
      series: [
        {
          type: "pie",
          radius: ["48%", "72%"],
          data: data,
          label: { color: "#a3a8b8", fontSize: 11 }
        }
      ]
    });
  }

  function normalizeNotification(item) {
    return {
      id: item.notification_id || item.outbox_id || item.id,
      title: item.title || item.event_summary || "通知",
      summary: item.event_summary || item.body || "",
      severity: String(item.severity || "info").toLowerCase(),
      source: item.source || "",
      created_at: item.created_at || item.observation_time,
      audit_codes: item.audit_codes || [],
      evidence_refs: item.evidence_refs || [],
      demo: Badges.isDemoSource(item.source, item.payload || item),
      unread: item.status === "PENDING" || item.read === false || item.unread === true
    };
  }

  function renderTimeline(items) {
    show($("timelineSkeleton"), false);
    var list = $("timelineList");
    var empty = $("timelineEmpty");
    if (!items.length) {
      show(empty, true);
      list.innerHTML = "";
      return;
    }
    show(empty, false);
    list.innerHTML = items
      .map(function (item) {
        var audits = (item.audit_codes || []).map(Badges.audit).join("");
        var evidence = Badges.evidence(item.evidence_refs || []);
        var demo = item.demo ? Badges.demoWatermark() : "";
        return (
          '<article class="event-card" data-id="' +
          Badges.esc(item.id) +
          '">' +
          Badges.severityBar(item.severity) +
          "<div><h3>" +
          Badges.esc(item.title) +
          demo +
          "</h3><p class=\"event-meta\">" +
          Badges.esc(item.summary) +
          '</p><div class="event-foot">' +
          evidence +
          audits +
          '</div><button type="button" class="followup-btn" data-followup="' +
          Badges.esc(item.id) +
          '">追问 →</button></div><time class="event-time">' +
          Badges.esc(formatTime(item.created_at)) +
          "</time></article>"
        );
      })
      .join("");
  }

  function prependNotification(raw) {
    var item = normalizeNotification(raw);
    state.notifications = [item].concat(
      state.notifications.filter(function (row) {
        return row.id !== item.id;
      })
    );
    renderTimeline(state.notifications);
    bumpUnread(1);
    if (item.severity === "critical") {
      $("bell").classList.add("has-critical");
      maybeBeep();
    }
  }

  function bumpUnread(delta) {
    state.unread = Math.max(0, state.unread + delta);
    var node = $("unreadCount");
    node.textContent = String(state.unread);
    node.hidden = state.unread <= 0;
  }

  function setUnread(count) {
    state.unread = Math.max(0, count);
    var node = $("unreadCount");
    node.textContent = String(state.unread);
    node.hidden = state.unread <= 0;
  }

  function maybeBeep() {
    if (!state.sound || !window.AudioContext) return;
    try {
      var ctx = new AudioContext();
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      osc.frequency.value = 880;
      gain.gain.value = 0.04;
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.12);
    } catch (err) {}
  }

  function renderWatch(rules) {
    var active = (rules || []).filter(function (rule) {
      return (rule.status || "active") === "active";
    });
    var chips = $("watchChips");
    var empty = $("watchEmpty");
    if (!active.length) {
      chips.innerHTML = "";
      show(empty, true);
      return;
    }
    show(empty, false);
    chips.innerHTML = active
      .map(function (rule) {
        return '<span class="watch-chip">' + Badges.esc(ruleLabel(rule)) + "</span>";
      })
      .join("");
  }

  async function loadOverview() {
    try {
      setRegionError($("overviewError"), "");
      var data = await getJSON("/api/portfolio/positions");
      renderOverview(data);
    } catch (err) {
      show($("overviewSkeleton"), false);
      setRegionError($("overviewError"), "持仓概览加载失败", loadOverview);
    }
  }

  async function loadTimeline() {
    try {
      setRegionError($("timelineError"), "");
      var data = await getJSON("/api/v1/notifications");
      var rows = Array.isArray(data) ? data.map(normalizeNotification) : [];
      rows.sort(function (a, b) {
        return String(b.created_at).localeCompare(String(a.created_at));
      });
      state.notifications = rows;
      renderTimeline(rows);
      await loadUnread(rows);
    } catch (err) {
      show($("timelineSkeleton"), false);
      setRegionError($("timelineError"), "时间线加载失败", loadTimeline);
    }
  }

  async function loadUnread(fallbackRows) {
    try {
      var data = await getJSON("/api/v1/notifications?unread=count");
      if (data && typeof data.unread === "number") {
        setUnread(data.unread);
        return;
      }
      var rows = Array.isArray(data) ? data : fallbackRows || [];
      setUnread(
        rows.filter(function (item) {
          var row = item.id ? item : normalizeNotification(item);
          return row.unread;
        }).length
      );
    } catch (err) {
      setUnread(0);
    }
  }

  async function loadWatch() {
    try {
      var data = await getJSON("/api/v1/watch-rules");
      renderWatch(Array.isArray(data) ? data : data && data.items);
    } catch (err) {
      renderWatch([]);
    }
  }

  async function loadReady() {
    var bar = $("degradeBar");
    try {
      var data = await getJSON("/api/v1/ready");
      var checks = (data && data.checks) || [];
      var degraded = checks.filter(function (item) {
        return item.ok === false;
      });
      if (!degraded.length && data && data.status === "READY") {
        show(bar, false);
        return;
      }
      bar.hidden = false;
      bar.textContent =
        "依赖降级：" +
        degraded
          .map(function (item) {
            return (item.name || "dependency") + " " + (item.detail || "");
          })
          .join("；");
    } catch (err) {
      bar.hidden = false;
      bar.textContent = "就绪探针不可用，区域数据可能不完整。";
    }
  }

  function startPoll() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(function () {
      loadTimeline();
      loadWatch();
    }, POLL_MS);
  }

  function parseSseBlocks(buffer) {
    var parts = buffer.split("\n\n");
    var rest = parts.pop() || "";
    var events = [];
    parts.forEach(function (block) {
      var eventName = "message";
      var dataLines = [];
      block.split("\n").forEach(function (line) {
        if (line.indexOf("event:") === 0) eventName = line.slice(6).trim();
        if (line.indexOf("data:") === 0) dataLines.push(line.slice(5).trim());
      });
      if (!dataLines.length) return;
      try {
        events.push({ event: eventName, data: JSON.parse(dataLines.join("\n")) });
      } catch (err) {}
    });
    return { rest: rest, events: events };
  }

  async function connectNotificationStream() {
    var bar = $("sseBar");
    if (state.streamAbort) state.streamAbort.abort();
    state.streamAbort = new AbortController();
    try {
      var response = await fetch("/api/v1/notifications/stream", {
        headers: jsonHeaders(),
        signal: state.streamAbort.signal
      });
      if (!response.ok || !response.body) throw new Error("sse unavailable");
      bar.hidden = true;
      state.sseBackoff = 1000;
      var reader = response.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";
      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        var parsed = parseSseBlocks(buffer);
        buffer = parsed.rest;
        parsed.events.forEach(function (frame) {
          var payload = frame.data || {};
          if (frame.event === "notification" || payload.type === "notification") {
            prependNotification(payload);
            loadOverview();
          }
        });
      }
      throw new Error("sse closed");
    } catch (err) {
      if (err && err.name === "AbortError") return;
      bar.hidden = false;
      bar.textContent = "SSE 断线，已回退 30s 轮询并准备重连。";
      startPoll();
      setTimeout(connectNotificationStream, state.sseBackoff);
      state.sseBackoff = Math.min(state.sseBackoff * 2, 15000);
    }
  }

  async function followup(id) {
    var data = await postJSON("/api/v1/notifications/" + encodeURIComponent(id) + "/followup");
    var summary = (data && data.event_summary) || "";
    var sessionId = data && data.session_id;
    $("eventChip").textContent = summary || "事件上下文";
    var openParams = new URLSearchParams();
    var embedParams = new URLSearchParams();
    if (sessionId) {
      openParams.set("sessionId", sessionId);
      embedParams.set("sessionId", sessionId);
    }
    if (summary) {
      openParams.set("followup", summary);
      embedParams.set("followup", summary);
    }
    embedParams.set("embed", "1");
    $("drawerOpenChat").href = openParams.toString() ? "/lab?" + openParams.toString() : "/lab";
    var frame = $("drawerFrame");
    if (frame) {
      frame.hidden = false;
      frame.src = "/lab?" + embedParams.toString();
    }
    $("followupDrawer").classList.add("open");
  }

  $("soundToggle").onclick = function () {
    state.sound = !state.sound;
    localStorage.setItem(SOUND_KEY, state.sound ? "on" : "off");
    this.textContent = state.sound ? "提示音开" : "提示音关";
    this.setAttribute("aria-pressed", String(state.sound));
  };
  $("soundToggle").textContent = state.sound ? "提示音开" : "提示音关";
  $("drawerClose").onclick = function () {
    $("followupDrawer").classList.remove("open");
    var frame = $("drawerFrame");
    if (frame) {
      frame.src = "about:blank";
      frame.hidden = true;
    }
  };
  $("timelineList").addEventListener("click", function (event) {
    var follow = event.target.closest("[data-followup]");
    if (follow) {
      event.preventDefault();
      followup(follow.getAttribute("data-followup")).catch(function () {
        setRegionError($("timelineError"), "追问入口失败", loadTimeline);
      });
      return;
    }
    var evidence = event.target.closest("[data-evidence]");
    if (!evidence) return;
    var pop = document.createElement("div");
    pop.className = "evidence-pop";
    pop.textContent = evidence.getAttribute("data-evidence") || "";
    document.body.appendChild(pop);
    var rect = evidence.getBoundingClientRect();
    pop.style.left = rect.left + "px";
    pop.style.top = rect.bottom + 6 + "px";
    setTimeout(function () {
      pop.remove();
    }, 2800);
  });

  loadReady();
  loadOverview();
  loadTimeline();
  loadWatch();
  startPoll();
  connectNotificationStream();
})();
