"use strict";
// Chutku on the phone (W6 / HERMES_PLAN P1-P9). The device credential lives only on this phone; every approval,
// screen view and control session asks for the PIN again. Nothing here can do more than the laptop allows.
const $ = id => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
let csrf = "";
const store = {
  get credential() { try { return localStorage.getItem("chutku-credential") || ""; } catch { return ""; } },
  set credential(v) { try { v ? localStorage.setItem("chutku-credential", v) : localStorage.removeItem("chutku-credential"); } catch {} },
};

async function api(path, data, raw) {
  const options = { credentials: "same-origin", headers: {} };
  if (data !== undefined) {
    options.method = "POST";
    options.headers["X-Chutku-CSRF"] = csrf;
    if (raw) { options.body = data; } else { options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(data); }
  }
  const response = await fetch(path, options);
  if (response.status === 204) return null;
  const type = response.headers.get("Content-Type") || "";
  if (!type.startsWith("application/json")) { if (!response.ok) throw new Error("failed"); return response; }
  const payload = await response.json();
  if (response.status === 401) { show("login"); }
  if (!response.ok) throw new Error(payload.error || "failed");
  return payload;
}
function show(view) { for (const id of ["pair", "login", "app"]) $(id).hidden = id !== view; }
function status(text) { $("status").textContent = text; }
function askPin(why) {
  return new Promise(resolve => {
    $("pin-why").textContent = why || "Enter your PIN"; $("pin-input").value = "";
    $("pin-dialog").onclose = () => resolve($("pin-dialog").returnValue === "ok" ? $("pin-input").value : null);
    $("pin-dialog").showModal();
  });
}

// ---- P1: pairing and unlock ---------------------------------------------------------------------------------------
const pairCode = new URLSearchParams(location.hash.slice(1)).get("code");
if (pairCode) { $("pair-code").value = pairCode; history.replaceState(null, "", "/"); }
$("pair-go").addEventListener("click", async () => {
  try {
    const result = await api("/api/pair", { code: $("pair-code").value, name: $("pair-name").value, pin: $("pair-pin").value });
    store.credential = result.credential;
    await unlock($("pair-pin").value);
  } catch (e) { status(e.message); }
});
async function unlock(pin) {
  const result = await api("/api/login", { credential: store.credential, pin });
  csrf = result.csrf; show("app"); status(result.name); refresh();
}
$("login-go").addEventListener("click", () => unlock($("login-pin").value).catch(e => status(e.message)));
$("forget").addEventListener("click", () => { store.credential = ""; show("pair"); });

// ---- tabs ----------------------------------------------------------------------------------------------------------
document.querySelectorAll(".tabs button").forEach(b => b.addEventListener("click", () => {
  document.querySelectorAll(".tabs button").forEach(x => x.classList.toggle("on", x === b));
  for (const name of ["chat", "screen", "pad", "files"]) $("tab-" + name).hidden = name !== b.dataset.tab;
}));

