"use strict";
const $ = id => document.getElementById(id);
const node = (tag, className, text) => { const e = document.createElement(tag); if(className) e.className=className; if(text!==undefined) e.textContent=text; return e; };
const tokenFromLink = new URLSearchParams(location.hash.slice(1)).get("token");
const startTab = new URLSearchParams(location.hash.slice(1)).get("tab");
if(tokenFromLink){try{sessionStorage.setItem("chutku-token",tokenFromLink);}catch{}}
if(location.hash)history.replaceState(null,"",location.pathname);
let sessionToken = tokenFromLink || "";
try{sessionToken = sessionToken || sessionStorage.getItem("chutku-token") || "";}catch{}
let state=null, busy=false;
const labels={mind:"Mind map",home:"Command center",memory:"Memory",history:"Activity",capabilities:"Capabilities",verification:"Verification"};
const MODE_HELP={
  review:"Review: every step waits for your click before it runs.",
  auto_safe:"Auto (safe): looking, opening apps/files/sites and other easily reversible steps run by themselves. File changes and anything risky wait for your click.",
  auto_edits:"Auto (incl. edits): also runs file changes that Chutku can undo. Deleting, sending, closing apps, power and anything after reading untrusted content still wait for your click.",
  owner:"Owner (no approvals): everything runs by itself, including messages to people in your memory. Asks only for file changes, any deletion, shutdown/killing programs, messages to someone new, and steps right after reading web pages or messages."};
const TERMINAL=new Set(["done","clarify","failed","stopped","cancelled"]);

function error(message){$("error-banner").textContent=message;$("error-banner").hidden=!message;}
function setBusy(value){busy=value;$("run-status").textContent=value?"Working…":"Ready";$("run-status").classList.toggle("busy",value);$("send").disabled=value;$("mic").disabled=value;}
async function api(path,data){
  const options={headers:{"X-Chutku-Token":sessionToken}};
  if(data!==undefined){options.method="POST";options.headers["Content-Type"]="application/json";options.body=JSON.stringify(data);}
  let response;
  try{response=await fetch(path,options);}catch{throw new Error("Chutku is disconnected. Keep its terminal running, or restart and open the new session link.");}
  const payload=await response.json();
  if(!response.ok)throw new Error(payload.error||"The request failed.");
  return payload;
}
function switchTab(id){if(id==="mind")loadMind();document.querySelectorAll(".view").forEach(e=>e.hidden=e.id!==id);document.querySelectorAll(".nav-item").forEach(e=>e.classList.toggle("active",e.dataset.tab===id));$("page-label").textContent=labels[id];}
document.querySelectorAll("[data-tab]").forEach(e=>e.addEventListener("click",()=>switchTab(e.dataset.tab)));

// ---- autonomy selector (remembered per browser) ----
function currentMode(){return document.querySelector('input[name="mode"]:checked')?.value||"review";}
function setMode(mode){const input=document.querySelector(`input[name="mode"][value="${mode}"]`)||document.querySelector('input[name="mode"][value="review"]');input.checked=true;$("mode-help").textContent=MODE_HELP[input.value];}
let savedMode="owner";try{savedMode=localStorage.getItem("chutku-mode")||"owner";}catch{}
setMode(savedMode);
document.querySelectorAll('input[name="mode"]').forEach(e=>e.addEventListener("change",()=>{setMode(e.value);try{localStorage.setItem("chutku-mode",e.value);}catch{}}));

// ---- chat rendering ----
function log(){const area=$("chat-log");area.querySelector(".chat-empty")?.remove();return area;}
function scrollChat(){const area=$("chat-log");area.scrollTop=area.scrollHeight;}
function userBubble(text,voice){const b=node("div","bubble user");b.append(node("p","",(voice?"🎙 ":"")+text));log().append(b);scrollChat();}
function assistantBubble(){const b=node("div","bubble assistant");log().append(b);scrollChat();return b;}
function badge(text,kind){return node("span","badge "+(kind||""),text);}
const STEP_ICON={COMPLETED:"✓",FAILED:"!",DENIED:"⛔",WAITING_CONFIRMATION:"?",CLARIFYING:"?"};

