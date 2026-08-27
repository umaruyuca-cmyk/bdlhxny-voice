/** 固定分析用例：预设台词 → 真实 LLM tool-calling。无会话、无自由输入、无 mock。 */
(function () {
  "use strict";

  var AUTH_TOKEN_KEY = "bdlh_runtime.auth.token.v1";
  var params = new URLSearchParams(location.search);
  var followup = (params.get("followup") || "").trim();
  var sessionId = (params.get("sessionId") || "").trim();
  var embed = params.get("embed") === "1";

  var SCRIPTS = [
    { id: "research-01", category: "行情", message: "宁德时代现在什么价", note: "真实循环 · 行情工具" },
    { id: "research-03", category: "估值", message: "贵州茅台估值高不高", note: "真实循环 · 估值工具" },
    { id: "suit-03", category: "适合度", message: "做一次适合度筛查", note: "C-2 DRAFT，需登录" },
    { id: "watch-01", category: "看护", message: "300750 跌破阈值了，现在什么价", note: "watch 场景 · 真实报价" },
    { id: "follow-01", category: "记忆", message: "对我的换房计划有影响吗", note: "L3 记忆 + 真实分析" }
  ];

  var $ = function (id) { return document.getElementById(id); };
  var messagesEl = $("messages");
  var statusEl = $("status");
  var answerEl = $("answer");
  var loadedEl = $("loadedTools");
  var auditsEl = $("audits");
  var controller = null;
  var liveLlm = null;

  function token() {
    return localStorage.getItem(AUTH_TOKEN_KEY) || "";
  }

  function setStatus(text, kind) {
    statusEl.textContent = text;
    statusEl.className = "status" + (kind ? " " + kind : "");
  }

  function pyStr(value) {
    return JSON.stringify(value == null ? "" : String(value));
  }

  function pyRepr(value) {
    try {
      return JSON.stringify(value, null, 2);
    } catch (err) {
      return pyStr(value);
    }
  }

  function renderMessages(list) {
    messagesEl.textContent = "";
    list.forEach(function (item) {
      var line = document.createElement("span");
      if (item.cls === "HumanMessage") {
        line.className = "cls";
        line.textContent = "HumanMessage(content=" + pyStr(item.content) + ")\n\n";
      } else if (item.cls === "SystemMessage") {
        line.className = "cls";
        line.textContent = "SystemMessage(content=load_prompt(" + pyStr(item.files) + "))\n\n";
      } else if (item.cls === "AIMessage") {
        line.className = item.tool_calls && item.tool_calls.length ? "tool" : "cls";
        if (item.tool_calls && item.tool_calls.length) {
          line.textContent = "AIMessage(tool_calls=" + pyRepr(item.tool_calls) + ")\n\n";
        } else {
          line.textContent = "AIMessage(content=" + pyStr(item.content || "") + ")\n\n";
        }
      } else if (item.cls === "ToolMessage") {
        line.className = "tool";
        line.textContent = "ToolMessage(name=" + pyStr(item.name) + ", content=" + pyRepr(item.content) + ")\n\n";
      } else {
        line.className = "err";
        line.textContent = String(item.content || "") + "\n";
      }
      messagesEl.appendChild(line);
    });
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function setGraph(active, extras) {
    extras = extras || {};
    var nodes = document.querySelectorAll(".lc-graph [data-node]");
    Array.prototype.forEach.call(nodes, function (node) {
      var name = node.getAttribute("data-node");
      node.classList.remove("active", "done", "skip");
      if (extras.skip && extras.skip.indexOf(name) >= 0) node.classList.add("skip");
      if (extras.done && extras.done.indexOf(name) >= 0) node.classList.add("done");
      if (name === active) node.classList.add("active");
    });
  }

  function parseSseChunk(buffer, onEvent) {
    var parts = buffer.split("\n\n");
    var rest = parts.pop() || "";
    parts.forEach(function (block) {
      var type = "message";
      var dataLines = [];
      block.split("\n").forEach(function (line) {
        if (line.indexOf("event:") === 0) type = line.slice(6).trim();
        else if (line.indexOf("data:") === 0) dataLines.push(line.slice(5).trim());
      });
      if (!dataLines.length) return;
      try {
        onEvent(type, JSON.parse(dataLines.join("\n")));
      } catch (err) {
        onEvent(type, { raw: dataLines.join("\n") });
      }
    });
    return rest;
  }

  function applyLoopMeta(meta, state) {
    if (!meta) return;
    if (typeof meta.entered_loop === "boolean") state.enteredLoop = meta.entered_loop;
    if (meta.fastpath_name) state.fastpath = meta.fastpath_name;
    if (Array.isArray(meta.loaded_tools) && meta.loaded_tools.length) {
      state.loaded = meta.loaded_tools;
      loadedEl.hidden = false;
      loadedEl.textContent = "loaded_tools = " + pyRepr(meta.loaded_tools);
    }
  }

  function finishGraph(state) {
    if (state.fastpath) {
      setGraph("fastpath", { done: ["input", "router", "fastpath", "final"], skip: ["bind", "middleware", "toolmessage"] });
    } else if (state.enteredLoop || state.sawTool) {
      setGraph("final", { done: ["input", "router", "bind", "aimessage", "final"], skip: ["fastpath"] });
    } else {
      setGraph("final", { done: ["input", "router", "final"] });
    }
  }

  function markLlmDead(detail) {
    liveLlm = false;
    $("llmBanner").textContent = "真实 LLM 不可用：" + detail + "。配置 LLM_API_KEY 后重启引擎。本页不用 mock。";
  }

  async function probeReady() {
    try {
      var response = await fetch("/api/v1/ready");
      var data = await response.json();
      if (!response.ok || data.status === "NOT_READY") {
        $("llmBanner").textContent = "引擎未就绪（" + (data.status || response.status) + "）。分析用例不会跑。";
        liveLlm = false;
        return;
      }
      liveLlm = true;
      $("llmBanner").textContent = "引擎就绪。点用例将走真实 LLM 推理，不是脚本金标。";
    } catch (err) {
      liveLlm = false;
      $("llmBanner").textContent = "无法连接引擎 /ready。";
    }
  }

  async function refreshAuth() {
    var value = token();
    if (!value) {
      $("authState").textContent = "未登录（组合/适合度类用例需要）";
      return;
    }
    try {
      var response = await fetch("/api/v1/auth/me", { headers: { Authorization: "Bearer " + value } });
      if (!response.ok) throw new Error("expired");
      var me = await response.json();
      $("authState").textContent = me.username || me.userId || "已登录";
    } catch (err) {
      localStorage.removeItem(AUTH_TOKEN_KEY);
      $("authState").textContent = "未登录";
    }
  }

  async function login() {
    setStatus("登录中…", "running");
    try {
      var response = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: $("username").value.trim(),
          password: $("password").value
        })
      });
      var data = await response.json();
      if (!response.ok) throw new Error(data.error || "登录失败");
      if (!data.token) throw new Error("响应无 token");
      localStorage.setItem(AUTH_TOKEN_KEY, data.token);
      await refreshAuth();
      setStatus("已登录", "done");
    } catch (err) {
      setStatus(err.message || "登录失败", "error");
    }
  }

  async function runScript(item) {
    if (controller) controller.abort();
    if (liveLlm === false) {
      answerEl.className = "trial-result-body error";
      answerEl.textContent = "拒绝执行：真实 LLM 不可用，不用 mock 代替分析。";
      setStatus("已拦截", "error");
      return;
    }
    controller = new AbortController();
    $("stopBtn").hidden = false;
    answerEl.className = "trial-result-body placeholder";
    answerEl.textContent = "正在调用真实 LLM…";
    auditsEl.textContent = "";
    loadedEl.hidden = true;
    loadedEl.textContent = "";
    if (window.SentinelBlocks) window.SentinelBlocks.mount($("blocks"), []);
    else $("blocks").innerHTML = "";

    var chain = [
      { cls: "SystemMessage", files: "system_base.md, scene_chat.md" },
      { cls: "HumanMessage", content: item.message }
    ];
    renderMessages(chain);
    setGraph("router", { done: ["input"] });
    setStatus("真实推理中… " + (item.note || ""), "running");

    var sid = sessionId || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
    var headers = { "Content-Type": "application/json", Accept: "text/event-stream" };
    if (token()) headers.Authorization = "Bearer " + token();
    var state = { sawTool: false, enteredLoop: false, fastpath: null, loaded: [], answer: "" };
    try {
      var response = await fetch("/api/v1/chat/stream", {
        method: "POST",
        headers: headers,
        body: JSON.stringify({
          sessionId: sid,
          message: item.message,
          enabledSkillIds: []
        }),
        signal: controller.signal
      });
      if (!response.ok) {
        answerEl.className = "trial-result-body error";
        answerEl.textContent = "HTTP " + response.status + " " + (await response.text());
        setStatus("失败", "error");
        return;
      }
      var reader = response.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";
      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        buffer = parseSseChunk(buffer, function (type, data) {
          var payload = data && typeof data === "object" ? data : {};
          var eventType = payload.type || type;
          if (eventType === "status" && payload.step === "degraded") {
            var limitation = payload.limitation || "DEGRADED";
            if (limitation === "LLM_UNAVAILABLE") markLlmDead("LLM_UNAVAILABLE");
            chain.push({ cls: "error", content: "degraded: " + limitation });
            renderMessages(chain);
            answerEl.className = "trial-result-body error";
            answerEl.textContent = "真实 LLM 不可用（" + limitation + "），本页不接受规则替身。";
            setStatus("LLM 不可用", "error");
          } else if (eventType === "tool.step") {
            state.sawTool = true;
            state.enteredLoop = true;
            var toolName = payload.tool || payload.name || "";
            var args = payload.arguments || {};
            var status = String(payload.status || "pending").toLowerCase();
            if (status === "pending") {
              chain.push({ cls: "AIMessage", tool_calls: [{ name: toolName, args: args }] });
              setGraph("middleware", { done: ["input", "router", "bind", "aimessage"], skip: ["fastpath"] });
              setStatus("工具调用 · " + toolName, "running");
            } else {
              var obs = payload.observation || payload.summary || { status: payload.status, auditCode: payload.auditCode };
              chain.push({ cls: "ToolMessage", name: toolName, content: obs });
              setGraph("toolmessage", { done: ["input", "router", "bind", "aimessage", "middleware"], skip: ["fastpath"] });
              setStatus("Observation · " + toolName, "running");
            }
            renderMessages(chain);
          } else if (eventType === "token" && payload.content) {
            state.answer += payload.content;
            answerEl.className = "trial-result-body";
            answerEl.textContent = state.answer;
            var last = chain[chain.length - 1];
            if (!last || last.cls !== "AIMessage" || last.tool_calls) {
              chain.push({ cls: "AIMessage", content: state.answer });
            } else {
              last.content = state.answer;
            }
            setGraph(state.sawTool ? "final" : "bind", {
              done: state.sawTool ? ["input", "router", "bind"] : ["input", "router"],
              skip: ["fastpath"]
            });
            renderMessages(chain);
          } else if (eventType === "response.final") {
            applyLoopMeta(payload, state);
            if (payload.answer) {
              state.answer = payload.answer;
              answerEl.className = "trial-result-body";
              answerEl.textContent = state.answer;
              var tail = chain[chain.length - 1];
              if (tail && tail.cls === "AIMessage" && !tail.tool_calls) tail.content = state.answer;
              else chain.push({ cls: "AIMessage", content: state.answer });
              renderMessages(chain);
            }
            if (window.SentinelBlocks && payload.blocks) window.SentinelBlocks.mount($("blocks"), payload.blocks);
            var codes = payload.audit_codes || [];
            if (codes.indexOf("LLM_UNAVAILABLE") >= 0) {
              markLlmDead("终帧 LLM_UNAVAILABLE");
              answerEl.className = "trial-result-body error";
            }
            var badges = window.SentinelBadges;
            auditsEl.innerHTML = codes.map(function (code) {
              return badges ? badges.audit(code) : '<span class="badge-audit">' + code + "</span>";
            }).join(" ");
            finishGraph(state);
          } else if (eventType === "done") {
            finishGraph(state);
            if (statusEl.classList.contains("running")) {
              setStatus(
                "结束 " + (payload.status || "") + (state.enteredLoop || state.sawTool ? " · 真实循环" : ""),
                state.answer ? "done" : "error"
              );
            }
          } else if (eventType === "error" || eventType === "guardrail.blocked") {
            chain.push({ cls: "error", content: payload.message || JSON.stringify(payload) });
            renderMessages(chain);
            answerEl.className = "trial-result-body error";
            answerEl.textContent = payload.message || JSON.stringify(payload);
            setStatus("失败", "error");
          }
        });
      }
    } catch (err) {
      if (err.name === "AbortError") {
        setStatus("已停止", "error");
        return;
      }
      answerEl.className = "trial-result-body error";
      answerEl.textContent = String(err.message || err);
      setStatus("失败", "error");
    } finally {
      $("stopBtn").hidden = true;
    }
  }

  function renderScripts() {
    var root = $("scripts");
    root.innerHTML = "";
    SCRIPTS.forEach(function (item) {
      var button = document.createElement("button");
      button.type = "button";
      button.setAttribute("data-case", item.id);
      button.innerHTML = "<span class=\"cat\">" + item.category + "</span>" + item.message;
      button.addEventListener("click", function () {
        Array.prototype.forEach.call(root.querySelectorAll("button"), function (node) {
          node.classList.remove("active");
        });
        button.classList.add("active");
        runScript(item);
      });
      root.appendChild(button);
    });
  }

  if (embed) document.body.classList.add("embed");
  if (followup) {
    $("followupHint").hidden = false;
    $("followupHint").textContent = "事件上下文：" + followup + "。仍用固定用例，不打开对话页。";
  }
  $("loginBtn").addEventListener("click", login);
  $("password").addEventListener("keydown", function (event) {
    if (event.key === "Enter") login();
  });
  $("stopBtn").addEventListener("click", function () {
    if (controller) controller.abort();
  });
  renderScripts();
  refreshAuth();
  probeReady().then(function () {
    if (followup) {
      var follow = SCRIPTS.filter(function (item) { return item.id === "follow-01"; })[0];
      var btn = document.querySelector("[data-case='follow-01']");
      if (btn) btn.classList.add("active");
      runScript(follow);
    }
  });
})();
