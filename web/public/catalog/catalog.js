/* 工具目录与用例库:分页组件 + 渲染(公开站零后端,读静态 JSON)。 */
(function (global) {
  "use strict";

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"]/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
    });
  }

  /** 分页渲染引擎 */
  function paginate(container, items, opts) {
    var page = 1;
    var pageSize = opts.pageSize || 20;
    var filtered = items;

    function pages() { return Math.max(1, Math.ceil(filtered.length / pageSize)); }

    function renderTable() {
      var p = pages();
      if (page > p) page = p;
      var start = (page - 1) * pageSize;
      var slice = filtered.slice(start, start + pageSize);
      container.querySelector("[data-cat-table]").innerHTML = opts.renderRows(slice);
      renderPager();
      container.querySelector("[data-cat-count]").textContent =
        filtered.length === 0 ? "无匹配结果" :
        "显示 " + (start + 1) + "–" + Math.min(start + pageSize, filtered.length) + " / 共 " + filtered.length + " 条";
    }

    function renderPager() {
      var p = pages();
      var btns = [];
      btns.push('<button data-pg="prev" ' + (page <= 1 ? "disabled" : "") + ">‹</button>");
      var range = pageRange(page, p);
      range.forEach(function (n) {
        if (n === "…") btns.push('<span class="ellipsis">…</span>');
        else btns.push('<button data-pg="' + n + '" class="' + (n === page ? "active" : "") + '">' + n + "</button>");
      });
      btns.push('<button data-pg="next" ' + (page >= p ? "disabled" : "") + ">›</button>");
      var pager = container.querySelector("[data-cat-pager]");
      pager.innerHTML = btns.join("");
      pager.querySelectorAll("button").forEach(function (b) {
        b.addEventListener("click", function () {
          var v = this.getAttribute("data-pg");
          if (v === "prev") page--; else if (v === "next") page++;
          else page = parseInt(v, 10);
          renderTable();
        });
      });
    }

    function pageRange(cur, total) {
      if (total <= 7) return Array.from({ length: total }, function (_, i) { return i + 1; });
      var s = [1];
      if (cur > 3) s.push("…");
      for (var i = Math.max(2, cur - 1); i <= Math.min(total - 1, cur + 1); i++) s.push(i);
      if (cur < total - 2) s.push("…");
      s.push(total);
      return s;
    }

    var searchInput = container.querySelector("[data-cat-search]");
    if (searchInput) {
      searchInput.addEventListener("input", function () {
        page = 1;
        filtered = opts.filter(items, searchInput.value, getFilterValues());
        renderTable();
      });
    }
    container.querySelectorAll("[data-cat-filter]").forEach(function (sel) {
      sel.addEventListener("change", function () {
        page = 1;
        filtered = opts.filter(items, searchInput ? searchInput.value : "", getFilterValues());
        renderTable();
      });
    });
    function getFilterValues() {
      var vals = {};
      container.querySelectorAll("[data-cat-filter]").forEach(function (sel) {
        vals[sel.getAttribute("data-cat-filter")] = sel.value;
      });
      return vals;
    }

    filtered = opts.filter(items, "", {});
    renderTable();
  }

  // ── 工具列表 ──
  function initToolsList() {
    fetch("/showcase-data/tools.json", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || !data.tools) throw new Error("数据加载失败");
        var domains = Array.from(new Set(data.tools.map(function (t) { return t.domain; }))).sort();
        var sel = document.querySelector("[data-cat-filter='domain']");
        if (sel) domains.forEach(function (d) {
          var o = document.createElement("option"); o.value = d; o.textContent = d; sel.appendChild(o);
        });
        paginate(document, data.tools, {
          pageSize: 20,
          filter: function (items, q, f) {
            return items.filter(function (t) {
              if (f.domain && t.domain !== f.domain) return false;
              if (!q) return true;
              return (t.name + " " + t.description + " " + t.domain).toLowerCase().indexOf(q.toLowerCase()) >= 0;
            });
          },
          renderRows: function (rows) {
            return rows.map(function (t) {
              return "<tr>" +
                '<td><a href="/tools/detail.html?name=' + encodeURIComponent(t.name) + '"><code>' + esc(t.name) + "</code></a></td>" +
                "<td>" + esc(t.description) + "</td>" +
                '<td><span class="cat-badge domain">' + esc(t.domain) + "</span></td>" +
                '<td><span class="cat-badge side-' + esc(t.side_effect) + '">' + esc(t.side_effect) + "</span></td>" +
                '<td><span class="cat-badge risk-' + esc(t.risk_level) + '">' + esc(t.risk_level) + "</span></td>" +
                "<td>" + (t.requires_auth ? "是" : "否") + "</td>" +
                "<td>" + (t.enabled ? "✓" : "—") + "</td>" +
                "</tr>";
            }).join("");
          }
        });
      })
      .catch(function (err) {
        document.querySelector("[data-cat-table]").innerHTML =
          '<tr><td colspan="7" style="text-align:center;color:var(--doc-faint)">加载失败: ' + esc(err.message) + "</td></tr>";
      });
  }

  // ── 用例列表 ──
  function initCasesList() {
    fetch("/showcase-data/cases.json", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || !data.cases) throw new Error("数据加载失败");
        paginate(document, data.cases, {
          pageSize: 20,
          filter: function (items, q, f) {
            return items.filter(function (c) {
              if (f.kind && c.kind !== f.kind) return false;
              if (f.scene && c.scene !== f.scene) return false;
              if (!q) return true;
              return (c.id + " " + (c.title || "") + " " + (c.checks && c.checks.category || "") + " " + (c.message || "")).toLowerCase().indexOf(q.toLowerCase()) >= 0;
            });
          },
          renderRows: function (rows) {
            return rows.map(function (c) {
              return "<tr>" +
                '<td><a href="/cases/detail.html?id=' + encodeURIComponent(c.id) + '"><code>' + esc(c.id) + "</code></a></td>" +
                "<td>" + esc(c.checks && c.checks.category || c.title || "—") + "</td>" +
                '<td><span class="cat-badge kind-' + c.kind + '">' + esc(c.kind_label) + "</span></td>" +
                "<td>" + esc(c.scene) + "</td>" +
                "<td>" + (c.authenticated ? "是" : "否") + "</td>" +
                "<td>" + (c.tool_count || 0) + "</td>" +
                "</tr>";
            }).join("");
          }
        });
      })
      .catch(function (err) {
        document.querySelector("[data-cat-table]").innerHTML =
          '<tr><td colspan="6" style="text-align:center;color:var(--doc-faint)">加载失败: ' + esc(err.message) + "</td></tr>";
      });
  }

  // ── 工具详情 ──
  function initToolDetail() {
    var name = new URLSearchParams(location.search).get("name");
    fetch("/showcase-data/tools.json", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        var tool = data.tools.find(function (t) { return t.name === name; });
        if (!tool) throw new Error("未找到工具: " + name);
        document.title = tool.name + " · 工具目录";

        var h = '<div class="cat-detail-card">';
        h += "<h2 style=\"font-family:ui-monospace,Consolas,monospace;font-size:22px;word-break:break-all\">" + esc(tool.name) + "</h2>";
        h += "<p style=\"font-size:15px;margin-top:4px\">" + esc(tool.description) + "</p>";

        h += '<div class="cat-meta">';
        h += '<span class="cat-meta-item">领域 <span class="cat-badge domain">' + esc(tool.domain) + "</span></span>";
        h += '<span class="cat-meta-item">风险 <span class="cat-badge risk-' + esc(tool.risk_level) + '">' + esc(tool.risk_level) + "</span></span>";
        h += '<span class="cat-meta-item">副作用 <span class="cat-badge side-' + esc(tool.side_effect) + '">' + esc(tool.side_effect) + "</span></span>";
        h += '<span class="cat-meta-item">需登录 <strong>' + (tool.requires_auth ? "是" : "否") + "</strong></span>";
        h += '<span class="cat-meta-item">适配器 <strong>' + esc(tool.adapter) + "</strong></span>";
        h += '<span class="cat-meta-item">状态 <strong>' + (tool.enabled ? "启用" : "停用") + "</strong></span>";
        h += '<span class="cat-meta-item">只读 <strong>' + (tool.read_only ? "是" : "否") + "</strong></span>";
        h += '<span class="cat-meta-item">需确认 <strong>' + (tool.requires_confirmation ? "是" : "否") + "</strong></span>";
        h += '<span class="cat-meta-item">超时 <strong>' + (tool.timeout_seconds || "—") + "s</strong></span>";
        h += "</div>";

        if (tool.required_arguments && tool.required_arguments.length > 0) {
          h += "<h3>必填参数</h3><ul>";
          tool.required_arguments.forEach(function (arg) {
            h += "<li><code>" + esc(arg) + "</code></li>";
          });
          h += "</ul>";
        }

        if (tool.depends_on && tool.depends_on.length > 0) {
          h += "<h3>依赖</h3><p>" + tool.depends_on.map(function (d) { return "<code>" + esc(d) + "</code>"; }).join(" · ") + "</p>";
        }

        if (tool.toolsets && tool.toolsets.length > 0) {
          h += "<h3>所属工具集</h3><p>" + tool.toolsets.map(function (ts) {
            return '<span class="cat-badge domain">' + esc(ts) + "</span>";
          }).join(" ") + "</p>";
        }

        if (tool.operations && tool.operations.length > 0) {
          h += "<h3>操作证</h3><p>" + tool.operations.map(function (op) {
            return "<code>" + esc(op) + "</code>";
          }).join(" · ") + "</p>";
        }

        h += "</div>";
        h += '<p><a href="/tools/">← 返回工具列表</a></p>';
        document.getElementById("toolDetail").innerHTML = h;
      })
      .catch(function (err) {
        document.getElementById("toolDetail").innerHTML =
          '<div class="cat-detail-card"><p>加载失败: ' + esc(err.message) + '</p><p><a href="/tools/">← 返回工具列表</a></p></div>';
      });
  }

  // ── 用例详情 ──
  function initCaseDetail() {
    var id = new URLSearchParams(location.search).get("id");
    fetch("/showcase-data/cases.json", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        var c = data.cases.find(function (x) { return x.id === id; });
        if (!c) throw new Error("未找到用例: " + id);
        document.title = c.id + " · 用例库";

        var checks = c.checks || {};
        var expectedTools = checks.expected_tools || [];
        var expectedOrder = checks.expected_order || [];
        var absentTools = checks.absent_tools || [];
        var expectedParams = checks.expected_params || null;
        var note = checks.note || "";

        var h = '<div class="cat-detail-card">';
        h += "<h2><code>" + esc(c.id) + "</code></h2>";
        h += '<p style="margin-top:4px"><span class="cat-badge kind-' + c.kind + '">' + esc(c.kind_label) + "</span>";
        if (checks.category) h += ' <strong style="margin-left:8px">' + esc(checks.category) + "</strong>";
        if (c.title) h += " · " + esc(c.title);
        h += "</p>";

        h += '<div class="cat-meta">';
        h += '<span class="cat-meta-item">场景 <strong>' + esc(c.scene) + "</strong></span>";
        h += '<span class="cat-meta-item">需登录 <strong>' + (c.authenticated ? "是" : "否") + "</strong></span>";
        h += '<span class="cat-meta-item">版本 <strong>v' + c.current_version + "</strong></span>";
        h += '<span class="cat-meta-item">Token 预算 <strong>' + (c.token_budget || "—") + "</strong></span>";
        h += '<span class="cat-meta-item">状态 <strong>' + esc(c.status) + "</strong></span>";
        h += "</div>";

        // 问题描述(核心内容,突出展示)
        h += '<h3 style="margin-top:20px">问题描述</h3>';
        h += '<div style="background:#f8f9fc;border-left:3px solid var(--doc-accent);border-radius:0 8px 8px 0;padding:16px 20px;font-size:14.5px;line-height:1.7;color:var(--doc-text)">' + esc(c.message) + "</div>";

        // 期望工具链
        if (expectedTools.length > 0) {
          h += '<h3 style="margin-top:24px">期望工具(' + expectedTools.length + " 个)</h3>";
          if (expectedOrder.length === expectedTools.length) {
            h += '<p style="font-size:12.5px;color:var(--doc-faint);margin-bottom:8px">按期望调用顺序:</p>';
            h += '<ol class="cat-tool-chain">';
            expectedOrder.forEach(function (t, i) {
              h += '<li><a href="/tools/detail.html?name=' + encodeURIComponent(t) + '"><code>' + esc(t) + "</code></a></li>";
            });
            h += "</ol>";
          } else {
            h += '<ul style="list-style:none;padding:0">';
            expectedTools.forEach(function (t) {
              h += '<li style="padding:6px 0;border-bottom:1px solid #eef1f6"><a href="/tools/detail.html?name=' + encodeURIComponent(t) + '"><code>' + esc(t) + "</code></a></li>";
            });
            h += "</ul>";
          }
        }

        // 期望参数
        if (expectedParams) {
          h += '<h3 style="margin-top:20px">期望参数</h3>';
          h += '<pre class="cat-schema">' + esc(JSON.stringify(expectedParams, null, 2)) + "</pre>";
        }

        // 禁止工具
        if (absentTools.length > 0) {
          h += '<h3 style="margin-top:20px">禁止调用的工具(' + absentTools.length + " 个)</h3>";
          h += "<p>" + absentTools.map(function (t) {
            return '<span class="cat-badge risk-high">' + esc(t) + "</span>";
          }).join(" ") + "</p>";
        }

        // 备注
        if (note) {
          h += '<h3 style="margin-top:20px">设计说明</h3>';
          h += '<p style="font-size:13px;color:var(--doc-dim)">' + esc(note) + "</p>";
        }

        h += "</div>";
        h += '<p><a href="/cases/">← 返回用例列表</a></p>';
        document.getElementById("caseDetail").innerHTML = h;
      })
      .catch(function (err) {
        document.getElementById("caseDetail").innerHTML =
          '<div class="cat-detail-card"><p>加载失败: ' + esc(err.message) + '</p><p><a href="/cases/">← 返回用例列表</a></p></div>';
      });
  }

  global.CATALOG = {
    initToolsList: initToolsList,
    initCasesList: initCasesList,
    initToolDetail: initToolDetail,
    initCaseDetail: initCaseDetail
  };
})(globalThis);