function approvalCard(approval,onDecide){
  const card=node("div","approval");
  card.append(node("strong","","Confirm this exact step"),node("p","",approval.consequence||approval.tool));
  const facts=node("pre","",JSON.stringify({tool:approval.tool,risk:approval.risk_label||approval.risk,arguments:approval.arguments,why:approval.reason},null,2));
  const row=node("div","approval-actions"),yes=node("button","primary","Approve"),no=node("button","text-button","Cancel");
  for(const [button,value] of [[yes,true],[no,false]])button.addEventListener("click",async()=>{yes.disabled=no.disabled=true;await onDecide(value);});
  row.append(yes,no);card.append(facts,row);return card;
}

function renderDirect(bubble,payload){
  const result=payload.result;bubble.replaceChildren();
  const ok=result.state==="COMPLETED";
  bubble.append(badge(ok?"VERIFIED":String(result.state).replaceAll("_"," "),ok?"ok":"warn"),node("pre","",payload.message));
  if(result.approval){bubble.append(approvalCard(result.approval,async approved=>{
    try{const next=await api(approved?"/api/approve":"/api/approval/cancel",{token:result.approval.token});renderDirect(bubble,next);refresh();}catch(e){error(e.message);}
  }));}
  if(result.task_id){const t=node("button","text-button","Trace ↗");t.addEventListener("click",()=>showTrace(result.task_id));bubble.append(t);}
}

function renderSession(bubble,s){
  bubble.replaceChildren();
  const head=node("div","session-head");
  const statusText={planning:"Thinking…",running:"Working…",waiting_confirmation:"Needs your OK",done:"Done",clarify:"Needs more detail",failed:"Stopped",stopped:"Stopped by policy",cancelled:"Cancelled"}[s.status]||s.status;
  head.append(badge(statusText,s.status==="done"?"ok":TERMINAL.has(s.status)?"warn":"live"),badge(s.mode.replace("_"," "),"mode"));
  if(s.planners.some(p=>p.planner==="gemini"))head.append(badge("planned with Gemini","cloud"));
  if(s.tainted)head.append(badge("read untrusted content","warn"));
  if(s.suspicious)head.append(badge("page tried to give instructions","danger"));
  bubble.append(head);
  if(s.declared_plan.length&&!TERMINAL.has(s.status)){const plan=node("ol","declared");s.declared_plan.forEach(p=>plan.append(node("li","",p)));bubble.append(node("div","small-title","Plan"),plan);}
  if(s.steps.length){
    const list=node("div","steps-live");
    s.steps.forEach(step=>{const row=node("div","step "+step.state.toLowerCase());row.append(node("span","step-icon",STEP_ICON[step.state]||"·"),node("span","step-text",step.purpose+" — "+step.tool));
      if(step.message&&step.state!=="COMPLETED")row.append(node("span","step-msg",step.message));
      if(step.task_id){const t=node("button","text-button","trace");t.addEventListener("click",()=>showTrace(step.task_id));row.append(t);}
      list.append(row);});
    bubble.append(list);
  }
  if(s.reply&&(TERMINAL.has(s.status)||s.status==="waiting_confirmation"||s.status==="running"))bubble.append(node("p","reply",s.reply));
  if(s.pending){bubble.append(approvalCard({...s.pending.approval},async approved=>{
    try{const next=await api("/api/agent/confirm",{id:s.id,approve:approved});renderSession(bubble,next.session);follow(bubble,s.id);}catch(e){error(e.message);}
  }));}
  if(!TERMINAL.has(s.status)){const stop=node("button","text-button danger-text","Stop");stop.addEventListener("click",async()=>{try{const r=await api("/api/agent/stop",{id:s.id});renderSession(bubble,r.session);}catch(e){error(e.message);}});bubble.append(stop);}
  scrollChat();
}

