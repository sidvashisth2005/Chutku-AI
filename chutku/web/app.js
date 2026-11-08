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
const labels={board:"Board",automations:"Automations",settings:"Settings",phone:"Phone",voicelock:"Voice lock",skills:"Skills I learned",reliability:"Reliability",mind:"Mind map",home:"Home",memory:"Memory",history:"Activity",capabilities:"Capabilities",verification:"Verification"};
const MODE_HELP={
  review:"Review: every step waits for your click before it runs.",
  auto_safe:"Auto (safe): looking, opening apps/files/sites and other easily reversible steps run by themselves. File changes and anything risky wait for your click.",
  auto_edits:"Auto (incl. edits): also runs file changes that Chutku can undo. Deleting, sending, closing apps, power and anything after reading untrusted content still wait for your click.",
  owner:"Owner (no approvals): everything runs by itself, including messages to people in your memory. Asks only for file changes, any deletion, shutdown/killing programs, messages to someone new, and steps right after reading web pages or messages."};
const TERMINAL=new Set(["done","clarify","failed","stopped","cancelled"]);

function error(message){$("error-banner").textContent=message;$("error-banner").hidden=!message;
  const ob=$("onboarding");if(ob&&!ob.hidden&&message){let line=ob.querySelector(".err-line");if(!line){line=node("div","err-line");const acts=ob.querySelector(".onboarding-actions");if(acts)acts.before(line);else ob.append(line);}line.className="err-line";line.textContent=message;}}
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
function switchTab(id){if(id==="board")loadBoard();if(id==="automations")loadAutomations();if(id==="settings")loadSetup();if(id==="phone")loadPhone();if(id==="mind")loadMind();if(id==="reliability")loadReliability();if(id==="skills")loadSkills();if(id==="voicelock")loadVoiceLock();document.querySelectorAll(".view").forEach(e=>e.hidden=e.id!==id);document.querySelectorAll(".nav-item").forEach(e=>e.classList.toggle("active",e.dataset.tab===id));$("page-label").textContent=labels[id];}
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
      if(step.trust)row.append(node("span","step-trust"+(step.low_trust?" weak":""),step.trust+" ✓"));
      if(step.task_id){const t=node("button","text-button","trace");t.addEventListener("click",()=>showTrace(step.task_id));row.append(t);}
      list.append(row);});
    bubble.append(list);
  }
  if(s.reply&&(TERMINAL.has(s.status)||s.status==="waiting_confirmation"||s.status==="running"))bubble.append(node("p","reply",s.reply));
  if(s.context_chars&&TERMINAL.has(s.status)){   // H29 context gauge: what the brain read, part by part
    const parts=Object.entries(s.context_chars).filter(([,n])=>n>2).sort((a,b)=>b[1]-a[1]),total=parts.reduce((t,[,n])=>t+n,0);
    const gauge=node("details","brain-view");gauge.append(node("summary","small-title","Brain view: "+total.toLocaleString()+" characters"));
    parts.forEach(([k,n])=>gauge.append(node("div","small",k+": "+n.toLocaleString()+" ("+Math.round(100*n/Math.max(total,1))+"%)")));
    bubble.append(gauge);}
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

