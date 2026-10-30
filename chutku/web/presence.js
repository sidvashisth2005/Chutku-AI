"use strict";
// Chutku's presence (W4, 2026-10-29): a living orb that listens, thinks and speaks with her, live captions, and
// each step of the current task with its verified result. Reads /api/presence ~10x a second (memory only).
const $ = id => document.getElementById(id);
const fromLink = new URLSearchParams(location.hash.slice(1)).get("token");
if(fromLink){try{sessionStorage.setItem("chutku-token",fromLink);}catch{}history.replaceState(null,"",location.pathname);}
let token = fromLink || ""; try{token = token || sessionStorage.getItem("chutku-token") || "";}catch{}
const compact = new URLSearchParams(location.search).get("compact") === "1";
const LABELS = {idle:"Ready",listening:"Listening",thinking:"Thinking",running:"Working",speaking:"Speaking",
  confirm:"Needs your OK",done:"Done",clarify:"Question",error:"Problem",paused:"Paused"};
let state = {phase:"idle",mic_level:0,voice_level:0,steps:[]};
let shown = {level:0, phase:"idle"};

async function api(path, data){
  const options = {headers:{"X-Chutku-Token":token}};
  if(data!==undefined){options.method="POST";options.headers["Content-Type"]="application/json";options.body=JSON.stringify(data);}
  const response = await fetch(path, options);
  const payload = await response.json();
  if(!response.ok) throw new Error(payload.error || "failed");
  return payload;
}

// ---- the orb -------------------------------------------------------------------------------------------------
const canvas = $("orb"), ctx = canvas.getContext("2d");
const particles = Array.from({length:70}, (_, i) => ({a:Math.random()*Math.PI*2, r:0.55+Math.random()*0.4,
  s:(0.15+Math.random()*0.6)*(i%2?1:-1), z:Math.random()}));
function accent(){return getComputedStyle(document.body).getPropertyValue("--accent").trim() || "#22d3ee";}
function draw(t){
  const size = canvas.width, c = size/2, color = accent();
  const target = Math.min(1, state.phase==="speaking" ? state.voice_level : state.mic_level*14);
  shown.level += (target - shown.level) * 0.25;
  const busy = state.phase==="thinking" || state.phase==="running";
  const breathe = 0.5 + 0.5*Math.sin(t/(busy?260:900));
  ctx.clearRect(0,0,size,size);
  // halo
  const halo = ctx.createRadialGradient(c,c,size*0.08,c,c,size*0.5);
  halo.addColorStop(0, color+"55"); halo.addColorStop(0.5, color+"18"); halo.addColorStop(1, "transparent");
  ctx.fillStyle = halo; ctx.beginPath(); ctx.arc(c,c,size*0.5,0,Math.PI*2); ctx.fill();
  // rings
  for(let ring=0; ring<3; ring++){
    const radius = size*(0.22 + ring*0.075) * (1 + shown.level*0.18*(ring+1)/3);
    ctx.strokeStyle = color + (ring===0?"cc":ring===1?"77":"33");
    ctx.lineWidth = ring===0 ? 2.5 : 1.4;
    ctx.beginPath();
    const turn = t/1000*(busy?1.6:0.4)*(ring%2?-1:1);
    const gap = busy ? 1.1 : 0.0;
    ctx.arc(c,c,radius, turn, turn + Math.PI*2 - gap);
    ctx.stroke();
  }
  // voice wave around the core
  if(state.phase==="listening" || state.phase==="speaking"){
    ctx.beginPath();
    for(let k=0; k<=96; k++){
      const a = k/96*Math.PI*2;
      const wobble = Math.sin(a*6 + t/120)*Math.sin(a*3 - t/200);
      const r = size*0.17*(1 + shown.level*0.55*wobble + 0.04*breathe);
      const x = c + r*Math.cos(a), y = c + r*Math.sin(a);
      k ? ctx.lineTo(x,y) : ctx.moveTo(x,y);
    }
    ctx.closePath(); ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();
  }
  // core
  const core = ctx.createRadialGradient(c - size*0.04, c - size*0.05, size*0.01, c, c, size*0.16);
  core.addColorStop(0, "#ffffff"); core.addColorStop(0.25, color); core.addColorStop(1, color+"10");
  ctx.fillStyle = core; ctx.beginPath(); ctx.arc(c,c,size*(0.11 + 0.015*breathe + shown.level*0.03),0,Math.PI*2); ctx.fill();
  // particles
  for(const p of particles){
    p.a += p.s*0.004*(busy?3:1);
    const r = size*0.5*p.r*(0.92 + 0.08*Math.sin(t/700 + p.z*9));
    ctx.fillStyle = color + (p.z>0.5?"aa":"55");
    ctx.beginPath(); ctx.arc(c + r*Math.cos(p.a), c + r*Math.sin(p.a), 1 + p.z*1.6, 0, Math.PI*2); ctx.fill();
  }
  requestAnimationFrame(draw);
}