// Server-sent updates read with fetch() (so the session token stays in a header, never in the URL).
// Returns true when the stream ended normally; throws when streaming is not available (the caller then polls).
async function stream(path,onData){
  const response=await fetch(path,{headers:{"X-Chutku-Token":sessionToken}});
  if(!response.ok||!response.body)throw new Error("no stream");
  const reader=response.body.getReader(),decoder=new TextDecoder();
  let buffer="";
  for(;;){
    const {value,done}=await reader.read();
    if(done)return true;
    buffer+=decoder.decode(value,{stream:true});
    let cut;
    while((cut=buffer.indexOf("\n\n"))>=0){
      const block=buffer.slice(0,cut);buffer=buffer.slice(cut+2);
      if(block.startsWith("data: ")&&onData(JSON.parse(block.slice(6)))===false){reader.cancel().catch(()=>{});return true;}
    }
  }
}
async function follow(bubble,id){
  // Each task updates its own bubble; the box stays free so more orders can be queued meanwhile.
  try{
    let finished=false;
    try{
      for(let round=0;round<20&&!finished;round++){   // a stream lasts about a minute; long tasks reconnect
        await stream("/api/events?id="+encodeURIComponent(id),({session})=>{
          renderSession(bubble,session);
          finished=TERMINAL.has(session.status)||session.status==="waiting_confirmation";
          return !finished;
        });
      }
    }catch{}
    for(;!finished;){   // fallback: ask every 0.6 s (older browser, or the stream was cut)
      await new Promise(r=>setTimeout(r,600));
      const {session}=await api("/api/agent/session?id="+encodeURIComponent(id));
      renderSession(bubble,session);
      if(TERMINAL.has(session.status)||session.status==="waiting_confirmation")break;
    }
  }catch(e){error(e.message);}
  finally{refresh().catch(()=>{});refreshToday();}
}

async function ask(message){
  if(busy||!message.trim())return;error("");switchTab("home");userBubble(message);
  const bubble=assistantBubble();bubble.append(node("p","muted","Thinking…"));setBusy(true);
  try{
    const payload=await api("/api/chat",{message,mode:currentMode()});
    if(payload.kind==="direct"){renderDirect(bubble,payload);setBusy(false);refresh().catch(()=>{});return;}
    seenSessions.add(payload.session.id);bubble.dataset.session=payload.session.id;
    renderSession(bubble,payload.session);setBusy(false);await follow(bubble,payload.session.id);
  }catch(e){bubble.replaceChildren(badge("NOT RUN","warn"),node("p","",e.message));setBusy(false);}
}
$("chat-form").addEventListener("submit",e=>{e.preventDefault();const text=$("chat-input").value;$("chat-input").value="";ask(text);});
$("chat-input").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();$("chat-form").requestSubmit();}});
document.querySelectorAll("[data-command]").forEach(e=>e.addEventListener("click",()=>ask(e.dataset.command)));
document.querySelectorAll("[data-ask]").forEach(e=>e.addEventListener("click",()=>ask(e.dataset.ask)));

$("mic").addEventListener("click",async()=>{
  if(busy)return;error("");switchTab("home");setBusy(true);
  const bubble=assistantBubble();bubble.append(node("p","muted","Listening… speak now."));
  try{
    const payload=await api("/api/voice/ask",{mode:currentMode()});
    if(!payload.transcript){bubble.replaceChildren(badge("NOTHING HEARD","warn"),node("p","",payload.message));setBusy(false);return;}
    bubble.remove();userBubble(payload.transcript,true);const reply=assistantBubble();
    seenSessions.add(payload.session.id);reply.dataset.session=payload.session.id;
    renderSession(reply,payload.session);setBusy(false);await follow(reply,payload.session.id);
  }catch(e){bubble.replaceChildren(badge("NOT RUN","warn"),node("p","",e.message));setBusy(false);}
});