async function ask(message,stay){   // stay: the Memory tab saves a note without jumping to Home (2026-11-08)
  if(busy||!message.trim())return;error("");if(!stay)switchTab("home");userBubble(message);
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
  $("wake-state").textContent=h.wake_error?"Microphone problem":h.wake_listening?"Listening for “Oye Chutku”":"Wake phrase off";
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
async function loadReliability(){
  try{
    const {rows}=await api("/api/reliability");const box=$("reliability-table");box.replaceChildren();
    if(!rows.length){box.append(node("p","muted","Nothing measured yet: steps that change something are counted as they run."));return;}
    const table=node("table","reliability");const head=node("tr");["Action","On","Worked","Rate","Lower bound"].forEach(h=>head.append(node("th","",h)));table.append(head);
    rows.forEach(r=>{const tr=node("tr",r.lower_bound!==null&&r.lower_bound<0.7&&r.trials-r.passes>=2?"weak":"");
      [r.tool,r.target,`${r.passes}/${r.trials}`,Math.round(r.rate*100)+"%",r.lower_bound===null?"–":r.lower_bound.toFixed(2)].forEach(v=>tr.append(node("td","",String(v))));table.append(tr);});
    box.append(table);
  }catch(e){error(e.message);}
}
function pct(v){return v===null||v===undefined?"–":Math.round(v*100)+"%";}
async function loadSkills(data){
  try{
    const s=data||await api("/api/reflexes");const box=$("skills-table");box.replaceChildren();
    box.append(node("p","muted",`Instant answers this week: ${pct(s.instant_this_week)} (last week ${pct(s.instant_last_week)}).`));
    if(!s.skills.length){box.append(node("p","muted","Nothing learned yet."));return;}
    const table=node("table","reliability");const head=node("tr");["Phrase","Steps","Examples","Worked",""].forEach(h=>head.append(node("th","",h)));table.append(head);
    s.skills.forEach(k=>{const tr=node("tr",k.enabled?"":"weak");
      [k.phrase,k.tools.join(" → "),k.examples.join(" · "),`${k.passes}/${k.hits}`+(k.enabled?"":" (off: "+k.disabled_reason+")")].forEach(v=>tr.append(node("td","",String(v))));
      const cell=node("td"),b=node("button","text-button",k.enabled?"Switch off":"Switch on");
      b.addEventListener("click",async()=>{try{await loadSkills(await api("/api/reflexes",{id:k.id,enabled:!k.enabled}));}catch(e){error(e.message);}});
      cell.append(b);tr.append(cell);table.append(tr);});
    box.append(table);
  }catch(e){error(e.message);}
}
async function loadVoiceLock(action){
  const box=$("voicelock-panel");
  try{
    if(action==="clip")box.prepend(node("p","muted","Listening… read the highlighted line now."));
    const s=await api("/api/voice/enroll",{action:action||"status"});box.replaceChildren();
    box.append(node("p","",`Lock: ${s.voice_lock?"on":"off"} · Voice enrolled: ${s.enrolled?"yes":"no"} · Threshold ${s.threshold}`));
    if(s.learning&&s.enrolled)box.append(node("p","muted",`Learned from your voice ${s.learning.adapted||0} times`+(s.learning.refused?` (${s.learning.refused} updates refused: too far from your enrollment)`:"")+"."));
    if(s.learned!==undefined)box.append(node("p","",s.learned?"Thanks: Chutku learned that voice as yours.":"Not learned: that voice is too different from your enrollment. Re-enroll if your voice really changed."));
    if(s.ok===false)box.append(node("p","muted",`Only ${s.heard_seconds} s of speech heard; read it again a little louder.`));
    if(s.enrolled_with)box.append(node("p","",`Enrolled with ${s.enrolled_with} clips.`));
    const list=node("ol");s.lines.forEach((l,i)=>{const li=node("li",i===s.clips?"current":"",l);if(i<s.clips)li.append(node("span","muted"," ✓"));list.append(li);});box.append(list);
    const row=node("div","approval-actions");
    const add=(label,act,cls)=>{const b=node("button",cls||"text-button",label);b.addEventListener("click",()=>loadVoiceLock(act));row.append(b);};
    if(s.clips<s.lines.length)add(`Record line ${s.clips+1}`,"clip","primary");
    if(s.clips>=6)add("Finish enrollment","finish","primary");
    if(s.clips)add("Start over","reset");
    if(s.enrolled)add(s.voice_lock?"Turn lock off":"Turn lock on",s.voice_lock?"lock_off":"lock_on");
    if(s.rejected_waiting)add(`That was me (score ${s.rejected_score})`,"that_was_me","primary");
    box.append(row);
  }catch(e){error(e.message);}
}
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
    const forget=node("button","danger","Forget");forget.setAttribute("aria-label","Forget "+m.key);forget.addEventListener("click",()=>forgetNote(m.key));row.append(text,forget);area.append(row);
  });if(!area.childNodes.length)area.append(node("p","empty-note","No matching notes. Save something you'd like to remember."));$("memory-count").textContent=state.memories.length;
}
// 2026-11-08: Forget used to send a chat command, jump to Home and leave its approval card there. Now the question is
// asked here, and the user's "OK" is the approval that deleting always needs.
async function forgetNote(key){
  if(!confirm(`Forget “${key}”? Chutku will no longer remember it.`))return;
  try{const r=await api("/api/chat",{message:"forget "+key,mode:currentMode()});const res=r.result||{};
    if(res.state==="WAITING_CONFIRMATION"&&res.approval)await api("/api/approve",{token:res.approval.token});
    await refresh();}catch(e){error(e.message);}
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
  $("grants-summary").textContent="File access: "+(roots.join("  ")||"sandbox only")+" · system folders are read-only";
  renderPause(state.actions_paused);renderHistory();renderMemories();renderCapabilities();
  $("stop-core").hidden=!state.guard_active;$("guard-status").textContent=state.guard_active?"GUARD ACTIVE · Ctrl+Alt+F12 or Stop Chutku stops everything":"GUARD INACTIVE · Launch with Start-Chutku.cmd for the independent emergency stop";
  renderVerification(state.verification);renderHandsfree(state.handsfree);
  if(state.handsfree&&state.handsfree.latest_session)seenSessions.add(state.handsfree.latest_session);
}
$("stop-core").addEventListener("click",async()=>{try{await api("/api/control",{action:"stop"});}catch{}$("connection").textContent="Emergency stop requested";error("Independent stop requested. Restart Chutku and inspect Activity before resuming. Completed effects may remain.");});
$("pause-actions").addEventListener("click",async()=>{try{const result=await api("/api/control",{action:$("pause-note").hidden?"pause":"resume"});renderPause(result.actions_paused);}catch(e){error(e.message);}});
$("memory-form").addEventListener("submit",async e=>{e.preventDefault();await ask("remember "+$("memory-key").value+" = "+$("memory-value").value,true);$("memory-key").value="";$("memory-value").value="";});
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
  const night=c.night?node("div","tile-sub",c.night):node("span");
  const instant=c.instant&&c.instant.this_week!==null?node("div","tile-sub",`Instant answers this week: ${pct(c.instant.this_week)} (last week ${pct(c.instant.last_week)})`):node("span");
  tile("tile-chutku",node("div","tile-big",String(c.done)),node("div","tile-sub",`actions done · ${c.refused} refused`+(c.log_intact?"":" · LOG DAMAGED")),instant,night,
    list(c.latest.slice(0,3).map(a=>[TOOL_WORDS[a.tool]||a.tool,a.state==="COMPLETED"?"✓":a.state==="DENIED"?"⛔":"…"])));
}
async function refreshToday(){try{renderToday(await api("/api/today"));}catch{}}
tickClock();setInterval(tickClock,15000);setInterval(refreshToday,60000);
refresh().then(()=>{if(startTab&&labels[startTab])switchTab(startTab);refreshToday();setTimeout(refreshToday,4000);setTimeout(pollHandsfree,1500);}).catch(e=>{$("connection").textContent="Session unavailable";error(e.message);});

// ---- W4: Chutku's live phase colours the command center (brand orb, accents) ----
async function pollPhase(){
  try{const p=await api("/api/presence");document.body.dataset.phase=p.phase;}catch{}
  setTimeout(pollPhase,1000);
}
pollPhase();
$("open-presence")?.addEventListener("click",()=>{window.open("/presence#token="+encodeURIComponent(sessionToken),"chutku-presence","width=380,height=620");});


