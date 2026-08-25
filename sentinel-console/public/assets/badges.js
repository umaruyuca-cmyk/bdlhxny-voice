/**
 * 全局徽标组件（设计文档 §7.2）：审计码 / 证据编号 / 演示注入水印 / 严重度色条。
 * 看护首页、通知卡、追问上下文共用，禁止各页自造样式名词。
 */
(function (root) {
  "use strict";

  var AUDIT_HINTS = {
    "RO-OK": "只读校验通过",
    "DQ-OK": "数据质量正常",
    "DQ-STALE": "数据新鲜度不足",
    "LLM_UNAVAILABLE": "语言模型不可用",
    "SEMANTIC_FORBIDDEN": "语义快路径禁止",
    "GUARDRAIL_BLOCKED": "治理中间件拦截"
  };

  function esc(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function audit(code) {
    var value = String(code || "").trim();
    if (!value) return "";
    var hint = AUDIT_HINTS[value] || "审计码";
    return (
      '<span class="badge-audit" title="' +
      esc(hint) +
      '">' +
      esc(value) +
      "</span>"
    );
  }

  function evidence(refs, options) {
    var list = Array.isArray(refs) ? refs : [];
    return list
      .map(function (ref, index) {
        var label = String(index + 1);
        var title = String(ref || "");
        return (
          '<button type="button" class="badge-evidence" data-evidence="' +
          esc(title) +
          '" title="' +
          esc(title) +
          '">[' +
          esc(label) +
          "]</button>"
        );
      })
      .join("");
  }

  function demoWatermark() {
    return '<span class="badge-demo" title="演示注入（C-4）">演示注入</span>';
  }

  function severityBar(severity) {
    var level = String(severity || "info").toLowerCase();
    if (level !== "warning" && level !== "critical") level = "info";
    return '<span class="badge-severity badge-severity-' + level + '" aria-hidden="true"></span>';
  }

  function isDemoSource(source, payload) {
    if (String(source || "") === "demo_inject") return true;
    if (payload && payload.demo === true) return true;
    return false;
  }

  root.SentinelBadges = {
    audit: audit,
    evidence: evidence,
    demoWatermark: demoWatermark,
    severityBar: severityBar,
    isDemoSource: isDemoSource,
    esc: esc
  };
})(typeof window !== "undefined" ? window : globalThis);
