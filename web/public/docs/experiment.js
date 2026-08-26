/* 实验模块共享脚本(前后端对接契约 v1):
   同源 API 访问(匿名 Cookie / 所有者 Bearer)、类型徽章、哈希 chip、轮询。
   依赖:页面自身保证相对路径 /api/v1/* 可达(部署层反代到 engine)。 */
window.EXP = (function () {
  "use strict";

  var ANON_RUN_CAP = 8; // 匿名角色运行数上限(plan_template_batch 角色上限)

  function token() { return sessionStorage.getItem("lab_token") || ""; }
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
    if (!value) return "—";
    var text = String(value).replace("T", " ").replace("Z", "");
    return text.length > 19 ? text.slice(0, 19) : text;
  }

  var JOB_STATUS_LABEL = {
    QUEUED: "排队中", RUNNING: "进行中", COMPLETE: "已完成", PARTIAL: "部分完成",
    FAILED: "失败", CANCELLED: "已取消", INTERRUPTED: "已中断",
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

  /* 模板卡片(模板中心/发起页共用):目的、受控变量与变体、技术口径行 */
  function templateCardHtml(t, locked) {
    var variants = (t.variants || []).map(function (v) { return variantLabel(t, v.label); }).join(" / ");
    var perm = t.owner_allowed === false ? "仅匿名" : (t.anonymous_allowed ? "免登录可用" : "仅登录所有者");
    return '<div class="tpl-card' + (locked ? " locked" : " linked") + '">' +
      '<div class="tpl-head"><span class="tpl-name">' + esc(title(t)) + "</span>" +
      classificationBadge(t.classification) + "</div>" +
      '<div class="tpl-purpose">' + esc(t.purpose) + "</div>" +
      '<div class="tpl-var">受控变量:<b>' + esc(varLabel(t)) + "</b>" + (variants ? " — " + esc(variants) : "") + "</div>" +
      '<div class="tpl-tech">' + esc(t.template_id) + " v" + esc(t.version) + " · variable: " + esc((t.independent_variable || []).join(",")) + "</div>" +
      '<div class="tpl-foot"><span class="tpl-perm">' + perm + (locked ? " · 需登录后发起" : "") + "</span>" +
      '<span class="tpl-go">' + (locked ? "需登录" : "发起实验 →") + "</span></div></div>";
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
    loadTemplates: loadTemplates,
    templateCardHtml: templateCardHtml,
  };
})();