// ---- hands-free (hotkey / wake phrase) ----
const seenSessions=new Set();
function renderHandsfree(h){
  if(!h)return;
  $("hotkey-state").textContent=h.hotkey_active?h.hotkey+" talks from anywhere":"Hotkey unavailable (another app owns "+h.hotkey+")";
  $("wake-toggle").checked=h.wake_word;$("handsfree-mode").value=h.handsfree_mode;if(h.browser)$("browser-choice").value=h.browser;$("offline-toggle").checked=!!h.offline_mode;
  $("wake-state").textContent=h.wake_error?"MIC ERROR":h.wake_listening?"LISTENING FOR “OYE CHUTKU”":"WAKE OFF";
  $("wake-state").classList.toggle("busy",Boolean(h.wake_listening));
}
async function setPreference(change){try{const r=await api("/api/preferences",change);renderHandsfree(r.handsfree);}catch(e){error(e.message);}}
$("wake-toggle").addEventListener("change",e=>setPreference({wake_word:e.target.checked}));
$("handsfree-mode").addEventListener("change",e=>setPreference({handsfree_mode:e.target.value}));
$("browser-choice").addEventListener("change",e=>setPreference({browser:e.target.value}));
$("offline-toggle").addEventListener("change",e=>setPreference({offline_mode:e.target.checked}));
async function pollHandsfree(){
  try{
    if(!busy){
      const latest=await api("/api/agent/latest");renderHandsfree(latest.handsfree);
      if(latest.id&&!seenSessions.has(latest.id)){
        seenSessions.add(latest.id);
        const {session}=await api("/api/agent/session?id="+encodeURIComponent(latest.id));
        if(session.origin==="voice"&&!document.querySelector(`[data-session="${latest.id}"]`)){
          switchTab("home");userBubble(session.goal,true);const b=assistantBubble();b.dataset.session=latest.id;
          renderSession(b,session);await follow(b,latest.id);
        }
      }
    }
  }catch{}
  setTimeout(pollHandsfree,1500);
}