// ---- P2: chat, live progress, approvals ----------------------------------------------------------------------------
function bubble(text, who) { const b = el("div", "msg " + who, text); $("log").append(b); $("log").scrollTop = 1e9; return b; }
function render(box, s) {
  box.replaceChildren(el("div", "", s.reply || (s.status === "done" ? "Done." : "…")));
  for (const step of s.steps || []) box.append(el("div", "step " + (step.state === "COMPLETED" ? "ok" : step.state === "FAILED" || step.state === "DENIED" ? "bad" : ""), step.purpose || step.tool));
  if (s.pending) {
    const card = el("div", "approval");
    card.append(el("strong", "", "Needs your OK: "), el("span", "", s.pending.consequence || s.pending.tool));
    if (s.pending.laptop_only) card.append(el("p", "small", "Ye laptop pe approve karna hoga."));
    else {
      const row = el("div", "row"), yes = el("button", "primary", "Approve (PIN)"), no = el("button", "", "Cancel");
      for (const [button, approve] of [[yes, true], [no, false]]) button.addEventListener("click", async () => {
        const pin = await askPin(approve ? "PIN to approve" : "PIN to cancel"); if (!pin) return;
        try { const r = await api("/api/approve", { id: s.id, approve, pin, nonce: s.pending.nonce }); render(box, r.session); follow(box, s.id); } catch (e) { status(e.message); }
      });
      row.append(yes, no); card.append(row);
    }
    box.append(card);
  }
}
async function follow(box, id) {
  for (let i = 0; i < 600; i++) {
    let s; try { s = (await api("/api/session?id=" + encodeURIComponent(id))).session; } catch { return; }
    render(box, s);
    if (["done", "clarify", "failed", "stopped", "cancelled", "waiting_confirmation"].includes(s.status)) {
      if (s.status === "done" || s.status === "clarify") speak(id, s.reply);
      // Z5: the approval question is spoken here too, so the laptop at home stays silent
      if (s.status === "waiting_confirmation" && s.pending) speak(id, "Ek approval chahiye: " + (s.pending.consequence || s.pending.tool));
      return;
    }
    await new Promise(r => setTimeout(r, 700));
  }
}
async function speak(id, text) {
  try {
    const response = await api("/api/say?id=" + encodeURIComponent(id));
    if (response) { const audio = new Audio(URL.createObjectURL(await response.blob())); await audio.play(); return; }
  } catch {}
  if ("speechSynthesis" in window && text) {
    const u = new SpeechSynthesisUtterance(text.replace(/\s*\[Verified:.*\]\s*$/, ""));
    u.voice = speechSynthesis.getVoices().find(v => /hi-IN|en-IN/.test(v.lang) && /female|swara|neerja/i.test(v.name)) || null;
    speechSynthesis.speak(u);
  }
}
$("ask").addEventListener("submit", async e => {
  e.preventDefault(); const text = $("message").value.trim(); if (!text) return;
  $("message").value = ""; bubble(text, "me"); const box = bubble("…", "her");
  try { const r = await api("/api/chat", { message: text }); render(box, r.session); follow(box, r.session.id); } catch (err) { box.textContent = err.message; }
});
$("resume").addEventListener("click", async () => { const pin = await askPin("PIN to resume Chutku"); if (pin) api("/api/resume", { pin }).then(refresh).catch(e => status(e.message)); });
async function refresh() { try { const me = await api("/api/whoami"); $("paused").hidden = !me.paused; $("control-bar").hidden = !me.control_allowed; } catch {} }

// ---- P3: hold to talk ------------------------------------------------------------------------------------------------
let recorder = null, chunks = [];
async function startTalk() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    chunks = []; recorder = new MediaRecorder(stream);
    recorder.ondataavailable = e => chunks.push(e.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop()); $("talk").classList.remove("rec");
      const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      const box = bubble("🎙 …", "her");
      try {
        const r = await api("/api/voice", blob, true);
        if (r.transcript) bubble("🎙 " + r.transcript, "me");
        if (r.session) { render(box, r.session); follow(box, r.session.id); } else box.textContent = r.message;
      } catch (e) { box.textContent = e.message; }
    };
    recorder.start(); $("talk").classList.add("rec");
    setTimeout(() => recorder && recorder.state === "recording" && recorder.stop(), 30000);
  } catch { status("Microphone not allowed"); }
}
$("talk").addEventListener("pointerdown", startTalk);
for (const ev of ["pointerup", "pointerleave", "pointercancel"]) $("talk").addEventListener(ev, () => recorder && recorder.state === "recording" && recorder.stop());

// ---- Z5: sound on the laptop, only on purpose ------------------------------------------------------------------------
$("laptop-say").addEventListener("click", async () => {
  const text = $("laptop-text").value.trim(); if (!text) return;
  try { await api("/api/laptop/say", { text }); $("laptop-text").value = ""; status("Laptop pe bol rahi hoon"); } catch (e) { status(e.message); }
});
let laptopRecorder = null;
$("laptop-talk").addEventListener("pointerdown", async () => {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true }), parts = [];
    laptopRecorder = new MediaRecorder(stream);
    laptopRecorder.ondataavailable = e => parts.push(e.data);
    laptopRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop()); $("laptop-talk").classList.remove("rec");
      try { const r = await api("/api/laptop/voice", new Blob(parts, { type: laptopRecorder.mimeType || "audio/webm" }), true); status(`Laptop pe chal raha hai (${r.playing_seconds} s)`); } catch (e) { status(e.message); }
    };
    laptopRecorder.start(); $("laptop-talk").classList.add("rec");
    setTimeout(() => laptopRecorder && laptopRecorder.state === "recording" && laptopRecorder.stop(), 30000);
  } catch { status("Microphone not allowed"); }
});
for (const ev of ["pointerup", "pointerleave", "pointercancel"]) $("laptop-talk").addEventListener(ev, () => laptopRecorder && laptopRecorder.state === "recording" && laptopRecorder.stop());

