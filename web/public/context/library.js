/* 长上下文库页渲染:静态列表 + 登录后按需压缩测试(不发起模型调用)。
 * 公开态零后端依赖;压缩按钮仅在持有会话令牌时出现,调用私有运行 API。 */
(function () {
  "use strict";

  var RUN_API = window.__RUN_API__ || "http://127.0.0.1:8090";
  var listEl = document.getElementById("libraryList");
  var panelEl = document.getElementById("compressPanel");

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"]/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
    });
  }

  function logged() {
    try {
      return !!sessionStorage.getItem("lab_token");
    } catch (err) {
      return false;
    }
  }

  function token() {
    try {
      return sessionStorage.getItem("lab_token") || "";
    } catch (err) {
      return "";
    }
  }

  function renderCompressReport(report, meta) {
    if (!report) return '<div class="placeholder-block">压缩测试无返回。</div>';
    var ratio = report.original_tokens > 0 ? Math.round((report.working_tokens / report.original_tokens) * 100) : null;
    var rows = (report.decisions || []).slice(0, 40).map(function (d) {
      return "<tr><td><code>" + esc(d.item_id) + "</code></td><td>" + esc(d.action) + "</td><td>" +
        esc(d.input_tokens) + " → " + esc(d.output_tokens) + "</td><td>" + esc(d.reason) + "</td></tr>";
    }).join("");
    var counts = report.counts || {};
    return '<div class="note"><strong>' + esc(meta.case_id) + " 压缩测试结果</strong>(budgeted,预算 " +
      esc(report.token_budget) + " token,口径 " + esc(report.tokenizer_version) + ")</div>" +
      '<table><thead><tr><th>指标</th><th>值</th></tr></thead><tbody>' +
      "<tr><td>原始 token</td><td>" + esc(report.original_tokens) + "</td></tr>" +
      "<tr><td>工作 token</td><td>" + esc(report.working_tokens) + (ratio == null ? "" : "(为原文的 " + ratio + "%)") + "</td></tr>" +
      "<tr><td>强制项保留</td><td>" + (report.required_retained ? "是(100%)" : '<span style="color:#b23b3b">否</span>') + "</td></tr>" +
      "<tr><td>条目决策计数</td><td>保留 " + esc(counts.kept) + " / 压缩 " + esc(counts.compressed) +
        " / 引用 " + esc(counts.referenced) + " / 隔离 " + esc(counts.isolated) + " / 省略 " + esc(counts.omitted) + "</td></tr>" +
      "</tbody></table>" +
      (rows ? '<details class="metric-def" open><summary>逐条决策(前 40 条)</summary><table><thead><tr><th>条目</th><th>决策</th><th>token</th><th>原因</th></tr></thead><tbody>' +
        rows + "</tbody></table></details>" : "");
  }

  function runCompress(meta) {
    var box = document.getElementById("compress-result-" + meta.case_id);
    if (!box) return;
    box.innerHTML = '<p class="lab-note">压缩中…(只跑构建器,不调用模型)</p>';
    fetch(RUN_API + "/api/v1/context-compress", {
      method: "POST",
      headers: { Authorization: "Bearer " + token(), "Content-Type": "application/json" },
      body: JSON.stringify({ case_id: meta.case_id }),
    })
      .then(function (res) {
        return res.json().then(function (body) { return { status: res.status, body: body }; });
      })
      .then(function (outcome) {
        if (outcome.status === 401) {
          box.innerHTML = '<p class="lab-note">会话已失效:请重新登录后再试。</p>';
          return;
        }
        if (outcome.status !== 200) {
          throw new Error((outcome.body && outcome.body.detail) || ("HTTP " + outcome.status));
        }
        box.innerHTML = renderCompressReport(outcome.body, meta);
      })
      .catch(function (err) {
        box.innerHTML = '<p class="lab-note">压缩测试失败:' + esc(err.message) + "(私有运行 API 未启动或不可达)</p>";
      });
  }

  function renderList(payload) {
    var cases = (payload && payload.cases) || [];
    if (!cases.length) {
      listEl.innerHTML = '<div class="placeholder-block">长上下文库为空。</div>';
      return;
    }
    var isLogged = logged();
    var rows = cases.map(function (meta) {
      var counts = meta.item_counts || {};
      var marks = [
        meta.has_injection ? '<span class="badge INVALID" title="含 untrusted 注入条目">注入</span>' : "",
        meta.has_cross_user ? '<span class="badge INVALID" title="含跨用户条目(应被隔离)">跨用户</span>' : "",
        meta.has_stale ? '<span class="badge INVALID" title="含过期条目(不得入答案)">过期</span>' : "",
      ].join(" ");
      var compressBtn = isLogged
        ? '<button type="button" class="ctx-compress-btn" data-case="' + esc(meta.case_id) + '">压缩测试</button>'
        : "";
      var linkBtn = isLogged
        ? ' <a class="ctx-link-btn" href="/lab/?link=' + encodeURIComponent(meta.case_id) + '">联动对照</a>'
        : "";
      return "<tr><td><code>" + esc(meta.case_id) + "</code></td>" +
        "<td>" + esc(meta.direction) + "</td>" +
        "<td>" + esc(meta.message) + "</td>" +
        "<td>约 " + esc(meta.token_estimate) + "</td>" +
        "<td>" + esc(meta.item_count) + " 条(强制 " + esc(counts.required) + " / 可压缩 " + esc(counts.compressible) +
          " / 仅引用 " + esc(counts.reference_only || 0) + " / 干扰 " + esc(counts.distractor) + ")</td>" +
        "<td>" + esc(meta.variants.full_raw.token_budget) + " / " + esc(meta.variants.budgeted_comp.token_budget) + "</td>" +
        "<td>" + (marks || "—") + "</td>" +
        '<td><a href="' + esc(meta.txt) + '" download>原文 .txt</a></td>' +
        "<td>" + compressBtn + linkBtn + "</td></tr>" +
        '<tr class="ctx-compress-row" hidden><td colspan="9" id="compress-result-' + esc(meta.case_id) + '"></td></tr>';
    }).join("");
    listEl.innerHTML = '<table><thead><tr><th>题号</th><th>内容方向</th><th>问题</th><th>token 估算</th><th>条目构成</th>' +
      "<th>预算 full / 压缩</th><th>对抗标记</th><th>原文</th><th>操作</th></tr></thead><tbody>" + rows + "</tbody></table>" +
      (isLogged ? "" : '<p class="lab-note">登录后此列出现「压缩测试」与「联动对照」按钮(公开浏览不提供)。</p>');
    Array.prototype.slice.call(listEl.querySelectorAll(".ctx-compress-btn")).forEach(function (btn) {
      btn.addEventListener("click", function () {
        var caseId = btn.getAttribute("data-case");
        var meta = cases.filter(function (c) { return c.case_id === caseId; })[0];
        var row = btn.closest("tr").nextElementSibling;
        if (row) row.hidden = !row.hidden;
        if (row && !row.hidden) runCompress(meta || { case_id: caseId });
      });
    });
  }

  function renderPanel() {
    if (!panelEl) return;
    if (logged()) {
      panelEl.classList.remove("placeholder-block");
      panelEl.innerHTML = "<p>已登录:点击上表每行的「压缩测试」,按该用例压缩变体预算现场执行一次构建器,展示原始/工作 token 与逐条决策;「联动对照」跳转运行台,用原始与压缩内容分别跑三组实现。</p>";
    } else {
      panelEl.innerHTML = "<p>压缩测试与联动对照按钮仅登录后显示:登录入口在右上角,登录成功后自动进入运行台,再回到本页即可看到按钮。</p>";
    }
  }

  fetch("/showcase-data/context-library.json", { cache: "no-store" })
    .then(function (res) { return res.ok ? res.json() : null; })
    .then(renderList)
    .catch(function () {
      listEl.innerHTML = '<div class="placeholder-block">长上下文库数据缺失(待 generate-context-library 产物)。</div>';
    });
  renderPanel();
})();