// ---- mind map (hand-drawn SVG: the page's CSP allows no libraries; all text set with textContent) ----
const SVGNS="http://www.w3.org/2000/svg";
function svg(tag,attrs,text){const e=document.createElementNS(SVGNS,tag);for(const [k,v] of Object.entries(attrs||{}))e.setAttribute(k,String(v));if(text!==undefined)e.textContent=text;return e;}
function short(s,n){s=String(s||"");return s.length>n?s.slice(0,n-1)+"…":s;}
async function loadMind(){try{renderMind(await api("/api/mind"));}catch(e){error(e.message);}}
function renderMind(m){
  const open=items=>(items||[]).map(i=>({label:i.text,detail:(i.done?"✓ done":"open")+" · #"+i.id+(i.added?" · added "+i.added:""),done:i.done}));
  const branches=[
    ["People",(m.people||[]).map(p=>({label:p.name+((p.aliases||[]).length?" ("+p.aliases.join(", ")+")":""),detail:[p.relation,p.whatsapp&&"WhatsApp: "+p.whatsapp,p.phone&&"Phone: "+p.phone,...(p.notes||[])].filter(Boolean).join(" · ")||"No details yet."}))],
    ["About you",Object.entries(m.facts||{}).map(([k,v])=>({label:k+": "+v,detail:k+" = "+v}))],
    ...["assignments","schedule","goals","projects","skills","domains","notes"].map(n=>[n[0].toUpperCase()+n.slice(1),open((m.lists||{})[n])]),
    ["Habits",(m.habits||[]).map(h=>({label:h,detail:h}))],
    ["Recent topics",(m.topics||[]).map(t=>({label:t,detail:"You talked about “"+t+"” recently."}))]];
  const root=$("mind-svg");root.replaceChildren();const cx=500,cy=340,n=branches.length;
  const detail=(title,text)=>{const d=$("mind-detail");d.replaceChildren(node("h3","",title),node("p","",text));};
  branches.forEach(([name,leaves],i)=>{
    const a=-Math.PI/2+i*2*Math.PI/n,bx=cx+165*Math.cos(a),by=cy+150*Math.sin(a);
    root.append(svg("line",{x1:cx,y1:cy,x2:bx,y2:by,class:"mind-edge"}));
    const shown=leaves.slice(0,6),span=Math.min(2*Math.PI/n*0.9,0.18*Math.max(shown.length,1));
    shown.forEach((leaf,j)=>{const la=a+(shown.length>1?-span/2+span*j/(shown.length-1):0);
      const lx=cx+300*Math.cos(la),ly=cy+270*Math.sin(la),right=Math.cos(la)>=0;
      root.append(svg("line",{x1:bx,y1:by,x2:lx,y2:ly,class:"mind-edge thin"}));
      const g=svg("g",{class:"mind-leaf"+(leaf.done?" done":""),tabindex:0});
      g.append(svg("circle",{cx:lx,cy:ly,r:5}),svg("text",{x:lx+(right?9:-9),y:ly+4,"text-anchor":right?"start":"end"},short(leaf.label,26)));
      const show=()=>detail(name,leaf.label+" — "+leaf.detail);g.addEventListener("click",show);g.addEventListener("keydown",e=>{if(e.key==="Enter")show();});
      root.append(g);});
    const g=svg("g",{class:"mind-branch"+(leaves.length?"":" empty"),tabindex:0});
    g.append(svg("circle",{cx:bx,cy:by,r:30}),svg("text",{x:bx,y:by+4,"text-anchor":"middle"},short(name,12)));
    const more=leaves.length>6?` (+${leaves.length-6} more)`:"";
    const show=()=>detail(name,leaves.length?leaves.map(l=>"• "+l.label).join("\n"):"Nothing here yet."+more);
    g.addEventListener("click",show);g.addEventListener("keydown",e=>{if(e.key==="Enter")show();});root.append(g);});
  const c=svg("g",{class:"mind-root"});c.append(svg("circle",{cx,cy,r:42}),svg("text",{x:cx,y:cy+5,"text-anchor":"middle"},"You"));root.append(c);
}