// ---- P4: live screen, P9: point-and-ask, P5: tap control ---------------------------------------------------------------
let viewing = false, lastHash = "";
async function frames() {
  while (viewing) {
    try {
      const response = await api("/api/screen/frame?h=" + lastHash);
      if (response) { lastHash = response.headers.get("X-Frame-Hash") || ""; const url = URL.createObjectURL(await response.blob()); const old = $("frame").src; $("frame").src = url; if (old.startsWith("blob:")) URL.revokeObjectURL(old); }
    } catch (e) { status(e.message); viewing = false; break; }
    await new Promise(r => setTimeout(r, controlling ? 120 : 330));
  }
}
$("screen-go").addEventListener("click", async () => { const pin = await askPin("PIN to see the laptop screen"); if (!pin) return; try { await api("/api/screen/start", { pin }); viewing = true; frames(); } catch (e) { status(e.message); } });
$("screen-stop").addEventListener("click", () => { viewing = false; api("/api/screen/stop", {}).catch(() => {}); });
function point(e) { const r = $("frame").getBoundingClientRect(); return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) }; }
let pressTimer = null, downAt = null, lastTap = 0;
$("frame").addEventListener("pointerdown", e => { downAt = point(e); pressTimer = setTimeout(() => { if ($("tap-mode").value === "control") send([{ kind: "right", ...downAt }]); downAt = null; }, 500); });
$("frame").addEventListener("pointerup", async e => {
  clearTimeout(pressTimer); if (!downAt) return; const p = point(e); downAt = null;
  if ($("tap-mode").value === "ask") {
    const question = prompt("Is jagah ke baare mein kya karna hai? (\"ye kya hai\", \"isko band karo\")"); if (!question) return;
    bubble("👆 " + question, "me"); const box = bubble("…", "her");
    try { const r = await api("/api/point", { x: p.x, y: p.y, question }); render(box, r.session); follow(box, r.session.id); } catch (err) { box.textContent = err.message; }
    return;
  }
  const now = Date.now(); send([{ kind: now - lastTap < 300 ? "double" : "tap", ...p }]); lastTap = now;
});
$("frame").addEventListener("wheel", e => { if ($("tap-mode").value === "control") { e.preventDefault(); send([{ kind: "scroll", ...point(e), dy: e.deltaY > 0 ? -3 : 3 }]); } }, { passive: false });
let controlling = false;
async function send(events) { try { await api("/api/control/input", { events }); } catch (e) { status(e.message); } }
async function startControl() { const pin = await askPin("PIN to control the laptop"); if (!pin) return; try { await api("/api/control/start", { pin }); controlling = true; $("tap-mode").value = "control"; status("Controlling"); } catch (e) { status(e.message); } }
function stopControl() { controlling = false; api("/api/control/stop", {}).catch(() => {}); status("Control ended"); }
$("control-go").addEventListener("click", startControl);
$("control-stop").addEventListener("click", stopControl);
$("pad-go").addEventListener("click", startControl);
$("pad-stop").addEventListener("click", stopControl);

// ---- Z5: trackpad (moves from where the cursor is) and a live keyboard ---------------------------------------------------
let inputs = Promise.resolve();
function queued(path, data) { inputs = inputs.then(() => api(path, data)).catch(e => status(e.message)); return inputs; }   // in order
const here = kind => queued("/api/control/input", { events: [{ kind, at: "cursor" }] });
const SPEED = 2.2, touches = new Map();
let moved = { dx: 0, dy: 0 }, flushing = null, gesture = null, dragging = false;
function flush() {
  flushing = null; const dx = Math.round(moved.dx), dy = Math.round(moved.dy); if (!dx && !dy) return;
  moved = { dx: 0, dy: 0 };
  queued("/api/control/input", { events: [{ kind: "nudge", dx: Math.max(-400, Math.min(400, dx)), dy: Math.max(-400, Math.min(400, dy)) }] });
}
$("pad").addEventListener("pointerdown", e => {
  $("pad").setPointerCapture(e.pointerId); touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (touches.size === 1) gesture = { at: Date.now(), travel: 0, fingers: 1 }; else if (gesture) gesture.fingers = Math.max(gesture.fingers, touches.size);
});
$("pad").addEventListener("pointermove", e => {
  const last = touches.get(e.pointerId); if (!last || !gesture) return;
  const dx = e.clientX - last.x, dy = e.clientY - last.y; touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
  gesture.travel += Math.abs(dx) + Math.abs(dy);
  if (touches.size >= 2) { gesture.scroll = (gesture.scroll || 0) + dy; if (Math.abs(gesture.scroll) > 24) { queued("/api/control/input", { events: [{ kind: "scroll", at: "cursor", dy: gesture.scroll > 0 ? 2 : -2 }] }); gesture.scroll = 0; } return; }
  moved.dx += dx * SPEED; moved.dy += dy * SPEED; if (!flushing) flushing = setTimeout(flush, 30);
});
for (const ev of ["pointerup", "pointercancel"]) $("pad").addEventListener(ev, e => {
  touches.delete(e.pointerId); if (touches.size || !gesture) return;
  const tap = Date.now() - gesture.at < 250 && gesture.travel < 12; if (tap) here(gesture.fingers >= 2 ? "right" : "tap"); gesture = null;
});
$("pad-left").addEventListener("click", () => here("tap"));
$("pad-right").addEventListener("click", () => here("right"));
$("pad-up").addEventListener("click", () => queued("/api/control/input", { events: [{ kind: "scroll", at: "cursor", dy: 3 }] }));
$("pad-down").addEventListener("click", () => queued("/api/control/input", { events: [{ kind: "scroll", at: "cursor", dy: -3 }] }));
$("pad-drag").addEventListener("click", () => { dragging = !dragging; here(dragging ? "down" : "up"); $("pad-drag").textContent = "Drag: " + (dragging ? "on" : "off"); $("pad").classList.toggle("drag", dragging); });
// Phone keyboards rarely report keys, so the field keeps two spaces: shorter = Backspace, longer = new text.
const KEEP = "  "; $("live-keys").value = KEEP;
async function key(combo) { try { await queued("/api/control/keys", { combo }); } catch {} }
$("live-keys").addEventListener("input", () => {
  const value = $("live-keys").value; $("live-keys").value = KEEP;
  if (value.length < KEEP.length) { for (let i = value.length; i < KEEP.length; i++) key("backspace"); return; }
  const text = value.slice(KEEP.length); if (text) queued("/api/control/text", { text });
});
$("live-keys").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); key("enter"); } });

