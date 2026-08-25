/**
 * ResultBlock 渲染器注册表（设计文档 §7.8）。
 * block.type → 组件；未知类型降级为折叠 JSON，不报错、不丢弃。
 * 数字只展示工具 payload，前端不重算综合分。
 */
(function (root) {
  "use strict";

  var SUITABILITY_DISCLOSURE = "本结果仅为风险匹配筛查草稿，不构成投资建议。";
  var _seq = 0;

  function esc(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function num(value, digits) {
    var n = Number(value);
    if (!Number.isFinite(n)) return esc(value == null ? "—" : value);
    return n.toLocaleString("zh-CN", { maximumFractionDigits: digits == null ? 2 : digits });
  }

  function trend(value) {
    var key = String(value || "").toLowerCase();
    if (key === "up" || key === "▲") return "▲";
    if (key === "down" || key === "▼") return "▼";
    return "→";
  }

  function registry() {
    return {
      ScoreCard: renderScoreCard,
      AnalysisReport: renderAnalysisReport,
      SuitabilityDraft: renderSuitabilityDraft,
      PortfolioHealth: renderPortfolioHealth,
      QuoteTable: renderQuoteTable
    };
  }

  function render(block) {
    var type = block && block.type;
    var payload = (block && block.payload) || {};
    var fn = registry()[type];
    var html = fn ? fn(payload, block) : renderUnknown(block);
    return '<article class="result-block" data-block-type="' + esc(type || "Unknown") + '">' + html + "</article>";
  }

  function renderAll(blocks) {
    if (!Array.isArray(blocks) || !blocks.length) return "";
    return '<div class="result-blocks">' + blocks.map(render).join("") + "</div>";
  }

  function mount(host, blocks) {
    if (!host) return;
    host.innerHTML = renderAll(blocks);
    hydrate(host);
    bindQuoteSort(host);
  }

  function isForbiddenConclusion(text) {
    return /适合|推荐买入/.test(String(text || ""));
  }

  function renderScoreCard(payload, block) {
    var dims = Array.isArray(payload.dimensions) ? payload.dimensions : [];
    var chartId = "score-radar-" + ++_seq;
    var rows = dims
      .map(function (dim) {
        var score = Number(dim.score);
        var width = Number.isFinite(score) ? Math.max(0, Math.min(100, score)) : 0;
        var findings = (dim.findings || [])
          .map(function (item) {
            return "<li>" + esc(item) + "</li>";
          })
          .join("");
        return (
          '<div class="score-dim"><span>' +
          esc(dim.name) +
          '</span><i style="width:' +
          width +
          '%"></i><b>' +
          esc(score) +
          "</b> " +
          trend(dim.trend) +
          (findings
            ? ' <details class="score-detail"><summary>明细</summary><ul>' + findings + "</ul></details>"
            : "") +
          "</div>"
        );
      })
      .join("");
    return (
      '<header class="block-head">' +
      esc(payload.name || "") +
      " " +
      esc(payload.symbol || "") +
      " · 综合评分</header>" +
      '<div class="score-layout"><div class="score-chart" id="' +
      chartId +
      '" data-dims="' +
      esc(JSON.stringify(dims)) +
      '"></div>' +
      '<div class="score-summary"><strong>' +
      esc(payload.overall) +
      " / " +
      esc(payload.scale || 100) +
      "</strong><span>" +
      esc(payload.rating || "") +
      '</span><small>' +
      esc((block && block.data_time) || payload.data_time || "") +
      "</small></div></div>" +
      '<div class="score-dims">' +
      rows +
      "</div>" +
      '<footer class="block-foot">评分由服务端确定性加权；前端不重算。</footer>'
    );
  }

  function renderAnalysisReport(payload) {
    var dims = Array.isArray(payload.dimensions) ? payload.dimensions : [];
    return (
      '<header class="block-head">分析明细</header>' +
      dims
        .map(function (dim, index) {
          var findings = (dim.findings || [])
            .map(function (item) {
              return "<li>" + esc(item) + "</li>";
            })
            .join("");
          var metrics = dim.metrics || {};
          var kv = Object.keys(metrics)
            .map(function (key) {
              return "<tr><th>" + esc(key) + "</th><td>" + num(metrics[key]) + "</td></tr>";
            })
            .join("");
          return (
            "<details class=\"report-dim\"" +
            (index === 0 ? " open" : "") +
            "><summary>" +
            esc(dim.name || "维度") +
            "</summary><ul>" +
            findings +
            "</ul><table class=\"quote-table\">" +
            kv +
            "</table></details>"
          );
        })
        .join("")
    );
  }

  function renderSuitabilityDraft(payload) {
    var matches = (Array.isArray(payload.matches) ? payload.matches : []).filter(function (item) {
      return !isForbiddenConclusion(item);
    });
    var risks = (Array.isArray(payload.risks) ? payload.risks : []).filter(function (item) {
      return !isForbiddenConclusion(item);
    });
    return (
      '<header class="block-head">风险匹配筛查（DRAFT · 非适当性结论）</header>' +
      '<div class="suit-grid"><section><h4>匹配项</h4><ul>' +
      (matches.length
        ? matches.map(function (item) { return "<li>✓ " + esc(item) + "</li>"; }).join("")
        : "<li class=\"muted\">暂无匹配项</li>") +
      "</ul></section><section><h4>风险项</h4><ul>" +
      (risks.length
        ? risks.map(function (item) { return "<li>⚠ " + esc(item) + "</li>"; }).join("")
        : "<li class=\"muted\">暂无风险项</li>") +
      "</ul></section></div>" +
      '<p class="suit-disclosure">' +
      esc(SUITABILITY_DISCLOSURE) +
      "</p>"
    );
  }

  function renderPortfolioHealth(payload, block) {
    var chartId = "port-pie-" + ++_seq;
    var sectors = Array.isArray(payload.sectors) ? payload.sectors : [];
    var risks = (payload.risks || []).map(function (item) { return "<li>" + esc(item) + "</li>"; }).join("");
    return (
      '<header class="block-head">组合诊断</header>' +
      '<div class="port-metrics"><span>HHI <i style="width:' +
      Math.max(4, Math.min(100, Number(payload.hhi) * 100)) +
      '%"></i> ' +
      num(payload.hhi, 4) +
      "</span><span>前三大 <i style=\"width:" +
      Math.max(4, Math.min(100, Number(payload.top3_weight) * 100)) +
      '%"></i> ' +
      num(Number(payload.top3_weight) * 100, 1) +
      '%</span></div><div class="score-chart" id="' +
      chartId +
      '" data-sectors="' +
      esc(JSON.stringify(sectors)) +
      '"></div><ul>' +
      risks +
      "</ul>"
    );
  }

  function renderQuoteTable(payload) {
    var columns = Array.isArray(payload.columns) ? payload.columns : Object.keys((payload.rows && payload.rows[0]) || {});
    var rows = Array.isArray(payload.rows) ? payload.rows : [];
    var head = columns
      .map(function (col, index) {
        return '<th data-col="' + index + '" role="button" tabindex="0">' + esc(col) + "</th>";
      })
      .join("");
    var body = rows
      .map(function (row) {
        return (
          "<tr>" +
          columns
            .map(function (col) {
              var value = row[col];
              var cls = Number(value) > 0 ? "num-up" : Number(value) < 0 ? "num-down" : "";
              return '<td class="' + cls + '">' + (typeof value === "number" ? num(value) : esc(value)) + "</td>";
            })
            .join("") +
          "</tr>"
        );
      })
      .join("");
    return '<header class="block-head">行情表</header><table class="quote-table"><thead><tr>' + head + "</tr></thead><tbody>" + body + "</tbody></table>";
  }

  function renderUnknown(block) {
    return (
      '<details class="block-unknown"><summary>未知结果块 ' +
      esc(block && block.type) +
      "</summary><pre>" +
      esc(JSON.stringify(block, null, 2)) +
      "</pre></details>"
    );
  }

  function hydrate(rootEl) {
    if (!rootEl || !window.echarts) return;
    rootEl.querySelectorAll("[id^='score-radar-']").forEach(function (el) {
      var dims = [];
      try { dims = JSON.parse(el.getAttribute("data-dims") || "[]"); } catch (err) {}
      var chart = window.echarts.init(el);
      chart.setOption({
        radar: { indicator: dims.map(function (d) { return { name: d.name, max: 100 }; }) },
        series: [{ type: "radar", data: [{ value: dims.map(function (d) { return Number(d.score) || 0; }) }] }]
      });
    });
    rootEl.querySelectorAll("[id^='port-pie-']").forEach(function (el) {
      var sectors = [];
      try { sectors = JSON.parse(el.getAttribute("data-sectors") || "[]"); } catch (err) {}
      var chart = window.echarts.init(el);
      chart.setOption({
        series: [{
          type: "pie",
          radius: ["40%", "70%"],
          data: sectors.map(function (s) { return { name: s.name, value: s.weight }; })
        }]
      });
    });
  }

  function bindQuoteSort(rootEl) {
    if (!rootEl) return;
    rootEl.querySelectorAll("table.quote-table").forEach(function (table) {
      table.querySelectorAll("th[data-col]").forEach(function (th) {
        th.addEventListener("click", function () {
          var idx = Number(th.getAttribute("data-col"));
          var tbody = table.tBodies[0];
          if (!tbody) return;
          var rows = Array.prototype.slice.call(tbody.rows);
          var dir = th.getAttribute("data-dir") === "asc" ? "desc" : "asc";
          th.setAttribute("data-dir", dir);
          rows.sort(function (a, b) {
            var av = a.cells[idx] ? a.cells[idx].textContent : "";
            var bv = b.cells[idx] ? b.cells[idx].textContent : "";
            var an = Number(String(av).replace(/,/g, ""));
            var bn = Number(String(bv).replace(/,/g, ""));
            var cmp =
              Number.isFinite(an) && Number.isFinite(bn) ? an - bn : String(av).localeCompare(String(bv), "zh-CN");
            return dir === "asc" ? cmp : -cmp;
          });
          rows.forEach(function (row) {
            tbody.appendChild(row);
          });
        });
      });
    });
  }

  root.SentinelBlocks = {
    render: render,
    renderAll: renderAll,
    mount: mount,
    hydrate: hydrate,
    SUITABILITY_DISCLOSURE: SUITABILITY_DISCLOSURE
  };
})(typeof window !== "undefined" ? window : globalThis);