// ---- captions, steps, approval -------------------------------------------------------------------------------
const ICON = {COMPLETED:"✓", FAILED:"!", DENIED:"⛔", WAITING_CONFIRMATION:"?"};
function renderSteps(steps){
  const list = $("steps"); list.replaceChildren();
  for(const step of steps){
    const li = document.createElement("li");
    const running = !step.state || step.state==="EXECUTING" || step.state==="PLANNED";
    li.className = step.state==="COMPLETED" ? "ok" : (step.state==="FAILED"||step.state==="DENIED") ? "bad" : running ? "run" : "";
    const mark = document.createElement("span"); mark.className = "mark"; mark.textContent = running ? "" : (ICON[step.state] || "·");
    const text = document.createElement("div");
    const purpose = document.createElement("div"); purpose.textContent = step.purpose || step.tool;
    const tool = document.createElement("div"); tool.className = "tool";
    tool.textContent = step.tool + (step.state==="COMPLETED" ? (step.verified ? " · verified" : " · done") : "");
    text.append(purpose, tool); li.append(mark, text); list.append(li);
  }
}
function render(){
  document.body.dataset.phase = state.phase;
  $("phase").textContent = state.healed && state.phase==="idle" ? "Restarted · ready" : (LABELS[state.phase] || state.phase);
  $("heard").textContent = state.heard || "";
  const live = (state.conversation||[]).slice(-1)[0];
  $("reply").textContent = state.phase==="paused" ? (state.message || "Actions are paused.")
    : (state.reply || (live && live[0]==="chutku" ? live[1] : "") || (state.phase==="error" ? state.message : ""));
  renderSteps(state.steps || []);
  const pending = state.pending;
  $("approval").hidden = !pending;
  if(pending) $("approval-text").textContent = pending.consequence || pending.tool;
  $("foot").textContent = state.mic_muted ? "Mic is muted (Ctrl+Alt+X)" : state.phone ? "📱 Phone connected" :
    "Ctrl+Alt+Space to talk · press again while I speak to cut me off";
}
// In the corner window (pywebview): shrink to a small orb after 6 s of nothing happening, grow at once when she
// listens, thinks, speaks or needs an answer.
let quietSince = Date.now(), small = false;
function fit(){
  const bridge = window.pywebview && window.pywebview.api;
  if(!bridge) return;
  const quiet = state.phase==="idle" || state.phase==="done" || state.phase==="paused";
  if(!quiet) quietSince = Date.now();
  const want = quiet && Date.now() - quietSince > 6000;
  if(want !== small){ small = want; document.body.classList.toggle("compact", small); bridge.size(small).catch(() => {}); }
}
async function poll(){
  try{ state = await api("/api/presence"); render(); fit(); }
  catch{ state = {...state, phase:"error", message:"Chutku is not running."}; render(); }
  setTimeout(poll, state.phase==="idle" || state.phase==="paused" ? 400 : 100);
}
async function decide(approve){
  if(!state.session_id) return;
  $("approve").disabled = $("reject").disabled = true;
  try{ await api("/api/agent/confirm", {id:state.session_id, approve}); }catch{}
  $("approve").disabled = $("reject").disabled = false;
}
$("approve").addEventListener("click", () => decide(true));
$("reject").addEventListener("click", () => decide(false));
$("talk").addEventListener("click", () => api("/api/presence/talk", {}).catch(() => {}));
if(compact) document.body.classList.add("compact");
requestAnimationFrame(draw);
poll();