// ---- W6: the Phone panel (phone access through the owner's tailnet) ----
async function loadPhone(){
  try{
    const r=await api("/api/remote");
    $("phone-state").textContent=r.available===false?"Phone access runs inside the real Chutku only.":
      (r.enabled?`On · ${r.url||""}`:"Off")+(r.phone_active?" · 📱 phone connected":"")+(r.viewing?" · screen being watched":"")+(r.controlling?" · CONTROLLED FROM PHONE":"")+(r.control_allowed?" · control allowed":" · control forbidden");
    showBoot(r.boot);loadTelegram();
    const list=$("phone-devices");list.replaceChildren();
    for(const d of (r.devices||[]).filter(d=>!d.revoked)){
      const row=node("div","activity-row"),name=node("div","activity-title",d.name),rm=node("button","text-button danger-text","Remove");
      rm.addEventListener("click",async()=>{await phoneAction({action:"revoke",device_id:d.id});});
      row.append(name,rm);list.append(row);
    }
    if(!list.children.length)list.append(node("p","muted","No phone paired yet."));
  }catch(e){error(e.message);}
}
async function phoneAction(body){
  try{const r=await api("/api/remote",body);
    if(body.action==="pair"){
      const box=$("phone-pairing");box.replaceChildren();
      if(r.error){box.append(node("p","muted",r.error));}
      else showPairing(r);
    } else if(r.steps){ $("phone-state").textContent=r.steps; return; }
    loadPhone();
  }catch(e){error(e.message);}
}
// Owner 2026-11-08, "a cakewalk": one button. Each press (and a repeat every 3 s) does the next missing step: install
// Tailscale, sign in, turn phone access on, then the code to scan with three plain steps for the phone.
let connecting=null;
function showPairing(r){
  const box=$("phone-pairing");box.replaceChildren();
  box.append(node("h2","","Code: "+r.code));
  if(r.phone_steps){const ol=node("ol","muted");r.phone_steps.forEach(t=>ol.append(node("li","",t)));box.append(ol);}
  box.append(node("p","muted",`Or open ${r.link} on the phone (valid ${r.minutes} minutes).`));
  appendQr(box,r.qr_svg);
}
function appendQr(box,text){
  if(text){const svg=new DOMParser().parseFromString(text,"image/svg+xml").documentElement;if(svg&&svg.nodeName==="svg"){svg.setAttribute("width","220");svg.setAttribute("height","220");box.append(document.importNode(svg,true));}}
}
// 2026-11-08 Telegram without a terminal: BotFather, paste the token (checked with Telegram, never shown again), then
// scan a code so the phone's Telegram pairs itself (t.me/<bot>?start=CODE); typing /pair CODE still works.
async function loadTelegram(){
  const box=$("tg-box");if(!box)return;
  let r;try{r=await api("/api/telegram",{action:"status"});}catch(e){box.replaceChildren(node("p","muted",e.message));return;}
  box.replaceChildren();
  if(!r.token_stored){
    const ol=node("ol","muted"),first=node("li","","Open "),a=node("a","","@BotFather");a.href="https://t.me/BotFather";a.target="_blank";a.rel="noopener noreferrer";
    first.append(a," in Telegram (on the phone or here).");
    ol.append(first,node("li","","Send /newbot, then any name, then a username that ends in \"bot\"."),node("li","","Copy the token it sends you (numbers:letters) and paste it here."));
    const input=node("input");input.type="password";input.placeholder="123456789:ABC...";input.autocomplete="off";input.id="tg-token";
    box.append(ol,input,button("Connect bot",async()=>{await api("/api/telegram",{action:"token",token:input.value.trim()});input.value="";await loadTelegram();await pairTelegram();},"primary"));
    return;
  }
  box.append(node("p","",(r.bot?`Bot @${r.bot}`:"Bot connected")+(r.paired?" · your phone's chat is paired.":" · not paired with your phone yet.")));
  const row=node("div","row-buttons");
  row.append(button(r.paired?"Pair a different phone":"Pair my phone",pairTelegram,r.paired?"":"primary"));
  if(r.paired)row.append(button("Unpair",async()=>{await api("/api/telegram",{action:"unpair"});$("tg-pair").replaceChildren();loadTelegram();}));
  box.append(row);
}
let tgWaiting=null;
async function pairTelegram(){
  const r=await api("/api/telegram",{action:"pair"}),box=$("tg-pair");box.replaceChildren();
  if(r.link){box.append(node("p","","Scan this with your phone's camera (or open the link there), then press Start in Telegram."));appendQr(box,r.qr_svg);
    const a=node("a","",r.link);a.href=r.link;a.target="_blank";a.rel="noopener noreferrer";box.append(a);}
  box.append(node("p","muted",`Or send /pair ${r.code} to your bot (valid ${r.valid_minutes} minutes).`));
  clearTimeout(tgWaiting);const until=Date.now()+r.valid_minutes*60000;
  const wait=async()=>{try{if((await api("/api/telegram",{action:"status"})).paired){box.replaceChildren(node("p","","Paired. Send your bot a message to try it."));loadTelegram();return;}}catch{}
    if(Date.now()<until)tgWaiting=setTimeout(wait,3000);};
  tgWaiting=setTimeout(wait,3000);
}
// 2026-11-08 "Reach this laptop after a restart": one Windows prompt runs the setup (or its removal); the state is
// what Chutku can see without admin rights: the boot notice's log and the lock-screen helper answering.
function showBoot(b){const s=$("boot-state");if(!s||!b)return;
  s.textContent=!b.available?"This copy of Chutku has no boot-access files.":(b.on?"On.":"Off.")+(b.last?" Last boot notice: "+b.last:"");}
