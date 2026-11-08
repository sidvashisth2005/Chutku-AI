"use strict";
// Chutku's presence (W4, 2026-10-29): a living orb that listens, thinks and speaks with her, live captions, and
// each step of the current task with its verified result. Reads /api/presence ~10x a second (memory only).
const $ = id => document.getElementById(id);
const BAR = new URLSearchParams(location.search).get("view") === "bar";   // Y1: the compact bar at the top
const fromLink = new URLSearchParams(location.hash.slice(1)).get("token");
if(fromLink){try{sessionStorage.setItem("chutku-token",fromLink);}catch{}history.replaceState(null,"",location.pathname+location.search);}
let token = fromLink || ""; try{token = token || sessionStorage.getItem("chutku-token") || "";}catch{}
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
const canvas = $(BAR ? "eyes" : "orb"), ctx = canvas.getContext("2d");
const particles = Array.from({length:70}, (_, i) => ({a:Math.random()*Math.PI*2, r:0.55+Math.random()*0.4,
  s:(0.15+Math.random()*0.6)*(i%2?1:-1), z:Math.random()}));
function accent(){return getComputedStyle(document.body).getPropertyValue("--accent").trim() || "#ff7a3d";}

// ---- her face on the core (X11 eyes with moods, X12 mouth) -----------------------------------------------------
// The mood comes from /api/presence ("mood"); each look is a target the face eases toward, so moods morph.
// open: eye height, x/y: gaze, tilt: sad slant of the lids, smile: mouth curve at rest, blink: ms between blinks.
const LOOKS = {
  calm:      {open:0.85, x:0,   y:0,     tilt:0,    smile:0.5,  blink:[3500,6500]},
  listening: {open:1.15, x:0,   y:-0.35, tilt:0,    smile:0.3,  blink:[2500,5000]},
  thinking:  {open:0.5,  x:1,   y:-0.3,  tilt:0,    smile:0,    blink:[4000,7000]},
  speaking:  {open:0.75, x:0,   y:0,     tilt:0,    smile:0.35, blink:[3000,5000]},
  happy:     {open:0.85, x:0,   y:0,     tilt:0,    smile:1,    blink:null},
  sorry:     {open:0.7,  x:0,   y:0.35,  tilt:0.8,  smile:-0.6, blink:[3000,6000]},
  sleepy:    {open:0.04, x:0,   y:0.3,   tilt:0,    smile:0,    blink:null},
  love:      {open:0.85, x:0,   y:0,     tilt:0,    smile:1,    blink:null},   // hearts: the owner thanked her
  confused:  {open:0.9,  x:0,   y:0,     tilt:0,    smile:-0.1, blink:null},   // spirals: she has to ask
  annoyed:   {open:0.7,  x:0,   y:0.1,   tilt:0,    smile:-0.3, blink:[3000,6000]},   // brows down: he sounds annoyed
};
// Mouth sizes in units of the core radius: closed, slightly open, round, open, wide.
const MOUTHS = [{w:0,h:0}, {w:0.17,h:0.05}, {w:0.1,h:0.11}, {w:0.18,h:0.13}, {w:0.26,h:0.15}];
const INK = "#04111dea";
let ink = INK;   // dark on the orb's bright core; the bar draws its eyes in the accent colour instead
const still = matchMedia("(prefers-reduced-motion: reduce)");   // then: no blinking or glancing, a static face
const face = {open:0.85, x:0, y:0, tilt:0, smile:0.5, blinkAt:-1e9, nextBlink:1500, voice:0, shape:0, shapeAt:0, mw:0, mh:0};

