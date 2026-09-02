/* 站点共享脚本(信息架构 v3):导航高亮增强 + 全站统一的数字/时间格式化 + 复制按钮。
 * 本站为纯静态展示:不调用任何后端 API,不读写会话存储,不提供登录或发起入口。
 * 静态导航已由站点生成器写入页面 HTML,本脚本只做活动态增强;禁用脚本也可完整浏览。 */
(function () {
  "use strict";

  var NAV = [
    { href: "/", match: function (p) { return p === "/" || p === "/index.html"; } },
    { href: "/results/", match: function (p) { return p.indexOf("/results") === 0; } },
    { href: "/evidence/", match: function (p) { return p.indexOf("/evidence") === 0; } },
    { href: "/system/", match: function (p) { return p.indexOf("/system") === 0; } },
    { href: "/methodology/", match: function (p) { return p.indexOf("/methodology") === 0; } },
  ];

  (function highlightNav() {
    var nav = document.querySelector("nav.site-nav");
    if (!nav) return;
    var path = location.pathname;
    var links = Array.prototype.slice.call(nav.querySelectorAll("a"));
    links.forEach(function (a) {
      var item = NAV.filter(function (n) { return n.href === a.getAttribute("href"); })[0];
      if (item && item.match(path)) a.classList.add("on");
    });
  })();

  (function highlightToc() {
    var toc = document.querySelector(".page-toc");
    if (!toc || !("IntersectionObserver" in window)) return;
    var links = Array.prototype.slice.call(toc.querySelectorAll('a[href^="#"]'));
    var map = {};
    links.forEach(function (a) { map[a.getAttribute("href").slice(1)] = a; });
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        var link = map[entry.target.id];
        if (link && entry.isIntersecting) {
          links.forEach(function (a) { a.classList.remove("on"); });
          link.classList.add("on");
        }
      });
    }, { rootMargin: "-20% 0px -70% 0px" });
    Object.keys(map).forEach(function (id) {
      var el = document.getElementById(id);
      if (el) observer.observe(el);
    });
  })();

  var p2 = function (n) { return (n < 10 ? "0" : "") + n; };

  window.SITE = {
    /** 全站统一时间格式:yyyy-MM-dd HH:mm:ss(本地时区);无效值返回「未记录」。 */
    fmtTime: function (value) {
      if (!value) return "未记录";
      var d = new Date(value);
      if (isNaN(d.getTime())) return "未记录";
      return d.getFullYear() + "-" + p2(d.getMonth() + 1) + "-" + p2(d.getDate()) + " " +
        p2(d.getHours()) + ":" + p2(d.getMinutes()) + ":" + p2(d.getSeconds());
    },
    /** 整数:千分位;无效值返回「未记录」。 */
    fmtInt: function (value) {
      var n = Number(value);
      if (!Number.isFinite(n)) return "未记录";
      return n.toLocaleString("zh-CN");
    },
    /** 比例 [0,1]:百分数一位小数;null/undefined 显示「未记录」。 */
    fmtPct: function (value) {
      var n = Number(value);
      if (!Number.isFinite(n)) return "未记录";
      return (n * 100).toFixed(1) + "%";
    },
    /** 耗时:<1s 用 ms,<60s 用 s,其余用「X 分 Y 秒」。 */
    fmtMs: function (value) {
      var n = Number(value);
      if (!Number.isFinite(n)) return "未记录";
      if (n < 1000) return Math.round(n) + " ms";
      if (n < 60000) return (n / 1000).toFixed(1) + " s";
      var m = Math.floor(n / 60000);
      var s = Math.round((n % 60000) / 1000);
      return m + " 分 " + p2(s) + " 秒";
    },
    /** 短哈希/ID:默认 8 位前缀展示。 */
    fmtId: function (value, len) {
      if (!value) return "未记录";
      return String(value).slice(0, len || 8);
    },
    esc: function (v) {
      return String(v == null ? "" : v).replace(/[&<>"]/g, function (ch) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
      });
    },
    /** 复制到剪贴板(轻量浏览操作;按钮反馈固定为「已复制」)。 */
    copyText: function (text, btn) {
      var done = function () {
        if (!btn) return;
        var original = btn.textContent;
        btn.textContent = "已复制";
        btn.classList.add("done");
        setTimeout(function () {
          btn.textContent = original;
          btn.classList.remove("done");
        }, 1400);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, done);
      } else {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand("copy"); } catch (e) { /* 忽略 */ }
        document.body.removeChild(ta);
        done();
      }
    },
    /** 状态 → 固定「颜色 + 文字」双编码 chip。 */
    statusChip: function (status, validity) {
      if (validity === "INVALID" || status === "INVALID") {
        return '<span class="st st-warn" title="无效运行:不进指标分母">无效</span>';
      }
      if (status === "COMPLETE") return '<span class="st st-ok" title="运行完成">完成</span>';
      if (status === "FAILED") return '<span class="st st-bad" title="有效环境下的任务失败">失败</span>';
      if (status === "CANCELLED") return '<span class="st st-muted" title="人工取消">已取消</span>';
      if (status === "PENDING_JUDGMENT") return '<span class="st st-muted" title="等待评测">待评测</span>';
      if (status === "NOT_RUN") return '<span class="st st-muted" title="未发起运行">未运行</span>';
      return '<span class="st st-muted">未记录</span>';
    },
  };
})();
