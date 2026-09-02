/* 系统总览页数据块:只读正式批次索引,渲染最新发布状态。
 * 索引缺失(尚未发布)时保持真实空状态;不回退旧批次,不用构成数字冒充成绩。 */
(function () {
  "use strict";

  var S = window.SITE;
  var SC = window.SHOWCASE;

  function el(id) { return document.getElementById(id); }

  function renderEmpty(box) {
    box.innerHTML =
      '<div class="placeholder-block"><strong>尚无正式实验结果。</strong>' +
      "正式批次由维护者在私有侧运行并经发布校验后登记;当前公开快照中没有正式批次," +
      "因此这里没有实验数字。系统构成与执行方式见下方说明与「执行逻辑」页。</div>";
  }

  function renderIndex(box, index) {
    var batches = (index.formal_batches || []).filter(function (b) { return b.is_formal; });
    if (batches.length === 0) { renderEmpty(box); return; }
    var latest = index.latest_batch && index.latest_batch.is_formal ? index.latest_batch : null;
    var ref = latest || batches[0];
    var html = '<div class="fact-row">' +
      '<div class="fact"><b>' + S.fmtInt(batches.length) + '</b><span>正式发布批次</span></div>' +
      '<div class="fact"><b>' + S.fmtInt(ref.case_count) + '</b><span>最新批次用例数</span></div>' +
      '<div class="fact"><b>' + S.fmtInt(ref.runs_per_case) + '</b><span>每用例重复次数</span></div>' +
      '<div class="fact"><b>' + S.esc(ref.model) + '</b><span>运行模型</span></div>' +
      "</div>" +
      '<table class="kv"><tbody>' +
      "<tr><th>最新批次</th><td><span class=\"hash\">" + S.esc(ref.batch_id) + "</span>" +
      ' <a href="/results/?batch=' + encodeURIComponent(ref.batch_id) + '">查看结果</a>' +
      ' · <a href="/evidence/?batch=' + encodeURIComponent(ref.batch_id) + '">查看证据</a></td></tr>' +
      "<tr><th>发布时间</th><td>" + S.fmtTime(ref.published_at) + "</td></tr>" +
      "<tr><th>代码版本</th><td><span class=\"hash\">" + S.esc(ref.git_commit) + "</span></td></tr>" +
      "</tbody></table>" +
      '<p class="note">实验结论与逐项指标在「实验结果」页按批次展开;每个数字可下钻到支持它的单次运行证据。</p>';
    box.innerHTML = html;
  }

  async function init() {
    var box = el("homePublication");
    if (!box) return;
    var index = await SC.loadIndex();
    if (!index || !Array.isArray(index.formal_batches)) {
      box.innerHTML = '<div class="placeholder-block">发布索引不可读:当前没有可展示的正式批次。</div>';
      return;
    }
    renderIndex(box, index);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
