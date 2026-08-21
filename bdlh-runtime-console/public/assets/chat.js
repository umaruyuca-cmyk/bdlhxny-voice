/* ================================================================
   对话页逻辑 · 单助手精简版
   - 本地会话管理（localStorage）+ 远端会话静默同步
   - SSE 流式问答（POST /api/v1/chat/stream）
   ================================================================ */
(function(){
"use strict";

/* ---------- DOM ---------- */
var sidebar=document.getElementById("sidebar");
var sessionList=document.getElementById("sessionList");
var newChatBtn=document.getElementById("newChat");
var chatTitle=document.getElementById("chatTitle");
var hero=document.getElementById("hero");
var scrollBox=document.getElementById("scroll");
var messages=document.getElementById("messages");
var composer=document.getElementById("composer");
var input=document.getElementById("input");
var sendBtn=document.getElementById("sendBtn");
var toastEl=document.getElementById("toast");

/* ---------- 常量与状态 ---------- */
var MOCK=new URLSearchParams(location.search).has("mock");
var STORAGE_BASE=MOCK?"grid.chat.mock.v2":"grid.chat.v1";
var AUTH_TOKEN_KEY="bdlh_runtime.auth.token.v1";
var MOCK_VER_KEY="grid.chat.mock.ver";
var MOCK_DATA_VERSION=3; /* mock 演示数据有变更时递增，旧缓存自动重建 */
var MAX_SESSIONS=30;
var MODE="general"; // 后端协议字段，单助手固定值
var STOCK_SKILL="finance.stock-research";
var NATIVE_FETCH=window.fetch.bind(window);
var AUTH={ready:MOCK,user:MOCK?{userId:"mock",username:"演示模式"}:null};
var AUTH_MODE="login";

var ST={
  sessions:[],
  activeId:null,
  sending:false,
  streamText:"",
  controller:null,
  activeRunId:null,
  pauseAcked:false,
  loadingEarlier:false,
  page:"chat"
};

var STEP_LABEL={
  classifying:"理解你的问题",
  direct_chat:"组织回答",
  react_planning:"规划分析步骤",
  searching_web:"联网检索资料",
  reading_sources:"整理检索来源",
  stock_validating:"校验分析标的",
  skill_executing:"执行深度分析",
  route_executing:"执行深度分析",
  searching_vector:"检索知识库",
  retrieval_result:"整理检索结果"
};

/* ---------- 工具 ---------- */
function $(sel,root){return (root||document).querySelector(sel);}
function esc(s){var d=document.createElement("div");d.textContent=s==null?"":s;return d.innerHTML;}
function uid(){return "s_"+Date.now().toString(36)+Math.random().toString(36).slice(2,7);}
function now(){return Date.now();}
function toast(msg){
  toastEl.textContent=msg;
  toastEl.classList.add("show");
  clearTimeout(toastEl._t);
  toastEl._t=setTimeout(function(){toastEl.classList.remove("show");},2200);
}
function scrollBottom(){scrollBox.scrollTop=scrollBox.scrollHeight;}
function storageKey(){return STORAGE_BASE+"."+(AUTH.user?AUTH.user.userId:"anonymous");}
async function apiFetch(resource,options){
  var next=Object.assign({},options||{});
  next.headers=new Headers(next.headers||{});
  var token=localStorage.getItem(AUTH_TOKEN_KEY);
  if(token)next.headers.set("Authorization","Bearer "+token);
  var response=await NATIVE_FETCH(resource,next);
  if(response.status===401&&String(resource).indexOf("/api/v1/auth/")<0){
    AUTH.ready=false;AUTH.user=null;localStorage.removeItem(AUTH_TOKEN_KEY);showAuth();
  }
  return response;
}

/* ---------- 会话存取 ---------- */
function persist(){
  try{localStorage.setItem(storageKey(),JSON.stringify({sessions:ST.sessions,activeId:ST.activeId}));}catch(e){}
}
function restore(){
  try{
    var raw=localStorage.getItem(storageKey());
    if(!raw)return;
    var data=JSON.parse(raw);
    ST.sessions=Array.isArray(data.sessions)?data.sessions:[];
    ST.activeId=data.activeId||null;
  }catch(e){ST.sessions=[];ST.activeId=null;}
}
function activeSession(){
  for(var i=0;i<ST.sessions.length;i++)if(ST.sessions[i].id===ST.activeId)return ST.sessions[i];
  return null;
}
function makeSession(){
  return {id:uid(),title:"新的对话",messages:[],updatedAt:now(),remote:false,enabledSkills:[]};
}
function ensureSessionSkills(s){
  if(!s)return;
  if(!Array.isArray(s.enabledSkills))s.enabledSkills=[];
}
function isStockQuestion(q){
  return /分析|估值|研报|股票|个股|市盈率|市净率|标的|ETF|基金|板块|\d{6}|588200|科创|芯片|茅台|600519/.test(String(q||""));
}
function skillEnabled(id){
  var s=activeSession();
  if(!s)return false;
  ensureSessionSkills(s);
  return s.enabledSkills.indexOf(id)>=0;
}
function setSkillEnabled(id,on,note){
  var s=activeSession();
  if(!s){
    s=makeSession();
    ST.sessions.push(s);
    ST.activeId=s.id;
  }
  ensureSessionSkills(s);
  var i=s.enabledSkills.indexOf(id);
  if(on&&i<0)s.enabledSkills.push(id);
  if(!on&&i>=0)s.enabledSkills.splice(i,1);
  s.updatedAt=now();
  persist();
  syncPluginUi();
  if(note==="on")toast("已启用股票分析（本对话）");
  if(note==="off")toast("已关闭股票分析");
}
function syncPluginUi(){
  var on=skillEnabled(STOCK_SKILL);
  var toggle=document.getElementById("pluginToggle");
  var chip=document.getElementById("chipEnabled");
  var ro=document.getElementById("roTag");
  var skillStock=document.getElementById("skillStock");
  var statusTag=document.getElementById("statusTag");
  var navPlugins=document.getElementById("navPlugins");
  if(toggle){
    toggle.classList.toggle("on",on);
    toggle.setAttribute("aria-checked",on?"true":"false");
  }
  if(chip)chip.hidden=!on;
  if(ro)ro.hidden=!on;
  if(skillStock)skillStock.classList.toggle("on",on);
  if(statusTag){
    statusTag.textContent=on?"本对话已启用":"未启用";
    statusTag.className="tag "+(on?"ok":"off");
  }
  if(navPlugins)navPlugins.classList.toggle("on",ST.page==="plugins");
}
function showPage(name){
  ST.page=name==="plugins"?"plugins":"chat";
  var viewChat=document.getElementById("viewChat");
  var viewPlugins=document.getElementById("viewPlugins");
  if(viewChat)viewChat.classList.toggle("on",ST.page==="chat");
  if(viewPlugins)viewPlugins.classList.toggle("on",ST.page==="plugins");
  syncPluginUi();
  if(ST.page==="plugins"){
    if(qnav)qnav.style.display="none";
    if(qpanel)qpanel.classList.remove("open");
  }else{
    rebuildQnav();
  }
}
function showEnableNudge(question){
  hero.classList.add("hidden");
  chatTitle.textContent=activeSession()?activeSession().title:"新的对话";
  var row=document.createElement("div");
  row.className="msg user";
  row.innerHTML='<div class="body"><div class="text">'+esc(question)+"</div></div>";
  messages.appendChild(row);
  var ai=document.createElement("div");
  ai.className="msg";
  ai.innerHTML='<div class="avatar">G</div><div class="body">'+
    '<div class="text">要做标的深度研究，需要先启用「股票分析」插件。</div>'+
    '<div class="nudge"><div class="t">前往插件页启用</div>'+
    '<div class="d">启用后回到对话继续提问。也可以一键启用并继续。</div>'+
    '<div class="acts">'+
    '<button class="btn primary" type="button" data-act="enable-continue">启用并继续</button>'+
    '<button class="btn" type="button" data-act="open-plugins">打开插件页</button>'+
    "</div></div></div>";
  messages.appendChild(ai);
  rebuildQnav();
  scrollBottom();
  ai.addEventListener("click",function(e){
    var btn=e.target.closest("[data-act]");
    if(!btn)return;
    var act=btn.getAttribute("data-act");
    if(act==="open-plugins"){showPage("plugins");return;}
    if(act==="enable-continue"){
      setSkillEnabled(STOCK_SKILL,true,"on");
      ai.remove();
      row.remove();
      send(question,false);
    }
  });
}
function adoptServerSessionId(serverId){
  var s=activeSession();
  if(!s||!serverId||s.id===serverId)return;
  s.id=serverId;s.remote=true;
  ST.activeId=serverId;
  persist();
}

/* ---------- 会话列表渲染（按时间分组） ---------- */
function groupLabel(t){
  var d=new Date(t);
  var today=new Date();today.setHours(0,0,0,0);
  var day=new Date(d);day.setHours(0,0,0,0);
  var diff=Math.round((today-day)/86400000);
  if(diff<=0)return "今天";
  if(diff===1)return "昨天";
  if(diff<7)return "7 天内";
  if(diff<30)return "30 天内";
  return "更早";
}
var GROUP_ORDER=["今天","昨天","7 天内","30 天内","更早"];
function renderSessionList(){
  sessionList.innerHTML="";
  if(!ST.sessions.length){
    sessionList.innerHTML='<div class="sessions-empty">还没有对话，从下方输入框开始</div>';
    return;
  }
  var sorted=ST.sessions.slice().sort(function(a,b){return b.updatedAt-a.updatedAt;});
  var lastGroup=null;
  sorted.forEach(function(s){
    var g=groupLabel(s.updatedAt);
    if(g!==lastGroup){
      lastGroup=g;
      var label=document.createElement("div");
      label.className="sessions-group";
      label.textContent=g;
      sessionList.appendChild(label);
    }
    var item=document.createElement("div");
    item.className="session"+(s.id===ST.activeId?" active":"");
    item.innerHTML='<span>'+esc(s.title)+'</span>'+
      '<button class="del" type="button" aria-label="删除对话">'+
      '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m-9 0 1 13h8l1-13"/></svg>'+
      '</button>';
    item.addEventListener("click",function(){switchSession(s.id);});
    $(".del",item).addEventListener("click",function(e){
      e.stopPropagation();
      deleteSession(s.id);
    });
    sessionList.appendChild(item);
  });
}
function switchSession(id){
  if(ST.sending)return;
  ST.activeId=id;
  persist();
  renderSessionList();
  showPage("chat");
  renderMessages();
  syncPluginUi();
  var s=activeSession();
  if(s&&s.remote&&!s.loaded)loadSessionDetail(s);
}
async function deleteSession(id){
  var target=ST.sessions.find(function(s){return s.id===id;});
  if(target&&target.remote&&!MOCK){
    try{
      var response=await apiFetch("/api/v1/conversations/"+encodeURIComponent(id),{method:"DELETE"});
      if(!response.ok&&response.status!==404){toast("暂时无法删除该对话");return;}
    }catch(e){toast("暂时无法删除该对话");return;}
  }
  ST.sessions=ST.sessions.filter(function(s){return s.id!==id;});
  if(ST.activeId===id)ST.activeId=ST.sessions.length?ST.sessions[0].id:null;
  persist();
  renderSessionList();
  renderMessages();
}
function newChat(){
  if(ST.sending)return;
  ST.activeId=null;
  persist();
  renderSessionList();
  showPage("chat");
  renderMessages();
  syncPluginUi();
  input.focus();
}

/* ---------- 消息渲染 ---------- */
function renderMessages(){
  messages.innerHTML="";
  var s=activeSession();
  var list=s&&s.messages?s.messages:[];
  chatTitle.textContent=s?s.title:"新的对话";
  hero.classList.toggle("hidden",list.length>0);
  list.forEach(function(m){appendMessage(m.role,m.content,false);});
  scrollBottom();
  rebuildQnav();
  ensureScrollable();
  syncPluginUi();
}
function appendMessage(role,content,animate){
  var row=document.createElement("div");
  row.className="msg"+(role==="user"?" user":"");
  if(!animate)row.style.animation="none";
  if(role==="user"){
    row.innerHTML='<div class="body"><div class="text">'+esc(content)+'</div></div>';
  }else{
    row.innerHTML='<div class="avatar">G</div><div class="body">'+
      '<div class="msg-status"><i></i><span></span></div>'+
      '<div class="text">'+esc(content)+'</div>'+
      '<div class="msg-actions">'+
        '<button class="act-btn act-copy" type="button" title="复制回答">'+
          '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>'+
          '<span>复制</span></button>'+
        '<button class="act-btn act-regen" type="button" title="重新回答">'+
          '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg>'+
          '<span>重新回答</span></button>'+
      '</div></div>';
    bindActions(row);
  }
  messages.appendChild(row);
  updateLastAi();
  return row;
}
function bindActions(row){
  var copyBtn=$(".act-copy",row);
  copyBtn.addEventListener("click",function(){
    var text=$(".text",row).textContent;
    function ok(){
      copyBtn.classList.add("done-ok");
      $("span",copyBtn).textContent="已复制";
      setTimeout(function(){
        copyBtn.classList.remove("done-ok");
        $("span",copyBtn).textContent="复制";
      },1600);
    }
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(text).then(ok,function(){fallbackCopy(text);ok();});
    }else{fallbackCopy(text);ok();}
  });
  $(".act-regen",row).addEventListener("click",regenerate);
}
function fallbackCopy(text){
  var ta=document.createElement("textarea");
  ta.value=text;ta.style.position="fixed";ta.style.opacity="0";
  document.body.appendChild(ta);ta.select();
  try{document.execCommand("copy");}catch(e){}
  ta.remove();
}
/* 只有最后一条 AI 消息显示「重新回答」 */
function updateLastAi(){
  var rows=messages.querySelectorAll(".msg:not(.user)");
  rows.forEach(function(r){r.classList.remove("last-ai");});
  if(rows.length)rows[rows.length-1].classList.add("last-ai");
}
function regenerate(){
  if(ST.sending)return;
  var s=activeSession();
  if(!s||!s.messages.length)return;
  var last=s.messages[s.messages.length-1];
  if(last.role!=="assistant")return;
  var userMsg=null;
  for(var i=s.messages.length-2;i>=0;i--){
    if(s.messages[i].role==="user"){userMsg=s.messages[i].content;break;}
  }
  if(!userMsg)return;
  s.messages.pop();
  var rows=messages.querySelectorAll(".msg:not(.user)");
  if(rows.length)rows[rows.length-1].remove();
  persist();
  send(userMsg,true);
}
function createAgentRow(){
  var row=appendMessage("assistant","",true);
  var text=$(".text",row);
  text.innerHTML='<span class="typing"><i></i><i></i><i></i></span>';
  scrollBottom();
  return row;
}
function setStatus(row,step,skill){
  var bar=$(".msg-status",row);
  if(!bar)return;
  var label=STEP_LABEL[step]||"";
  if(!label)return;
  bar.classList.add("show");
  $("span",bar).textContent=label+(skill?" · "+skill:"")+"…";
}
function clearStatus(row){
  var bar=$(".msg-status",row);
  if(bar)bar.classList.remove("show");
}

/* ---------- 上滑加载更早消息（骨架条 + 滚动位置保持） ---------- */
function hasEarlier(s){
  return !!(s&&Array.isArray(s.earlierBatches)&&s.earlierBatches.length);
}
function buildSkeleton(){
  var skel=document.createElement("div");
  skel.className="skel";
  skel.innerHTML="<i></i>".repeat(8);
  return skel;
}
async function loadEarlier(){
  var s=activeSession();
  if(ST.loadingEarlier||ST.sending||!hasEarlier(s))return;
  ST.loadingEarlier=true;

  var prevHeight=scrollBox.scrollHeight;
  var prevTop=scrollBox.scrollTop;

  var skel=buildSkeleton();
  messages.insertBefore(skel,messages.firstChild);
  scrollBox.scrollTop=prevTop+skel.offsetHeight;

  await delay(950);

  var batch=s.earlierBatches.pop(); // 取最早的一批
  s.messages=batch.concat(s.messages);
  persist();

  skel.remove();
  batch.forEach(function(m){
    var row=appendMessage(m.role,m.content,false);
    messages.insertBefore(row,messages.firstChild);
  });
  updateLastAi();
  rebuildQnav();

  /* 恢复视口：新增内容在上方，滚动位置相应下移，视觉不跳动 */
  scrollBox.scrollTop=prevTop+(scrollBox.scrollHeight-prevHeight);
  ST.loadingEarlier=false;
}
/* 消息不足一屏且还有更早历史时，自动补载直到出现滚动条（否则无法上滑触发） */
function ensureScrollable(){
  var s=activeSession();
  if(!hasEarlier(s)||ST.loadingEarlier||ST.sending)return;
  if(scrollBox.scrollHeight<=scrollBox.clientHeight+4){
    Promise.resolve(loadEarlier()).then(ensureScrollable);
  }
}

/* ---------- 提问锚点导航 + 提问目录面板 ---------- */
var qnav=null,qpanel=null,qpanelList=null;
function ensureQnav(){
  if(qnav)return;
  var main=document.querySelector(".main");
  qnav=document.createElement("div");
  qnav.className="qnav";
  var toggle=document.createElement("button");
  toggle.type="button";
  toggle.className="qnav-toggle";
  toggle.title="全部提问";
  toggle.setAttribute("aria-label","全部提问");
  toggle.innerHTML='<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h10"/></svg>';
  toggle.addEventListener("click",function(e){
    e.stopPropagation();
    toggleQpanel();
  });
  qnav.appendChild(toggle);
  main.appendChild(qnav);

  qpanel=document.createElement("div");
  qpanel.className="qpanel";
  qpanel.innerHTML=
    '<div class="qpanel-fade qpanel-fade-top"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M6 15l6-6 6 6"/></svg></div>'+
    '<div class="qpanel-list"></div>'+
    '<div class="qpanel-fade qpanel-fade-bottom"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg></div>';
  main.appendChild(qpanel);
  qpanelList=qpanel.querySelector(".qpanel-list");
  qpanelList.addEventListener("scroll",updateQpanelFades);
  qpanel.addEventListener("click",function(e){e.stopPropagation();});
}
function toggleQpanel(force){
  ensureQnav();
  var open=typeof force==="boolean"?force:!qpanel.classList.contains("open");
  qpanel.classList.toggle("open",open);
  if(open){
    updateQpanelFades();
    var cur=qpanelList.querySelector(".qpanel-item.active");
    if(cur)cur.scrollIntoView({block:"center"});
  }
}
function updateQpanelFades(){
  if(!qpanelList)return;
  qpanel.querySelector(".qpanel-fade-top").classList.toggle("show",qpanelList.scrollTop>8);
  qpanel.querySelector(".qpanel-fade-bottom").classList.toggle("show",
    qpanelList.scrollHeight-qpanelList.scrollTop-qpanelList.clientHeight>8);
}
document.addEventListener("click",function(){
  if(qpanel&&qpanel.classList.contains("open"))toggleQpanel(false);
});
function rebuildQnav(){
  ensureQnav();
  qnav.querySelectorAll("i").forEach(function(o){o.remove();});
  qpanelList.innerHTML="";
  if(ST.page==="plugins"){
    qnav.style.display="none";
    toggleQpanel(false);
    return;
  }
  var rows=messages.querySelectorAll(".msg.user");
  if(!rows.length){
    qnav.style.display="none";
    toggleQpanel(false);
    return;
  }
  rows.forEach(function(row,idx){
    var full=row.textContent.trim().replace(/\s+/g," ");
    var short=full.length>42?full.slice(0,42)+"…":full;

    var bar=document.createElement("i");
    var tip=document.createElement("span");
    tip.className="qnav-tip";
    tip.textContent=short;
    bar.appendChild(tip);
    bar.addEventListener("click",function(){
      row.scrollIntoView({behavior:"smooth",block:"center"});
    });
    qnav.appendChild(bar);

    var item=document.createElement("button");
    item.type="button";
    item.className="qpanel-item";
    item.innerHTML='<span class="qi">'+(idx+1<10?"0":"")+(idx+1)+"</span>"+esc(full);
    item.title=full;
    item.addEventListener("click",function(){
      toggleQpanel(false);
      row.scrollIntoView({behavior:"smooth",block:"center"});
    });
    qpanelList.appendChild(item);
  });
  qnav.style.display="flex";
  markQnavActive();
  updateQpanelFades();
}
function markQnavActive(){
  if(!qnav)return;
  var bars=qnav.querySelectorAll("i");
  var rows=messages.querySelectorAll(".msg.user");
  /* row.offsetTop 相对 .main，换算到 scrollBox 内容坐标 */
  var base=scrollBox.offsetTop;
  var mid=scrollBox.scrollTop+scrollBox.clientHeight*0.4;
  var activeIdx=-1;
  rows.forEach(function(row,i){
    if(row.offsetTop-base<=mid)activeIdx=i;
  });
  bars.forEach(function(b,i){b.classList.toggle("active",i===activeIdx);});
  if(qpanelList){
    qpanelList.querySelectorAll(".qpanel-item").forEach(function(it,i){
      it.classList.toggle("active",i===activeIdx);
    });
  }
}

/* ---------- SSE ---------- */
async function consumeSse(response,onEvent){
  if(!response.body)throw new Error("浏览器不支持流式响应");
  var reader=response.body.getReader();
  var decoder=new TextDecoder("utf-8");
  var buffer="";
  while(true){
    var chunk=await reader.read();
    var value=chunk.value,done=chunk.done;
    buffer+=decoder.decode(value||new Uint8Array(),{stream:!done}).replace(/\r\n/g,"\n");
    var boundary;
    while((boundary=buffer.indexOf("\n\n"))>=0){
      var frame=buffer.slice(0,boundary);
      buffer=buffer.slice(boundary+2);
      var payload=frame.split("\n").filter(function(l){return l.indexOf("data:")===0;})
        .map(function(l){return l.slice(5).replace(/^\s+/,"");}).join("\n");
      if(payload){
        var keep=onEvent(JSON.parse(payload));
        if(keep===false){await reader.cancel();return;}
      }
    }
    if(done)return;
  }
}

function handleEvent(data,row){
  var text=$(".text",row);
  var type=data.type;
  if(type==="status"){
    setStatus(row,data.step,data.skill);
  }else if(type==="agent_run"){
    if(data.sessionId)adoptServerSessionId(data.sessionId);
    if(data.runId)ST.activeRunId=data.runId;
    ST.pauseAcked=false;
  }else if(type==="run.paused"){
    ST.pauseAcked=!!data.resumable;
    if($(".typing",text))text.textContent="";
    clearStatus(row);
    text.textContent=text.textContent||"已暂停，可回复「继续」恢复。";
  }else if(type==="guardrail.blocked"){
    if($(".typing",text))text.textContent="";
    clearStatus(row);
    text.classList.remove("streaming");
    text.textContent=data.message||("请求已被安全策略阻断"+(data.auditCode?"（"+data.auditCode+"）":""));
    text.classList.add("error");
  }else if(type==="token"){
    var tok=data.content||"";
    ST.streamText+=tok;
    if($(".typing",text))text.textContent="";
    clearStatus(row);
    text.textContent=ST.streamText;
    text.classList.add("streaming");
    scrollBottom();
  }else if(type==="clarification"){
    var options=(data.options||[]).map(function(o){
      if(typeof o==="string"){
        var text=String(o||"").trim();
        return text?{label:text,message:text}:null;
      }
      if(o&&o.label&&o.message)return o;
      if(o&&o.message)return {label:o.label||o.message,message:o.message};
      return null;
    }).filter(Boolean);
    if($(".typing",text))text.textContent="";
    clearStatus(row);
    addAskCard(row,data.prompt||"请补充完成分析所需的信息。",options.map(function(o,i){
      return {label:o.label,primary:i===0,message:o.message};
    }),data.responseStructure||"");
    scrollBottom();
    input.focus();
    // clarification 已由 Graph interrupt 持久化；立即结束本次读取，解除发送锁，
    // 用户随后输入或点击选项时由下一次 chat 请求恢复原线程。
    return false;
  }else if(type==="done"){
    if(data.sessionId)adoptServerSessionId(data.sessionId);
    if($(".typing",text)){
      text.textContent=data.status==="REFUSED"?("请求已被护栏拦截："+(data.reason||"")):"对话已完成。";
    }
    clearStatus(row);
    text.classList.remove("streaming");
    var s=activeSession();
    if(s&&ST.streamText){
      s.messages.push({role:"assistant",content:ST.streamText});
      s.updatedAt=now();
      persist();
    }
    return false;
  }else if(type==="error"){
    if($(".typing",text))text.textContent="";
    clearStatus(row);
    text.classList.remove("streaming");
    text.textContent+=(text.textContent?"\n":"")+(data.message||"服务暂时不可用，请稍后重试。");
    text.classList.add("error");
    return false;
  }
  return true;
}

/* ---------- 澄清选项卡 ---------- */
function addAskCard(row,promptText,options,responseStructure){
  var body=$(".body",row);
  var old=$(".ask-card",body);
  if(old)old.remove();
  var card=document.createElement("div");
  card.className="ask-card";
  card.innerHTML='<div class="ask-title">需要确认</div><div class="ask-text">'+esc(promptText)+'</div><div class="ask-options"></div>';
  var wrap=$(".ask-options",card);
  var structure=String(responseStructure||"");
  options.forEach(function(opt){
    var btn=document.createElement("button");
    btn.type="button";
    btn.className="ask-btn"+(opt.primary?" primary":"");
    btn.textContent=opt.label;
    btn.addEventListener("click",function(){
      card.remove();
      if(isOpenProfileAction(opt.message)||(structure==="SUITABILITY"&&isOpenProfileAction(opt.label))){
        void openProfileModal({resumeAfter:true});
        return;
      }
      send(opt.message);
    });
    wrap.appendChild(btn);
  });
  if(structure==="SUITABILITY"&&!options.some(function(o){return isOpenProfileAction(o.message||o.label);})){
    var profileBtn=document.createElement("button");
    profileBtn.type="button";
    profileBtn.className="ask-btn primary";
    profileBtn.textContent="填写并确认金融资料";
    profileBtn.addEventListener("click",function(){
      card.remove();
      void openProfileModal({resumeAfter:true});
    });
    wrap.insertBefore(profileBtn,wrap.firstChild);
  }
  if(!options.length&&structure!=="SUITABILITY"){
    var hint=document.createElement("span");
    hint.className="ask-hint";
    hint.textContent="请在下方输入框补充后继续";
    wrap.appendChild(hint);
  }
  body.appendChild(card);
}

function isOpenProfileAction(text){
  var value=String(text||"");
  return value.indexOf("打开金融资料")>=0||value.indexOf("确认金融资料")>=0||value.indexOf("填写并确认")>=0;
}

/* ---------- 金融资料确认 ---------- */
var profileModal=document.getElementById("profileModal");
var profileForm=document.getElementById("profileForm");
var profileError=document.getElementById("profileError");
var PROFILE_RESUME_MESSAGE="我已确认风险偏好与持仓，请继续评估适不适合我";

async function openProfileModal(opts){
  if(!AUTH.ready){showAuth();return;}
  profileError.textContent="";
  profileModal.dataset.resumeAfter=opts&&opts.resumeAfter?"1":"0";
  try{
    var res=await apiFetch("/api/v1/user/financial-profile");
    if(res.ok){
      var data=await res.json();
      document.getElementById("profileVersion").value=String(data.profile_version||0);
      if(data.currency)document.getElementById("profileCurrency").value=data.currency;
      if(data.cash!=null)document.getElementById("profileCash").value=data.cash;
      if(data.risk_tolerance)document.getElementById("profileRisk").value=data.risk_tolerance;
      if(data.max_loss_tolerance_pct!=null)document.getElementById("profileMaxLoss").value=data.max_loss_tolerance_pct;
      if(data.liquid_assets!=null)document.getElementById("profileLiquid").value=data.liquid_assets;
      if(data.near_term_cash_needs!=null)document.getElementById("profileCashNeeds").value=data.near_term_cash_needs;
      if(data.near_term_cash_needs_horizon_days!=null)document.getElementById("profileHorizon").value=data.near_term_cash_needs_horizon_days;
      var first=(data.positions||[])[0];
      if(first){
        document.getElementById("posSymbol").value=first.symbol||"";
        document.getElementById("posName").value=first.name||"";
        document.getElementById("posQty").value=first.quantity!=null?first.quantity:"";
        document.getElementById("posCost").value=first.cost_price!=null?first.cost_price:"";
        if(first.exchange)document.getElementById("posExchange").value=first.exchange;
        if(first.target_weight!=null)document.getElementById("posWeight").value=first.target_weight;
      }
    }else{
      document.getElementById("profileVersion").value="0";
    }
  }catch(err){
    document.getElementById("profileVersion").value="0";
  }
  profileModal.hidden=false;
}

function closeProfileModal(){
  profileModal.hidden=true;
  profileError.textContent="";
}

function idempotencyKey(prefix){
  return prefix+"-"+Date.now()+"-"+Math.random().toString(36).slice(2,10);
}

profileForm.addEventListener("submit",async function(e){
  e.preventDefault();
  if(!AUTH.ready){showAuth();return;}
  profileError.textContent="";
  var saveBtn=document.getElementById("profileSave");
  saveBtn.disabled=true;
  try{
    var expected=Number(document.getElementById("profileVersion").value||0);
    var profileBody={
      expected_profile_version:expected,
      currency:document.getElementById("profileCurrency").value.trim()||"CNY",
      cash:Number(document.getElementById("profileCash").value),
      risk_tolerance:document.getElementById("profileRisk").value,
      max_loss_tolerance_pct:Number(document.getElementById("profileMaxLoss").value),
      liquid_assets:Number(document.getElementById("profileLiquid").value),
      near_term_cash_needs:Number(document.getElementById("profileCashNeeds").value),
      near_term_cash_needs_horizon_days:Number(document.getElementById("profileHorizon").value)
    };
    var profileRes=await apiFetch("/api/v1/user/financial-profile",{
      method:"PUT",
      headers:{"Content-Type":"application/json","Idempotency-Key":idempotencyKey("profile")},
      body:JSON.stringify(profileBody)
    });
    if(!profileRes.ok){
      var profileErr=await profileRes.json().catch(function(){return {};});
      throw new Error(profileErr.message||profileErr.detail||("资料确认失败 HTTP "+profileRes.status));
    }
    var profileData=await profileRes.json();
    var nextVersion=Number(profileData.profile_version||expected+1);
    var symbol=document.getElementById("posSymbol").value.trim();
    if(symbol){
      var qty=Number(document.getElementById("posQty").value);
      var cost=Number(document.getElementById("posCost").value);
      if(!(qty>0)||!(cost>=0))throw new Error("填写持仓时请提供有效数量与成本价");
      var positionsBody={
        expected_profile_version:nextVersion,
        positions:[{
          symbol:symbol,
          name:document.getElementById("posName").value.trim()||symbol,
          asset_type:"stock",
          quantity:qty,
          cost_price:cost,
          buy_date:new Date().toISOString().slice(0,10),
          target_weight:Number(document.getElementById("posWeight").value||0),
          sector:null,
          risk_role:null,
          exchange:document.getElementById("posExchange").value,
          currency:document.getElementById("profileCurrency").value.trim()||"CNY"
        }]
      };
      var posRes=await apiFetch("/api/v1/user/portfolio-positions",{
        method:"PUT",
        headers:{"Content-Type":"application/json","Idempotency-Key":idempotencyKey("positions")},
        body:JSON.stringify(positionsBody)
      });
      if(!posRes.ok){
        var posErr=await posRes.json().catch(function(){return {};});
        throw new Error(posErr.message||posErr.detail||("持仓确认失败 HTTP "+posRes.status));
      }
    }
    var resume=profileModal.dataset.resumeAfter==="1";
    closeProfileModal();
    toast("金融资料已确认");
    if(resume)send(PROFILE_RESUME_MESSAGE);
  }catch(err){
    profileError.textContent=err&&err.message?err.message:"确认失败，请稍后重试";
  }finally{
    saveBtn.disabled=false;
  }
});
document.getElementById("profileCancel").addEventListener("click",closeProfileModal);

/* ---------- 发送 ---------- */
async function send(preset,regenerateExisting){
  if(!AUTH.ready){showAuth();return;}
  var value=(preset||input.value).trim();
  if(!value||ST.sending)return;

  /* 股票深度问题：未启用 Skill 时先引导，不静默进入研究链路 */
  if(!regenerateExisting&&isStockQuestion(value)&&!skillEnabled(STOCK_SKILL)){
    input.value="";
    autoGrow();
    showPage("chat");
    showEnableNudge(value);
    return;
  }

  ST.sending=true;
  sendBtn.disabled=true;
  input.value="";
  autoGrow();

  var s=activeSession();
  if(!s){
    s=makeSession();
    ST.sessions.push(s);
    while(ST.sessions.length>MAX_SESSIONS)ST.sessions.shift();
    ST.activeId=s.id;
  }
  ensureSessionSkills(s);
  if(!s.messages.length)s.title=value.length>24?value.slice(0,24)+"…":value;
  if(!regenerateExisting)s.messages.push({role:"user",content:value});
  s.updatedAt=now();
  persist();
  renderSessionList();
  chatTitle.textContent=s.title;
  hero.classList.add("hidden");
  showPage("chat");

  if(!regenerateExisting)appendMessage("user",value,true);
  rebuildQnav();
  var row=createAgentRow();
  ST.streamText="";

  if(MOCK){
    try{await mockFlow(value,row);}
    finally{
      ST.sending=false;
      sendBtn.disabled=false;
      renderSessionList();
      rebuildQnav();
      syncPluginUi();
    }
    return;
  }

  var controller=new AbortController();
  ST.controller=controller;
  ST.activeRunId=null;
  ST.pauseAcked=false;

  try{
    var response=await apiFetch("/api/v1/chat/stream",{
      method:"POST",
      headers:{"Content-Type":"application/json","Accept":"text/event-stream"},
      body:JSON.stringify({
        sessionId:s.id,
        mode:MODE,
        message:value,
        instrument:null,
        regenerate:!!regenerateExisting,
        enabledSkillIds:s.enabledSkills.slice()
      }),
      signal:controller.signal
    });
    if(!response.ok)throw new Error(await response.text()||("HTTP "+response.status));
    await consumeSse(response,function(data){return handleEvent(data,row);});
  }catch(err){
    if(err.name!=="AbortError"){
      var text=$(".text",row);
      if($(".typing",text))text.textContent="";
      clearStatus(row);
      text.classList.remove("streaming");
      if(!text.textContent){
        text.textContent="暂时无法连接研究服务，请确认后端已启动后重试。";
        text.classList.add("error");
      }
    }
  }finally{
    ST.controller=null;
    ST.sending=false;
    sendBtn.disabled=false;
    renderSessionList();
    rebuildQnav();
    syncPluginUi();
  }
}

/* ---------- Mock 演示（?mock=1，不依赖后端） ---------- */
function delay(ms){return new Promise(function(r){setTimeout(r,ms);});}

var MOCK_ANSWERS={
  stock:"科创芯片ETF（588200）跟踪上证科创板芯片指数，前三大权重股为中芯国际、海光信息、寒武纪，合计占比约 30%，行业集中在芯片设计与制造环节。\n\n估值方面，指数当前市盈率约 58 倍，处于近三年 60% 分位——不算便宜，但相比 2021 年高点 90% 分位已明显消化。市销率约 7.2 倍，处于 55% 分位。\n\n从驱动因素看：\n· 国产替代是中期主线，先进制程扩产带动设备与材料订单\n· 短期波动主要来自海外管制消息与板块轮动，近一月振幅约 12%\n· 成分股一季报整体营收同比 +18%，盈利端处于修复通道\n\n结论：估值中性偏贵，适合分批而非一次性介入；若作为卫星仓位，建议控制在组合的 10% 以内。\n\n以上仅供研究参考，不构成投资建议。",
  concept:"最大回撤（Max Drawdown）指在选定周期内，净值从最高点回落到最低点的最大幅度，用来衡量一只基金「最惨的时候有多惨」。\n\n举个例子：某基金净值从 1.5 元跌到 1.05 元再反弹，最大回撤就是 (1.5-1.05)/1.5 = 30%。\n\n看这个指标时注意三点：\n1. 和同类比才有意义——股票型基金普遍大于债券型，跨类型比较没有参考价值\n2. 看回撤修复时间——跌得深但修复快，和跌得深且长期趴窝，是完全不同的持有体验\n3. 结合自己的承受力——如果你无法接受 20% 的浮亏，就不该碰历史最大回撤 40% 的产品\n\n一般来说，宽基指数基金的长期最大回撤在 25%-45% 区间，行业主题基金可能超过 50%。",
  market:"半导体板块近期的核心逻辑可以归纳为三条线：\n\n一、国产替代加速。先进制程设备、EDA 工具、高端材料的国产化率仍处于低位，政策与订单双轮驱动，这是持续性最强的主线。\n\n二、AI 算力需求外溢。大模型训练与推理需求带动先进封装、HBM 存储、光模块等细分环节景气度上行，相关公司业绩弹性已经在财报中兑现。\n\n三、周期见底信号。全球半导体销售额同比连续回升，库存周期进入被动去库阶段，设计类公司毛利率环比改善。\n\n风险同样明确：板块整体估值分位偏高，对利空消息敏感，波动会显著大于宽基。参与方式上，定投或分批比择时梭哈更适合当前位置。"
};
var MOCK_DEFAULT="这是个值得拆解的问题。从研究角度可以这样看：\n\n1. 先明确核心变量——这个问题里最关键的假设是什么，数据能不能支撑\n2. 再看外部环境——同类问题在当前市场条件下通常怎么演化\n3. 最后落到行动——下一步是继续观察、小步验证，还是等待更好的时机\n\n如果你补充一些具体背景（比如涉及哪个标的、什么时间维度），我可以给出更聚焦的分析。";

function mockReplyFor(q){
  if(/588200|科创|芯片|ETF|估值|股|基金|板块|沪深|定投/.test(q)){
    if(/回撤|概念|什么是/.test(q))return MOCK_ANSWERS.concept;
    if(/半导体|热点|逻辑/.test(q))return MOCK_ANSWERS.market;
    return MOCK_ANSWERS.stock;
  }
  if(/什么是|回撤|概念/.test(q))return MOCK_ANSWERS.concept;
  return MOCK_DEFAULT;
}

async function mockFlow(value,row){
  var isStock=/588200|科创|芯片|ETF|估值|股|基金|板块|沪深|半导体/.test(value);
  handleEvent({type:"status",step:"classifying"},row);
  await delay(650);
  if(isStock){
    handleEvent({type:"status",step:"stock_validating"},row);
    await delay(750);
    handleEvent({type:"status",step:"skill_executing",skill:"stock-analysis"},row);
    await delay(1000);
  }else{
    handleEvent({type:"status",step:"searching_web"},row);
    await delay(850);
    handleEvent({type:"status",step:"reading_sources"},row);
    await delay(700);
  }
  var reply=mockReplyFor(value);
  for(var i=0;i<reply.length;i+=2){
    handleEvent({type:"token",content:reply.slice(i,i+2)},row);
    await delay(18);
  }
  await delay(200);
  handleEvent({type:"done",status:"COMPLETED",sessionId:null},row);
}

function injectMockSessions(){
  var t=now();
  ST.sessions=[
    {id:"mock_s1",title:"科创芯片ETF 还能拿吗",updatedAt:t-3600000,remote:false,earlierBatches:[
      [
        {role:"user",content:"帮我建一个科创芯片ETF的跟踪框架"},
        {role:"assistant",content:"可以按三个层次跟踪：\n\n一、估值层：指数市盈率、市销率及其近三年分位，每周更新一次即可。\n\n二、基本面层：前十大权重股的季报营收/利润增速、晶圆厂产能利用率、设备招标数据。\n\n三、情绪层：板块成交额占比、融资余额变化、相关新闻舆情热度。\n\n三层分别回答「贵不贵、好不好、热不热」，买卖决策就有了依据。"},
        {role:"user",content:"估值层的数据一般从哪里看？"},
        {role:"assistant",content:"几个常用来源：\n\n· 中证指数官网——指数市盈率、市净率及分位的官方口径\n· 基金公司官网/APP——ETF 的净值、溢价率、规模变化\n· 交易所披露——份额申购赎回数据，反映资金流向\n\n建议固定一个口径长期跟踪，频繁更换数据源反而会让分位失去可比性。"}
      ],
      [
        {role:"user",content:"为什么科创芯片ETF的波动比沪深300大这么多？"},
        {role:"assistant",content:"核心是成分股结构不同：\n\n沪深300是 300 家大盘蓝筹，行业分散，单一公司暴雷对指数影响有限；科创芯片集中在半导体一个赛道，成分股不足 50 只，且以高估值成长股为主。\n\n成长股定价依赖远期预期，利率、政策、海外管制的风吹草动都会放大波动。年化波动率大约是沪深300的 1.8 倍——这是它高弹性的代价，也是仓位要控制的原因。"}
      ]
    ],messages:[
      {role:"user",content:"科创芯片ETF最近跌了这么多，还能拿吗？"},
      {role:"assistant",content:"短期回调主要受板块轮动和消息面影响，国产替代的中期逻辑没有破坏。\n\n从估值看，指数市盈率分位已从 90% 回落到 60% 附近，压力释放了大半。如果你成本不高、仓位不重，可以继续持有观察；如果仓位偏重，可以借反弹把仓位降到舒适水平。\n\n关键跟踪点：成分股季报兑现情况、海外管制政策变化。"},
      {role:"user",content:"我的成本在净值 1.35 左右，仓位大概两成，需要减吗？"},
      {role:"assistant",content:"以当前净值 1.28 附近看，你的浮亏约 5%，两成仓位属于中等偏重。\n\n建议这样处理：\n· 不需要恐慌清仓——估值分位 60% 并不算极端，中期逻辑还在\n· 但两成仓对单一行业主题来说偏重，可以趁反弹减到 10%-15%，把波动降到你能安心持有的水平\n· 剩余部分用季度维度跟踪，别盯日线\n\n减仓的节奏比时点重要：分两次，间隔一到两周，避免卖在单日低点。"},
      {role:"user",content:"那减出来的钱放到哪里比较合适？"},
      {role:"assistant",content:"减出来的仓位可以按「先稳后进」的顺序安排：\n\n第一层：货币基金或短债基金，作为机动资金，占比一半左右——它的作用是在板块继续下探时有子弹补仓。\n\n第二层：宽基指数，比如沪深300 或中证 A500，当前估值分位中性偏低，适合分批转入，平滑单一行业的波动。\n\n暂时不建议的：另一个高波动行业主题——那就只是换了了个赛道继续承担同样的风险，失去了减仓的意义。"}
    ]},
    {id:"mock_s2",title:"沪深300 估值处于什么位置",updatedAt:t-7200000,remote:false,messages:[
      {role:"user",content:"沪深300现在的估值处于历史什么位置？适合定投吗"},
      {role:"assistant",content:"沪深300 当前市盈率约 12.5 倍，处于近十年 45% 分位；市净率约 1.3 倍，处于 25% 分位附近——整体处于中性偏低的区域。\n\n从定投角度，这个位置属于「可以正常投」的区间：既不是明显低估的黄金坑，也没有高估风险。保持既定节奏即可，不需要刻意加码或停止。"}
    ]},
    {id:"mock_s3",title:"什么是基金的最大回撤",updatedAt:t-90000000,remote:false,messages:[
      {role:"user",content:"什么是基金的最大回撤？怎么看这个指标"},
      {role:"assistant",content:"最大回撤（Max Drawdown）指在选定周期内，净值从最高点回落到最低点的最大幅度，用来衡量一只基金「最惨的时候有多惨」。\n\n看的时候注意三点：\n1. 和同类比才有意义\n2. 看回撤修复时间\n3. 结合自己的承受力\n\n宽基指数基金的长期最大回撤一般在 25%-45% 区间。"}
    ]},
    {id:"mock_s4",title:"半导体设备的国产替代节奏",updatedAt:t-10*86400000,remote:false,messages:[
      {role:"user",content:"半导体设备国产化现在进行到哪一步了？"},
      {role:"assistant",content:"整体处于「刻蚀、薄膜沉积率先突破，光刻仍在追赶」的格局。\n\n刻蚀设备国产化率已超过 20%，中微公司等进入 5nm 产线验证；薄膜沉积约 15%；光刻环节国产化率仍低于 5%，是最长的短板。\n\n投资视角上，订单能见度和产线验证进度比概念更重要——关注各公司合同负债与存货中发出商品的增速。"}
    ]}
  ];
  ST.activeId="mock_s1";
}

/* ---------- Mock 工具条（仅 ?mock=1 显示：骨架条预览 / 重置数据） ---------- */
function initMockTools(){
  var bar=document.createElement("div");
  bar.className="mock-tools";
  bar.innerHTML=
    '<button type="button" data-act="skel">骨架条预览</button>'+
    '<button type="button" data-act="reset">重置演示数据</button>';
  document.body.appendChild(bar);
  var skelEl=null;
  bar.addEventListener("click",function(e){
    var act=e.target.dataset?e.target.dataset.act:null;
    if(!act)return;
    if(act==="skel"){
      if(skelEl){
        skelEl.remove();skelEl=null;
        e.target.textContent="骨架条预览";
      }else{
        skelEl=buildSkeleton();
        messages.insertBefore(skelEl,messages.firstChild);
        e.target.textContent="关闭骨架条";
      }
    }else if(act==="reset"){
      try{
        localStorage.removeItem(STORAGE_KEY);
        localStorage.removeItem(MOCK_VER_KEY);
      }catch(err){}
      location.reload();
    }
  });
}

/* ---------- 远端会话同步（静默失败） ---------- */
async function syncRemoteSessions(){
  try{
    var res=await apiFetch("/api/v1/conversations?mode="+MODE+"&limit="+MAX_SESSIONS);
    if(!res.ok)return;
    var remote=await res.json();
    if(!Array.isArray(remote))return;
    var localDrafts=ST.sessions.filter(function(s){return !s.remote;});
    var merged=remote.map(function(item){
      var existing=null;
      for(var i=0;i<ST.sessions.length;i++)if(ST.sessions[i].id===item.sessionId){existing=ST.sessions[i];break;}
      return existing||{
        id:item.sessionId,title:item.title||"未命名对话",
        messages:[],updatedAt:item.updatedAt?Date.parse(item.updatedAt):now(),
        remote:true,loaded:false
      };
    });
    localDrafts.forEach(function(d){
      var dup=merged.some(function(m){return m.id===d.id;});
      if(!dup)merged.push(d);
    });
    ST.sessions=merged;
    if(!ST.activeId&&merged.length)ST.activeId=merged[0].id;
    persist();
    renderSessionList();
    var s=activeSession();
    if(s&&s.remote&&!s.loaded)loadSessionDetail(s);
    else renderMessages();
  }catch(e){/* 后端未启动时保持本地数据 */}
}
async function loadSessionDetail(s){
  try{
    var res=await apiFetch("/api/v1/conversations/"+encodeURIComponent(s.id));
    if(!res.ok)return;
    var detail=await res.json();
    var list=Array.isArray(detail.messages)?detail.messages:[];
    s.messages=list.filter(function(m){return m&&m.content;}).map(function(m){
      return {role:m.role==="user"?"user":"assistant",content:m.content};
    });
    s.loaded=true;
    if(detail.session&&detail.session.title)s.title=detail.session.title;
    persist();
    if(ST.activeId===s.id){renderSessionList();renderMessages();}
  }catch(e){}
}

/* ---------- 用户认证 ---------- */
function showAuth(message){
  var modal=document.getElementById("authModal");
  modal.hidden=false;
  document.getElementById("authError").textContent=message||"";
  setAuthMode(AUTH_MODE);
  setTimeout(function(){document.getElementById("authUsername").focus();},0);
}
function setAuthMode(mode){
  AUTH_MODE=mode;
  var registering=mode==="register";
  document.getElementById("authTitle").textContent=registering?"注册 BDLH Agent Runtime":"登录 BDLH Agent Runtime";
  document.getElementById("authHint").textContent=registering?"填写用户名和至少 8 位密码。注册成功后将直接进入对话。":"登录后，对话、记忆和个人资料将按账号独立保存。";
  document.getElementById("authLogin").textContent=registering?"提交注册":"登录";
  document.getElementById("authRegister").textContent=registering?"返回登录":"注册账号";
  document.getElementById("authPassword").autocomplete=registering?"new-password":"current-password";
  document.getElementById("authError").textContent="";
}
function updateAccount(){
  document.getElementById("accountButton").textContent=AUTH.user?AUTH.user.username:"登录";
}
function resetForUser(){
  ST.sessions=[];ST.activeId=null;ST.sending=false;ST.streamText="";ST.controller=null;
  restore();
  renderSessionList();
  renderMessages();
  updateAccount();
  if(!MOCK)syncRemoteSessions();
}
function completeAuth(data){
  AUTH.ready=true;
  AUTH.user={userId:String(data.userId),username:data.username};
  if(data.token)localStorage.setItem(AUTH_TOKEN_KEY,data.token);
  document.getElementById("authPassword").value="";
  document.getElementById("authModal").hidden=true;
  resetForUser();
  input.focus();
}
async function initializeAuth(){
  if(MOCK){
    restore();
    var mockVer=null;
    try{mockVer=localStorage.getItem(MOCK_VER_KEY);}catch(e){}
    if(!ST.sessions.length||mockVer!==String(MOCK_DATA_VERSION)){
      injectMockSessions();
      persist();
      try{localStorage.setItem(MOCK_VER_KEY,String(MOCK_DATA_VERSION));}catch(e){}
    }
    renderSessionList();renderMessages();updateAccount();initMockTools();
    return;
  }
  var token=localStorage.getItem(AUTH_TOKEN_KEY);
  if(!token){showAuth();return;}
  try{
    var response=await NATIVE_FETCH("/api/v1/auth/me",{headers:{Authorization:"Bearer "+token}});
    if(response.ok){completeAuth(Object.assign(await response.json(),{token:token}));return;}
    if(response.status===401||response.status===403)localStorage.removeItem(AUTH_TOKEN_KEY);
    showAuth(response.status>=500?"登录服务暂时不可用，请稍后重试":"登录状态已失效，请重新登录");
  }catch(e){
    // 网络故障不删除仍可能有效的 Token。
    showAuth("暂时无法连接登录服务，请稍后重试");
  }
}
async function login(){
  var username=document.getElementById("authUsername").value.trim();
  var password=document.getElementById("authPassword").value;
  var error=document.getElementById("authError");
  if(!username||password.length<8){error.textContent="请输入用户名和至少 8 位密码";return;}
  var registering=AUTH_MODE==="register";
  error.textContent=registering?"正在注册…":"正在登录…";
  try{
    var response=await NATIVE_FETCH("/api/v1/auth/"+(registering?"register":"login"),{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({username:username,password:password})
    });
    var data=await response.json();
    if(!response.ok)throw new Error(data.error||(registering?"注册失败":"登录失败"));
    completeAuth(data);
  }catch(e){error.textContent=e.message||"认证服务暂时不可用";}
}

document.getElementById("authLogin").addEventListener("click",login);
document.getElementById("authRegister").addEventListener("click",function(){setAuthMode(AUTH_MODE==="register"?"login":"register");});
document.getElementById("authPassword").addEventListener("keydown",function(e){if(e.key==="Enter")login();});
document.getElementById("accountButton").addEventListener("click",function(){
  if(!AUTH.ready){showAuth();return;}
  if(MOCK)return;
  if(window.confirm("退出当前账号？")){
    localStorage.removeItem(AUTH_TOKEN_KEY);
    document.getElementById("authPassword").value="";
    location.reload();
  }
});

/* ---------- 输入框 ---------- */
function autoGrow(){
  input.style.height="auto";
  input.style.height=Math.min(input.scrollHeight,200)+"px";
}
input.addEventListener("input",autoGrow);
input.addEventListener("keydown",function(e){
  if(e.key==="Enter"&&!e.shiftKey&&!e.isComposing){
    e.preventDefault();
    send();
  }
});
document.addEventListener("keydown",function(e){
  if(e.key!=="Escape")return;
  if(!ST.sending&&!ST.activeRunId&&!ST.pauseAcked)return;
  e.preventDefault();
  if(e.shiftKey){
    if(ST.controller){try{ST.controller.abort();}catch(err){}}
    requestCancelRun();
    return;
  }
  if(!ST.sending||!ST.controller)return;
  requestPauseAndAbort();
});

async function requestCancelRun(){
  var runId=ST.activeRunId;
  if(!runId||MOCK){
    ST.sending=false;
    sendBtn.disabled=false;
    return;
  }
  try{
    var response=await apiFetch("/api/v1/agent-runs/"+encodeURIComponent(runId)+"/cancel",{
      method:"POST",
      headers:{"Accept":"application/json"}
    });
    if(response.ok){
      ST.pauseAcked=false;
      ST.activeRunId=null;
      toast("已取消当前分析");
    }
  }catch(err){
    toast("取消请求失败，请稍后重试");
  }
}

async function requestPauseAndAbort(){
  var runId=ST.activeRunId;
  // 先请求 pause 再 abort：避免 SSE 断开后服务端完成路径清掉 pending。
  if(runId&&!MOCK){
    try{
      var response=await apiFetch("/api/v1/agent-runs/"+encodeURIComponent(runId)+"/pause",{
        method:"POST",
        headers:{"Accept":"application/json"}
      });
      if(response.ok){
        var ack=await response.json();
        ST.pauseAcked=!!(ack.resumable||ack.resumable===undefined);
        toast(ST.pauseAcked?"已暂停，可回复「继续」恢复":"已请求暂停");
      }
    }catch(err){
      toast("暂停请求失败，请稍后重试");
    }
  }
  var controller=ST.controller;
  if(controller){
    try{controller.abort();}catch(err){}
  }
  ST.sending=false;
  sendBtn.disabled=false;
}

composer.addEventListener("submit",function(e){
  e.preventDefault();
  send();
});

/* ---------- 建议卡片 / Skill chips ---------- */
document.querySelectorAll(".suggest").forEach(function(btn){
  btn.addEventListener("click",function(){
    send(btn.dataset.q||"");
  });
});

var skillStockBtn=document.getElementById("skillStock");
if(skillStockBtn){
  skillStockBtn.addEventListener("click",function(){
    if(skillEnabled(STOCK_SKILL))setSkillEnabled(STOCK_SKILL,false,"off");
    else showPage("plugins");
  });
}
function bindGotoPlugins(id){
  var el=document.getElementById(id);
  if(el)el.addEventListener("click",function(){showPage("plugins");});
}
bindGotoPlugins("skillGotoPlugins");
bindGotoPlugins("dockPlugins");
bindGotoPlugins("navPlugins");
var navProfile=document.getElementById("navProfile");
if(navProfile)navProfile.addEventListener("click",function(){void openProfileModal({resumeAfter:false});});
var btnBackChat=document.getElementById("btnBackChat");
if(btnBackChat)btnBackChat.addEventListener("click",function(){showPage("chat");});
var btnBackChat2=document.getElementById("btnBackChat2");
if(btnBackChat2)btnBackChat2.addEventListener("click",function(){showPage("chat");});
var pluginToggle=document.getElementById("pluginToggle");
if(pluginToggle){
  pluginToggle.addEventListener("click",function(){
    var next=!skillEnabled(STOCK_SKILL);
    setSkillEnabled(STOCK_SKILL,next,next?"on":"off");
  });
}
var btnEnableAndChat=document.getElementById("btnEnableAndChat");
if(btnEnableAndChat){
  btnEnableAndChat.addEventListener("click",function(){
    setSkillEnabled(STOCK_SKILL,true,"on");
    showPage("chat");
    input.placeholder="股票分析已启用，直接提问即可";
    input.focus();
  });
}
var chipEnabled=document.getElementById("chipEnabled");
if(chipEnabled){
  chipEnabled.addEventListener("click",function(e){
    if(e.target.closest("#chipClose")){setSkillEnabled(STOCK_SKILL,false,"off");return;}
    showPage("plugins");
  });
}

/* ---------- 侧边栏 ---------- */
newChatBtn.addEventListener("click",newChat);
var sidebarCollapse=document.getElementById("sidebarCollapse");
function setSidebarCollapsed(collapsed){
  sidebar.classList.toggle("collapsed",collapsed);
  sidebarCollapse.setAttribute("aria-expanded",String(!collapsed));
  sidebarCollapse.setAttribute("aria-label",collapsed?"展开历史记录":"收起历史记录");
  sidebarCollapse.title=collapsed?"展开历史记录":"收起历史记录";
}
sidebarCollapse.addEventListener("click",function(){
  if(window.innerWidth<=860){
    sidebar.classList.remove("open");
    return;
  }
  setSidebarCollapsed(!sidebar.classList.contains("collapsed"));
});
document.getElementById("mobileMenu").addEventListener("click",function(){
  setSidebarCollapsed(false);
  sidebar.classList.toggle("open");
});
document.addEventListener("click",function(e){
  if(window.innerWidth>860)return;
  if(!sidebar.classList.contains("open"))return;
  if(sidebar.contains(e.target)||document.getElementById("mobileMenu").contains(e.target))return;
  sidebar.classList.remove("open");
});

/* ---------- 回到底部 + 上滑加载 ---------- */
var toBottom=document.getElementById("toBottom");
scrollBox.addEventListener("scroll",function(){
  var far=scrollBox.scrollHeight-scrollBox.scrollTop-scrollBox.clientHeight>320;
  toBottom.classList.toggle("show",far);
  markQnavActive();
  if(scrollBox.scrollTop<72)loadEarlier();
});
toBottom.addEventListener("click",function(){
  scrollBox.scrollTo({top:scrollBox.scrollHeight,behavior:"smooth"});
});

/* ---------- 启动 ---------- */
void initializeAuth();
autoGrow();
syncPluginUi();

})();