// ---- other tabs ----
function activityRow(task){
  const failed=task.state!=="COMPLETED",row=node("div","activity-row"),icon=node("div","activity-icon"+(failed?" failed":""),failed?"!":"✓");
  const main=node("div","activity-main");main.append(node("div","activity-title",task.tool.replaceAll("_"," ")),node("div","activity-time",new Date(task.timestamp).toLocaleString()));
  const state_=node("span","activity-state"+(failed?" failed":""),task.state.replaceAll("_"," "));
  const trace=node("button","text-button","Trace ↗");trace.addEventListener("click",()=>showTrace(task.task_id));row.append(icon,main,state_,trace);return row;
}
function renderHeard(){const area=$("heard-list");if(!area)return;area.replaceChildren();(state.heard||[]).forEach(h=>{const row=node("div","activity-row");const when=new Date((h.at||0)*1000).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"});row.append(node("strong","",`“${h.text||""}”`),node("span","muted",` ${h.path} · ${when} · ${h.decision}${h.confidence!=null?` · conf ${h.confidence}`:""}`));area.append(row);});if(!area.childNodes.length)area.append(node("p","empty-note","Nothing heard yet."));}
function renderHistory(){renderHeard();for(const [id,limit] of [["recent",4],["history-list",20]]){const area=$(id);area.replaceChildren();state.history.slice(0,limit).forEach(t=>area.append(activityRow(t)));if(!area.childNodes.length)area.append(node("p","empty-note","Your first task will appear here."));}}
function renderMemories(){
  const terms=$("memory-search").value.toLocaleLowerCase().split(/\s+/).filter(Boolean),area=$("memory-list");area.replaceChildren();
  state.memories.filter(m=>terms.every(q=>(m.key+" "+m.value).toLocaleLowerCase().includes(q))).forEach(m=>{
    const row=node("div","memory-row"),text=node("div");text.append(node("h3","",m.key),node("p","",m.value),node("span","memory-meta","USER STATED · "+new Date(m.updated_at).toLocaleString()));
    const forget=node("button","danger","Forget");forget.setAttribute("aria-label","Forget "+m.key);forget.addEventListener("click",()=>ask("forget "+m.key));row.append(text,forget);area.append(row);
  });if(!area.childNodes.length)area.append(node("p","empty-note","No matching notes. Save something you'd like to remember."));$("memory-count").textContent=state.memories.length;
}
function renderCapabilities(){
  $("capability-list").replaceChildren();
  const risks=["Observation","Low-risk / reversible","Data modification","External side effect","Privileged","Disabled"];
  const granted=new Set((state.capability_grants||[]).filter(g=>g.active).map(g=>g.capability));
  state.tools.forEach(t=>{const card=node("article","capability");const need=t.required_capability;
    card.append(node("h3","",t.name),node("p","",t.description),node("span","risk","R"+t.risk.level+" · "+risks[t.risk.level]+(need?(granted.has(need)?" · ✓ "+need:" · needs "+need):"")));$("capability-list").append(card);});
  $("limits").replaceChildren(...state.limits.map(text=>node("p","",text)));
}
function renderPause(paused){$("pause-actions").textContent=paused?"Resume actions":"Pause actions";$("pause-note").hidden=!paused||!!document.querySelector(".alert.paused");}
function renderVerification(report){const area=$("verification-results");area.replaceChildren();if(!report){area.append(node("p","empty-note","No release verification saved yet."));return;}area.append(node("p","muted",(report.stale?"SOURCE CHANGED SINCE VERIFICATION · ":"VERIFIED SOURCE SNAPSHOT · ")+report.timestamp_utc));(report.checks||[]).forEach(check=>{const card=node("article","capability");card.append(node("h3","",check.title),node("span","risk",check.passed?"PASS":"NEEDS ATTENTION"),node("p","",check.detail));area.append(card);});}
async function refresh(){
  state=await api("/api/state");$("connection").textContent="Local session connected";$("sandbox-path").textContent=state.sandbox;
  const roots=(state.resource_grants||[]).filter(g=>g.active&&g.access.includes("modify")).map(g=>g.root);
  $("grants-summary").textContent="FILE ACCESS "+(roots.join("  ")||"sandbox only")+" · system folders are read-only";
  renderPause(state.actions_paused);renderHistory();renderMemories();renderCapabilities();
  $("stop-core").hidden=!state.guard_active;$("guard-status").textContent=state.guard_active?"GUARD ACTIVE · Ctrl+Alt+F12 or Stop Chutku stops everything":"GUARD INACTIVE · Launch with Start-Chutku.cmd for the independent emergency stop";
  renderVerification(state.verification);renderHandsfree(state.handsfree);
  if(state.handsfree&&state.handsfree.latest_session)seenSessions.add(state.handsfree.latest_session);
}
$("stop-core").addEventListener("click",async()=>{try{await api("/api/control",{action:"stop"});}catch{}$("connection").textContent="Emergency stop requested";error("Independent stop requested. Restart Chutku and inspect Activity before resuming. Completed effects may remain.");});
$("pause-actions").addEventListener("click",async()=>{try{const result=await api("/api/control",{action:$("pause-note").hidden?"pause":"resume"});renderPause(result.actions_paused);}catch(e){error(e.message);}});
$("memory-form").addEventListener("submit",async e=>{e.preventDefault();await ask("remember "+$("memory-key").value+" = "+$("memory-value").value);$("memory-key").value="";$("memory-value").value="";});
$("memory-search").addEventListener("input",()=>state&&renderMemories());
$("refresh").addEventListener("click",()=>refresh().catch(e=>error(e.message)));
async function showTrace(id){try{const payload=await api("/api/trace?id="+encodeURIComponent(id));$("trace-id").textContent=id;$("trace-events").replaceChildren();payload.events.forEach(event=>{const item=node("div","trace-event");item.append(node("strong","",event.event_type.replaceAll("_"," ")),node("pre","",JSON.stringify(event.details,null,2)));$("trace-events").append(item);});if(!payload.events.length)$("trace-events").append(node("p","empty-note","No trace found."));$("trace-dialog").showModal();}catch(e){error(e.message);}}
$("close-trace").addEventListener("click",()=>$("trace-dialog").close());
// ---- Today panel (read-only snapshot; untrusted text is set with textContent only) ----
const TOOL_WORDS={"filesystem.write_text":"Wrote a file","filesystem.move":"Moved a file","filesystem.copy":"Copied a file",
  "filesystem.recycle":"Recycled","filesystem.create_directory":"Made a folder","apps.launch":"Opened an app",
  "files.organize":"Tidied a folder","reminder.set":"Set a reminder","log.undo":"Undid an action"};
function tile(id,...children){const body=$(id).querySelector(".tile-body");body.replaceChildren(...children);}
function list(rows){const ul=node("ul");rows.forEach(([a,b])=>{const li=node("li");li.append(node("span","",a),node("span","",b));ul.append(li);});return ul;}
function tickClock(){const now=new Date();$("today-clock").textContent=now.toLocaleTimeString([], {hour:"numeric",minute:"2-digit"});}
function renderToday(t){
  $("today-alerts").replaceChildren(...(t.alerts||[]).map(a=>{const row=node("div","alert");row.append(node("strong","",a.title),node("span","",a.message));return row;}));
  if(t.actions_paused){
    const row=node("div","alert paused");
    row.append(node("strong","","Paused"),node("span","",t.paused_reason||"Actions are paused."));$("pause-note").hidden=true;
    const go=node("button","routine-chip","▶ Resume actions");
    go.addEventListener("click",async()=>{go.disabled=true;try{const r=await api("/api/control",{action:"resume"});renderPause(r.actions_paused);refreshToday();}catch(e){error(e.message);go.disabled=false;}});
    row.append(go);$("today-alerts").prepend(row);
  }
  const cut=t.interrupted;let dismissed="";try{dismissed=sessionStorage.getItem("chutku-dismissed")||"";}catch{}
  if(cut&&String(cut.started)!==dismissed){
    const row=node("div","alert interrupted");row.append(node("strong","","Interrupted"),node("span","",`Chutku stopped while doing: “${cut.goal}”. Nothing was retried automatically.`));
    const retry=node("button","routine-chip","↻ Retry"),hide=node("button","routine-chip ghost","Dismiss");
    retry.addEventListener("click",()=>{row.remove();try{sessionStorage.setItem("chutku-dismissed",String(cut.started));}catch{}ask(cut.goal);});
    hide.addEventListener("click",()=>{row.remove();try{sessionStorage.setItem("chutku-dismissed",String(cut.started));}catch{}});
    row.append(retry,hide);$("today-alerts").prepend(row);
  }
  const sug=$("today-suggestions");if(sug){sug.replaceChildren();(t.suggestions||[]).forEach(s=>{
    const row=node("div","alert suggestion");row.append(node("strong","","Suggestion"),node("span","",s.text));
    const yes=node("button","routine-chip","✓ Yes"),later=node("button","routine-chip ghost","Not now");
    const answer=async(action)=>{row.remove();try{await api("/api/suggestions",{id:s.id,action});}catch(e){error(e.message);}};
    yes.addEventListener("click",()=>{answer("accept");ask(s.command);});later.addEventListener("click",()=>answer("dismiss"));
    row.append(yes,later);sug.append(row);});}
  const routineRow=$("routines");routineRow.replaceChildren(node("span","tile-label","Routines"));
  (t.routines||[]).forEach(r=>{const b=node("button","routine-chip","▶ "+r.name+" mode");b.title=r.commands.join(" · ");b.addEventListener("click",()=>ask("start "+r.name+" mode"));routineRow.append(b);});
  const add=node("button","routine-chip ghost","+ New routine");add.addEventListener("click",()=>{$("chat-input").value="save routine work: open visual studio code, play lofi hip hop on youtube, set volume to 30";$("chat-input").focus();});routineRow.append(add);
  $("today-greeting").textContent=t.greeting+".";$("today-date").textContent=t.date;
  const w=t.weather;
  if(!w)tile("tile-weather",node("div","tile-sub","Loading the forecast…"));
  else if(w.error)tile("tile-weather",node("div","tile-sub",w.error.includes("city")?"Say “remember city = Delhi” once to see your weather here.":w.error));
  else tile("tile-weather",node("div","tile-big",Math.round(w.temperature_c)+"°"),node("div","",w.sky||""),
    node("div","tile-sub",(w.today?`${Math.round(w.today.min_c)}° – ${Math.round(w.today.max_c)}°`+(w.today.rain_chance_percent!=null?` · rain ${w.today.rain_chance_percent}%`:""):"")+" · "+(w.place||"").split(",")[0]));
  const drives=node("div");(t.disk.drives||[]).forEach(d=>{const row=node("div");const used=100-d.free_percent;
    row.append(node("div","",`${d.drive[0]}:  ${d.free_gb} GB free of ${Math.round(d.total_gb)} GB`));
    const bar=node("div","bar"+(d.low?" low":""));const fill=node("i");fill.style.width=used+"%";bar.append(fill);row.append(bar);drives.append(row);});
  tile("tile-disk",drives,...(t.disk.low_space.length?[node("div","warn-text","Low space on "+t.disk.low_space.join(", "))]:[]));
  const n=t.notes||{open:0,items:[]};
  tile("tile-notes",n.items.length?list(n.items.map(i=>[i.text,"#"+i.id])):node("div","tile-sub","Nothing to do. Try “note: buy milk”."),
    ...(n.open>n.items.length?[node("div","tile-sub",`+${n.open-n.items.length} more`)]:[]));
  tile("tile-reminders",t.reminders.length?list(t.reminders.map(r=>[r.message,new Date(r.at).toLocaleString([], {weekday:"short",hour:"numeric",minute:"2-digit"})])):node("div","tile-sub","Nothing scheduled. Try “remind me in 20 minutes to stretch”."));
  tile("tile-recent",t.recent_files.length?list(t.recent_files.slice(0,5).map(f=>[f.name,f.modified.slice(11)])):node("div","tile-sub",t.recent_scope.length?"No changes in the last 3 days.":"Grant access to your user folders to see recent work."));
  const c=t.chutku_today;
  tile("tile-chutku",node("div","tile-big",String(c.done)),node("div","tile-sub",`actions done · ${c.refused} refused`+(c.log_intact?"":" · LOG DAMAGED")),
    list(c.latest.slice(0,3).map(a=>[TOOL_WORDS[a.tool]||a.tool,a.state==="COMPLETED"?"✓":a.state==="DENIED"?"⛔":"…"])));
}
async function refreshToday(){try{renderToday(await api("/api/today"));}catch{}}
tickClock();setInterval(tickClock,15000);setInterval(refreshToday,60000);
refresh().then(()=>{if(startTab&&labels[startTab])switchTab(startTab);refreshToday();setTimeout(refreshToday,4000);setTimeout(pollHandsfree,1500);}).catch(e=>{$("connection").textContent="Session unavailable";error(e.message);});