// ---- P6: typing and shortcut bar ---------------------------------------------------------------------------------------
async function typeText(enter) {
  const text = $("type-text").value; if (!text && !enter) return;
  try { await api("/api/control/text", { text, enter }); $("type-text").value = ""; }
  catch (e) { if (/PIN/.test(e.message)) { const pin = await askPin(e.message); if (pin) api("/api/control/text", { text, enter, pin }).catch(x => status(x.message)); } else status(e.message); }
}
$("type-send").addEventListener("click", () => typeText(false));
$("type-enter").addEventListener("click", () => typeText(true));
for (const combo of ["esc", "tab", "enter", "backspace", "delete", "up", "down", "left", "right", "home", "end", "pageup", "pagedown", "ctrl+c", "ctrl+v", "ctrl+z", "ctrl+s", "alt+tab", "win+d", "alt+f4"]) {
  const b = el("button", "", combo);
  b.addEventListener("click", async () => {
    if (combo === "alt+f4" && !confirm("Pakka band karun?")) return;
    try { await api("/api/control/keys", { combo }); } catch (e) { if (/PIN/.test(e.message)) { const pin = await askPin(e.message); if (pin) api("/api/control/keys", { combo, pin }).catch(x => status(x.message)); } else status(e.message); }
  });
  $("keys").append(b);
}

// ---- P7: clipboard -----------------------------------------------------------------------------------------------------
$("clip-get").addEventListener("click", async () => { const pin = await askPin("PIN to read the laptop clipboard"); if (!pin) return; try { const r = await api("/api/clipboard/get", { pin }); $("type-text").value = r.text; try { await navigator.clipboard.writeText(r.text); } catch {} status("Clipboard copied"); } catch (e) { status(e.message); } });
$("clip-paste").addEventListener("click", async () => { const text = $("type-text").value; if (!text) return; try { await api("/api/clipboard/set", { text, paste: true }); } catch (e) { status(e.message); } });

// ---- P8: files ---------------------------------------------------------------------------------------------------------
$("upload-go").addEventListener("click", async () => {
  const file = $("upload-file").files[0]; if (!file) return;
  try { const r = await api("/api/files/upload?name=" + encodeURIComponent(file.name), file, true); $("upload-out").textContent = "Saved: " + r.saved; } catch (e) { $("upload-out").textContent = e.message; }
});
$("get-go").addEventListener("click", async () => {
  const pin = await askPin("PIN to fetch a laptop file"); if (!pin) return;
  try { const response = await api("/api/files/get", { path: $("get-path").value, pin }); const blob = await response.blob(); const a = el("a"); a.href = URL.createObjectURL(blob); a.download = $("get-path").value.split(/[\\/]/).pop(); a.click(); $("get-out").textContent = "Downloaded " + blob.size + " bytes"; }
  catch (e) { $("get-out").textContent = e.message; }
});

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
show(store.credential ? "login" : "pair");
