/* 长上下文库页渲染:三套场景化冻结 Session。
 * 仓库文件只作为 Session 内的冻结工具结果出现；公开态零后端依赖。 */
(function () {
  "use strict";

  var listEl = document.getElementById("libraryList");
  var panelEl = document.getElementById("compressPanel");

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"]/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
    });
  }
  function num(v, suffix) { return v == null ? "—" : String(v) + (suffix || ""); }
  function pct(v) { return v == null ? "—" : v + "%"; }

  var KIND_BADGE = {
    session: '<span class="tag ok">完整 Session</span>',
  };

  function statsLine(entry) {
    var s = entry.stats || {};
    if (entry.kind_key === "session") {
      return s.event_count + " 个事件(用户 " + s.user_messages + " / 助手 " + s.assistant_messages +
        " / 工具对 " + s.tool_pairs + " / 失败 " + s.failed_tool_pairs + ")· " +
        window.SITE.fmtDate(s.first_at) + " ~ " + window.SITE.fmtDate(s.last_at);
    }
    return "—";
  }

  function sourceMaterialsBlock(entry) {
    var sources = entry.source_materials || [];
    if (!sources.length) return "";
    return '<details class="metric-def"><summary>Session 内使用的仓库材料(' + sources.length + ")</summary><ul>" +
      sources.map(function (source) { return "<li><code>" + esc(source) + "</code></li>"; }).join("") +
      "</ul></details>";
  }

  function strategiesBlock(entry) {
    var strategies = entry.strategies || [];
    if (!strategies.length) return "";
    return '<h4 style="margin:14px 0 6px;font-size:13.5px">四种处理策略实测(编译冻结工件)</h4>' +
      '<table><thead><tr><th>策略</th><th>版本</th><th>预算</th><th>原文 → 工作 token</th><th>压缩</th><th>事件桶 保留/压缩/引用/省略</th><th>构建耗时</th></tr></thead><tbody>' +
      strategies.map(function (s) {
        return "<tr><td>" + esc(s.title) + "</td><td><code>" + esc(s.strategy_version) + "</code></td><td>" + num(s.token_budget) + "</td>" +
          "<td>" + num(s.original_tokens) + " → <strong>" + num(s.working_tokens) + "</strong></td>" +
          "<td>" + pct(s.compression_pct == null ? null : s.compression_pct) + "</td>" +
          "<td>" + num(s.kept) + " / " + num(s.compressed) + " / " + num(s.referenced) + " / " + num(s.omitted) + "</td>" +
          "<td>" + num(s.build_duration_ms, " ms") + "</td></tr>";
      }).join("") + "</tbody></table>" +
      "";
  }

  function renderList(payload) {
    var entries = (payload && payload.entries) || [];
    if (!entries.length) {
      listEl.innerHTML = '<div class="placeholder-block">长上下文库为空。</div>';
      return;
    }
    var cards = entries.map(function (e) {
      return '<div class="doc-card" style="padding:16px 18px">' +
        '<h3 style="margin:0 0 6px;font-size:15px">' + esc(e.title) + " " + (KIND_BADGE[e.kind_key] || "") + "</h3>" +
        '<p style="margin:0 0 8px;font-size:13px;color:var(--doc-dim);line-height:1.6">' + esc(e.summary || "") + "</p>" +
        '<div class="note" style="margin:8px 0"><strong>语料说明</strong>：' + esc(e.disclosure || "场景化冻结 Session。") + "</div>" +
        '<div class="kv"><span>规模</span><b>' + statsLine(e) + "</b></div>" +
        '<div class="kv"><span>原始 Session token</span><b>' + num(e.original_tokens) + "</b></div>" +
        '<details class="metric-def"><summary>本用例的当前问题</summary><p>' + esc(e.current_question || "") + "</p></details>" +
        '<div class="kv"><span>原文下载</span><b><a href="' + esc(e.txt) + '" download>' + esc(e.id) + '.txt</a></b></div>' +
        '<div class="kv"><span>进入实验</span><b><a href="/experiment/compression?session_id=' + encodeURIComponent(e.id) + '">压缩用例实验</a></b></div>' +
        strategiesBlock(e) +
        sourceMaterialsBlock(e) +
        "</div>";
    }).join("\n");
    listEl.innerHTML =
      '<div class="note"><strong>语料来源</strong>：' + esc(payload.generated_from || "场景化冻结 Session") +
      " · 口径 " + esc(payload.tokenizer_version || "") + "</div>" +
      '<div class="doc-grid" style="grid-template-columns:repeat(auto-fill,minmax(420px,1fr))">' + cards + "</div>";
  }

  fetch("/showcase-data/context-library.json", { cache: "no-store" })
    .then(function (res) { return res.ok ? res.json() : null; })
    .then(renderList)
    .catch(function () {
      listEl.innerHTML = '<div class="placeholder-block">长上下文库数据缺失(待 generate-context-library 产物)。</div>';
    });
  if (panelEl) panelEl.innerHTML = "";
})();
