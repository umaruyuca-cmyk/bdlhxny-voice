/* 实验模块共享脚本(前后端对接契约 v1):
   同源 API 访问(匿名 Cookie / 所有者 Bearer)、类型徽章、哈希 chip、轮询。
   依赖:页面自身保证相对路径 /api/v1/* 可达(部署层反代到 engine)。 */
window.EXP = (function () {
  "use strict";

  var ANON_RUN_CAP = 8; // 匿名角色运行数上限(plan_template_batch 角色上限)

  function token() {
    // 所有者会话键 ts_owner;兼容一次性迁移旧键 lab_token
    var legacy = sessionStorage.getItem("lab_token");
    if (legacy) { sessionStorage.setItem("ts_owner", legacy); sessionStorage.removeItem("lab_token"); }
    return sessionStorage.getItem("ts_owner") || "";
  }
  function isOwner() { return !!token(); }

  function api(method, path, body) {
    var headers = { "Content-Type": "application/json" };
    if (token()) headers["Authorization"] = "Bearer " + token();
    return fetch(path, {
      method: method,
      headers: headers,
      cache: "no-store",
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) {
          var message = data && data.detail ? String(data.detail) : "HTTP " + res.status;
          var error = new Error(message);
          error.status = res.status;
          error.detail = message;
          throw error;
        }
        return data;
      });
    });
  }
  function get(path) { return api("GET", path); }
  function post(path, body) { return api("POST", path, body); }

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  var CLASSIFICATION = {
    formal: { cls: "b-green", label: "正式单变量" },
    "formal-single-variable": { cls: "b-green", label: "正式单变量" },
    "cross-diagnostic": { cls: "b-orange", label: "专项交叉" },
    "special-cross": { cls: "b-orange", label: "专项交叉" },
  };
  function classificationBadge(cls) {
    var meta = CLASSIFICATION[cls] || { cls: "b-gray", label: cls || "未知" };
    return '<span class="badge ' + meta.cls + '">' + esc(meta.label) + "</span>";
  }
  function badge(cls, label, extra) {
    return '<span class="badge ' + cls + '"' + (extra || "") + ">" + esc(label) + "</span>";
  }

  /* 模板文案层(IA §二.7 第一层用规范中文名;注册表是代码常量,此处集中维护展示名,
     服务端字段仍为技术名,技术口径行照原样展示) */
  var TEMPLATE_TEXT = {
    "context-strategy-comparison": {
      title: "长上下文记忆策略对比", varLabel: "上下文策略",
      variants: { full: "完整上下文", "recent-window": "最近窗口", "single-summary": "单轮摘要", budgeted: "预算化裁剪" },
    },
    "governance-on-off": {
      title: "工具调用治理的有效性验证", varLabel: "治理配置",
      variants: { off: "治理关闭", standard: "标准治理" },
    },
    "tool-delivery-comparison": {
      title: "工具提供方式对比", varLabel: "工具提供方式",
      variants: { all: "全量装载", search: "检索式装载" },
    },
    "tool-availability-degradation": {
      title: "工具可用性降级与诚实性", varLabel: "工具可用性档位",
      variants: { "full-catalog": "完整目录", "remove-preferred": "排除首选", "remove-preferred-and-alternative": "排除首选与替代" },
    },
    "temperature-stability": {
      title: "采样温度与输出稳定性", varLabel: "采样温度",
      variants: { "t0.0": "温度 0.0", "t0.1": "温度 0.1", "t0.3": "温度 0.3", "t0.7": "温度 0.7" },
    },
    "compression-method-comparison": {
      title: "压缩方法对照:抽取式 vs 生成式", varLabel: "压缩方法",
      variants: { budgeted: "抽取式(代码)", "budgeted-llm": "生成式(LLM 摘要)" },
    },
    "max-agent-steps-stability": {
      title: "单次步数与输出稳定性", varLabel: "单次最大步数",
      variants: { "steps-3": "3 步", "steps-4": "4 步", "steps-5": "5 步" },
    },
  };
  function textOf(t) { return TEMPLATE_TEXT[t.template_id] || {}; }
  function title(t) { return textOf(t).title || t.independent_variable_label || t.template_id; }
  function varLabel(t) { return textOf(t).varLabel || t.independent_variable_label || (t.independent_variable || []).join(","); }
  function variantLabel(t, label) {
    var map = textOf(t).variants || {};
    return map[label] || label;
  }

  function hashChip(value) {
    if (!value) return '<span class="null-cell">无</span>';
    var text = String(value);
    return '<button type="button" class="hash" data-copy="' + esc(text) + '" title="' + esc(text) + '" onclick="EXP.copyHash(this)">' + esc(text.slice(0, 8)) + "</button>";
  }
  function copyHash(el) {
    var value = el.getAttribute("data-copy") || "";
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).catch(function () { /* 剪贴板不可用时静默 */ });
    }
  }

  function fmtTime(value) {
    // 全站统一 yyyyMMdd HH:mm:ss(docs.js 先于本脚本加载;兜底实现保持同格式)
    if (window.SITE && window.SITE.fmtTime) return window.SITE.fmtTime(value);
    if (!value) return "—";
    var d = new Date(value);
    if (isNaN(d.getTime())) return String(value).replace("T", " ").slice(0, 19);
    var p2 = function (n) { return (n < 10 ? "0" : "") + n; };
    return "" + d.getFullYear() + p2(d.getMonth() + 1) + p2(d.getDate()) +
      " " + p2(d.getHours()) + ":" + p2(d.getMinutes()) + ":" + p2(d.getSeconds());
  }

  var JOB_STATUS_LABEL = {
    QUEUED: "排队中", RUNNING: "进行中", COMPLETE: "已完成", PARTIAL: "部分完成",
    FAILED: "失败", CANCELLED: "已取消", INTERRUPTED: "已中断",
    // 所有者运行通道(/api/v1/jobs)的状态词:running/done/error
    running: "进行中", done: "已完成", error: "失败",
  };
  var BATCH_STATUS_LABEL = {
    RUNNING: "进行中", COMPLETE: "已完成", FAILED: "失败", CANCELLED: "已取消", CREATED: "已创建",
  };
  function jobStatusLabel(status) { return JOB_STATUS_LABEL[status] || String(status || "—"); }
  function batchStatusLabel(status) { return BATCH_STATUS_LABEL[status] || String(status || "—"); }
  function jobActive(status) { return status === "QUEUED" || status === "RUNNING"; }

  function statusTag(status, kind) {
    var label = kind === "batch" ? batchStatusLabel(status) : jobStatusLabel(status);
    var cls = "b-gray";
    if (status === "COMPLETE" || status === "done") cls = "b-green";
    else if (status === "RUNNING" || status === "QUEUED" || status === "queued" || status === "running") cls = "b-blue";
    else if (status === "FAILED" || status === "error" || status === "INTERRUPTED") cls = "b-orange";
    return badge(cls, label);
  }

  /* 5s 轮询(对接契约 §9.1):getFn 返回 Promise;isActive(data) 为真继续,否则停止 */
  function poll(getFn, render, isActive, intervalMs) {
    var timer = null;
    var stopped = false;
    function tick() {
      if (stopped) return;
      getFn().then(function (data) {
        if (stopped) return;
        render(data);
        if (!isActive(data)) return;
        timer = setTimeout(tick, intervalMs || 5000);
      }).catch(function () {
        if (!stopped) timer = setTimeout(tick, (intervalMs || 5000) * 2);
      });
    }
    tick();
    return function stop() { stopped = true; if (timer) clearTimeout(timer); };
  }

  /* 模板清单:所有者取完整注册表,匿名取公开选项内的匿名视角 */
  function loadTemplates() {
    if (isOwner()) {
      return get("/api/v1/experiment-templates").then(function (payload) {
        return { templates: (payload && payload.templates) || [], owner: true };
      });
    }
    return get("/api/v1/public/test-options").then(function (payload) {
      var registry = payload && payload.templates && payload.templates.templates;
      return { templates: registry || [], owner: false, options: payload };
    });
  }

  /* 模板卡片(模板中心/发起页共用;P1-4 精简):默认只留名称/目的/受控变量/主按钮;
     「正式单变量」是全站常态不在每卡重复,徽章只表达例外(专项交叉/需登录);
     模板 ID、变量路径、指标与重复范围收进「技术详情」折叠区。 */
  function templateCardHtml(t, locked) {
    var variants = (t.variants || []).map(function (v) { return variantLabel(t, v.label); }).join(" / ");
    var badgeHtml = "";
    var cls = t.classification || "";
    if (cls === "special-cross" || cls === "cross-diagnostic") badgeHtml = classificationBadge(cls);
    var permNote = "";
    if (locked) permNote = '<span class="tpl-perm">仅登录所有者可发起</span>';
    else if (t.owner_allowed === false) permNote = '<span class="tpl-perm">仅匿名测试可发起</span>';
    var range = t.repeat_count_range || [];
    var metrics = (t.result_metrics || []).join("、");
    return '<div class="tpl-card' + (locked ? " locked" : " linked") + '">' +
      '<div class="tpl-head"><span class="tpl-name">' + esc(title(t)) + "</span>" + badgeHtml + "</div>" +
      '<div class="tpl-purpose">' + esc(t.purpose) + "</div>" +
      '<div class="tpl-var">受控变量:<b>' + esc(varLabel(t)) + "</b>" + (variants ? " — " + esc(variants) : "") + "</div>" +
      '<details class="tpl-detail"><summary>技术详情</summary>' +
      '<div class="tpl-tech">' + esc(t.template_id) + " v" + esc(t.version) +
      " · variable: " + esc((t.independent_variable || []).join(",")) + "</div>" +
      (metrics ? '<div class="tpl-tech">指标:' + esc(metrics) + "</div>" : "") +
      '<div class="tpl-tech">重复 ' + esc(range[0] != null ? range[0] : "?") + "–" + esc(range[1] != null ? range[1] : "?") +
      " 次 · 批次上限 " + esc(t.max_runs_per_batch != null ? t.max_runs_per_batch : "?") + " 次运行</div>" +
      "</details>" +
      '<div class="tpl-foot">' + permNote +
      '<span class="tpl-go">' + (locked ? "需登录" : "发起实验 →") + "</span></div></div>";
  }

  /* 状态化进度组件(P0-4 落地为 P2-4 共享组件):进度条仅在「运行中 + 总量已知」时
     渲染真实比例;排队/完成/失败只用阶段文字,不出现满格装饰条或无依据百分比。 */
  function jobProgress(j) {
    var done = j.completed_units || 0;
    var total = j.total_units || 0;
    if (j.status === "RUNNING" && total > 0) {
      var pct = Math.min(100, Math.max(0, Math.round(done * 100 / total)));
      return '<div class="prog" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + pct +
        '" aria-label="已完成 ' + done + " / " + total + ' 个单元">' +
        '<div class="prog-bar" style="width:' + pct + '%"></div></div>' +
        '<small>已完成 ' + done + " / " + total + " 个单元</small>";
    }
    if (j.status === "QUEUED") return '<small class="job-phase">排队中,尚未开始执行</small>';
    if (j.status === "COMPLETE") return '<small class="job-phase">完成 · 共 ' + (total || done) + " 个单元</small>";
    return "";
  }

  /* 运行事件实时流(阶段二,设计 §7.2):fetch ReadableStream 手工解析 SSE——
     所有者鉴权是 Bearer 头(sessionStorage),原生 EventSource 不可行。
     断线以 lastEventId 指数退避重连(服务端按 sequence 续传,客户端只接受
     更大序号去重);收到 run.completed 后回调 onDone 并停止。返回 stop()。 */
  function streamRunEvents(runId, handlers, opts) {
    handlers = handlers || {};
    opts = opts || {};
    var stopped = false;
    var controller = new AbortController();
    var lastEventId = opts.lastEventId || 0;
    var attempt = 0;

    function parseFrame(frame) {
      var sequence = 0, eventType = "", data = "";
      frame.split("\n").forEach(function (line) {
        if (line.indexOf("id:") === 0) sequence = parseInt(line.slice(3).trim(), 10) || 0;
        else if (line.indexOf("event:") === 0) eventType = line.slice(6).trim();
        else if (line.indexOf("data:") === 0) data += line.slice(5).trim();
        /* ": ping" 心跳注释行忽略 */
      });
      if (!eventType || !data) return null;
      try {
        var body = JSON.parse(data);
        return { sequence: body.sequence || sequence, eventType: eventType, payload: body.payload };
      } catch (e) { return null; }
    }

    function connect() {
      if (stopped) return;
      var url = "/api/v1/runs/" + encodeURIComponent(runId) + "/events/stream";
      if (lastEventId > 0) url += "?last_event_id=" + lastEventId;
      var headers = {};
      if (token()) headers["Authorization"] = "Bearer " + token();
      if (lastEventId > 0) headers["Last-Event-ID"] = String(lastEventId);
      fetch(url, { headers: headers, cache: "no-store", signal: controller.signal }).then(function (res) {
        if (!res.ok || !res.body) throw new Error("HTTP " + res.status);
        attempt = 0;
        var reader = res.body.getReader();
        var decoder = new TextDecoder("utf-8");
        var buffer = "";
        function pump() {
          return reader.read().then(function (chunk) {
            if (stopped) { try { reader.cancel(); } catch (e) {} return; }
            buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !chunk.done });
            var frames = buffer.split("\n\n");
            buffer = frames.pop(); // 末段可能是残帧,留在缓冲
            frames.forEach(function (frame) {
              var event = parseFrame(frame);
              if (!event || event.sequence <= lastEventId) return;
              lastEventId = event.sequence;
              if (handlers.onEvent) handlers.onEvent(event);
              if (event.eventType === "run.completed") {
                stopped = true;
                if (handlers.onDone) handlers.onDone(event);
                try { reader.cancel(); } catch (e) {}
              }
            });
            if (chunk.done) throw new Error("服务端关闭了事件流");
            return pump();
          });
        }
        return pump();
      }).catch(function (err) {
        if (stopped || controller.signal.aborted) return;
        attempt += 1;
        var delay = Math.min(15000, 1000 * Math.pow(2, attempt - 1));
        if (handlers.onError) handlers.onError(err, delay);
        setTimeout(connect, delay);
      });
    }

    connect();
    return function stop() { stopped = true; controller.abort(); };
  }

  return {
    ANON_RUN_CAP: ANON_RUN_CAP,
    token: token,
    isOwner: isOwner,
    api: api,
    get: get,
    post: post,
    esc: esc,
    badge: badge,
    classificationBadge: classificationBadge,
    title: title,
    varLabel: varLabel,
    variantLabel: variantLabel,
    hashChip: hashChip,
    copyHash: copyHash,
    fmtTime: fmtTime,
    jobStatusLabel: jobStatusLabel,
    batchStatusLabel: batchStatusLabel,
    jobActive: jobActive,
    statusTag: statusTag,
    poll: poll,
    streamRunEvents: streamRunEvents,
    loadTemplates: loadTemplates,
    templateCardHtml: templateCardHtml,
    jobProgress: jobProgress,
  };
})();