function watchBoot(on,until=Date.now()+180000){
  setTimeout(async()=>{try{const r=await api("/api/remote");if(r.boot&&r.boot.on===on){showBoot(r.boot);return;}}catch{}
    if(Date.now()<until)watchBoot(on,until);else $("boot-state").textContent+=" Nothing changed yet: if you clicked No, press the button again.";},3000);
}
for(const [id,on] of [["boot-on",true],["boot-off",false]])
  $(id)?.addEventListener("click",async()=>{try{const r=await api("/api/remote",{action:on?"boot_on":"boot_off"});$("boot-state").textContent=r.message;if(r.started)watchBoot(on);}catch(e){error(e.message);}});
async function connectPhone(started=Date.now()){
  clearTimeout(connecting);
  try{
    const r=await api("/api/remote",{action:"connect"});
    if(r.stage==="ready"){$("phone-state").textContent="Phone access is on. Scan the code with your phone.";showPairing(r);loadPhone();return;}
    const box=$("phone-pairing");box.replaceChildren(node("p","",r.message||""));
    if(r.url){const a=node("a","",r.stage==="sign_in"?"Open the sign-in page":"Open the download page");a.href=r.url;a.target="_blank";a.rel="noopener noreferrer";box.append(a);}
    if(r.stage!=="problem"&&Date.now()-started<15*60000)connecting=setTimeout(()=>connectPhone(started),3000);
  }catch(e){error(e.message);}
}
$("phone-connect")?.addEventListener("click",()=>connectPhone());
for(const [id,action] of [["phone-disable","disable"],["phone-pair","pair"],["phone-arm","arm"],["phone-disarm","disarm"]])
  $(id)?.addEventListener("click",()=>phoneAction({action}));

