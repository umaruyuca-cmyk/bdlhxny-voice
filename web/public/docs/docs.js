/* 站点共享脚本：顶栏导航注入 / 侧栏级联手风琴互斥 / 移动端侧栏 / 目录滚动跟随 */
(function () {
  "use strict";

  // 0. 原型 v2 外壳(前端信息架构 §三:5 个一级模块):wordmark + 五导航 + 角色标签。
  //    P2-1:主导航已由站点生成器/页面模板静态写入,本脚本只做增强——
  //    按路径推导活动态;旧缓存页缺静态 nav 时兜底注入。禁用脚本也能用基础导航。
  (function injectChrome() {
    var inner = document.querySelector(".topbar-inner");
    if (!inner) return;
    var brand = inner.querySelector(".brand");
    if (brand && !brand.querySelector(".wordmark")) {
      brand.innerHTML = '<span class="wordmark"><b>Touchstone</b><span>Agent Eval</span></span>';
    }

    var NAV = [
      { href: "/", label: "公告", match: function (p) { return p === "/" || p === "/index.html"; } },
      { href: "/experiment/", label: "实验", match: function (p) { return p.indexOf("/experiment") === 0; } },
      { href: "/test/", label: "我的测试", match: function (p) { return p.indexOf("/test") === 0; } },
      { href: "/assets/", label: "数据资产", match: function (p) {
        return ["/cases", "/tools", "/context", "/assets", "/showcase"].some(function (prefix) {
          return p.indexOf(prefix) === 0;
        });
      } },
      { href: "/docs/", label: "文档", match: function (p) {
        return ["/about", "/engine", "/judging", "/ops", "/docs"].some(function (prefix) {
          return p.indexOf(prefix) === 0;
        });
      } },
    ];
    var path = location.pathname;
    var nav = inner.querySelector("nav.site-nav");
    if (!nav) {
      // 兜底:页面缺静态导航(极旧缓存)时注入;正常路径不会走到这里
      nav = document.createElement("nav");
      nav.className = "site-nav";
      nav.setAttribute("aria-label", "站点模块导航");
      nav.innerHTML = NAV.map(function (item) {
        return '<a href="' + item.href + '">' + item.label + "</a>";
      }).join("");
      inner.insertBefore(nav, inner.querySelector(".topbar-actions") || null);
    }
    // 活动态高亮(交互增强):静态导航本身不依赖脚本可用
    var links = Array.prototype.slice.call(nav.querySelectorAll("a"));
    links.forEach(function (a) {
      var item = NAV.filter(function (n) { return n.href === a.getAttribute("href"); })[0];
      if (item && item.match(path)) a.classList.add("on");
    });

    var actions = inner.querySelector(".topbar-actions");
    if (actions && !actions.querySelector(".role-label")) {
      var role = document.createElement("span");
      role.className = "role-label";
      actions.insertBefore(role, actions.firstChild);
      var user = sessionStorage.getItem("lab_user");
      role.textContent = user ? "登录所有者" : "匿名访客";
    }
  })();

  // 1. 侧栏级联手风琴：单开模式——展开一组时收起其他组(原生 details 负责自身开合)
  var sideGroups = Array.prototype.slice.call(document.querySelectorAll(".side-group"));
  sideGroups.forEach(function (g) {
    var summary = g.querySelector("summary");
    if (!summary) return;
    summary.addEventListener("click", function () {
      sideGroups.forEach(function (x) {
        if (x !== g) x.removeAttribute("open");
      });
    });
  });

  // 2. 移动端：侧栏开合
  var btn = document.getElementById("sideBtn");
  var side = document.getElementById("docsSide");
  if (btn && side) {
    btn.addEventListener("click", function () { side.classList.toggle("open"); });
    side.addEventListener("click", function (e) {
      if (e.target.closest("a")) side.classList.remove("open");
    });
  }

  // 3. 目录滚动跟随（scroll-spy;目录在主内容顶部的页内锚点条）
  var links = Array.prototype.slice.call(document.querySelectorAll('.page-toc a[href^="#"]'));
  var targets = links
    .map(function (a) { return document.getElementById(a.getAttribute("href").slice(1)); })
    .filter(Boolean);
  if (links.length && targets.length) {
    var spy = function () {
      var pos = window.scrollY + 140;
      var current = targets[0];
      targets.forEach(function (t) { if (t.offsetTop <= pos) current = t; });
      links.forEach(function (a) {
        a.classList.toggle("active", a.getAttribute("href") === "#" + current.id);
      });
    };
    window.addEventListener("scroll", spy, { passive: true });
    spy();
  }
  // 3.5 全站时间展示格式:yyyyMMdd HH:mm:ss(本地时区)——页面脚本经 window.SITE.fmtTime /
  //     fmtDate(仅日期 yyyyMMdd)使用;后端返回的 ISO 8601 原始串不再直接上屏。
  window.SITE = {
    fmtTime: function (value) {
      if (value == null || value === "") return "—";
      var d = new Date(value);
      if (isNaN(d.getTime())) return String(value).replace("T", " ").slice(0, 19);
      var p2 = function (n) { return (n < 10 ? "0" : "") + n; };
      return "" + d.getFullYear() + p2(d.getMonth() + 1) + p2(d.getDate()) +
        " " + p2(d.getHours()) + ":" + p2(d.getMinutes()) + ":" + p2(d.getSeconds());
    },
    fmtDate: function (value) {
      if (value == null || value === "") return "—";
      var d = new Date(value);
      if (isNaN(d.getTime())) return String(value).slice(0, 10).replace(/-/g, "");
      var p2 = function (n) { return (n < 10 ? "0" : "") + n; };
      return "" + d.getFullYear() + p2(d.getMonth() + 1) + p2(d.getDate());
    },
  };

  // 4. 登录遮罩(当前页弹窗,不跳转) + 登录态三按钮(登录/实验中心/退出登录)
  var RUN_API = window.__RUN_API__ || "http://127.0.0.1:8090";
  // 所有者会话键:ts_owner(旧键 lab_token 一次性迁移,老会话不掉线)
  function ownerToken() {
    var legacy = sessionStorage.getItem("lab_token");
    if (legacy) { sessionStorage.setItem("ts_owner", legacy); sessionStorage.removeItem("lab_token"); }
    return sessionStorage.getItem("ts_owner") || "";
  }
  var labBtn = document.querySelector(".topbar-lab");
  var loginBtn = document.querySelector(".topbar-login");
  var logoutBtn = document.querySelector(".topbar-logout");
  function refreshAuthState() {
    var logged = !!ownerToken();
    var role = document.querySelector(".role-label");
    if (role) role.textContent = logged ? "登录所有者" : "匿名访客";
    // 实验中心入口:登录后可见(所有者在实验模块发起正式批次)
    if (labBtn) {
      labBtn.style.display = logged ? "inline-flex" : "none";
      labBtn.href = logged ? "/experiment/" : undefined;
    }
    if (loginBtn) loginBtn.style.display = logged ? "none" : "inline-flex";
    if (logoutBtn) logoutBtn.style.display = logged ? "inline-flex" : "none";
  }
  refreshAuthState();
  if (logoutBtn) {
    logoutBtn.addEventListener("click", function () {
      var token = ownerToken();
      sessionStorage.removeItem("ts_owner");
      sessionStorage.removeItem("lab_user");
      refreshAuthState();
      if (token) {
        fetch(RUN_API + "/api/v1/logout", {
          method: "POST",
          headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
        }).catch(function () { /* 服务端注销尽力而为,本地会话已清 */ });
      }
      if (location.pathname !== "/") location.href = "/";
    });
  }

  if (loginBtn) {
    loginBtn.setAttribute("title", "登录后可在实验模块发起正式批次、使用高级设置并查看自己的全部批次");
    var mask = document.createElement("div");
    mask.className = "login-mask";
    mask.innerHTML =
      '<div class="login-dialog" role="dialog" aria-modal="true" aria-label="所有者登录">' +
      "<h3>所有者登录</h3>" +
      '<p class="login-sub">仅项目所有者；密码连续输错 5 次将锁定 15 分钟。登录后留在当前页，可：</p>' +
      '<ul class="login-caps">' +
      "<li><strong>按实验模板发起正式批次</strong>（预估运行数 → 确认 → 提交；可使用高级设置）</li>" +
      "<li>跟踪批次进度，运行中可协作取消</li>" +
      "<li>查看「我的批次」全部历史与单次运行完整明细</li>" +
      "</ul>" +
      '<label>用户名<input class="login-user" type="text" autocomplete="username" aria-describedby="loginErr"></label>' +
      '<label>密码<input class="login-pass" type="password" autocomplete="current-password" aria-describedby="loginErr"></label>' +
      '<p class="login-err" id="loginErr" aria-live="polite"></p>' +
      '<div class="login-row"><button type="button" class="login-cancel">取消</button>' +
      '<button type="button" class="login-go">登录</button></div></div>';
    document.body.appendChild(mask);
    var user = mask.querySelector(".login-user");
    var pass = mask.querySelector(".login-pass");
    var err = mask.querySelector(".login-err");
    var dialog = mask.querySelector(".login-dialog");
    var dialogOpener = null; // 打开前的焦点元素,关闭后归还

    function focusables() {
      return Array.prototype.filter.call(
        dialog.querySelectorAll("button, input, a[href]"),
        function (el) { return el.offsetParent != null; },
      );
    }
    function open() {
      err.textContent = "";
      user.setAttribute("aria-invalid", "false");
      pass.setAttribute("aria-invalid", "false");
      dialogOpener = document.activeElement;
      mask.classList.add("show");
      user.focus();
    }
    function close() {
      mask.classList.remove("show");
      pass.value = "";
      // 焦点归还触发按钮(P2-2):键盘用户关闭弹窗后不丢焦点
      var back = dialogOpener || loginBtn;
      if (back && typeof back.focus === "function") back.focus();
      dialogOpener = null;
    }
    loginBtn.addEventListener("click", function (e) {
      e.preventDefault(); // 不跳转登录页,当前页遮罩
      open();
    });
    mask.addEventListener("click", function (e) {
      if (e.target === mask) close();
    });
    mask.querySelector(".login-cancel").addEventListener("click", close);
    document.addEventListener("keydown", function (e) {
      if (!mask.classList.contains("show")) return;
      if (e.key === "Escape") { close(); return; }
      // 焦点圈定(P2-2):Tab/Shift+Tab 在弹窗内首尾循环,不漏到页面底层
      if (e.key === "Tab") {
        var list = focusables();
        if (!list.length) return;
        var first = list[0];
        var last = list[list.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    });
    pass.addEventListener("keydown", function (e) {
      if (e.key === "Enter") submit();
    });
    mask.querySelector(".login-go").addEventListener("click", submit);

    function submit() {
      if (!user.value.trim() || !pass.value) {
        err.textContent = "请输入用户名与密码";
        if (!user.value.trim()) user.setAttribute("aria-invalid", "true");
        if (!pass.value) pass.setAttribute("aria-invalid", "true");
        return;
      }
      err.textContent = "登录中…";
      fetch(RUN_API + "/api/v1/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: user.value.trim(), password: pass.value }),
      })
        .then(function (res) {
          return res.json().then(function (body) {
            return { status: res.status, body: body };
          });
        })
        .then(function (outcome) {
          if (outcome.status === 200 && outcome.body.token) {
            sessionStorage.setItem("lab_token", outcome.body.token);
            sessionStorage.setItem("lab_user", outcome.body.username || "");
            refreshAuthState();
            err.textContent = "登录成功，正在刷新当前页…";
            setTimeout(function () {
              close();
              // 登录后留在当前页刷新角色视图(实验模块同页双角色);不硬跳运行台
              location.reload();
            }, 600);
          } else if (outcome.status === 423) {
            err.textContent = "账号已锁定，请稍后再试";
          } else {
            err.textContent = "用户名或密码错误（连续失败会锁定）";
          }
        })
        .catch(function () {
          err.textContent = "无法连接运行 API（服务未启动，或当前为无登录能力的公开部署）";
        });
    }
  }
})();