// Amplitude lip-sync (X12 v1): her voice's loudness (0..1) picks one of five mouth shapes; it knows no phonemes.
// A level within 0.03 of a band edge keeps the previous shape, so the mouth does not flicker on the edge.
function mouthShape(level, previous){
  const edges = [0.05, 0.2, 0.4, 0.65];
  const shape = edges.filter(edge => level >= edge).length;
  if(Math.abs(shape - previous) === 1 && Math.abs(level - edges[Math.min(shape, previous)]) < 0.03) return previous;
  return shape;
}
function drawEye(cx, cy, u, side, mood, blink, t){   // side: -1 her right (screen left), +1 the other
  const w = 0.12*u, h = 0.24*u*face.open*blink;
  ctx.fillStyle = ctx.strokeStyle = ink; ctx.lineWidth = 0.07*u; ctx.lineCap = "round";
  if(mood==="happy"){   // smiling eyes: ^ ^
    ctx.beginPath(); ctx.arc(cx, cy + 0.1*u, 0.15*u, Math.PI*1.2, Math.PI*1.8); ctx.stroke(); return;
  }
  if(mood==="love"){    // hearts that beat
    const s = 0.13*u*(still.matches ? 1 : 1 + 0.08*Math.sin(t/180));
    ctx.fillStyle = "#ff5c93"; ctx.beginPath(); ctx.moveTo(cx, cy + s*0.9);
    ctx.bezierCurveTo(cx - s*1.7, cy - s*0.3, cx - s*0.7, cy - s*1.5, cx, cy - s*0.5);
    ctx.bezierCurveTo(cx + s*0.7, cy - s*1.5, cx + s*1.7, cy - s*0.3, cx, cy + s*0.9); ctx.fill(); return;
  }
  if(mood==="confused"){   // spirals that turn
    const turn = still.matches ? 0 : side*t/400;
    ctx.lineWidth = 0.045*u; ctx.beginPath();
    for(let k=0; k<=36; k++){
      const a = k/36*Math.PI*5 + turn, r = 0.16*u*k/36;
      k ? ctx.lineTo(cx + r*Math.cos(a), cy + r*Math.sin(a)) : ctx.moveTo(cx, cy);
    }
    ctx.stroke(); return;
  }
  if(mood==="annoyed"){    // brows slanting down toward the nose
    const inner = cx - side*w*1.6, outer = cx + side*w*1.6, top = cy - 0.24*u*face.open - 0.1*u;
    ctx.lineWidth = 0.06*u; ctx.beginPath(); ctx.moveTo(outer, top - 0.05*u); ctx.lineTo(inner, top + 0.07*u); ctx.stroke();
  }
  if(h < 0.05*u){       // closed: a soft downward curve
    ctx.beginPath(); ctx.moveTo(cx - w*1.3, cy); ctx.quadraticCurveTo(cx, cy + 0.09*u, cx + w*1.3, cy); ctx.stroke(); return;
  }
  ctx.save();
  if(face.tilt > 0.02){ // sorry: the lid drops toward the outer corner
    const inner = cx - side*w*2, outer = cx + side*w*2, top = cy - h*1.05;
    ctx.beginPath(); ctx.moveTo(inner, top); ctx.lineTo(outer, top + face.tilt*h*1.6);
    ctx.lineTo(outer, cy + h*2); ctx.lineTo(inner, cy + h*2); ctx.closePath(); ctx.clip();
  }
  ctx.beginPath(); ctx.ellipse(cx, cy, w, h, 0, 0, Math.PI*2); ctx.fill();
  ctx.restore();
  ctx.fillStyle = "#ffffffcc";   // catchlight
  ctx.beginPath(); ctx.arc(cx + w*0.35, cy - h*0.45, 0.04*u, 0, Math.PI*2); ctx.fill();
}
function faceStep(t){   // ease toward the mood's look and run the blinks; one call per frame
  const mood = LOOKS[state.mood] ? state.mood : "calm", look = LOOKS[mood], calm = still.matches;
  const k = calm ? 1 : 0.12;
  const glance = calm || mood!=="thinking" ? 1 : (Math.sin(t/2600) > 0 ? 1 : -1);   // thinking: looks one side, then the other
  face.open += (look.open - face.open)*k; face.x += (look.x*glance - face.x)*k; face.y += (look.y - face.y)*k;
  face.tilt += (look.tilt - face.tilt)*k; face.smile += (look.smile - face.smile)*k;
  let blink = 1;
  if(!calm && look.blink){
    if(t >= face.nextBlink){
      face.blinkAt = t;
      const [low, high] = look.blink;
      face.nextBlink = t + (Math.random() < 0.15 ? 260 : low + Math.random()*(high - low));   // sometimes a double blink
    }
    const e = t - face.blinkAt;
    if(e < 160) blink = 1 - Math.sin(Math.PI*e/160);
  }
  return {mood, blink};
}
function drawEyes(cx, cy, u, spread, mood, blink, t){
  const gx = face.x*0.13*u, gy = face.y*0.13*u;
  drawEye(cx - spread*u + gx, cy + gy, u, -1, mood, blink, t);
  drawEye(cx + spread*u + gx, cy + gy, u, 1, mood, blink, t);
  return {gx, gy};
}
function drawFace(t, c, u){
  const {mood, blink} = faceStep(t), calm = still.matches;
  const {gx, gy} = drawEyes(c, c - 0.16*u, u, 0.36, mood, blink, t);
  // mouth: her voice level, smoothed (fast open, slower close), then held at least 90 ms per shape
  const speaking = state.phase==="speaking", target = speaking ? Math.min(1, state.voice_level || 0) : 0;
  face.voice += (target - face.voice)*(target > face.voice ? 0.5 : 0.2);
  const want = calm ? (speaking ? 1 : 0) : mouthShape(face.voice, face.shape);
  if(want !== face.shape && t - face.shapeAt > 90){face.shape = want; face.shapeAt = t;}
  const shape = MOUTHS[face.shape], mk = calm ? 1 : 0.4;
  face.mw += (shape.w - face.mw)*mk; face.mh += (shape.h - face.mh)*mk;
  const mx = c + gx*0.5, my = c + 0.36*u + gy*0.5;
  ctx.fillStyle = ctx.strokeStyle = ink;
  if(face.mh > 0.03){
    ctx.beginPath(); ctx.ellipse(mx, my, face.mw*u, face.mh*u, 0, 0, Math.PI*2); ctx.fill();
  }else{                 // at rest: a curve that smiles, stays flat or frowns with the mood
    const half = (0.16 + 0.06*Math.max(0, face.smile))*u;
    ctx.lineWidth = 0.065*u; ctx.lineCap = "round";
    ctx.beginPath(); ctx.moveTo(mx - half, my - face.smile*0.04*u);
    ctx.quadraticCurveTo(mx, my + face.smile*0.16*u, mx + half, my - face.smile*0.04*u); ctx.stroke();
  }
}
function drawBar(t){   // Y1: just her eyes, glowing in the phase colour
  const {mood, blink} = faceStep(t);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ink = accent();
  drawEyes(canvas.width/2, canvas.height/2, canvas.height*1.05, 0.46, mood, blink, t);
}
function draw(t){   // the one animation loop
  BAR ? drawBar(t) : drawOrb(t);
  requestAnimationFrame(draw);
}
function drawOrb(t){
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
  const coreRadius = size*(0.11 + 0.015*breathe + shown.level*0.03);
  ctx.fillStyle = core; ctx.beginPath(); ctx.arc(c,c,coreRadius,0,Math.PI*2); ctx.fill();
  drawFace(t, c, still.matches ? size*0.11 : coreRadius);
  // particles
  for(const p of particles){
    p.a += p.s*0.004*(busy?3:1);
    const r = size*0.5*p.r*(0.92 + 0.08*Math.sin(t/700 + p.z*9));
    ctx.fillStyle = color + (p.z>0.5?"aa":"55");
    ctx.beginPath(); ctx.arc(c + r*Math.cos(p.a), c + r*Math.sin(p.a), 1 + p.z*1.6, 0, Math.PI*2); ctx.fill();
  }
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
// ---- Y1: the compact bar and the switch between bar and full window ---------------------------------------------
function windowApi(name){   // pywebview's js_api (chutku/presence.py Bridge); false in a plain browser
  const call = window.pywebview && window.pywebview.api && window.pywebview.api[name];
  if(call){ call().catch(() => {}); return true; }
  return false;
}
function barText(){   // one live line (owner, 2026-11-06): what he says and what she says, as it happens
  const live = (state.conversation||[]).slice(-1)[0];   // Gemini Live streams both sides here, word by word
  const step = (state.steps||[]).find(s => !s.state || s.state==="EXECUTING");
  if(state.pending) return "Needs your OK: " + (state.pending.consequence || state.pending.tool);
  if(state.phase==="paused") return state.message || "Actions are paused.";
  if(state.phase==="error") return state.message || "Something went wrong.";
  if(live && live[1] && state.phase !== "idle") return (live[0]==="chutku" ? "Chutku: " : "You: ") + live[1];
  if(state.phase==="listening") return state.heard ? "You: " + state.heard : "Listening…";
  if(state.phase==="thinking" || state.phase==="running")
    return step ? (step.purpose || step.tool) : (state.heard ? "You: " + state.heard : "Thinking…");
  if(state.reply && ["speaking","done","clarify"].includes(state.phase)) return "Chutku: " + state.reply;
  return state.mic_muted ? "Mic is muted (Ctrl+Alt+X)" : "Ready · Ctrl+Alt+Space";
}
// Showing/hiding the bar while she works and opening the full window for an approval are decided in Python
// (chutku/presence.py StateWatcher): a hidden WebView2 window pauses its timers.
// Live captions (owner 2026-11-06: "no dot dot, the words should appear and vanish in real time"): the newest
// words that fit, with the oldest dropped word by word, and the speaker label kept in front.
function showNewestWords(line, text){
  const m = text.match(/^(You: |Chutku: )/), label = m ? m[1] : "", words = text.slice(label.length).split(/\s+/);
  let start = 0;
  line.textContent = text;
  while(line.scrollWidth > line.clientWidth && start < words.length - 1){
    start++;
    line.textContent = label + words.slice(start).join(" ");
  }
}
// X13: YouTube inside Chutku's window (privacy-enhanced embed; the page's CSP allows only this frame source)
let videoShown = "";
function renderVideo(video){
  const id = video && /^[\w-]{11}$/.test(video.id) ? video.id : "";
  $("video").hidden = !id;
  if(id === videoShown) return;
  videoShown = id;
  const frame = $("video-frame");
  frame.textContent = "";
  if(!id) return;
  const player = document.createElement("iframe");
  player.src = "https://www.youtube-nocookie.com/embed/" + id + "?autoplay=1";
  player.allow = "autoplay; encrypted-media; picture-in-picture";
  player.referrerPolicy = "strict-origin-when-cross-origin";
  player.title = video.title || "YouTube";
  frame.appendChild(player);
  $("video-title").textContent = video.title || "";
}
function renderBar(){
  document.body.dataset.phase = state.phase;
  const text = barText(), line = $("strip-text");
  if(line.title !== text){ line.title = text; showNewestWords(line, text); }
}
function render(){
  if(BAR) return renderBar();
  document.body.dataset.phase = state.phase;
  $("phase").textContent = state.healed && state.phase==="idle" ? "Restarted · ready" : (LABELS[state.phase] || state.phase);
  $("heard").textContent = state.heard || "";
  const live = (state.conversation||[]).slice(-1)[0];
  $("reply").textContent = state.phase==="paused" ? (state.message || "Actions are paused.")
    : (state.reply || (live && live[0]==="chutku" ? live[1] : "") || (state.phase==="error" ? state.message : ""));
  renderSteps(state.steps || []);
  renderVideo(state.video);
  const pending = state.pending;
  $("approval").hidden = !pending;
  if(pending) $("approval-text").textContent = pending.consequence || pending.tool;
  $("foot").textContent = state.mic_muted ? "Mic is muted (Ctrl+Alt+X)" : state.phone ? "📱 Phone connected" :
    "Ctrl+Alt+Space to talk · press again while I speak to cut me off";
}
async function poll(){
  try{ state = await api("/api/presence"); render(); }
  catch{ state = {...state, phase:"error", mood:"sorry", message:"Chutku is not running."}; render(); }
  // the window not showing (bar or full, Y1) polls once a second; the one on screen stays live
  // a window not on screen rests (1 s); the Python StateWatcher decides when it appears
  setTimeout(poll, document.hidden ? 1000 : state.phase==="idle" || state.phase==="paused" ? 400 : 100);
}
async function decide(approve){
  if(!state.session_id) return;
  $("approve").disabled = $("reject").disabled = true;
  try{ await api("/api/agent/confirm", {id:state.session_id, approve}); }catch{}
  $("approve").disabled = $("reject").disabled = false;
}
$("approve").addEventListener("click", () => decide(true));
$("reject").addEventListener("click", () => decide(false));
for(const id of ["talk", "strip-talk"])
  $(id).addEventListener("click", () => api("/api/presence/talk", {}).catch(() => {}));
// Expand / back to the bar: the Bridge swaps the windows. In a plain browser the bar's expand opens the full page;
// "to bar" shows only inside the Chutku window.
$("expand").addEventListener("click", () => windowApi("expand") || (location.search = ""));
$("to-bar").addEventListener("click", () => windowApi("compact"));
$("video-close").addEventListener("click", () => api("/api/presence/video/close", {}).catch(() => {}));
$("strip").hidden = !BAR;
document.querySelector(".presence").hidden = BAR;
document.body.classList.toggle("bar-view", BAR);
const showToBar = () => { $("to-bar").hidden = BAR || !window.pywebview; };
showToBar(); window.addEventListener("pywebviewready", showToBar);
requestAnimationFrame(draw);
poll();