// ---- W5: first-run setup and Settings (the same steps as `chutku.cli setup`) ----
let setupPoll=null;
function setupCard(title,help){const card=node("section","panel");card.append(node("h2","",title));if(help)card.append(node("p","muted",help));$("setup-steps").append(card);return card;}
function field(labelText,input){const wrap=node("div","grow");const label=node("label","",labelText);label.append(input);wrap.append(label);return wrap;}
function input(type,value,placeholder,max){const e=node("input");e.type=type;if(value)e.value=value;if(placeholder)e.placeholder=placeholder;if(max)e.maxLength=max;return e;}
function select(options,value){const e=node("select");options.forEach(o=>{const opt=node("option","",o);opt.value=o;if(o===value)opt.selected=true;e.append(opt);});return e;}
function button(text,onClick,kind){const b=node("button",kind||"",text);b.type="button";b.addEventListener("click",async()=>{b.disabled=true;try{await onClick();}catch(e){error(e.message);}finally{b.disabled=false;}});return b;}
async function setupStep(data){error("");const s=await api("/api/setup",data);renderSetup(s);return s;}
async function loadSetup(){try{renderSetup(await api("/api/setup"));}catch(e){error(e.message);}}
// Settings (after the first-run onboarding below). Owner 2026-11-08: a new user goes through the guided setup first
// and cannot skip the AI key; Settings is where everything is changed later.
function details(summary,open){const d=node("details");d.open=!!open;d.append(node("summary","",summary));return d;}
function renderSetup(s){
  if(!s.done){showOnboarding(s);return;}
  const box=$("setup-steps");box.replaceChildren();
  $("setup-eyebrow").textContent="Settings";
  $("setup-title").textContent="Settings";
  $("setup-subtitle").textContent="Change anything here at any time. Keys go to Windows Credential Manager and are never shown again.";
  const done=k=>s.steps&&s.steps[k]?" ✓":"";
  const a=s.assistant||{},name=a.ASSISTANT_NAME||"Chutku",hasKey=!!(s.keys_stored.groq||s.keys_stored.gemini);
  // 1. the free brain key
  let card=setupCard("1. Free brain key"+(hasKey?" ✓":""),hasKey?"A key is stored: Chutku is ready. You can add another one here.":"Chutku needs one free key to think fast. It takes a minute:");
  if(!hasKey){const ol=node("ol","muted");["Press “Get a free key”: it opens Groq. Sign in with Google.","Press “Create API Key”, then copy the key.","Paste it below and press Save."].forEach(t=>ol.append(node("li","",t)));card.append(ol);}
  const links=node("p","muted");const getKey=node("a","",hasKey?"Get another free key":"Get a free key");getKey.href=s.links.groq;getKey.target="_blank";getKey.rel="noopener noreferrer";
  const other=node("a","","(or a Gemini key)");other.href=s.links.gemini;other.target="_blank";other.rel="noopener noreferrer";links.append(getKey," ",other);card.append(links);
  const key=input("password","","Paste the key (starts with gsk_ or AIza)",200);key.autocomplete="off";
  const r1=node("div","memory-form");r1.append(field("Key",key),button("Check and save",async()=>{const k=key.value.trim();if(!k)throw new Error("Paste the key first.");await setupStep({action:"key",provider:providerOf(k),key:k});},"primary"));card.append(r1);
  card.append(node("p","muted",`Stored: Groq ${s.keys_stored.groq?"✓":"—"} · Gemini ${s.keys_stored.gemini?"✓":"—"}. Keys go to Windows Credential Manager and are never shown again.`));
  // 2. the owner's name
  card=setupCard("2. Your name (optional)"+done("name"),"So it can greet you by name.");
  const you=input("text","","Your name",60);const r2=node("div","memory-form");r2.append(field("What should it call you?",you),button("Save",()=>setupStep({action:"name",name:you.value}),"primary"));card.append(r2);
  // 3. its name and voice: already set
  card=setupCard("3. Its name and voice (optional)"+done("assistant"),`Ready as “${name}” (${a.ASSISTANT_GENDER||"female"}, ${a.ASSISTANT_LANGUAGE||"hinglish"}, ${a.ASSISTANT_STYLE||"warm"}). Say “Oye ${name}” or press Ctrl+Alt+Space.`);
  const nm=input("text",a.ASSISTANT_NAME,"Chutku",20),g=select(["female","male","neutral"],a.ASSISTANT_GENDER),l=select(["hinglish","english","hindi"],a.ASSISTANT_LANGUAGE),st=select(["warm","professional","witty","calm"],a.ASSISTANT_STYLE);
  const change=details("Change");const row=node("div","memory-form");row.append(field("Name",nm),field("Gender",g),field("Language",l),field("Style",st),button("Save",()=>setupStep({action:"assistant",ASSISTANT_NAME:nm.value,ASSISTANT_GENDER:g.value,ASSISTANT_LANGUAGE:l.value,ASSISTANT_STYLE:st.value}),"primary"));change.append(row);card.append(change);
  // 4. how much it does alone: this install's own default is the one marked "(recommended)" and listed first
  card=setupCard("4. How much it does on its own"+done("mode"),"Already set. Change it any time.");
  const short={auto_safe:"safe",auto_edits:"edits",owner:"full"},best=short[s.default_mode]||"safe";
  const modes=[["safe","Safe: looks and opens things by itself; asks before any change."],["edits","Edits: also changes files it can undo; asks before the rest."],["full","Full: does almost everything; still asks for deletes, risky steps and new people."]]
    .map(([value,text])=>[value,value===best?text.replace(":"," (recommended):"):text]).sort((x,y)=>(y[0]===best)-(x[0]===best));
  const current=short[s.mode]||best;
  modes.forEach(([value,text])=>{const label=node("label","radio");const r=node("input");r.type="radio";r.name="setup-mode";r.value=value;r.checked=value===current;r.addEventListener("change",()=>setupStep({action:"mode",mode:value}).catch(e=>error(e.message)));label.append(r," "+text);card.append(label);});
  // 5. microphone
  card=setupCard("5. Microphone check (optional)"+done("microphone"),"Press the button and speak for one second. The sound is measured, never kept.");
  const meter=node("progress");meter.max=100;meter.value=0;const heard=node("span","muted");
  card.append(button("Test the microphone",async()=>{const r=await api("/api/setup",{action:"mic"});meter.value=Math.min(100,Math.round((r.microphone.peak||0)*400));heard.textContent=r.microphone.heard?"Heard you.":"Very quiet: check Windows Settings > Sound > Input.";}),meter,heard);
  // 6. the phone: Tailscale and a QR code in the Phone panel (the account relay is for people who run their own server)
  card=setupCard("6. Use it from your phone (optional)"+done("phone"),s.phone_account?`Phone account: ${s.phone_account}`:"See the laptop's screen, control it, share files and talk to Chutku from your phone. The Phone panel sets up Tailscale (free) and shows a QR code to scan.");
  card.append(button("Set up my phone",()=>{switchTab("phone");connectPhone();},"primary"));
  const adv=details("Advanced: link through your own relay server");
  const relay=input("url","","https://your-relay.example",200),id=input("text","","ID",32),pw=input("password","","Password (8+)",128),pin=input("password","","Phone PIN (4-6 digits)",6),fresh=node("input");fresh.type="checkbox";
  const r6=node("div","memory-form");const nl=node("label","","New account ");nl.append(fresh);
  r6.append(field("Relay",relay),field("ID",id),field("Password",pw),field("PIN",pin),nl,button("Link phone",async()=>{await setupStep({action:"phone",relay:relay.value,id:id.value,password:pw.value,pin:pin.value,new:fresh.checked});pw.value="";pin.value="";}));adv.append(r6);card.append(adv);
  // 7. websites that need a login
  card=setupCard("7. Websites that need your login (optional)"+done("browser"),"Opens a browser window: sign in once to sites like WhatsApp Web or Gmail, and Chutku can use them for you.");
  card.append(button("Open the sign-in browser",()=>setupStep({action:"browser_login"})));
  // 8. offline packs
  let downloading=false;const packs=Object.entries(s.packs||{});
  packs.forEach(([,p])=>{if(p.state==="downloading")downloading=true;});
  card=setupCard("8. Work without internet (optional)"+done("packs"),"Downloads resume if interrupted and are checked against their pinned SHA-256; a file that does not match is deleted.");
  const offline=details("Offline packs",downloading);
  for(const [packName,p] of packs){
    const line=node("div","row-buttons");line.append(node("strong","",`${p.label} (about ${p.about_gb} GB)`));
    if(p.state==="installed")line.append(badge("installed","ok"));
    else if(p.state==="downloading"){const bar=node("progress");bar.max=p.total||1;bar.value=p.done||0;line.append(bar,node("span","muted",`${Math.round((p.done||0)/1e6)} MB${p.total?" of "+Math.round(p.total/1e6)+" MB":""}`));}
    else{if(p.state==="failed")line.append(badge("failed: "+(p.error||""),"warn"));line.append(button("Download",()=>setupStep({action:"download",pack:packName})));}
    offline.append(line);
  }
  card.append(offline);
  clearTimeout(setupPoll);if(downloading)setupPoll=setTimeout(loadSetup,2000);
  aboutCard();
  const end=node("div","row-buttons");
  end.append(button("Run the first-run setup again",()=>setupStep({action:"reopen"})));
  box.append(end);
}
// ---- First-run onboarding (owner 2026-11-08) ----
// "Don't let a new user jump into the app without their API key": a full-screen, step-by-step setup. The key is
// checked with the provider before it is kept, and the server refuses "finish" without one. It ends with a short
// celebration and the developer's name, then opens the app.
const SVG_NS="http://www.w3.org/2000/svg";
function svgIcon(paths){const svg=document.createElementNS(SVG_NS,"svg");svg.setAttribute("viewBox","0 0 24 24");svg.setAttribute("aria-hidden","true");
  for(const d of paths){const p=document.createElementNS(SVG_NS,"path");p.setAttribute("d",d);svg.append(p);}return svg;}
