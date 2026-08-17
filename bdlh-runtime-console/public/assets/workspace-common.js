
  /* ================================================================
     Agent 配置表：新增 Agent 只需在这里加一个配置对象
     字段：id / label / icon(svg path) / needsInstrument / welcome / prompts
     ================================================================ */
  /* 页面跳转：兼容 file:// 直开与 http 部署 */
  function go(path){
    if(!path)return;
    if(location.protocol==="file:"){
      const base=location.href.split(/[?#]/)[0];
      const dir=base.slice(0,base.lastIndexOf("/")+1);
      const target=dir+(path==="/"?"index.html":"workspace.html");
      const q=path.includes("?")?path.split("?")[1]:"";
      location.href=q?target+"?"+q:target;
    }else{
      location.href=path;
    }
  }

  const AUTH_TOKEN_KEY="bdlh_runtime.auth.token.v1";
  const NATIVE_FETCH=window.fetch.bind(window);
  const AUTH={ready:false,user:null,pendingQuestion:""};
  let authMode="login";

  async function apiFetch(resource,options={}){
    const next={...options,headers:new Headers(options.headers||{})};
    const token=localStorage.getItem(AUTH_TOKEN_KEY);
    if(token)next.headers.set("Authorization","Bearer "+token);
    const response=await NATIVE_FETCH(resource,next);
    if(response.status===401&&!String(resource).includes("/api/v1/auth/")){
      AUTH.ready=false;AUTH.user=null;localStorage.removeItem(AUTH_TOKEN_KEY);showAuthModal();
    }
    return response;
  }

  function userStorageKey(base){
    return base+"."+(AUTH.user?.userId||"anonymous");
  }
  const AGENTS=[
    {
      id:"general",
      label:"智能问答",
      description:"知识检索 · 方案讨论 · 联网核验",
      group:"core",
      icon:'<path d="M5 5.5h14v10H9l-4 3v-13Z"/>',
      needsInstrument:false,
      welcomeTitle:"今天想研究什么？",
      welcomeDesc:"从一个问题开始：梳理信息、验证事实、讨论方案，形成清晰的结论。",
      welcomePaths:[
        {primary:true,strong:"开始提问",desc:"适合知识解释、方案讨论、系统使用和需要检索核验的问题。",action:{type:"focus"}},
        {strong:"需要分析股票？",desc:"前往股市分析，选择股票、ETF 或基金后开始。",action:{type:"goto",url:"/agent?name=stock"}}
      ],
      prompts:[
        ["解释一个概念","帮我用通俗的方式解释一下什么是 ReAct Agent"],
        ["搜索核验信息","帮我搜索并核验近期人工智能领域的重要变化"],
        ["一起优化方案","帮我分析一个产品方案有哪些值得推敲的地方"]
      ],
      kicker:"CHAT AGENT",
      title:"智能问答",
      placeholder:"输入你想研究的问题…",
      hint:"问答 Agent · 需要时自动联网检索 · Enter 发送",
      newSessionDesc:"新会话已创建。从一个问题开始；需要核验的信息会进入受控检索流程。"
    },
    {
      id:"stock",
      label:"股市分析",
      description:"个股 · 板块 · 组合 · 量化",
      group:"core",
      icon:'<path d="M4 18V9m6 9V5m6 13v-7m4 7H2"/>',
      needsInstrument:true,
      welcomeTitle:"从一个标的研究",
      welcomeDesc:"分析个股、ETF、板块与组合；关键结论会同时呈现数据依据和限制。",
      welcomePaths:[
        {primary:true,strong:"选择分析标的",desc:"选择股票、ETF 或基金，后续问题自动沿用当前标的。",action:{type:"instrument"}},
        {strong:"先做普通问答",desc:"进入智能问答，处理知识解释和无需绑定标的的问题。",action:{type:"goto",url:"/agent?name=general"}}
      ],
      prompts:[
        ["现在适合买入吗","现在适合买入吗？重点看短线风险。"],
        ["查看板块热度","今天哪些行业板块最强？请展示热度组成。"],
        ["查看外围关注","半导体板块最近网上讨论度高吗？"],
        ["查看关键支撑位","分析关键支撑位和失效条件"]
      ],
      kicker:"STOCK AGENT",
      title:"股市分析",
      placeholder:"输入股票代码或投资问题…",
      hint:"个股决策需先选择标的；可直接询问板块热度",
      newSessionDesc:"新会话已创建。可直接研究板块和市场；涉及个股决策时，请先选择分析标的。"
    }
  ];

  const AGENT_GROUPS=[
    {id:"core",label:"AGENT SYSTEM"}
  ];

  const AGENT_MAP=Object.fromEntries(AGENTS.map(a=>[a.id,a]));

  const MAX_SESSIONS_PER_AGENT=20;
  const SESSION_STORAGE_KEY="bdlh_runtime.sessions.v2";

  const ST={
    mode:"stock",
    sessionsByMode:Object.fromEntries(AGENTS.map(a=>[a.id,createSessionList(a.id)])),
    sending:false,
    currentBubble:null,
    streamText:"",
    sideView:"runs",
    currentInstrument:loadInstrument(),
    pendingInstrument:null,
    activeController:null,
    activeRunId:null,
    currentTrace:null
  };

  function createSessionList(mode){
    const restored=restoreSessions(mode);
    if(restored&&restored.length){
      return {activeId:restored[restored.length-1].id, items:restored};
    }
    // 无历史会话：等待用户发起第一轮研究，避免在后端目录生成空会话。
    return {activeId:null, items:[]};
  }

  function makeSession(mode){
    const m=mode||ST.mode;
    return {
      id:genUUID(),
      title:defaultSessionTitle(m),
      store:document.createDocumentFragment(),
      messages:[],
      hasMessages:false,
      draft:true,
      runId:null,
      trace:null,
      createdAt:Date.now()
    };
  }

  function restoreSessions(mode){
    try{
      const raw=localStorage.getItem(userStorageKey(SESSION_STORAGE_KEY));
      if(!raw)return null;
      const all=JSON.parse(raw);
      const list=all[mode];
      if(!Array.isArray(list)||!list.length)return null;
      return list.slice(-MAX_SESSIONS_PER_AGENT).map(s=>Object.assign(makeSession(mode),{
        id:s.id,title:s.title||defaultSessionTitle(mode),hasMessages:!!s.hasMessages,
        draft:false,runId:s.runId||null,updatedAt:s.updatedAt||Date.now()
      }));
    }catch(e){
      return null;
    }
  }

  function persistSessions(){
    try{
      const data={};
      for(const mode of Object.keys(ST.sessionsByMode)){
        data[mode]=ST.sessionsByMode[mode].items.filter(s=>!s.draft).map(s=>({
          id:s.id,title:s.title,hasMessages:s.hasMessages,runId:s.runId,updatedAt:s.updatedAt||Date.now()
        }));
      }
      localStorage.setItem(userStorageKey(SESSION_STORAGE_KEY),JSON.stringify(data));
    }catch(e){/* 存储失败不影响使用 */}
  }

  function activeSession(){
    const list=ST.sessionsByMode[ST.mode];
    if(!list.activeId)return null;
    const cur=list.items.find(s=>s.id===list.activeId);
    return cur||null;
  }

  function curS(){
    return activeSession()||makeSession(ST.mode);
  }

  function genUUID(){
    return (globalThis.crypto&&crypto.randomUUID)?crypto.randomUUID():'session-'+Date.now()+"-"+Math.random().toString(36).slice(2,8);
  }

  function defaultSessionTitle(mode){
    return mode==="stock"?"新的观市研究":"新的知见对话";
  }

  function createSessionTitle(message){
    const normalized=String(message||"").replace(/\s+/g," ").trim();
    if(!normalized)return defaultSessionTitle(ST.mode);
    return normalized.length>22?normalized.slice(0,22)+"…":normalized;
  }

  const messages=document.getElementById("messages");
  const input=document.getElementById("input");
  const composer=document.getElementById("composer");
  const sendBtn=document.getElementById("sendBtn");
  const statusBar=document.getElementById("statusBar");
  const headSkill=document.getElementById("headSkill");
  const headRunId=document.getElementById("headRunId");
  const runsDrawer=document.getElementById("runsPanel")||null;
  const instrumentTitle=document.getElementById("instrumentTitle");
  const instrumentHint=document.getElementById("instrumentHint");
  const instrumentIcon=document.getElementById("instrumentIcon");
  const selectInstrument=document.getElementById("selectInstrument");
  const clearInstrument=document.getElementById("clearInstrument");
  const modeKicker=document.getElementById("modeKicker");
  const chatTitle=document.getElementById("chatTitle");
  const composerHint=document.getElementById("composerHint");

  updateSessionBadge();
  renderInstrument();

  function loadInstrument(){
    try{
      return JSON.parse(localStorage.getItem(userStorageKey("bdlh_runtime.currentInstrument"))||"null");
    }catch(e){
      return null;
    }
  }

  function saveInstrument(instrument){
    ST.currentInstrument=instrument;
    const key=userStorageKey("bdlh_runtime.currentInstrument");
    if(instrument)localStorage.setItem(key,JSON.stringify(instrument));
    else localStorage.removeItem(key);
    renderInstrument();
  }

  function renderInstrument(){
    const current=ST.currentInstrument;
    if(!current){
      instrumentIcon.textContent="＋";
      instrumentTitle.textContent="未选择分析标的";
      instrumentHint.textContent="可直接查询板块；个股决策需要选择股票、ETF 或基金";
      selectInstrument.textContent="选择标的";
      clearInstrument.style.display="none";
      if(ST.mode==="stock"){
        sendBtn.disabled=false;
        input.placeholder="询问板块热度、讨论度，或先选择个股标的…";
        composerHint.textContent="可直接询问板块；个股决策需先选择标的";
      }
      return;
    }
    instrumentIcon.textContent=(current.type==="股票"?"股":"基");
    instrumentTitle.innerHTML='<span class="instrument-code">'+escHtml(current.symbol)+'</span>'+escHtml(current.name||"当前标的")+' <span class="instrument-type">'+escHtml(current.type||"标的")+'</span>';
    instrumentHint.textContent="后续分析固定沿用这个标的；如需更换，请先点击切换";
    selectInstrument.textContent="切换";
    clearInstrument.style.display="";
  }

  function renderSessionList(){
    const listEl=document.getElementById("sessionList");
    if(!listEl)return;
    const list=ST.sessionsByMode[ST.mode];
    listEl.innerHTML=list.items.filter(s=>!s.draft).sort((a,b)=>(b.updatedAt||0)-(a.updatedAt||0)).map(s=>{
      const active=s.id===list.activeId?" active":"";
      const title=s.hasMessages?s.title:"未命名研究";
      return '<div class="session-item'+active+'" data-session="'+s.id+'" role="button" tabindex="0">'+
        '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>'+
        '<span>'+escHtml(title)+'</span></div>';
    }).join("");
    listEl.querySelectorAll(".session-item").forEach(el=>{
      el.addEventListener("click",()=>selectSession(el.dataset.session));
    });
  }

  function selectSession(id){
    const list=ST.sessionsByMode[ST.mode];
    const target=list.items.find(s=>s.id===id);
    if(!target||id===list.activeId)return;
    // 1. 保存当前消息（空白态 prev 为 null，直接丢弃）
    const prev=activeSession();
    if(prev){while(messages.firstChild)prev.store.appendChild(messages.firstChild);}
    // 2. 切换到目标会话
    list.activeId=id;
    ST.sending=false;
    ST.currentBubble=null;
    ST.streamText="";
    messages.replaceChildren();
    if(target.messages&&target.messages.length){
      renderSessionMessages(target);
    }else if(target.store.childNodes.length){
      messages.appendChild(target.store);
    }else{
      const cfg=AGENT_MAP[ST.mode];
      renderWelcome(cfg.needsInstrument&&ST.currentInstrument
        ?"继续分析 "+ST.currentInstrument.symbol
        :undefined,cfg.needsInstrument&&ST.currentInstrument
          ?"可继续针对当前标的提问，或先选择其他标的。"
          :cfg.newSessionDesc);
    }
    statusBar.innerHTML="";
    headSkill.textContent="";
    headRunId.textContent="";
    sendBtn.disabled=false;
    persistSessions();
    updateSessionBadge();
    renderCurrentTrace();
    setConversationUrl(target.id);
    input.value="";
    input.focus();
    void loadSessionDetail(target);
  }

  function updateSessionBadge(){
    const s=activeSession();
    const title=s&&!s.draft? (s.title||defaultSessionTitle(ST.mode)) : "新会话";
    const sessionName=document.getElementById("sessionName");
    if(sessionName)sessionName.textContent=title;
    const badge=document.getElementById("sessionBadge");
    if(badge){badge.textContent=title;badge.title=title;}
    renderSessionList();
  }

  function setConversationUrl(sessionId){
    const nextUrl=new URL(location.href);
    if(sessionId)nextUrl.searchParams.set("conversationId",sessionId);
    else nextUrl.searchParams.delete("conversationId");
    history.replaceState(null,"",nextUrl.toString());
  }

  function adoptServerSessionId(serverSessionId){
    const session=activeSession();
    if(!session||!serverSessionId||session.id===serverSessionId)return;
    const list=ST.sessionsByMode[ST.mode];
    const duplicate=list.items.find(item=>item!==session&&item.id===serverSessionId);
    if(duplicate){
      duplicate.messages=session.messages||duplicate.messages||[];
      duplicate.hasMessages=session.hasMessages;
      duplicate.title=session.title;
      duplicate.draft=false;
      list.items=list.items.filter(item=>item!==session);
      list.activeId=duplicate.id;
    }else{
      session.id=serverSessionId;
      session.draft=false;
    }
    persistSessions();
    updateSessionBadge();
    setConversationUrl(list.activeId);
  }

  function appendStoredMessage(message){
    if(!message||!message.content)return;
    if(message.role==="assistant"){
      const row=document.createElement("div");row.className="msg";
      row.innerHTML='<div class="avatar">AI</div><div class="bubble"></div>';
      row.querySelector(".bubble").textContent=message.content;
      messages.appendChild(row);
      return;
    }
    addUserMsg(message.content);
  }

  function renderSessionMessages(session){
    messages.replaceChildren();
    const history=Array.isArray(session?.messages)?session.messages:[];
    history.forEach(appendStoredMessage);
    if(!history.length){
      const cfg=AGENT_MAP[ST.mode];
      renderWelcome(cfg?.needsInstrument&&ST.currentInstrument
        ?"继续分析 "+ST.currentInstrument.symbol
        :undefined,
        cfg?.needsInstrument&&ST.currentInstrument
          ?"可继续针对当前标的提问，或先选择其他标的。"
          :cfg?.newSessionDesc);
    }
    updateIdleState();
    scrollMsgs();
  }

  async function loadSessionDetail(session){
    if(!session||session.draft)return;
    try{
      const response=await apiFetch("/api/v1/conversations/"+encodeURIComponent(session.id));
      if(!response.ok)throw new Error("HTTP "+response.status);
      const detail=await response.json();
      const serverSession=detail.session||{};
      session.id=serverSession.sessionId||session.id;
      session.title=serverSession.title||session.title;
      session.hasMessages=(serverSession.messageCount||0)>0;
      session.messages=Array.isArray(detail.messages)?detail.messages:[];
      session.draft=false;
      session.updatedAt=serverSession.updatedAt?Date.parse(serverSession.updatedAt):Date.now();
      persistSessions();
      updateSessionBadge();
      renderSessionMessages(session);
    }catch(error){
      toast("会话内容暂时无法加载");
    }
  }

  async function loadConversations(mode){
    const list=ST.sessionsByMode[mode];
    const activeDraft=list.items.find(session=>session.id===list.activeId&&session.draft);
    try{
      const response=await apiFetch("/api/v1/conversations?mode="+encodeURIComponent(mode)+"&limit="+MAX_SESSIONS_PER_AGENT);
      if(!response.ok)throw new Error("HTTP "+response.status);
      const remote=await response.json();
      const drafts=list.items.filter(session=>session.draft);
      list.items=(Array.isArray(remote)?remote:[]).map(item=>({
        id:item.sessionId,title:item.title||defaultSessionTitle(mode),store:document.createDocumentFragment(),
        messages:[],hasMessages:(item.messageCount||0)>0,draft:false,runId:null,trace:null,
        updatedAt:item.updatedAt?Date.parse(item.updatedAt):Date.now()
      })).concat(drafts);
      const requested=new URLSearchParams(location.search).get("conversationId");
      if(activeDraft&&list.items.some(session=>session.id===activeDraft.id))list.activeId=activeDraft.id;
      else if(requested&&list.items.some(session=>session.id===requested))list.activeId=requested;
      else if(!requested&&list.items.length)list.activeId=list.items[0].id;
      else if(list.activeId&&!list.items.some(session=>session.id===list.activeId))list.activeId=null;
      persistSessions();
      updateSessionBadge();
      const current=activeSession();
      if(current&&!current.draft){
        setConversationUrl(current.id);
        await loadSessionDetail(current);
      }
    }catch(error){
      // 后端暂不可用时保留本地目录，消息详情仍以当前页面缓存为准。
    }
  }

  function scrollMsgs(){
    messages.scrollTop=messages.scrollHeight;
  }

  function addUserMsg(text){
    const row=document.createElement("div");row.className="msg user";
    row.innerHTML='<div class="avatar">U</div><div class="bubble"></div>';
    row.querySelector(".bubble").textContent=text;
    messages.appendChild(row);scrollMsgs();
    updateIdleState();
  }

  function createAgentBubble(){
    clearEmpty();
    const row=document.createElement("div");row.className="msg";
    row.innerHTML='<div class="avatar">AI</div><div class="bubble streaming"><div class="typing"><i></i><i></i><i></i></div></div>';
    messages.appendChild(row);scrollMsgs();
    return row.querySelector(".bubble");
  }

  function clearEmpty(){
    const emptyDiv=messages.querySelector(".empty");
    if(emptyDiv)emptyDiv.remove();
  }

  function addStatusTags(statuses){
    statusBar.innerHTML="";
    statuses.forEach(s=>{
      const tag=document.createElement("span");
      tag.className="status-tag "+(s.active?"active":"done");
      tag.innerHTML=(s.active?'<i></i>':'')+s.label;
      statusBar.appendChild(tag);
    });
  }

  function setStatus(steps){
    const map={
      classifying:"识别需求",
      direct_chat:"直接问答",
      react_planning:"规划工具",
      searching_web:"搜索资料",
      reading_sources:"整理来源",
      stock_validating:"校验标的",
      skill_executing:"执行分析",
      searching_vector:"向量检索",
      retrieval_result:"检索完成"
    };
    const list=Object.entries(map).map(([k,v])=>({label:v,active:false,done:false}));
    let found=false;
    list.forEach(item=>{
      if(item.label===map[steps.current]){item.active=true;found=true;}
      else if(!found)item.done=true;
    });
    addStatusTags(list);
    if(steps.skill)headSkill.textContent="· "+steps.skill;else headSkill.textContent="";
  }

  function finalizeBubble(bubble){
    bubble.classList.remove("streaming");
    ST.currentBubble=null;
    ST.streamText="";
  }

  function addActionCard(bubble,title,text,buttons){
    const card=document.createElement("div");card.className="action-card";
    card.innerHTML='<div class="ac-title">'+title+'</div><div class="ac-text">'+text+'</div><div class="ac-btns"></div>';
    const btnRow=card.querySelector(".ac-btns");
    buttons.forEach(b=>{
      const btn=document.createElement("button");
      btn.className="ac-btn "+b.cls;
      btn.textContent=b.label;
      btn.addEventListener("click",b.action);
      btnRow.appendChild(btn);
    });
    bubble.appendChild(card);
  }

  async function send(text){
    if(!AUTH.ready){showAuthModal();return;}
    const value=(text||input.value).trim();if(!value||ST.sending)return;
    ST.sending=true;input.value="";sendBtn.disabled=true;
    // 草稿会话发出首条消息后进入正式会话目录（上限 20 条）。
    let s=activeSession();
    if(!s){
      const list=ST.sessionsByMode[ST.mode];
      s=makeSession(ST.mode);
      list.items.push(s);
      while(list.items.length>MAX_SESSIONS_PER_AGENT)list.items.shift();
      list.activeId=s.id;
    }
    s.draft=false;
    if(!s.hasMessages){
      s.hasMessages=true;
      s.title=createSessionTitle(value);
    }
    s.messages=s.messages||[];
    s.messages.push({role:"user",content:value});
    s.updatedAt=Date.now();
    persistSessions();
    updateSessionBadge();
    setConversationUrl(s.id);
    addUserMsg(value);

    const bubble=createAgentBubble();
    ST.currentBubble=bubble;
    ST.streamText="";
    headRunId.textContent="";

    const instrument=ST.mode==="stock"&&ST.currentInstrument?{
      symbol:ST.currentInstrument.symbol,
      assetType:normalizeAssetType(ST.currentInstrument.type)
    }:null;
    const controller=new AbortController();
    ST.activeController=controller;
    const phase={last:null};
    try{
      const response=await apiFetch("/api/v1/chat/stream",{
        method:"POST",
        headers:{"Content-Type":"application/json","Accept":"text/event-stream"},
        body:JSON.stringify({
          sessionId:activeSession().id,
          mode:ST.mode,
          message:value,
          instrument
        }),
        signal:controller.signal
      });
      if(!response.ok)throw new Error(await response.text()||("HTTP "+response.status));
      await consumeSse(response,data=>handleStreamEvent(data,bubble,phase));
    }catch(error){
      if(error.name!=="AbortError"){
        bubble.textContent="暂时无法连接研究服务，请稍后重试。";
        bubble.style.color="#e5484d";
        finalizeBubble(bubble);
      }
    }finally{
      ST.activeController=null;
      ST.sending=false;
      sendBtn.disabled=false;
      if(!ST.streamText&&bubble.querySelector(".typing"))finalizeBubble(bubble);
    }
  }

  /* 保留原型演示函数供离线页面复用，正式发送流程不再自动降级到模拟回答。 */
  async function simulateReply(question,bubble,phase){
    const cfg=AGENT_MAP[ST.mode];
    const instrumentText=ST.mode==="stock"&&ST.currentInstrument?ST.currentInstrument.symbol+" "+(ST.currentInstrument.name||""):"";
    const isStockQ=ST.mode==="stock"||/\d{6}/.test(question)||/板块|个股|买入|卖出|ETF|基金|涨|跌|支撑|压力|均线|MACD|RSI|仓位|组合|量化/.test(question);

    // 1. 状态进度（识别需求 → 检索/分析 → 生成）
    setStatus({current:"classifying"});
    await delay(500);
    if(isStockQ){
      setStatus({current:"stock_validating",skill:"finance-analysis-skill"});
      headSkill.textContent="· finance-analysis-skill";
      await delay(700);
      setStatus({current:"skill_executing",skill:"finance-analysis-skill"});
      await delay(900);
    }else{
      setStatus({current:"searching_vector"});
      headSkill.textContent="· knowledge-qa";
      await delay(600);
      setStatus({current:"retrieval_result",skill:"knowledge-qa"});
      await delay(500);
    }

    // 2. 生成回答
    const reply=buildDemoAnswer(question,cfg,instrumentText,isStockQ);
    headRunId.textContent="Run: "+(ST.mode==="stock"?"9f3a":"7d8e")+"2b1c";
    await streamTextInto(bubble,reply);

    // 3. 完成：状态条完成标记 + 运行追踪联动
    statusBar.innerHTML="";
    const doneTag=document.createElement("span");
    doneTag.className="status-tag done";
    doneTag.textContent="✓ 本轮完成";
    statusBar.appendChild(doneTag);
    headSkill.textContent="";
    headRunId.textContent="";
    loadAgentRuns();
  }

  function buildDemoAnswer(question,cfg,instrumentText,isStockQ){
    if(isStockQ&&!instrumentText&&/\d{6}/.test(question)){
      const sym=question.match(/\d{6}/)[0];
      return "检测到你提到标的 "+sym+"，但尚未绑定为当前分析对象。\n\n"+
        "· 点击「选择标的」将 "+sym+" 设为当前标的，后续问题会自动沿用。\n"+
        "· 或者直接告诉我需要分析的方向（买入时机 / 支撑位 / 板块对比）。\n\n"+
        "> 提示：个股决策需要显式绑定标的，Route 不会猜测。";
    }
    if(isStockQ){
      const target=instrumentText||"当前标的";
      return "基于 finance-analysis-skill 对 "+target+" 的分析：\n\n"+
        "**综合评分：78 / 100**（趋势 24 · 乖离 16 · MACD 12 · 量能 11 · RSI 8 · 支撑 7）\n\n"+
        "- 均线呈多头排列，MA5 乖离 +1.4%，处于健康区间。\n"+
        "- MACD 在零轴上方金叉，动能持续。\n"+
        "- RSI(6)=68，接近强势区，短线注意追高风险。\n"+
        "- 支撑位：MA20 附近（回踩可分批）。\n\n"+
        "**结论**：方向偏多，但短线乖离偏高，建议分批介入而非一次性买入。\n\n"+
        "> 数据时效：当前行情 · 结论仅供研究参考，不构成投资建议。";
    }
    if(/搜索|核验|检索/.test(question)){
      return "已通过受控检索流程核验：\n\n"+
        "**核心结论**：\n"+
        "· 该主题近期有 3 条高相关来源，观点一致。\n"+
        "· 关键数据已交叉验证，无冲突。\n\n"+
        "**来源**：bdlh-web-search-adapter 返回 5 条结果，采纳其中 3 条高置信来源。\n\n"+
        "> 如需更深入，可以继续追问具体细节。";
    }
    return "我理解你的问题是：「"+question+"」。\n\n"+
      "从研究角度，可以这样拆解：\n\n"+
      "1. **核心概念**：先明确关键术语的定义和边界。\n"+
      "2. **相关背景**：补充必要的上下文与前置条件。\n"+
      "3. **可行动作**：给出下一步可以验证或推进的具体步骤。\n\n"+
      "如果你愿意补充更多背景，我可以给出更聚焦的结论。";
  }

  function streamTextInto(bubble,text){
    return new Promise(resolve=>{
      if(bubble.querySelector(".typing"))bubble.textContent="";
      bubble.classList.add("streaming");
      let i=0;
      (function tick(){
        if(i<=text.length){
          ST.streamText=text.slice(0,i);
          bubble.textContent=ST.streamText;
          scrollMsgs();
          i+=3;
          setTimeout(tick,16);
        }else{
          bubble.classList.remove("streaming");
          finalizeBubble(bubble);
          resolve();
        }
      })();
    });
  }

  function delay(ms){return new Promise(r=>setTimeout(r,ms));}

  const TRACE_SEQUENCE=["ROUTE_DECISION","REACT_DECISION","TOOL_CALL","TOOL_OBSERVATION","REACT_TERMINATION","MODEL_GATE","MODEL_CALL","FINAL_ANSWER"];
  const TRACE_PROGRESS=["ROUTE_DECISION","REACT_DECISION","TOOL_CALL","TOOL_OBSERVATION","MODEL_GATE","MODEL_CALL"];

  /** Render the current response's agent path instead of a mixed history of audit runs. */
  function createTrace(data){
    const labels={ROUTE_DECISION:"路由",REACT_DECISION:"规划",TOOL_CALL:"工具",TOOL_OBSERVATION:"结果",REACT_TERMINATION:"收束",MODEL_GATE:"模型门禁",MODEL_CALL:"生成",FINAL_ANSWER:"完成"};
    const details={ROUTE_DECISION:"正在匹配研究路径",REACT_DECISION:"正在制定 ReAct 工具执行计划",TOOL_CALL:"等待工具调用",TOOL_OBSERVATION:"等待结构化数据返回",REACT_TERMINATION:"等待 ReAct 收束",MODEL_GATE:"等待数据与规则校验",MODEL_CALL:"等待模型生成结论",FINAL_ANSWER:"等待最终回答"};
    return {runId:data.runId||null,route:data.route||"",status:"running",startedAt:Date.now(),steps:TRACE_SEQUENCE.map(type=>({type,title:labels[type],detail:details[type],tech:"",status:type==="ROUTE_DECISION"?"active":"pending"}))};
  }

  function applyResearchTrace(data){
    const trace=createTrace(data);
    trace.status=data.status||"running";
    (Array.isArray(data.steps)?data.steps:[]).forEach(item=>{
      const node=trace.steps.find(step=>step.type===item.type);
      if(node)Object.assign(node,item);
    });
    const active=trace.steps.find(step=>step.type===data.currentStage);
    if(active&&trace.status!=="completed")active.status="active";
    const s=activeSession();
    if(s){s.trace=trace;s.runId=data.runId||s.runId;}
    renderCurrentTrace();
  }

  function renderCurrentTrace(){
    const list=document.getElementById("traceList"),progress=document.getElementById("traceProgress"),meta=document.getElementById("traceMeta"),trace=curS().trace;
    if(!list||!progress||!meta)return;
    if(!trace){progress.innerHTML="";meta.textContent="等待开始研究";list.innerHTML='<div class="empty">发起一次研究后，这里将展示路由、ReAct、工具和模型门禁。</div>';return;}
    meta.textContent=(trace.route||"本次研究")+" · "+(trace.status==="completed"?"已完成":"执行中");
    progress.innerHTML=TRACE_PROGRESS.map((type,index)=>{const node=trace.steps.find(item=>item.type===type);const state=node.status;return '<div class="trace-progress-item '+state+'"><span class="trace-progress-dot">'+(state==="done"?"✓":(state==="blocked"?"!":index+1))+'</span>'+node.title+'</div>';}).join("");
    list.innerHTML=trace.steps.map((node,index)=>'<div class="trace-step '+node.status+'"><span class="trace-step-no">'+(node.status==="done"?"✓":(node.status==="blocked"?"!":index+1))+'</span><strong class="trace-step-title">'+node.title+'</strong><div class="trace-step-detail">'+escHtml(node.detail)+(node.tech?'<small class="trace-tech">'+escHtml(node.tech)+'</small>':"")+'</div></div>').join("");
  }

  async function refreshCurrentTrace(runId){
    if(runId)curS().runId=runId;
    if(!curS().runId){renderCurrentTrace();return;}
    try{
      const response=await apiFetch("/api/v1/agent-runs/"+encodeURIComponent(curS().runId));
      if(response.ok){
        const replay=await response.json();
        const trace=createTrace({runId:curS().runId,route:businessRouteForRun(replay.run||{})});
        trace.status=replay.run?.status||"completed";
        (replay.steps||[]).forEach(step=>{
          const node=trace.steps.find(item=>item.type===step.stepType);
          if(!node)return;
          node.status="done";
          node.tech=step.name?({ROUTE_DECISION:"Route",REACT_DECISION:"Action",TOOL_CALL:"Tool",TOOL_OBSERVATION:"Observation",REACT_TERMINATION:"Termination",MODEL_GATE:"Gate",MODEL_CALL:"Model",FINAL_ANSWER:"FINAL_ANSWER"}[node.type]||"Step")+" · "+step.name:"";
          node.detail=traceDetail(node.type,step);
        });
        const failed=(replay.steps||[]).find(step=>step.stepType==="POLICY_REJECTION"||step.stepType==="ERROR");
        if(failed){const node=trace.steps.find(item=>item.type==="MODEL_GATE")||trace.steps.at(-1);node.status="blocked";node.detail=failed.summary||"规则校验未通过，停止生成结论";}
        curS().trace=trace;
      }
    }catch(e){/* Keep the streaming trace when the optional replay request is unavailable. */}
    renderCurrentTrace();
  }

  function traceDetail(type,step){
    const payload=step.payload||{};
    if(type==="ROUTE_DECISION")return "请求已映射到「"+routeLabel(payload.route||step.name||"")+"」执行路径";
    if(type==="REACT_DECISION")return "ReAct 第 "+(payload.round||1)+" 轮："+(payload.reasoningSummary||"选择下一步工具 Action");
    if(type==="TOOL_CALL")return "正在调用 "+({stock:"StockSkill · 标的分析",sector:"StockSkill · 板块分析",quant:"StockSkill · 量化分析",portfolio:"StockSkill · 组合分析",webSearch:"联网检索"}[step.name]||step.name)+" 获取研究数据";
    if(type==="TOOL_OBSERVATION")return "工具已返回结构化结果"+(payload.durationMs?" · 耗时 "+payload.durationMs+"ms":"");
    if(type==="REACT_TERMINATION")return "ReAct 已获得足够信息，结束工具调用";
    if(type==="MODEL_GATE")return payload.allowed===false?"数据或规则未通过，停止生成方向性结论":"数据质量与规则校验已通过，允许生成结论";
    if(type==="MODEL_CALL")return "正在调用回答模型生成解释性结论";
    return "已生成最终回答与分析看板";
  }

  function advanceTrace(statusStep){
    if(!curS().trace)return;
    const target={classifying:"ROUTE_DECISION",react_planning:"REACT_DECISION",route_executing:"REACT_DECISION",skill_executing:"TOOL_CALL",stock_validating:"TOOL_OBSERVATION",searching_web:"TOOL_CALL",reading_sources:"TOOL_OBSERVATION",direct_chat:"MODEL_CALL"}[statusStep];
    if(!target)return;
    const targetIndex=curS().trace.steps.findIndex(item=>item.type===target);
    curS().trace.steps.forEach((item,index)=>{if(index<targetIndex&&item.status!=="blocked")item.status="done";if(index===targetIndex)item.status="active";});
    renderCurrentTrace();
  }

  /* 轻提示：操作反馈（对接后端后保留，用于用户操作确认） */
  function toast(message){
    let el=document.getElementById("toast");
    if(!el){
      el=document.createElement("div");
      el.id="toast";
      el.className="toast";
      document.body.appendChild(el);
    }
    el.textContent=message;
    el.classList.add("show");
    clearTimeout(el._t);
    el._t=setTimeout(()=>el.classList.remove("show"),2200);
  }

  async function consumeSse(response,onEvent){
    if(!response.body)throw new Error("浏览器不支持流式响应");
    const reader=response.body.getReader();
    const decoder=new TextDecoder("utf-8");
    let buffer="";
    while(true){
      const {value,done}=await reader.read();
      buffer+=decoder.decode(value||new Uint8Array(),{stream:!done}).replace(/\r\n/g,"\n");
      let boundary;
      while((boundary=buffer.indexOf("\n\n"))>=0){
        const frame=buffer.slice(0,boundary);
        buffer=buffer.slice(boundary+2);
        const payload=frame.split("\n").filter(line=>line.startsWith("data:"))
          .map(line=>line.slice(5).trimStart()).join("\n");
        if(payload){
          const keepReading=onEvent(JSON.parse(payload));
          if(keepReading===false){await reader.cancel();return;}
        }
      }
      if(done)return;
    }
  }

  function handleStreamEvent(data,bubble,phase){
    const type=data.type;
    if(type==="status"){
      const step=data.step||"";
      if(step!==phase.last){
        phase.last=step;
        advanceTrace(step);
        if(step==="classifying")setStatus({current:"classifying"});
        else if(["direct_chat","react_planning","searching_web","reading_sources","stock_validating"].includes(step)){
          setStatus({current:step,skill:data.skill});
          headSkill.textContent="· "+(data.skill||"");
        }else if(step==="skill_executing"||step==="route_executing"){
          setStatus({current:"skill_executing",skill:data.skill});
          headSkill.textContent="· "+(data.skill||"");
        }
      }
    }else if(type==="agent_run"){
      headRunId.textContent="Run: "+(data.runId||"").slice(0,8);
      adoptServerSessionId(data.sessionId);
      if(data.runId){
        bubble.dataset.runId=data.runId;
        curS().runId=data.runId;
        curS().trace=createTrace(data);
        renderCurrentTrace();
      }
      if(data.route)headSkill.textContent="· "+data.route;
    }else if(type==="research_trace"){
      applyResearchTrace(data);
    }else if(type==="token"){
      const tok=data.content||"";
      ST.streamText+=tok;
      if(bubble.querySelector(".typing"))bubble.textContent="";
      bubble.textContent=ST.streamText;
      scrollMsgs();
    }else if(type==="ask"&&data.reason==="NEED_INSTRUMENT"){
      finalizeBubble(bubble);
      addActionCard(bubble,"请选择分析标的",data.prompt||"这项分析需要一个具体标的。请选择股票、ETF 或基金后继续。",[
        {label:"选择标的",cls:"primary",action:()=>openInstrumentModal()},
        {label:"前往普通问答",cls:"secondary",action:()=>go("/agent/general")}
      ]);
    }else if(type==="clarification"){
      const options=(data.options||[]).filter(option=>option.label&&option.message);
      if(options.length){
        addActionCard(
          bubble,
          "选择分析口径",
          data.prompt||"选择一个方向后继续分析。",
          options.map((option,index)=>({
            label:option.label,
            cls:index===0?"primary":"secondary",
            action:()=>{
              removeActionCard(bubble);
              send(option.message);
            }
          }))
        );
        scrollMsgs();
      }
    }else if(type==="done"){
      adoptServerSessionId(data.sessionId);
      if(bubble.querySelector(".typing")){
        bubble.textContent="";
        if(data.status==="REFUSED")bubble.textContent="请求已被护栏拦截："+(data.reason||"");
        else bubble.textContent+="对话已完成。";
      }
      const inlineContract=normalizeSkillContract(data.skillResult)||parseSkillContract(ST.streamText);
      const session=activeSession();
      if(session&&ST.streamText){
        session.messages=session.messages||[];
        session.messages.push({role:"assistant",content:ST.streamText});
        session.updatedAt=Date.now();
        persistSessions();
      }
      finalizeBubble(bubble);
      addAnswerMeta(bubble,data);
      if(inlineContract||data.skillResultAvailable){
        addSkillResultButton(bubble,data.runId||bubble.dataset.runId,inlineContract);
      }
      statusBar.innerHTML="";
      const doneTag=document.createElement("span");
      doneTag.className="status-tag done";
      doneTag.textContent="✓ "+(data.status==="COMPLETED"
        ?"本轮完成"
        :(data.status==="NEED_CLARIFICATION"?"等待选择":(data.status||"完成")));
      statusBar.appendChild(doneTag);
      headRunId.textContent="";
      headSkill.textContent="";
      refreshCurrentTrace(data.runId||curS().runId);
      return false;
    }else if(type==="error"){
      if(bubble.querySelector(".typing"))bubble.textContent="";
      bubble.textContent+=(bubble.textContent?"\n":"")+(data.message||"服务错误");
      bubble.style.color="#e5484d";
      finalizeBubble(bubble);
      statusBar.innerHTML="";
      return false;
    }
    return true;
  }

  function removeActionCard(bubble){
    const card=bubble.querySelector(".action-card");
    if(card)card.remove();
  }

  function addAnswerMeta(bubble,data){
    if(!data||bubble.querySelector(".answer-meta")||data.status!=="COMPLETED")return;
    const provider={deepseek:"DeepSeek",ollama:"Ollama",rule:"StockSkill 规则"}[data.modelProvider];
    if(!provider)return;
    const meta=document.createElement("div");
    meta.className="answer-meta";
    meta.innerHTML='<strong>回答来源：</strong>'+escHtml(provider)+(data.modelName?" · "+escHtml(data.modelName):"");
    bubble.appendChild(meta);
  }

  function renderStructuredSkillResult(bubble){
    const contract=parseSkillContract(ST.streamText);
    if(!contract)return false;
    const dashboard=buildSkillDashboard(contract);
    if(!dashboard)return false;
    bubble.textContent="";
    bubble.classList.add("skill-result-bubble");
    bubble.appendChild(dashboard);
    scrollMsgs();
    return true;
  }

  function addSkillResultButton(bubble,runId,inlineContract){
    if(bubble.querySelector(".skill-result-button"))return;
    const button=document.createElement("button");
    button.type="button";
    button.className="skill-result-button";
    button.innerHTML='<span>查看本次分析数据</span><small>StockSkill 结构化结果</small>';
    button.addEventListener("click",()=>openSkillResultModal(runId,inlineContract));
    bubble.appendChild(button);
    scrollMsgs();
  }

  async function openSkillResultModal(runId,inlineContract){
    const modal=document.getElementById("modalSkillResult");
    const body=document.getElementById("modalSkillResultBody");
    if(!modal||!body)return;
    modal.style.display="grid";
    body.innerHTML='<div class="skill-result-loading">正在读取本次 Skill 的结构化结果…</div>';
    const contract=inlineContract||await loadStoredSkillResult(runId);
    if(!contract){
      body.innerHTML='<div class="skill-result-empty"><strong>暂时没有可展示的数据</strong><span>本轮没有成功完成行情或回测 Skill，或运行记录暂不可读取。</span></div>';
      return;
    }
    const dashboard=buildSkillDashboard(contract);
    if(!dashboard){
      body.innerHTML='<div class="skill-result-empty"><strong>结果格式暂不支持</strong><span>已收到 Skill 数据，但当前页面尚未适配该命令类型。</span></div>';
      return;
    }
    body.replaceChildren(dashboard);
  }

  async function renderStoredSkillResult(bubble,runId){
    const contract=await loadStoredSkillResult(runId);
    if(!contract||bubble.querySelector(".skill-dashboard"))return;
    const dashboard=buildSkillDashboard(contract);
    if(!dashboard)return;
    bubble.classList.add("skill-result-bubble");
    bubble.appendChild(dashboard);
    scrollMsgs();
  }

  async function loadStoredSkillResult(runId){
    if(!runId)return null;
    try{
      const response=await apiFetch("/api/v1/agent-runs/"+encodeURIComponent(runId)+"/skill-results");
      if(!response.ok)return null;
      const result=await response.json();
      return (result.items||[])
        .map(item=>item?.observation)
        .find(item=>item?.schemaVersion&&item?.command&&item?.data)||null;
    }catch(e){
      // 运行结果不可读时保留对话正文，用户仍可继续提问。
      return null;
    }
  }

  function parseSkillContract(text){
    const normalized=String(text||"").trim()
      .replace(/^```(?:json)?\s*/i,"").replace(/\s*```$/," ").trim();
    if(!normalized.startsWith("{"))return null;
    try{
      const parsed=JSON.parse(normalized);
      return parsed?.schemaVersion&&parsed?.command&&parsed?.data?parsed:null;
    }catch(e){
      return null;
    }
  }

  function normalizeSkillContract(value){
    if(!value||typeof value!=="object"||Array.isArray(value))return null;
    return value.schemaVersion&&value.command&&value.data?value:null;
  }

  function buildSkillDashboard(contract){
    if(contract.command==="stock")return buildStockDashboard(contract);
    if(contract.command==="sector")return buildSectorDashboard(contract);
    if(contract.command==="quant")return buildQuantDashboard(contract);
    if(contract.command==="portfolio")return buildPortfolioDashboard(contract);
    return null;
  }

  function buildStockDashboard(contract){
    const data=contract.data||{};
    const quote=data.quote||{};
    const score=data.score||{};
    const technical=data.technical||{};
    const ma=technical.ma||{};
    const history=Array.isArray(data.history)?data.history:[];
    const title=[data.code,data.name].filter(Boolean).join(" · ")||"标的研究";
    const change=numberOrNull(quote.changePct);
    const card=document.createElement("article");
    card.className="skill-dashboard stock-dashboard";
    card.innerHTML='<div class="skill-dashboard-head"><div><span>STRUCTURED MARKET DATA</span><h3>'+escHtml(title)+'</h3></div><small>'+escHtml(contract.asOf||"数据时间待确认")+'</small></div>'+ 
      '<div class="skill-metrics">'+
        metricHtml("最新价",formatNumber(quote.price),change==null?"":formatSignedPercent(change),change)+
        metricHtml("系统判断",stockVerdict(score.total),"规则推理",null)+
        metricHtml("判断置信度",stockConfidence(score,technical),"信号一致性",null)+
        metricHtml("RSI(6)",formatNumber(technical.rsi?.rsi6),signalLabel(technical.rsi?.zone),null)+
      '</div>'+lineChartHtml(history.map(row=>row?.close),"收盘价走势")+
      '<div class="skill-levels">'+
        levelHtml("MA5",ma.ma5)+levelHtml("MA10",ma.ma10)+levelHtml("MA20",ma.ma20)+levelHtml("20日低点",technical.support?.low20)+
      '</div>'+decisionHtml("stock",{score,technical,quote,reasoning:data.reasoning||data.interpretation})+qualityHtml(contract.dataQuality)+skillSummaryHtml("stock",contract);
    return card;
  }

  function buildSectorDashboard(contract){
    const sectors=Array.isArray(contract.data?.sectors)?contract.data.sectors.slice(0,8):[];
    if(!sectors.length)return null;
    const maximum=Math.max(...sectors.map(item=>Number(item.heatScore)||0),1);
    const card=document.createElement("article");
    card.className="skill-dashboard sector-dashboard";
    card.innerHTML='<div class="skill-dashboard-head"><div><span>SECTOR HEATMAP</span><h3>板块热度</h3></div><small>'+escHtml(contract.asOf||"数据时间待确认")+'</small></div>'+ 
      '<div class="sector-bars">'+sectors.map((sector,index)=>{
        const score=Number(sector.heatScore)||0;
        const width=Math.max(3,Math.min(100,score/maximum*100));
        const change=numberOrNull(sector.changePct);
        return '<div class="sector-bar"><span class="sector-rank">'+(index+1)+'</span><strong>'+escHtml(sector.name||sector.code||"未命名板块")+'</strong><div class="sector-track"><i style="width:'+width.toFixed(1)+'%"></i></div><b>'+formatNumber(score)+'</b><em class="'+(change>=0?"up":"down")+'">'+formatSignedPercent(change)+'</em></div>';
      }).join("")+'</div>'+decisionHtml("sector",{sectors})+qualityHtml(contract.dataQuality)+skillSummaryHtml("sector",contract);
    return card;
  }

  function buildQuantDashboard(contract){
    const data=contract.data||{};
    const metrics=data.metrics||{};
    const totalReturn=numberOrNull(metrics.totalReturn);
    const maxDrawdown=numberOrNull(metrics.maxDrawdown);
    const annualizedVolatility=numberOrNull(metrics.annualizedVolatility);
    const card=document.createElement("article");
    card.className="skill-dashboard quant-dashboard";
    card.innerHTML='<div class="skill-dashboard-head"><div><span>QUANT BACKTEST</span><h3>量化轮动回测</h3></div><small>'+escHtml(contract.asOf||"数据时间待确认")+'</small></div>'+ 
      '<div class="skill-metrics">'+
        metricHtml("累计收益",formatRatioPercent(totalReturn),"",totalReturn)+ 
        metricHtml("最大回撤",formatRatioPercent(maxDrawdown),"",maxDrawdown)+ 
        metricHtml("夏普比率",formatNumber(metrics.sharpe),"",null)+
        metricHtml("年化波动",formatRatioPercent(annualizedVolatility),"",null)+
      '</div>'+lineChartHtml((data.equityCurve||[]).map(row=>row?.equity),"策略净值走势")+decisionHtml("quant",{metrics})+qualityHtml(contract.dataQuality)+skillSummaryHtml("quant",contract);
    return card;
  }

  function buildPortfolioDashboard(contract){
    const data=contract.data||{};
    const summary=data.summary||{};
    const holdings=Array.isArray(data.holdings)?data.holdings.slice(0,8):[];
    const maximum=Math.max(...holdings.map(item=>Number(item.marketValue)||0),1);
    const card=document.createElement("article");
    card.className="skill-dashboard portfolio-dashboard";
    card.innerHTML='<div class="skill-dashboard-head"><div><span>PORTFOLIO STRUCTURE</span><h3>组合结构与风险</h3></div><small>'+escHtml(contract.asOf||"数据时间待确认")+'</small></div>'+ 
      '<div class="skill-metrics">'+
        metricHtml("组合市值",formatNumber(summary.totalValue),"",null)+
        metricHtml("持仓盈亏",formatSignedPercent(summary.pnlPct),"",numberOrNull(summary.pnlPct))+ 
        metricHtml("现金占比",formatSignedPercent(summary.cashRatio),"",null)+
        metricHtml("持仓数量",String(holdings.length),"",null)+
      '</div>'+ 
      '<div class="sector-bars">'+holdings.map((holding,index)=>{
        const value=Number(holding.marketValue)||0;
        const width=Math.max(3,Math.min(100,value/maximum*100));
        const label=holding.position?.name||holding.position?.code||"未命名持仓";
        return '<div class="sector-bar"><span class="sector-rank">'+(index+1)+'</span><strong>'+escHtml(label)+'</strong><div class="sector-track"><i style="width:'+width.toFixed(1)+'%"></i></div><b>'+formatNumber(value)+'</b><em>'+escHtml(holding.position?.sector||"")+'</em></div>';
      }).join("")+'</div>'+decisionHtml("portfolio",{summary,holdings})+qualityHtml(contract.dataQuality)+skillSummaryHtml("portfolio",contract);
    return card;
  }

  function metricHtml(label,value,note,tone){
    const className=tone==null?"":(tone>=0?"up":"down");
    return '<div class="skill-metric"><span>'+escHtml(label)+'</span><strong class="'+className+'">'+escHtml(value)+'</strong>'+(note?'<small>'+escHtml(note)+'</small>':"")+'</div>';
  }

  function levelHtml(label,value){
    return '<div><span>'+escHtml(label)+'</span><strong>'+escHtml(formatNumber(value))+'</strong></div>';
  }

  function qualityHtml(quality){
    const status=quality?.status||"unknown";
    const label=status==="realtime"?"实时数据":(status==="verified"?"已核验数据":"数据受限");
    return '<div class="skill-quality '+escHtml(status)+'">'+escHtml(label)+(quality?.warnings?.length?' · '+escHtml(quality.warnings[0]):"")+'</div>';
  }

  function decisionHtml(command,context){
    const modelReasoning=normalizeReasoning(context.reasoning);
    if(modelReasoning)return '<section class="skill-decision model-reasoning"><span>智能推理结论</span><p>'+escHtml(modelReasoning.verdict)+'</p><ul>'+modelReasoning.reasons.map(reason=>'<li>'+escHtml(reason)+'</li>').join("")+'</ul>'+(modelReasoning.risk?'<small>风险提示：'+escHtml(modelReasoning.risk)+'</small>':"")+'<em>推理模型：'+escHtml(modelReasoning.model||"Agent 模型")+'</em></section>';
    let conclusion="";
    let basis="";
    let reasons=[];
    if(command==="stock"){
      const total=numberOrNull(context.score?.total);
      const rsi=numberOrNull(context.technical?.rsi?.rsi6);
      const state=scoreState(total);
      const trend=signalLabel(context.technical?.alignment)||"趋势待确认";
      const rsiText=rsi==null?"RSI 数据待确认":"RSI(6) 为 "+formatNumber(rsi);
      conclusion=(total==null?"暂不形成方向判断":state.verdict)+"：趋势信号为“"+trend+"”，"+rsiText+"。";
      basis=total==null?"技术评分数据尚未返回。":"规则评分 "+formatNumber(total)+" / 100 仅作为证据强弱参考，由行情、均线、动量与风险指标按固定规则汇总；并非投资评级或买卖指令。";
      reasons=["均线结构："+trend+"。",rsi==null?"动量指标待确认。":"动量指标：RSI(6) 为 "+formatNumber(rsi)+"，处于“"+(signalLabel(context.technical?.rsi?.zone)||"待确认")+"”。",numberOrNull(context.technical?.volume?.volumeRatio)==null?"成交活跃度待确认。":"成交活跃度：量比 "+formatNumber(context.technical?.volume?.volumeRatio)+"。"];
    }else if(command==="sector"){
      const leader=context.sectors?.[0];
      const change=numberOrNull(leader?.changePct);
      conclusion=leader?"“"+(leader.name||leader.code||"该板块")+"”当前热度排名第 1，处于本次样本的相对强势位置。":"尚无足够板块数据形成结论。";
      basis=leader?"热度评分 "+formatNumber(leader.heatScore)+(change==null?"。":"，当日涨跌 "+formatSignedPercent(change)+"。")+" 排名仅反映当前样本横截面对比。":"等待板块数据返回后计算。";
      if(leader)reasons=["热度评分 "+formatNumber(leader.heatScore)+"，位列样本第 1。",change==null?"当日涨跌数据待确认。":"当日涨跌 "+formatSignedPercent(change)+"。","强弱来自当前样本对比，仍需观察后续持续性。"];
    }else if(command==="quant"){
      const totalReturn=numberOrNull(context.metrics?.totalReturn);
      const drawdown=numberOrNull(context.metrics?.maxDrawdown);
      conclusion=totalReturn==null?"历史回测数据不足，暂不做策略判断。":"该策略在所选历史区间取得 "+formatRatioPercent(totalReturn)+" 的累计收益，并经历 "+formatRatioPercent(drawdown)+" 的最大回撤。";
      basis="这是历史样本中的规则回测结果，用于观察收益与风险特征，不代表未来表现。";
      reasons=[totalReturn==null?"累计收益数据待确认。":"累计收益："+formatRatioPercent(totalReturn)+"。",drawdown==null?"最大回撤数据待确认。":"最大回撤："+formatRatioPercent(drawdown)+"。","收益与回撤需要结合策略周期和交易成本继续验证。"];
    }else if(command==="portfolio"){
      const cashRatio=numberOrNull(context.summary?.cashRatio);
      const count=context.holdings?.length||0;
      conclusion="当前组合包含 "+count+" 项持仓"+(cashRatio==null?"。":"，现金占比 "+formatRatioPercent(cashRatio)+"。")+"";
      basis="组合判断基于持仓快照、当前市值及盈亏结构计算，不包含模型主观预测。";
      reasons=["持仓数量："+count+" 项。",cashRatio==null?"现金占比待确认。":"现金占比："+formatRatioPercent(cashRatio)+"。","风险还需结合行业集中度和单一标的权重进一步判断。"];
    }
    return '<section class="skill-decision"><span>系统判断</span><p>'+escHtml(conclusion)+'</p><ul>'+reasons.map(reason=>'<li>'+escHtml(reason)+'</li>').join("")+'</ul><small>'+escHtml(basis)+'</small><em>当前为 StockSkill 规则推理；接入模型后将优先展示模型结合这些证据给出的推理。</em></section>';
  }

  function normalizeReasoning(reasoning){
    if(!reasoning||typeof reasoning!=="object")return null;
    const verdict=String(reasoning.verdict||reasoning.conclusion||"").trim();
    const reasons=Array.isArray(reasoning.reasons)?reasoning.reasons:[];
    if(!verdict||!reasons.length)return null;
    return {verdict,reasons:reasons.slice(0,3).map(String),risk:String(reasoning.risk||reasoning.riskNote||"").trim(),model:String(reasoning.model||reasoning.modelName||"").trim()};
  }

  function stockVerdict(score){return scoreState(numberOrNull(score)).verdict;}

  function stockConfidence(score,technical){
    const total=numberOrNull(score?.total);
    const alignment=String(technical?.alignment||"").toLowerCase();
    if(total==null)return "待确认";
    if((total>=70&&alignment==="bullish")||(total<=30&&alignment==="bearish"))return "较高";
    if(total>=55||total<=45)return "中等";
    return "较低";
  }

  function scoreState(score){
    if(score==null)return {verdict:"待确认"};
    if(score>=70)return {verdict:"偏多"};
    if(score>=55)return {verdict:"谨慎偏多"};
    if(score>=40)return {verdict:"中性观望"};
    if(score>=25)return {verdict:"谨慎偏空"};
    return {verdict:"偏空"};
  }

  function skillSummaryHtml(command,contract){
    const statements={
      stock:"价格、趋势、均线、RSI 与风险位由 StockSkill 基于已获取行情和固定规则计算；模型仅负责把结果解释成自然语言。",
      sector:"热度排序、涨跌和资金流来自 StockSkill 的板块数据与标准化热度公式；模型不会自行编造板块强弱。",
      quant:"收益、回撤、夏普和净值曲线由 StockSkill 的历史回测引擎计算；它描述历史表现，不承诺未来收益。",
      portfolio:"市值、盈亏、现金比例和持仓结构由 StockSkill 按真实持仓快照计算；模型仅协助说明风险。"
    };
    return '<div class="skill-summary"><strong>StockSkill 分析依据</strong><span>'+escHtml(statements[command]||"此看板由 StockSkill 的结构化数据生成。")+'</span><small>数据截至 '+escHtml(contract.asOf||"待确认")+'</small></div>';
  }

  function signalLabel(value){
    const labels={
      strong_buy:"强买入",buy:"买入",hold:"持有",wait:"观望",sell:"卖出",strong_sell:"强卖出",
      strong:"强势",neutral:"中性",weak:"弱势",overbought:"超买区",oversold:"超卖区",
      bullish:"多头排列",bearish:"空头排列",mixed:"震荡"
    };
    const key=String(value||"").trim().toLowerCase();
    return labels[key]||String(value||"");
  }

  function lineChartHtml(values,label){
    const points=values.map(Number).filter(Number.isFinite);
    if(points.length<2)return '<div class="skill-chart-empty">'+escHtml(label)+'暂无可绘制数据</div>';
    const min=Math.min(...points),max=Math.max(...points),range=max-min||1;
    const coordinates=points.map((value,index)=>{
      const x=4+index/(points.length-1)*92;
      const y=90-(value-min)/range*74;
      return x.toFixed(2)+","+y.toFixed(2);
    }).join(" ");
    return '<figure class="skill-chart"><figcaption>'+escHtml(label)+'</figcaption><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="'+escHtml(label)+'"><line x1="4" y1="90" x2="96" y2="90"></line><polyline points="'+coordinates+'"></polyline></svg><div><span>'+escHtml(formatNumber(min))+'</span><span>'+escHtml(formatNumber(max))+'</span></div></figure>';
  }

  function finiteNumber(value){return Number.isFinite(Number(value));}
  function numberOrNull(value){const number=Number(value);return Number.isFinite(number)?number:null;}
  function formatNumber(value){const number=numberOrNull(value);return number==null?"—":number.toLocaleString("zh-CN",{maximumFractionDigits:2});}
  function formatSignedPercent(value){const number=numberOrNull(value);return number==null?"—":(number>0?"+":"")+number.toFixed(2)+"%";}
  function formatRatioPercent(value){const number=numberOrNull(value);return number==null?"—":formatSignedPercent(number*100);}

  function escHtml(s){
    if(!s)return"";
    const d=document.createElement("div");d.textContent=s;return d.innerHTML;
  }

  function extractSymbol(text){
    const match=String(text||"").match(/(?:^|\D)(\d{6})(?:\D|$)/);
    return match?match[1]:null;
  }

  function normalizeAssetType(type){
    const value=String(type||"").toLowerCase();
    if(value==="股票"||value==="stock")return"stock";
    if(value==="etf")return"etf";
    if(value==="基金"||value==="fund")return"fund";
    if(value==="open_fund"||value==="qdii")return value;
    return"auto";
  }

  function renderWelcome(title,description){
    const cfg=AGENT_MAP[ST.mode];
    if(!cfg)return;
    messages.replaceChildren();
    const idleTitle=document.getElementById("idleTitle");
    const idleSub=document.getElementById("idleSub");
    if(idleTitle)idleTitle.textContent=title||cfg.welcomeTitle;
    if(idleSub)idleSub.textContent=description||cfg.welcomeDesc;
    updateIdleState();
  }

  function updateIdleState(){
    const idle=!messages.childNodes.length;
    document.body.classList.toggle("idle",idle);
    if(idle){
      syncIdleChar();
      input.focus();
    }
  }

  function switchMode(mode,preserveMessages=true){
    if(!AGENT_MAP[mode]||ST.sending)return;
    if(mode!==ST.mode&&preserveMessages){
      const src=activeSession();
      if(src){while(messages.firstChild)src.store.appendChild(messages.firstChild);}
    }
    if(!preserveMessages)messages.replaceChildren();
    ST.mode=mode;
    document.body.dataset.mode=mode;
    const cfg=AGENT_MAP[mode];
    document.querySelectorAll(".agent-option").forEach(el=>{
      el.classList.toggle("active",el.dataset.agent===mode);
    });
    modeKicker.textContent=cfg.kicker;
    chatTitle.textContent=cfg.title;
    composerHint.textContent=cfg.needsInstrument&&ST.currentInstrument
      ?"当前标的 "+ST.currentInstrument.symbol+" · 也可直接询问板块"
      :cfg.hint;
    input.placeholder=cfg.needsInstrument&&ST.currentInstrument
      ?"继续分析 "+ST.currentInstrument.symbol+"，或询问板块…"
      :cfg.placeholder;
    sendBtn.disabled=false;
    statusBar.innerHTML="";
    headSkill.textContent="";
    headRunId.textContent="";
    if(preserveMessages){
      const storedSession=activeSession();
      if(storedSession){
        const stored=storedSession.store;
        if(!messages.childNodes.length&&stored.childNodes.length)messages.appendChild(stored);
      }
    }
    if(!messages.childNodes.length)renderWelcome();
    renderQuickPrompts();
    updateSessionBadge();
    syncIdleChar();
    if(AUTH.ready)void loadConversations(mode);
  }

  function renderQuickPrompts(){
    const cfg=AGENT_MAP[ST.mode];
    const prompts=cfg?cfg.prompts:[];
    document.getElementById("quickPrompts").innerHTML=prompts.map(item=>
      '<button class="ghost" data-prompt="'+escHtml(item[1])+'">'+escHtml(item[0])+'</button>'
    ).join("");
    bindQuickPrompts();
  }

  function bindQuickPrompts(){
    document.querySelectorAll("#quickPrompts [data-prompt]").forEach(button=>{
      button.addEventListener("click",()=>{
        input.value=button.dataset.prompt;
        input.focus();
      });
    });
  }

  function openInstrumentModal(){
    ST.pendingInstrument=ST.currentInstrument?{...ST.currentInstrument}:null;
    document.getElementById("instrumentSymbol").value=ST.currentInstrument?.symbol||"";
    document.getElementById("instrumentName").value=ST.currentInstrument?.name==="消息中识别"?"":(ST.currentInstrument?.name||"");
    document.getElementById("instrumentError").textContent="";
    document.querySelectorAll(".instrument-option").forEach(option=>option.classList.toggle("selected",option.dataset.symbol===ST.currentInstrument?.symbol));
    document.getElementById("modalInstrument").style.display="grid";
    setTimeout(()=>document.getElementById("instrumentSymbol").focus(),0);
  }

  function closeInstrumentModal(){
    document.getElementById("modalInstrument").style.display="none";
    ST.pendingInstrument=null;
  }

  function chooseInstrument(instrument){
    saveInstrument(instrument);
    closeInstrumentModal();
    switchMode("stock");
    input.placeholder="继续分析 "+instrument.symbol+"，或输入其他投资问题…";
    composerHint.textContent="当前标的 "+instrument.symbol+" · Enter 发送 · 结论仅供研究参考";
    sendBtn.disabled=false;
    input.focus();
    toast("标的已绑定："+instrument.symbol+" "+(instrument.name||""));
  }

  function confirmInstrument(){
    const symbol=document.getElementById("instrumentSymbol").value.trim();
    const name=document.getElementById("instrumentName").value.trim();
    if(!/^\d{6}$/.test(symbol)){
      document.getElementById("instrumentError").textContent="请输入 6 位股票、ETF 或基金代码";
      return;
    }
    const pending=ST.pendingInstrument&&ST.pendingInstrument.symbol===symbol?ST.pendingInstrument:null;
    chooseInstrument({symbol:symbol,name:name||pending?.name||"当前标的",type:pending?.type||"标的"});
  }

  /* 需求书字段的 Demo 运行数据：agent_runs + agent_steps + tool_executions */
  const DEMO_RUNS=[
    {
      runId:"run-9f3a2b1c",
      sessionId:"sess_ab12",
      intent:"STOCK_ANALYSIS",
      skillName:"stock-deep-analysis",
      skillVersion:"1.1.1",
      status:"completed",
      startedAt:new Date(Date.now()-6*60000).toISOString(),
      endedAt:new Date(Date.now()-5.5*60000).toISOString(),
      toolCallCount:4,
      maxToolCalls:6,
      finalAnswer:"588200 科创芯片ETF 综合评分 78，均线多头排列，短线存在追高迹象，建议分批而非一次性买入。",
      steps:[
        {stepNo:1,stepType:"ROUTE_DECISION",summary:"规则命中 STOCK_DECISION，允许 skill:stock",duration:"4ms"},
        {stepNo:2,stepType:"REACT_DECISION",summary:"规划 Capability: finance.stock-research",duration:"3ms"},
        {stepNo:3,stepType:"TOOL_CALL",summary:"MCP market-data: latest 588200",duration:"620ms"},
        {stepNo:4,stepType:"TOOL_OBSERVATION",summary:"评分78 · RSI6=68 · 乖离率MA5=+1.4%",duration:"0ms"},
        {stepNo:5,stepType:"MODEL_GATE",summary:"PaidModelGate 通过，DeepSeek 生成结论",duration:"1800ms"},
        {stepNo:6,stepType:"MODEL_CALL",summary:"deepseek-v4-pro 生成投资叙事",duration:"0ms"},
        {stepNo:7,stepType:"FINAL_ANSWER",summary:"输出结构化结论",duration:"0ms"}
      ],
      tools:[
        {tool:"market-data-mcp",action:"latest",params:{symbol:"588200",assetType:"etf"},status:"success",durationMs:620,errorCode:null},
        {tool:"bdlh-web-search-adapter",action:"search",params:{query:"科创芯片ETF 近期 资金流"},status:"skipped",durationMs:0,errorCode:"NOT_REQUIRED"},
        {tool:"ollama-embedding",action:"embed",params:{dim:1024},status:"success",durationMs:40,errorCode:null}
      ]
    },
    {
      runId:"run-7d8e4f2a",
      sessionId:"sess_ab12",
      intent:"SECTOR_ATTENTION",
      skillName:"investment-knowledge-qa",
      skillVersion:"1.0.0",
      status:"completed",
      startedAt:new Date(Date.now()-32*60000).toISOString(),
      endedAt:new Date(Date.now()-31*60000).toISOString(),
      toolCallCount:2,
      maxToolCalls:5,
      finalAnswer:"半导体板块近一周互联网讨论度处于高位，关键词集中在国产替代与 AI 算力。",
      steps:[
        {stepNo:1,stepType:"ROUTE_DECISION",summary:"SECTOR_ATTENTION，允许 skill:sector + WebSearch",duration:"5ms"},
        {stepNo:2,stepType:"TOOL_CALL",summary:"bdlh-web-search-adapter: 半导体 讨论度",duration:"1100ms"},
        {stepNo:3,stepType:"TOOL_OBSERVATION",summary:"返回 5 条检索结果",duration:"0ms"},
        {stepNo:4,stepType:"FINAL_ANSWER",summary:"本地模型归纳",duration:"900ms"}
      ],
      tools:[
        {tool:"bdlh-web-search-adapter",action:"search",params:{query:"半导体板块 讨论度"},status:"success",durationMs:1100,errorCode:null},
        {tool:"ollama-qwen",action:"generate",params:{model:"qwen3:1.5b"},status:"success",durationMs:900,errorCode:null}
      ]
    },
    {
      runId:"run-3c1e9a7b",
      sessionId:"sess_cd34",
      intent:"MARKET_CAUSAL_ANALYSIS",
      skillName:"stock-deep-analysis",
      skillVersion:"1.1.1",
      status:"failed",
      startedAt:new Date(Date.now()-90*60000).toISOString(),
      endedAt:new Date(Date.now()-89.5*60000).toISOString(),
      toolCallCount:3,
      maxToolCalls:6,
      finalAnswer:"",
      error:"证据不足：搜索返回 0 条有效结果，EVIDENCE_INSUFFICIENT",
      steps:[
        {stepNo:1,stepType:"ROUTE_DECISION",summary:"MARKET_CAUSAL_ANALYSIS，要求行情+外部证据",duration:"4ms"},
        {stepNo:2,stepType:"TOOL_CALL",summary:"MCP market-data: latest",duration:"510ms"},
        {stepNo:3,stepType:"TOOL_OBSERVATION",summary:"行情取得，评分正常",duration:"0ms"},
        {stepNo:4,stepType:"TOOL_CALL",summary:"bdlh-web-search-adapter: 上涨原因",duration:"2000ms"},
        {stepNo:5,stepType:"TOOL_OBSERVATION",summary:"0 条结果",duration:"0ms"},
        {stepNo:6,stepType:"POLICY_REJECTION",summary:"EVIDENCE_INSUFFICIENT 禁止付费",duration:"0ms"},
        {stepNo:7,stepType:"ERROR",summary:"结束为 failed",duration:"0ms"}
      ],
      tools:[
        {tool:"market-data-mcp",action:"latest",params:{symbol:"600519"},status:"success",durationMs:510,errorCode:null},
        {tool:"bdlh-web-search-adapter",action:"search",params:{query:"贵州茅台 上涨原因"},status:"failed",durationMs:2000,errorCode:"NO_RESULTS"}
      ]
    }
  ];

  async function loadAgentRuns(){
    const list=document.getElementById("runList");
    list.innerHTML='<div class="empty">加载中…</div>';
    let data=null;
    try{
      const r=await apiFetch("/api/v1/agent-runs?limit=20");
      if(r.ok){data=await r.json();}
    }catch(e){/* 后端不可用，回退 demo */}

    if(!Array.isArray(data)||!data.length){
      renderDemoRuns(list);
      return;
    }
    list.innerHTML=data.map(run=>{
      const status=run.status||"unknown";
      const started=run.startedAt?new Date(run.startedAt).toLocaleString("zh-CN"):"";
      const route=businessRouteForRun(run);
      return '<div class="run-card" data-runid="'+run.runId+'">'+
        '<div class="rc-head"><span class="rc-intent">'+escHtml(runLabel(run))+'</span>'+
        '<span class="run-status '+status+'">'+escHtml(runStatusLabel(status))+'</span></div>'+
        '<div class="rc-time">'+started+(run.toolCallCount!=null?" · 工具 "+run.toolCallCount+" 次":"")+'</div>'+
        '<span class="run-route">'+escHtml(route)+'</span>'+
        '</div>';
    }).join("");
    list.querySelectorAll(".run-card").forEach(card=>{
      card.addEventListener("click",()=>openRunDetail(card.dataset.runid));
    });
  }

  function renderDemoRuns(list){
    list.innerHTML=DEMO_RUNS.map(run=>{
      const status=run.status||"unknown";
      const started=new Date(run.startedAt).toLocaleString("zh-CN",{hour:"2-digit",minute:"2-digit"});
      const route=businessRouteForRun(run);
      return '<div class="run-card" data-runid="'+run.runId+'" data-demo="1">'+
        '<div class="rc-head"><span class="rc-intent">'+escHtml(runLabel(run))+'</span>'+
        '<span class="run-status '+status+'">'+escHtml(runStatusLabel(status))+'</span></div>'+
        '<div class="rc-time">'+started+' · 工具 '+run.toolCallCount+'/'+run.maxToolCalls+' 次</div>'+
        '<span class="run-route">'+escHtml(route)+'</span>'+
        '</div>';
    }).join("");
    list.querySelectorAll(".run-card").forEach(card=>{
      card.addEventListener("click",()=>{
        const run=DEMO_RUNS.find(x=>x.runId===card.dataset.runid);
        if(run)openRunDetailDemo(run);
      });
    });
  }

  function openRunDetailDemo(run){
    const modal=document.getElementById("modalRun");
    const body=document.getElementById("modalRunBody");
    modal.style.display="grid";
    const dur=(ms,label)=>ms?(' <span class="step-duration">'+label+' '+ms+'ms</span>'):'';
    body.innerHTML=
      '<div style="margin-bottom:10px"><strong>业务路径：</strong> <span class="run-route">'+escHtml(businessRouteForRun(run))+'</span></div>'+
      '<div style="margin-bottom:12px;color:var(--text-2);font-size:11px">'+
        '<strong>Run ID：</strong> '+escHtml(run.runId)+' · <strong>Skill：</strong> '+escHtml(run.skillName||"")+' v'+escHtml(run.skillVersion||"")+
        ' · <strong>状态：</strong> '+escHtml(runStatusLabel(run.status))+
        (run.error?' · <span style="color:var(--red)">'+escHtml(run.error)+'</span>':"")+
      '</div>'+
      '<div style="font-weight:600;margin-bottom:8px">执行流程 ('+run.steps.length+' 步)</div>'+
      run.steps.map(s=>'<div class="step-item"><span class="step-no">'+s.stepNo+'</span>'+
        '<span class="step-type">'+escHtml(stepLabel(s.stepType))+'</span>'+
        '<span class="step-summary">'+escHtml(s.summary)+'</span>'+
        dur(s.duration,"耗时")+'</div>').join("")+
      '<div style="font-weight:600;margin:14px 0 8px">工具调用 ('+run.tools.length+')</div>'+
      run.tools.map(t=>{
        const ok=t.status==="success";
        const st=t.status==="skipped"?"跳过":(ok?"成功":"失败");
        const stColor=ok?"var(--green)":(t.status==="skipped"?"var(--text-3)":"var(--red)");
        return '<div class="step-item"><span class="step-no">'+t.tool.slice(0,1).toUpperCase()+'</span>'+
          '<span class="step-type">'+escHtml(t.tool+' / '+t.action)+'</span>'+
          '<span class="step-summary">'+escHtml(t.params?JSON.stringify(t.params):"")+' <span style="color:'+stColor+'">· '+st+'</span>'+(t.durationMs?' · '+t.durationMs+'ms':'')+'</span></div>';
      }).join("")+
      (run.finalAnswer?'<div style="font-weight:600;margin:14px 0 6px">最终回答</div>'+
        '<div style="background:var(--bg);padding:12px;border-radius:10px;font-size:12px;line-height:1.7">'+escHtml(run.finalAnswer)+'</div>':"");
  }

  async function openRunDetail(runId){
    const modal=document.getElementById("modalRun");
    const body=document.getElementById("modalRunBody");
    modal.style.display="grid";
    body.innerHTML='<div class="empty">加载中…</div>';
    try{
      const r=await apiFetch("/api/v1/agent-runs/"+runId);
      const data=await r.json();
      const steps=data.steps||[];
      const routeStep=steps.find(step=>step.stepType==="ROUTE_DECISION");
      const internalRoute=routeStep?.payload?.route||routeStep?.name||"";
      let html='<div style="margin-bottom:8px"><strong>业务路径：</strong> '+escHtml(businessRouteForRun(data.run||{}))+
        (internalRoute?' <span class="run-route">'+escHtml(routeLabel(internalRoute))+'</span>':"")+'</div>';
      html+='<div style="margin-bottom:12px;color:var(--muted);font-size:11px"><strong>Run ID：</strong> '+escHtml(data.run?.runId||runId)+
        ' · <strong>状态：</strong> '+escHtml(runStatusLabel(data.run?.status||""))+
        ' · <strong>工具：</strong> '+(data.run?.toolCallCount||0)+'/'+(data.run?.maxToolCalls||0)+'</div>';
      if(steps.length){
        html+='<div style="font-weight:600;margin-bottom:8px">执行流程 ('+steps.length+' 步)</div>';
        steps.forEach((s,i)=>{
          html+='<div class="step-item"><span class="step-no">'+(i+1)+'</span>'+
            '<span class="step-type">'+escHtml(stepLabel(s.stepType||""))+'</span>'+
            '<span class="step-summary">'+escHtml(s.summary||"")+'</span>'+
            '</div>';
        });
      }
      if(data.run?.finalAnswer){
        html+='<div style="font-weight:600;margin-top:12px;margin-bottom:6px">最终回答</div>';
        html+='<div style="background:#f4f5f7;padding:12px;border-radius:8px;font-size:12px;line-height:1.7;max-height:200px;overflow:auto">'+escHtml(data.run.finalAnswer)+'</div>';
      }
      body.innerHTML=html;
    }catch(e){
      body.innerHTML='<div class="empty">加载失败: '+escHtml(e.message)+'</div>';
    }
  }

  function closeModal(){
    document.getElementById("modalRun").style.display="none";
  }

  function runLabel(run){
    const labels={
      "general-chat":"普通直接问答",
      "general-tool-agent":"联网工具问答",
      "stock-deep-analysis":"标的深度分析",
      "investment-knowledge-qa":"投资知识问答"
    };
    return labels[run.skillName]||run.skillName||run.intent||"未知流程";
  }

  function businessRouteForRun(run){
    if(run.skillName==="general-tool-agent")return"TOOL AGENT";
    if(String(run.skillName||"").includes("stock")||run.intent==="STOCK_ANALYSIS")return"STOCK ANALYSIS";
    return"DIRECT CHAT";
  }

  function runStatusLabel(status){
    return({completed:"已完成",running:"运行中",failed:"失败"})[status]||status||"未知";
  }

  function routeLabel(route){
    const labels={
      GENERAL_CHAT:"普通闲聊",
      KNOWLEDGE_QA:"投资知识",
      EXTERNAL_RESEARCH:"联网研究",
      MARKET_FACT:"行情与指标",
      STOCK_DECISION:"标的决策",
      MARKET_CAUSAL_ANALYSIS:"事件影响",
      NEED_CLARIFICATION:"需要补充"
    };
    return labels[route]||route;
  }

  function stepLabel(stepType){
    const labels={
      ROUTE_DECISION:"路由",
      REACT_DECISION:"规划",
      TOOL_CALL:"工具",
      TOOL_OBSERVATION:"结果",
      REACT_TERMINATION:"收束",
      MODEL_GATE:"模型门禁",
      MODEL_CALL:"生成",
      FINAL_ANSWER:"完成",
      POLICY_REJECTION:"策略拦截",
      ERROR:"错误"
    };
    return labels[stepType]||stepType;
  }

  function showRunPanel(){
    ST.sideView="runs";
    if(runsDrawer)runsDrawer.classList.add("open");
    document.querySelector(".main")?.classList.add("runs-open");
    renderCurrentTrace();
  }
  function newSession(){
    // 1. 先保存当前会话的消息到它的 store
    const prev=activeSession();
    if(prev){
      while(messages.firstChild)prev.store.appendChild(messages.firstChild);
    }
    // 2. 创建仅存在于当前页面的草稿会话，发首条消息后才写入后端目录
    const list=ST.sessionsByMode[ST.mode];
    list.items=list.items.filter(session=>!session.draft);
    const draft=makeSession(ST.mode);
    list.items.push(draft);
    list.activeId=draft.id;
    persistSessions();
    ST.sending=false;
    ST.currentBubble=null;
    ST.streamText="";
    if(ST.mode==="stock")saveInstrument(null);
    const cfg=AGENT_MAP[ST.mode];
    renderWelcome("新会话已创建",cfg.needsInstrument&&ST.currentInstrument
      ?"当前标的是 "+ST.currentInstrument.symbol+" "+(ST.currentInstrument.name||"")+"，也可以直接询问板块。"
      :cfg.newSessionDesc);
    statusBar.innerHTML="";
    headSkill.textContent="";
    headRunId.textContent="";
    sendBtn.disabled=false;
    updateSessionBadge();
    renderCurrentTrace();
    setConversationUrl(null);
    input.value="";
    input.focus();
    toast("已开始新的研究");
  }

  function showAuthModal(){
    const modal=document.getElementById("modalAuth");
    if(modal)modal.style.display="grid";
    document.getElementById("authError").textContent="";
    setAuthMode(authMode);
    setTimeout(()=>document.getElementById("authUsername")?.focus(),0);
  }

  function setAuthMode(mode){
    authMode=mode;
    const registering=mode==="register";
    document.getElementById("authTitle").textContent=registering?"注册 BDLH Agent Runtime":"登录 BDLH Agent Runtime";
    document.querySelector("#authLoginPanel .modal-intro").textContent=registering
      ?"填写用户名和至少 8 位密码。注册成功后将直接进入工作站。"
      :"登录后，对话、运行状态、记忆和个人偏好将按账号独立保存。";
    document.getElementById("authLoginButton").textContent=registering?"提交注册":"登录";
    document.getElementById("authRegisterButton").textContent=registering?"返回登录":"注册账号";
    document.getElementById("authPassword").autocomplete=registering?"new-password":"current-password";
    document.getElementById("authError").textContent="";
  }

  function updateAccountButton(){
    const button=document.getElementById("accountButton");
    if(button)button.textContent=AUTH.user?.username||"登录";
  }

  function resetWorkspaceForAuthenticatedUser(){
    ST.sessionsByMode=Object.fromEntries(AGENTS.map(agent=>[agent.id,createSessionList(agent.id)]));
    ST.currentInstrument=loadInstrument();
    messages.replaceChildren();
    updateAccountButton();
    switchMode(ST.mode,false);
  }

  function completeAuthentication(data){
    AUTH.ready=true;
    AUTH.user={userId:String(data.userId),username:data.username};
    if(data.token)localStorage.setItem(AUTH_TOKEN_KEY,data.token);
    document.getElementById("modalAuth").style.display="none";
    resetWorkspaceForAuthenticatedUser();
    if(AUTH.pendingQuestion){
      const question=AUTH.pendingQuestion;AUTH.pendingQuestion="";input.value=question;send(question);
    }
  }

  async function initializeAuthentication(initialQuestion){
    AUTH.pendingQuestion=initialQuestion||"";
    const token=localStorage.getItem(AUTH_TOKEN_KEY);
    if(token){
      try{
        const response=await NATIVE_FETCH("/api/v1/auth/me",{headers:{Authorization:"Bearer "+token}});
        if(response.ok){
          const profile=await response.json();
          completeAuthentication({...profile,token});
          return;
        }
      }catch(error){/* 登录服务暂不可用时进入登录页。 */}
      localStorage.removeItem(AUTH_TOKEN_KEY);
    }
    showAuthModal();
  }

  async function loginAccount(){
    const username=document.getElementById("authUsername").value.trim();
    const password=document.getElementById("authPassword").value;
    const error=document.getElementById("authError");
    if(!username||password.length<8){error.textContent="请输入用户名和至少 8 位密码";return;}
    const registering=authMode==="register";
    error.textContent=registering?"正在注册…":"正在登录…";
    try{
      const response=await NATIVE_FETCH(`/api/v1/auth/${registering?"register":"login"}`,{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({username,password})
      });
      const data=await response.json();
      if(!response.ok)throw new Error(data.error||(registering?"注册失败":"登录失败"));
      completeAuthentication(data);
    }catch(reason){error.textContent=reason.message||"认证服务暂时不可用";}
  }

  document.getElementById("sendBtn").addEventListener("click",()=>send());
  document.getElementById("authLoginButton").addEventListener("click",loginAccount);
  document.getElementById("authRegisterButton").addEventListener("click",()=>setAuthMode(authMode==="register"?"login":"register"));
  document.getElementById("authPassword").addEventListener("keydown",event=>{
    if(event.key==="Enter")loginAccount();
  });
  document.getElementById("accountButton").addEventListener("click",()=>{
    if(!AUTH.ready){showAuthModal();return;}
    if(window.confirm("退出当前账号？本机保存的该账号会话目录不会被删除。")){
      localStorage.removeItem(AUTH_TOKEN_KEY);
      location.reload();
    }
  });
  composer.addEventListener("submit",e=>{e.preventDefault();send()});
  input.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();send()}});
  document.getElementById("newSession").addEventListener("click",newSession);
  selectInstrument.addEventListener("click",openInstrumentModal);
  clearInstrument.addEventListener("click",()=>{
    saveInstrument(null);
    input.placeholder="询问板块热度、讨论度，或先选择个股标的…";
  });
  document.querySelectorAll("[data-open-instrument]").forEach(button=>button.addEventListener("click",openInstrumentModal));
  document.getElementById("marketOverview")?.addEventListener("click",()=>{
    toast("正在拉取市场全景…");
    send("今天哪些行业板块最强？请展示热度组成。");
  });
  const skipInstrument=document.getElementById("skipInstrument");
  if(skipInstrument)skipInstrument.addEventListener("click",()=>go("/agent/general"));
  document.querySelectorAll("[data-close-instrument]").forEach(button=>button.addEventListener("click",closeInstrumentModal));
  document.querySelectorAll("[data-close-skill-result]").forEach(button=>button.addEventListener("click",()=>{
    document.getElementById("modalSkillResult").style.display="none";
  }));
  document.getElementById("confirmInstrument").addEventListener("click",confirmInstrument);
  document.querySelectorAll(".instrument-option").forEach(option=>{
    option.addEventListener("click",()=>{
      ST.pendingInstrument={symbol:option.dataset.symbol,name:option.dataset.name,type:option.dataset.type};
      document.getElementById("instrumentSymbol").value=option.dataset.symbol;
      document.getElementById("instrumentName").value=option.dataset.name;
      document.getElementById("instrumentError").textContent="";
      document.querySelectorAll(".instrument-option").forEach(item=>item.classList.toggle("selected",item===option));
    });
  });
  document.querySelectorAll(".preset-chip").forEach(option=>{
    option.addEventListener("click",()=>chooseInstrument({symbol:option.dataset.symbol,name:option.dataset.name,type:option.dataset.type}));
  });

  bindQuickPrompts();

  const tabRunsEl=document.getElementById("tabRuns");
  if(tabRunsEl)tabRunsEl.addEventListener("click",showRunPanel);

  const runsCloseEl=document.getElementById("runsClose");
  if(runsCloseEl)runsCloseEl.addEventListener("click",()=>{
    if(runsDrawer)runsDrawer.classList.remove("open");
    document.querySelector(".main")?.classList.remove("runs-open");
  });

  const sidebarHomeEl=document.getElementById("sidebarHome");
  if(sidebarHomeEl)sidebarHomeEl.addEventListener("click",()=>go("/"));

  document.getElementById("modalRun").addEventListener("click",function(e){if(e.target===this)closeModal()});
  document.getElementById("modalInstrument").addEventListener("click",function(e){if(e.target===this)closeInstrumentModal()});

  /* ===== 侧边栏 Agent 切换列表 ===== */
  (function initAgentMenu(){
    const menu=document.getElementById("agentMenu");
    if(!menu)return;
    menu.innerHTML=AGENT_GROUPS.map(group=>{
      const agents=AGENTS.filter(agent=>agent.group===group.id);
      if(!agents.length)return "";
      return '<section class="agent-group" aria-label="'+escHtml(group.label)+'"><span class="agent-group-label">'+escHtml(group.label)+'</span>'+agents.map(agent=>
        '<button class="agent-option" data-agent="'+agent.id+'" type="button"><span class="agent-ico" aria-hidden="true"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'+(agent.icon||'<path d="M5 5.5h14v10H9l-4 3v-13Z"/>')+'</svg></span><span class="agent-copy"><strong>'+escHtml(agent.label)+'</strong><small>'+escHtml(agent.description)+'</small></span></button>'
      ).join("")+'</section>';
    }).join("");
    menu.querySelectorAll(".agent-option").forEach(btn=>{
      btn.addEventListener("click",()=>{
        const target=btn.dataset.agent;
        if(target===ST.mode)return;
        switchMode(target);
        const nextUrl=new URL(location.href);
        nextUrl.searchParams.set("name",target);
        history.replaceState(null,"",nextUrl.toString());
      });
    });
  })();

  /* 侧边栏折叠 */
  const collapseBtn=document.getElementById("sidebarCollapse");
  if(collapseBtn){
    collapseBtn.addEventListener("click",()=>{
      const sidebar=document.getElementById("sidebar");
      if(sidebar)sidebar.classList.toggle("collapsed");
    });
  }
  /* 移动端侧边栏开关 */
  const mobileToggle=document.getElementById("mobileSidebarToggle");
  if(mobileToggle){
    mobileToggle.addEventListener("click",()=>{
      const sidebar=document.getElementById("sidebar");
      if(sidebar)sidebar.classList.toggle("open");
    });
  }

  /* ===== 右下角桌面宠物：点击切机甲形态 + 弹台词（双击开运行追踪） ===== */
  (function initDeskpet(){
    const pet=document.getElementById("deskpet");
    const bubble=document.getElementById("deskpetBubble");
    if(!pet)return;
    const FORMS=[
      {id:"std",name:"STANDARD",msg:"模式切换 · NERV スタンダード。同步率确认，启动研究协处理器。"},
      {id:"gridman",name:"GRIDMAN",msg:"模式切换 · 電光超人グリッドマン。去守护想守护的东西。"},
      {id:"dynazenon",name:"DYNAZENON",msg:"模式切换 · ダイナゼノン。约好的事，趁赏味期内兑现吧。"},
      {id:"eva",name:"EVA · 初号機",msg:"模式切换 · エヴァンゲリオン。带着爱去理解，带着约定去完成。"}
    ];
    const formById=Object.fromEntries(FORMS.map(f=>[f.id,f]));
    let fIdx=0;
    const updateBubble=()=>{
      const current=pet.dataset.form||"std";
      const f=formById[current]||FORMS[0];
      bubble.textContent=f.msg;
    };
    const cycleForm=()=>{
      fIdx=(fIdx+1)%FORMS.length;
      pet.setAttribute("data-form",FORMS[fIdx].id);
      updateBubble();
    };
    updateBubble();
    let clickTimer=null;
    pet.addEventListener("click",(e)=>{
      if(e.target.closest(".deskpet-bubble"))return;
      if(clickTimer){clearTimeout(clickTimer);clickTimer=null;showRunPanel();return;}
      clickTimer=setTimeout(()=>{clickTimer=null;cycleForm();},240);
    });
  })();

  /* ===== 初始化：从 ?name= 参数选择当前 Agent，?q= 自动带入问题 ===== */
  const searchParams=new URLSearchParams(location.search);
  const initMode=AGENT_MAP[searchParams.get("name")||""]?searchParams.get("name"):"general";
  document.body.dataset.mode=initMode;
  switchMode(initMode,false);
  const initialQuestion=(searchParams.get("q")||"").trim();
  void initializeAuthentication(initialQuestion);

  /* ===== 桌面宠物跟随当前 Agent（智能问答=六花，股市分析=茜） ===== */
  function syncIdleChar(){
    const charByMode={general:"rikka",stock:"akane"};
    const target=charByMode[ST.mode]||"rikka";
    const pet=document.getElementById("deskpet");
    if(pet)pet.dataset.char=target;
    const bubble=document.getElementById("deskpetBubble");
    if(bubble)bubble.classList.remove("show");
  }
  (function initIdleChar(){
    syncIdleChar();
  })();



