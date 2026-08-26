/* 站点共享脚本：顶栏导航注入 / 侧栏级联手风琴互斥 / 移动端侧栏 / 目录滚动跟随 */
(function () {
  "use strict";

  // 0. 原型 v2 外壳(前端信息架构 §三:5 个一级模块):wordmark + 五导航 + 角色标签。
  //    导航注入到既有 topbar,旧页面不改标记即可获得新外壳;活动态按路径推导。
  (function injectChrome() {
    var inner = document.querySelector(".topbar-inner");
    if (!inner) return;
    var brand = inner.querySelector(".brand");
    if (brand) brand.innerHTML = '<span class="wordmark"><b>Touchstone</b><span>Agent Eval</span></span>';

    var NAV = [
      { href: "/", label: "公告", match: function (p) { return p === "/" || p === "/index.html"; } },
      { href: "/experiment/", label: "实验", match: function (p) { return p.indexOf("/experiment") === 0 || p.indexOf("/lab") === 0; } },
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
    var nav = document.createElement("nav");
    nav.className = "site-nav";
    nav.setAttribute("aria-label", "站点模块导航");
    nav.innerHTML = NAV.map(function (item) {
      return '<a href="' + item.href + '"' + (item.match(path) ? ' class="on"' : "") + ">" + item.label + "</a>";
    }).join("");
    inner.insertBefore(nav, inner.querySelector(".topbar-actions") || null);

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
  // 4. 登录遮罩(当前页弹窗,不跳转) + 登录态三按钮(登录/运行台/退出登录)
  var RUN_API = window.__RUN_API__ || "http://127.0.0.1:8090";
  var labBtn = document.querySelector(".topbar-lab");
  var loginBtn = document.querySelector(".topbar-login");
  var logoutBtn = document.querySelector(".topbar-logout");
  function refreshAuthState() {
    var logged = !!sessionStorage.getItem("lab_token");
    var role = document.querySelector(".role-label");
    if (role) role.textContent = logged ? "登录所有者" : "匿名访客";
    // 运行台只在私有部署存在:公开页 HTML 不硬链接 /lab,登录态由脚本动态赋址
    if (labBtn) {
      labBtn.style.display = logged ? "inline-flex" : "none";
      labBtn.href = logged ? "/lab/" : undefined;
    }
    if (loginBtn) loginBtn.style.display = logged ? "none" : "inline-flex";
    if (logoutBtn) logoutBtn.style.display = logged ? "inline-flex" : "none";
  }
  refreshAuthState();
  if (logoutBtn) {
    logoutBtn.addEventListener("click", function () {
      var token = sessionStorage.getItem("lab_token");
      sessionStorage.removeItem("lab_token");
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
      '<div class="login-dialog" role="dialog" aria-label="所有者登录">' +
      "<h3>所有者登录</h3>" +
      '<p class="login-sub">仅项目所有者；密码连续输错 5 次将锁定 15 分钟。登录后留在当前页，可：</p>' +
      '<ul class="login-caps">' +
      "<li><strong>按实验模板发起正式批次</strong>（预估运行数 → 确认 → 提交；可使用高级设置）</li>" +
      "<li>跟踪批次进度，运行中可协作取消</li>" +
      "<li>查看「我的批次」全部历史与单次运行完整明细</li>" +
      "</ul>" +
      '<label>用户名<input class="login-user" type="text" autocomplete="username"></label>' +
      '<label>密码<input class="login-pass" type="password" autocomplete="current-password"></label>' +
      '<p class="login-err" aria-live="polite"></p>' +
      '<div class="login-row"><button type="button" class="login-cancel">取消</button>' +
      '<button type="button" class="login-go">登录</button></div></div>';
    document.body.appendChild(mask);
    var user = mask.querySelector(".login-user");
    var pass = mask.querySelector(".login-pass");
    var err = mask.querySelector(".login-err");

    function open() {
      err.textContent = "";
      mask.classList.add("show");
      user.focus();
    }
    function close() {
      mask.classList.remove("show");
      pass.value = "";
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
      if (e.key === "Escape") close();
    });
    pass.addEventListener("keydown", function (e) {
      if (e.key === "Enter") submit();
    });
    mask.querySelector(".login-go").addEventListener("click", submit);

    function submit() {
      if (!user.value.trim() || !pass.value) {
        err.textContent = "请输入用户名与密码";
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