function providerOf(key){
  if(key.startsWith("AIza"))return "gemini";
  if(key.startsWith("gsk_"))return "groq";
  throw new Error("That doesn't look like a Groq key (starts with gsk_) or a Google key (starts with AIza). Copy the whole key again.");
}
const onboarding={s:null,step:"welcome",name:"",shown:false};
const OB_STEPS=["key","you","mic"];
function obCard(stepName){
  const box=$("onboarding"),card=node("div","onboarding-card");box.replaceChildren(card);
  if(OB_STEPS.includes(stepName)){
    const bar=node("div","onboarding-progress");OB_STEPS.forEach((k,i)=>{const seg=node("i");if(i<=OB_STEPS.indexOf(stepName))seg.className="on";bar.append(seg);});
    card.append(bar,node("div","onboarding-step",`Step ${OB_STEPS.indexOf(stepName)+1} of ${OB_STEPS.length}`));
  }
  return card;
}
function obActions(card,back,primaryText,onPrimary){
  const row=node("div","onboarding-actions");
  if(back)row.append(button("Back",back));
  row.append(node("span","grow"));
  const go=button(primaryText,onPrimary,"primary");row.append(go);card.append(row);return go;
}
function obFoot(card){const foot=node("div","onboarding-foot");const by=node("span","","Designed and developed by ");by.append(node("strong","","Siddhant Vashisth"));foot.append(by,node("span","","Your data stays on this PC"));card.append(foot);}
function showOnboarding(s){
  onboarding.s=s;
  if(!onboarding.shown){onboarding.shown=true;onboarding.step="welcome";}
  $("onboarding").hidden=false;document.body.classList.add("onboarding-open");
  ({welcome:obWelcome,key:obKey,you:obYou,mic:obMic}[onboarding.step]||obWelcome)();
}
function obGo(step){onboarding.step=step;showOnboarding(onboarding.s);}
function obWelcome(){
  const card=obCard("welcome");
  card.append(node("div","onboarding-logo"),node("h1","","Namaste! I'm Chutku."),
    node("p","","Your voice assistant for Windows. Tell me what you need in English, Hindi or Hinglish, and I'll do it on this PC, then tell you honestly how it went."));
  const list=node("div","feature-list");
  [[["M12 3a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z","M5 11a7 7 0 0 0 14 0M12 18v3"],"Talk or type","Press Ctrl+Alt+Space anywhere, or say “Oye Chutku”."],
   [["M12 3 4 6v6c0 4.5 3.4 8 8 9 4.6-1 8-4.5 8-9V6z","m8.5 12 2.5 2.5 4.5-5"],"Safe by design","I ask before anything serious, and deleted files go to the Recycle Bin."],
   [["M3 12h4l3-8 4 16 3-8h4"],"Takes about 2 minutes","One free AI key is all I need. I'll show you how to get it."]]
    .forEach(([paths,title,text])=>{const row=node("div");const t=node("div");t.append(node("b","",title),text);row.append(svgIcon(paths),t);list.append(row);});
  card.append(list);
  obActions(card,null,"Let's set up",()=>obGo("key"));obFoot(card);
}
function obKey(){
  const s=onboarding.s,has=!!(s.keys_stored.groq||s.keys_stored.gemini),card=obCard("key");
  card.append(node("h1","","Add your free AI key"),
    node("p","","Chutku uses a free AI service to understand you. Getting a key takes about a minute and costs nothing."));
  const ol=node("ol");
  const first=node("li","","Click ");const get=node("a","","Get my free key");get.href=s.links.groq;get.target="_blank";get.rel="noopener noreferrer";first.append(get," and sign in with Google.");
  ol.append(first,node("li","","Click “Create API Key”, give it any name, then copy the key."),node("li","","Paste it below and click “Check key”."));
  card.append(ol);
  const f=node("div","field"),label=node("label","","Your key"),key=input("password","","Paste here (starts with gsk_)",200);key.id="ob-key";key.autocomplete="off";key.spellcheck=false;
  label.htmlFor="ob-key";f.append(label,key);
  const alt=node("div","hint","Have a Google AI Studio key instead? That works too (it starts with AIza). ");const g=node("a","","Get one here");g.href=s.links.gemini;g.target="_blank";g.rel="noopener noreferrer";alt.append(g);f.append(alt);
  const status=node("div",has?"ok-line":"err-line",has?"✓ A working key is already saved. You can continue.":"");card.append(f,status);
  const check=async()=>{
    status.className="err-line";status.textContent="";
    const k=key.value.trim();
    if(!k){if(has){obGo("you");return;}throw new Error("Paste your key first.");}
    go.textContent="Checking…";
    try{onboarding.s=await api("/api/setup",{action:"key",provider:providerOf(k),key:k});}
    catch(e){status.textContent=e.message;go.textContent="Check key";return;}
    key.value="";status.className="ok-line";status.textContent="✓ Your key works. Chutku is connected.";
    setTimeout(()=>obGo("you"),700);
  };
  const go=obActions(card,()=>obGo("welcome"),has?"Continue":"Check key",check);
  key.addEventListener("input",()=>{go.textContent=key.value.trim()?"Check key":(has?"Continue":"Check key");});
  key.addEventListener("keydown",e=>{if(e.key==="Enter")go.click();});
  error("");obFoot(card);setTimeout(()=>key.focus(),50);
}
function obYou(){
  const s=onboarding.s,card=obCard("you");
  card.append(node("h1","","A little about you"),node("p","","Both are optional and you can change them any time in Settings."));
  const f=node("div","field"),label=node("label","","What should Chutku call you?"),you=input("text",onboarding.name,"Your name",60);you.id="ob-name";label.htmlFor="ob-name";f.append(label,you);card.append(f);
  card.append(node("label","","How much should Chutku do on her own?"));
  const short={auto_safe:"safe",auto_edits:"edits",owner:"full"},best=short[s.default_mode]||"safe";let chosen=short[s.mode]||best;
  [["safe","Safe","Looks and opens things by herself; asks before any change."],["edits","Edits","Also changes files she can undo; asks before the rest."],["full","Full","Does almost everything; still asks before deleting, risky steps and new people."]]
    .sort((x,y)=>(y[0]===best)-(x[0]===best)).forEach(([value,title,text])=>{
      const l=node("label","radio");const r=node("input");r.type="radio";r.name="ob-mode";r.value=value;r.checked=value===chosen;r.addEventListener("change",()=>{chosen=value;});
      const t=node("span");t.append(node("b","",title+(value===best?" (recommended)":"")),node("br"),node("span","muted",text));l.append(r,t);card.append(l);});
  obActions(card,()=>obGo("key"),"Continue",async()=>{
    const typed=you.value.trim();onboarding.name=typed;
    if(typed)onboarding.s=await api("/api/setup",{action:"name",name:typed});
    if(chosen!==(short[s.mode]||best)||!(s.steps&&s.steps.mode))onboarding.s=await api("/api/setup",{action:"mode",mode:chosen});
    obGo("mic");
  });
  obFoot(card);
}
function obMic(){
  const card=obCard("mic");
  card.append(node("h1","","Check your microphone"),node("p","","Click the button and say something for a second. The sound is only measured, never recorded or kept."));
  const meter=node("div","meter"),fill=node("i");meter.append(fill);const heard=node("div","hint","");
  card.append(button("Test my microphone",async()=>{heard.textContent="Listening…";const r=await api("/api/setup",{action:"mic"});
    fill.style.width=Math.min(100,Math.round((r.microphone.peak||0)*400))+"%";
    heard.textContent=r.microphone.heard?"✓ I can hear you.":"Very quiet. Check Windows Settings → System → Sound → Input, or skip and type instead.";}),meter,heard);
  obActions(card,()=>obGo("you"),"Finish setup",obFinish);obFoot(card);
}
async function obFinish(){
  try{onboarding.s=await api("/api/setup",{action:"finish"});}
  catch(e){onboarding.step="key";showOnboarding(onboarding.s);error(e.message);return;}
  obCelebrate();
}
function obCelebrate(){
  const card=obCard("done");card.classList.add("celebrate");
  const check=node("div","check");check.append(svgIcon(["M5 12.5 10 17 19 7"]));
  const who=onboarding.name?`, ${onboarding.name}`:"";
  card.append(check,node("h1","",`You're all set${who}!`),node("p","","Chutku is ready to help. Here's how to talk to her:"));
  const tips=node("div","tips");
  const t1=node("div");const k=node("kbd","","Ctrl");const k2=node("kbd","","Alt");const k3=node("kbd","","Space");t1.append("Press ",k," + ",k2," + ",k3," in any app and speak.");
  tips.append(t1,node("div","","Or just say “Oye Chutku”."),node("div","","Or type in the box on the Home page."));card.append(tips);
  const sig=node("div","signature","Designed and developed with care by");sig.append(node("strong","","Siddhant Vashisth"));card.append(sig);
  obActions(card,null,"Open Chutku",()=>{$("onboarding").hidden=true;$("onboarding").replaceChildren();document.body.classList.remove("onboarding-open");onboarding.shown=false;switchTab("home");if(typeof refresh==="function")refresh();checkForUpdate();});
  confetti();
}
function confetti(){
  if(matchMedia("(prefers-reduced-motion: reduce)").matches)return;
  const canvas=node("canvas");canvas.id="confetti";document.body.append(canvas);
  const ctx=canvas.getContext("2d"),dpr=window.devicePixelRatio||1;canvas.width=innerWidth*dpr;canvas.height=innerHeight*dpr;ctx.scale(dpr,dpr);
  const colors=["#d9480f","#ff7a3d","#f2b84b","#4cc38a","#2f80ed","#8a63d2"];
  const bits=Array.from({length:140},()=>({x:innerWidth/2+(Math.random()-.5)*160,y:innerHeight*0.42,vx:(Math.random()-.5)*13,vy:-Math.random()*13-4,s:5+Math.random()*6,r:Math.random()*6,vr:(Math.random()-.5)*.3,c:colors[Math.floor(Math.random()*colors.length)]}));
  const start=performance.now();
  (function frame(t){
    ctx.clearRect(0,0,innerWidth,innerHeight);
    for(const b of bits){b.vy+=.32;b.vx*=.99;b.x+=b.vx;b.y+=b.vy;b.r+=b.vr;ctx.save();ctx.translate(b.x,b.y);ctx.rotate(b.r);ctx.fillStyle=b.c;ctx.fillRect(-b.s/2,-b.s/4,b.s,b.s/2);ctx.restore();}
    if(t-start<3200)requestAnimationFrame(frame);else canvas.remove();
  })(start);
}
api("/api/setup").then(s=>{if(!s.done)showOnboarding(s);else checkForUpdate();}).catch(()=>{});

// ---- Updates and About (owner 2026-11-08: "publish an update to existing users, like a pop up") ----
function snoozed(version){try{return Number(localStorage.getItem("chutku-update-later-"+version)||0)>Date.now();}catch{return false;}}
function snooze(version){try{localStorage.setItem("chutku-update-later-"+version,String(Date.now()+24*3600e3));}catch{}}
async function checkForUpdate(){
  try{const u=await api("/api/update");
    if($("app-version"))$("app-version").textContent="Chutku "+u.current;
    if(u.available&&!u.developer_copy&&!snoozed(u.latest))showUpdate(u);
  }catch{}
}
function showUpdate(u){
  const d=$("update-dialog");d.replaceChildren();
  const head=node("div","dialog-head"),title=node("h2","","Update available");title.id="update-title";head.append(title);
  d.append(head,node("p","muted",`Chutku ${u.latest} is ready. You have ${u.current}.${u.size?` The download is about ${Math.round(u.size/1e6)} MB.`:""}`));
  if(u.notes)d.append(node("div","update-notes",u.notes.replace(/[#*_`]/g,"").replace(/\n{3,}/g,"\n\n").trim()));
  const bar=node("div","update-progress"),fill=node("i");bar.append(fill);bar.hidden=true;const status=node("p","muted","");
  const row=node("div","dialog-actions");
  const later=button("Later",()=>{snooze(u.latest);d.close();});
  const now=button("Update now",async()=>{
    later.hidden=true;now.hidden=true;bar.hidden=false;status.textContent="Downloading…";
    try{await api("/api/update",{action:"install"});}
    catch(e){status.textContent=e.message;bar.hidden=true;later.hidden=false;now.hidden=false;now.textContent="Try again";return;}
    const poll=async()=>{let j;try{j=(await api("/api/update")).job;}catch{status.textContent="Installing… Chutku closes and opens again by itself.";return;}
      if(j.state==="downloading"){fill.style.width=(j.size?Math.round(100*j.done/j.size):10)+"%";status.textContent=`Downloading… ${Math.round((j.done||0)/1e6)} MB`;}
      else if(j.state==="installing"){fill.style.width="100%";status.textContent="Installing… Chutku closes and opens again by itself in a minute.";}
      else if(j.state==="failed"){status.textContent=j.error||"The update failed.";later.hidden=false;now.hidden=false;now.textContent="Try again";return;}
      setTimeout(poll,1000);};
    poll();
  },"primary");
  row.append(later,now);d.append(bar,status,row);
  if(!d.open)d.showModal();
}
function aboutCard(){
  const card=setupCard("About Chutku","");const row=node("div","about");const logo=node("div","onboarding-logo");
  const text=node("div");const version=node("h3","","Chutku");const by=node("p","muted","Designed and developed by ");by.append(node("strong","","Siddhant Vashisth"),".");
  text.append(version,by);row.append(logo,text);card.append(row);
  const status=node("p","muted","");
  card.append(node("div","row-buttons"));
  card.lastChild.append(button("Check for updates",async()=>{status.textContent="Checking…";const u=await api("/api/update",{action:"check"});
    version.textContent="Chutku "+u.current;
    if(u.developer_copy)status.textContent="This is a developer copy: update it with git pull.";
    else if(u.available)showUpdate(u);
    else status.textContent=u.latest?`You have the newest version (${u.current}).`:"Could not reach the update server. Check your internet and try again.";}));
  card.append(status);
  api("/api/update").then(u=>{version.textContent="Chutku "+u.current;}).catch(()=>{});
}

// ---- W6: Board and Automations tabs ----
const BOARD_STATE={todo:"waiting",ready:"in line",running:"running",blocked:"stopped",review:"check it",done:"done",archived:"archived"};
let boardPoll=null;
async function loadBoard(){try{renderBoard(await api("/api/board"));}catch(e){error(e.message);}}
function renderBoard(b){
  const box=$("board-list");box.replaceChildren();clearTimeout(boardPoll);
  if(!b.tasks.length){box.append(node("p","muted","The board is empty."));return;}
  const table=node("table","reliability");const head=node("tr");["#","Task","Kind","Status",""].forEach(h=>head.append(node("th","",h)));table.append(head);
  for(const t of b.tasks.slice().reverse()){
    const tr=node("tr");tr.append(node("td","",String(t.id)),node("td","",t.title+(t.error?` (${t.error})`:"")),node("td","",t.kind==="research"?"research":"yours"),node("td","",BOARD_STATE[t.status]||t.status));
    const cell=node("td","row-buttons");
    if(b.running.includes(t.id))cell.append(button("Stop",async()=>renderBoard((await api("/api/board/stop",{id:t.id})).board),"danger"));
    if(t.kind==="owner"&&t.status!=="done")cell.append(button("Done",async()=>renderBoard(await api("/api/board",{action:"done",id:t.id}))));
    if(t.kind==="research"&&(t.status==="review"||t.status==="blocked")){cell.append(button("Looks right",async()=>renderBoard(await api("/api/board",{action:"done",id:t.id}))),button("Again",async()=>renderBoard(await api("/api/board",{action:"again",id:t.id}))));}
    if(t.status==="done")cell.append(button("Archive",async()=>renderBoard(await api("/api/board",{action:"archive",id:t.id}))));
    tr.append(cell);table.append(tr);
  }
  box.append(table);
  if(b.running.length)boardPoll=setTimeout(()=>{if(!$("board").hidden)loadBoard();},3000);
}
async function loadAutomations(){try{renderAutomations(await api("/api/automations"));}catch(e){error(e.message);}}
function renderAutomations(a){
  const active=$("automation-active");active.replaceChildren();
  if(!a.active.length)active.append(node("p","muted","None yet."));
  for(const job of a.active){const row=node("div","row-buttons");row.append(node("span","",job.summary||job.goal),button("Cancel",async()=>renderAutomations(await api("/api/automations",{action:"cancel",id:job.id})),"danger"));active.append(row);}
  const box=$("automation-catalog");box.replaceChildren();
  for(const item of a.catalog){
    const row=node("div","memory-form");row.append(node("strong","",`${item.name} (${item.every})`),node("span","muted",item.about));
    const inputs={};for(const [slot,value] of Object.entries(item.slots)){inputs[slot]=input(slot==="time"?"time":"text",value||"",value===null?"required":"",200);row.append(field(slot,inputs[slot]));}
    row.append(button("Create",async()=>{const slots={};for(const [k,e] of Object.entries(inputs))if(e.value)slots[k]=e.value;renderAutomations(await api("/api/automations",{action:"create",name:item.name,slots}));},"primary"));
    box.append(row);
  }
}
