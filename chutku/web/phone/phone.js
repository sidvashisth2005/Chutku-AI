"use strict";
// Chutku on the phone (W6 / HERMES_PLAN P1-P9, remote 2.0 2026-11-07). The device credential lives only on this phone.
// The unlock PIN covers screen, control, clipboard and files for 30 minutes; risky approvals and command windows ask
// again. Nothing here can do more than the laptop allows.
const $ = id => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
let csrf = "", relay = false;   // relay: this page came from the account relay (the phone app), not the tailnet
const keep = (name, v) => { try { v ? localStorage.setItem(name, v) : localStorage.removeItem(name); } catch {} };
const kept = name => { try { return localStorage.getItem(name) || ""; } catch { return ""; } };
const store = {
  get credential() { return kept("chutku-credential"); }, set credential(v) { keep("chutku-credential", v); },
  get token() { return kept("chutku-relay-token"); }, set token(v) { keep("chutku-relay-token", v); },
  // W6: the end-to-end key (raw, base64) and the account it belongs to.
  // shortcut: kept in localStorage like the token; a non-extractable IndexedDB CryptoKey would resist page scripts better.
  get key() { return kept("chutku-relay-key"); }, set key(v) { keep("chutku-relay-key", v); },
  get account() { return kept("chutku-relay-id"); }, set account(v) { keep("chutku-relay-id", v); },
};
let e2eKey = null;
async function sealedFetch(path, options) {
  // W6: the relay sees only {v, iv, ct}: method, path, body and the answer are encrypted end to end.
  if (!store.key) throw new Error("Log in again on this phone (encryption key missing).");
  e2eKey = e2eKey || await ChutkuE2E.importKey(store.key);
  let body = "";
  if (options.body !== undefined) {
    const bytes = new Uint8Array(await new Response(options.body).arrayBuffer());
    body = ChutkuE2E.b64(bytes);
  }
  const n = ChutkuE2E.nonce();
  const inner = { m: options.method || "GET", p: path, t: options.headers["Content-Type"] || (options.body && options.body.type) || "", b: body, ts: Math.floor(Date.now() / 1000), n };
  const envelope = await ChutkuE2E.seal(e2eKey, store.account, "req", inner);
  const response = await fetch("/t/e2e", { method: "POST", headers: { "Content-Type": "application/json", "Authorization": "Bearer " + store.token }, body: JSON.stringify(envelope) });
  if (!response.ok) return response;   // relay errors (401, 503 laptop offline...) are plain JSON from the relay
  const answer = await ChutkuE2E.open(e2eKey, store.account, "res", await response.json());
  if (answer.n !== n) throw new Error("The answer did not belong to this request.");
  return new Response(answer.s === 204 ? null : ChutkuE2E.unb64(answer.b || ""), { status: answer.s, headers: answer.h || {} });
}

async function api(path, data, raw) {
  const options = { credentials: "same-origin", headers: {} };
  if (data !== undefined) {
    options.method = "POST";
    if (!relay) options.headers["X-Chutku-CSRF"] = csrf;
    if (raw) { options.body = data; } else { options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(data); }
  }
  if (relay && path.startsWith("/relay/")) options.headers["Authorization"] = "Bearer " + store.token;
  const response = relay && path.startsWith("/api/") ? await sealedFetch(path, options) : await fetch(path, options);
  if (response.status === 204) return null;
  const type = response.headers.get("Content-Type") || "";
  if (!type.startsWith("application/json")) { if (!response.ok) throw new Error("failed"); return response; }
  const payload = await response.json();
  if (response.status === 401) { if (relay) { store.token = ""; show("account"); } else show("login"); }
  if (!response.ok) throw new Error(payload.error || "failed");
  return payload;
}
function show(view) { for (const id of ["account", "pair", "login", "app"]) $(id).hidden = id !== view; $("logout").hidden = !(relay && view === "app"); }
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
  csrf = result.csrf; status(result.name); await enterApp();
}
$("login-go").addEventListener("click", () => unlock($("login-pin").value).catch(e => status(e.message)));
$("forget").addEventListener("click", () => { store.credential = ""; show("pair"); });

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
        try { const r = await withPin(approve ? "PIN to approve" : "PIN to cancel", pin => api("/api/approve", { id: s.id, approve, pin, nonce: s.pending.nonce })); render(box, r.session); follow(box, s.id); } catch (e) { status(e.message); }
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
$("resume").addEventListener("click", () => withPin("PIN to resume Chutku", pin => api("/api/resume", pin ? { pin } : {})).then(refresh).catch(e => status(e.message)));
async function refresh() {
  try {
    const me = await api("/api/whoami"); $("paused").hidden = !me.paused;
    controlAllowed = !!me.control_allowed; controlling = !!me.controlling; showControl();
    if (me.assistant) { $("assistant-name").textContent = me.assistant; document.title = me.assistant; }
    if (relay) { csrf = me.csrf || ""; status(me.device || "Connected"); }
  } catch (e) { status(e.message); }
}

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

// ---- Phone remote 2.0 (owner 2026-11-07): one screen. The laptop screen fills the phone and touching it is the trackpad.
// The screen starts by itself; the PIN from unlocking covers screen, control and files for 30 minutes (risky steps ask).
const sleep = ms => new Promise(r => setTimeout(r, ms));
let viewing = false, looping = false, lastHash = "", cursorAt = null, controlAllowed = false, controlling = false;
function note(text) { $("screen-note").hidden = !text; $("screen-note").textContent = text || ""; }
async function withPin(why, call) {   // try inside the PIN session first; ask only when the laptop wants it
  try { return await call(undefined); }
  catch (e) { if (!/PIN/.test(e.message)) throw e; const pin = await askPin(why); if (!pin) throw new Error("Cancelled"); return call(pin); }
}
async function rawGet(path) {   // GET that keeps the status and headers (frames: 204 still carries the cursor)
  const options = { credentials: "same-origin", headers: {} };
  return relay ? sealedFetch(path, options) : fetch(path, options);
}
async function startScreen() {
  try {
    await withPin("PIN to see the laptop screen", pin => api("/api/screen/start", pin ? { pin } : {}));
    viewing = true; note(lastHash ? "" : "Getting the first picture…"); frames();
  } catch (e) { note(e.message === "Cancelled" ? "Tap ⋯ More → Resume the screen" : e.message); }
}
async function frames() {
  if (looping) return; looping = true;
  try {
    while (viewing) {
      if (document.hidden) { await sleep(600); continue; }
      let response;
      try { response = await rawGet("/api/screen/frame?h=" + lastHash); }
      catch { note("Can't reach the laptop. Retrying…"); await sleep(2000); continue; }
      const cursor = response.headers.get("X-Cursor");
      if (cursor && Date.now() - localMoveAt > 350) { try { cursorAt = JSON.parse(cursor); } catch {} }   // our own move wins briefly
      const monitor = response.headers.get("X-Monitor");
      if (monitor) { try { const m = JSON.parse(monitor); monitorPx = [m[2], m[3]]; } catch {} }
      if (response.status === 200) {
        lastHash = response.headers.get("X-Frame-Hash") || "";
        const url = URL.createObjectURL(await response.blob()), old = $("frame").src;
        $("frame").src = url; if (old.startsWith("blob:")) URL.revokeObjectURL(old);
        note(!old && innerHeight > innerWidth ? "Tip: turn the phone sideways or tap 🔍 for a bigger screen" : "");
        if (!old) setTimeout(() => { if ($("screen-note").textContent.startsWith("Tip")) note(""); }, 4000);
      } else if (response.status === 204) { note(""); }
      else {
        let message = "Retrying…"; try { message = (await response.json()).error || message; } catch {}
        if (response.status === 401) { viewing = false; if (relay) show("account"); else show("login"); break; }
        if (response.status === 403) { viewing = false; looping = false; return startScreen(); }   // ended or PIN: start again
        note(response.status === 429 ? "" : message);
        await sleep(response.status === 429 ? 1000 : 3000); continue;
      }
      drawCursor();
      await sleep(controlling ? 50 : 250);
    }
  } finally { looping = false; }
}
function frameRect() { return $("frame").getBoundingClientRect(); }
function drawCursor() {
  if (!cursorAt || !$("frame").naturalWidth) { $("cursor").hidden = true; return; }
  const img = frameRect(), canvas = $("canvas").getBoundingClientRect();
  $("cursor").style.left = (img.left - canvas.left + cursorAt[0] * img.width) + "px";
  $("cursor").style.top = (img.top - canvas.top + cursorAt[1] * img.height) + "px";
  $("cursor").hidden = false;
  if ($("stage").classList.contains("zoomed")) {   // keep the pointer in view while zoomed in
    const stage = $("stage"), x = cursorAt[0] * img.width, y = cursorAt[1] * img.height;
    if (x < stage.scrollLeft + 40 || x > stage.scrollLeft + stage.clientWidth - 40) stage.scrollLeft = x - stage.clientWidth / 2;
    if (y < stage.scrollTop + 40 || y > stage.scrollTop + stage.clientHeight - 40) stage.scrollTop = y - stage.clientHeight / 2;
  }
}
$("frame").addEventListener("load", drawCursor);
window.addEventListener("resize", drawCursor);
$("screen-go").addEventListener("click", () => { closeSheets(); startScreen(); });
$("screen-stop").addEventListener("click", () => { viewing = false; note("Screen paused. Tap ⋯ More → Resume the screen."); api("/api/screen/stop", {}).catch(() => {}); closeSheets(); });
document.addEventListener("visibilitychange", () => { if (!document.hidden && !$("app").hidden && !viewing && lastHash) startScreen(); });

// ---- control: starts by itself on the first touch, when the laptop allows it ------------------------------------------
function showControl() {
  $("control").classList.toggle("on", controlling); $("control-name").textContent = controlling ? "On" : "Control";
  $("stage").classList.toggle("controlling", controlling);
}
async function ensureControl() {
  if (controlling) return true;
  if (!controlAllowed) { status("Control is off. At the laptop say \"phone control on karo\" once."); return false; }
  try { await withPin("PIN to control the laptop", pin => api("/api/control/start", pin ? { pin } : {})); controlling = true; showControl(); return true; }
  catch (e) { status(e.message); return false; }
}
function stopControl() { controlling = false; showControl(); api("/api/control/stop", {}).catch(() => {}); status("Control ended"); }
$("control").addEventListener("click", () => controlling ? stopControl() : ensureControl());
$("control-stop").addEventListener("click", () => { stopControl(); closeSheets(); });
let inputs = Promise.resolve();
function queued(path, data) {   // in order, one at a time; a session that timed out is started again once
  inputs = inputs.then(() => api(path, data)).catch(async e => {
    if (/Start control/.test(e.message)) { controlling = false; showControl(); if (await ensureControl()) return api(path, data).catch(x => status(x.message)); }
    else status(e.message);
  });
  return inputs;
}
// Mouse input: ONE request in flight; whatever moved meanwhile rides along in the next one (PC check 2026-11-07: queued
// moves piled up behind ~100 ms Tailscale round trips, so the more you moved the further the pointer fell behind).
let pending = { dx: 0, dy: 0, events: [] }, inFlight = false, monitorPx = null, localMoveAt = 0;
function pump() {
  if (inFlight) return;
  const events = [];
  let dx = Math.round(pending.dx), dy = Math.round(pending.dy); pending.dx -= dx; pending.dy -= dy;
  while (dx || dy) { const sx = Math.max(-400, Math.min(400, dx)), sy = Math.max(-400, Math.min(400, dy)); events.push({ kind: "nudge", dx: sx, dy: sy }); dx -= sx; dy -= sy; }
  events.push(...pending.events.splice(0));
  if (!events.length) return;
  inFlight = true;
  api("/api/control/input", { events }).catch(async e => {
    if (/Start control/.test(e.message)) { controlling = false; showControl(); if (await ensureControl()) return api("/api/control/input", { events }).catch(x => status(x.message)); }
    else status(e.message);
  }).finally(() => { inFlight = false; if (pending.events.length || Math.abs(pending.dx) >= 1 || Math.abs(pending.dy) >= 1) pump(); });
}
const send = events => { pending.events.push(...events); pump(); };
const here = kind => send([{ kind, at: "cursor" }]);
function moveBy(dx, dy) {
  pending.dx += dx; pending.dy += dy; pump();
  if (cursorAt && monitorPx) {   // the pointer moves on the phone at once; the next frames correct it
    cursorAt = [Math.min(1, Math.max(0, cursorAt[0] + dx / monitorPx[0])), Math.min(1, Math.max(0, cursorAt[1] + dy / monitorPx[1]))];
    localMoveAt = Date.now(); drawCursor();
  }
}

// ---- touch on the screen: trackpad (default), tap where I touch, or ask about a spot ----------------------------------
const SPEED = 1.8, touches = new Map();
let gesture = null, pressTimer = null, dragging = false;
const mode = () => $("tap-mode").value;
function point(x, y) { const r = frameRect(); return { x: Math.min(1, Math.max(0, (x - r.left) / r.width)), y: Math.min(1, Math.max(0, (y - r.top) / r.height)) }; }
function setDragging(on) { dragging = on; $("stage").classList.toggle("dragging", on); if (on && navigator.vibrate) navigator.vibrate(25); }
$("stage").addEventListener("pointerdown", async e => {
  $("stage").setPointerCapture(e.pointerId); touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (touches.size === 1) {
    gesture = { at: Date.now(), travel: 0, fingers: 1, x: e.clientX, y: e.clientY, ready: mode() === "ask" || await ensureControl() };
    clearTimeout(pressTimer);
    pressTimer = setTimeout(() => {   // a still long-press: trackpad = drag, direct = right click
      if (!gesture || !gesture.ready || gesture.travel > 10 || touches.size !== 1) return;
      if (mode() === "pad") { setDragging(true); here("down"); }
      else if (mode() === "direct") { send([{ kind: "right", ...point(gesture.x, gesture.y) }]); gesture.used = true; }
    }, 450);
  } else if (gesture) gesture.fingers = Math.max(gesture.fingers, touches.size);
});
$("stage").addEventListener("pointermove", e => {
  const last = touches.get(e.pointerId); if (!last || !gesture) return;
  const dx = e.clientX - last.x, dy = e.clientY - last.y; touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
  gesture.travel += Math.abs(dx) + Math.abs(dy);
  if (!gesture.ready || mode() === "ask") return;
  if (touches.size >= 2) {   // two fingers: scroll
    gesture.scroll = (gesture.scroll || 0) + dy;
    if (Math.abs(gesture.scroll) > 22) { send([mode() === "direct" ? { kind: "scroll", ...point(e.clientX, e.clientY), dy: gesture.scroll > 0 ? 2 : -2 } : { kind: "scroll", at: "cursor", dy: gesture.scroll > 0 ? 2 : -2 }]); gesture.scroll = 0; }
    return;
  }
  if (mode() !== "pad") return;
  const accel = 1 + Math.min(Math.hypot(dx, dy) / 10, 2);   // slow = precise, fast = far
  moveBy(dx * SPEED * accel, dy * SPEED * accel);
});
for (const ev of ["pointerup", "pointercancel"]) $("stage").addEventListener(ev, async e => {
  touches.delete(e.pointerId); if (touches.size || !gesture) return;
  clearTimeout(pressTimer); const g = gesture; gesture = null;
  if (dragging) { here("up"); setDragging(false); return; }
  if (!g.ready || g.used || ev === "pointercancel") return;
  const tap = Date.now() - g.at < 300 && g.travel < 14; if (!tap) return;
  if (mode() === "ask") {
    const p = point(g.x, g.y), question = prompt("Is jagah ke baare mein kya karna hai? (\"ye kya hai\", \"isko band karo\")"); if (!question) return;
    openSheet("chat"); bubble("👆 " + question, "me"); const box = bubble("…", "her");
    try { const r = await api("/api/point", { x: p.x, y: p.y, question }); render(box, r.session); follow(box, r.session.id); } catch (err) { box.textContent = err.message; }
  } else if (mode() === "direct") send([{ kind: g.fingers >= 2 ? "right" : "tap", ...point(g.x, g.y) }]);
  else here(g.fingers >= 2 ? "right" : "tap");   // two quick taps make a double click on the laptop
});
$("mode").addEventListener("click", () => {
  const next = { pad: "direct", direct: "ask", ask: "pad" }[mode()]; $("tap-mode").value = next;
  $("mode-name").textContent = { pad: "Trackpad", direct: "Tap here", ask: "Ask" }[next];
});
$("tap-mode").addEventListener("change", () => { $("mode-name").textContent = { pad: "Trackpad", direct: "Tap here", ask: "Ask" }[mode()]; });
$("zoom").addEventListener("click", () => {
  const on = $("stage").classList.toggle("zoomed"); $("zoom-name").textContent = on ? "2x" : "Fit";
  $("zoom").classList.toggle("on", on); if (!on) { $("stage").scrollLeft = 0; $("stage").scrollTop = 0; } setTimeout(drawCursor, 50);
});

// ---- keyboard: the phone keyboard types live on the laptop; the key row sends single keys ----------------------------
// Phone keyboards rarely report keys, so the field keeps two spaces: shorter = Backspace, longer = new text.
const KEEP = "  "; $("live-keys").value = KEEP;
async function key(combo) {
  if (!await ensureControl()) return;
  if (combo === "alt+f4" && !confirm("Pakka band karun?")) return;
  queued("/api/control/keys", { combo }).then(() => {});
}
$("kbd").addEventListener("click", async () => { if (!await ensureControl()) return; $("live-keys").focus(); $("kbd").classList.add("on"); });
$("live-keys").addEventListener("blur", () => $("kbd").classList.remove("on"));
$("live-keys").addEventListener("input", () => {
  const value = $("live-keys").value; $("live-keys").value = KEEP;
  if (value.length < KEEP.length) { for (let i = value.length; i < KEEP.length; i++) queued("/api/control/keys", { combo: "backspace" }); return; }
  const text = value.slice(KEEP.length); if (text) queued("/api/control/text", { text });
});
$("live-keys").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); sendKeyWithPin("enter"); } });
async function sendKeyWithPin(combo) {   // Enter or paste into a command window needs the PIN every time
  try { await withPin("PIN: this window can run commands", pin => api("/api/control/keys", pin ? { combo, pin } : { combo })); }
  catch (e) { status(e.message); }
}
const KEY_ROW = [["Esc", "esc"], ["Tab", "tab"], ["Enter", "enter"], ["⌫", "backspace"], ["Del", "delete"], ["←", "left"], ["↑", "up"],
  ["↓", "down"], ["→", "right"], ["Ctrl+C", "ctrl+c"], ["Ctrl+V", "ctrl+v"], ["Ctrl+Z", "ctrl+z"], ["Ctrl+A", "ctrl+a"],
  ["Ctrl+S", "ctrl+s"], ["Alt+Tab", "alt+tab"], ["Desktop", "win+d"], ["Win", "win"], ["Home", "home"], ["End", "end"],
  ["PgUp", "pageup"], ["PgDn", "pagedown"], ["F5", "f5"], ["Close app", "alt+f4"]];
for (const [label, combo] of KEY_ROW) {
  const b = el("button", "", label);
  b.addEventListener("click", async () => { if (combo === "enter" || combo === "ctrl+v") { if (await ensureControl()) sendKeyWithPin(combo); } else key(combo); });
  $("keys").append(b);
}

// ---- sheets: Chutku, Files and More open over the screen --------------------------------------------------------------
function closeSheets() { for (const s of document.querySelectorAll(".sheet")) s.hidden = true; }
function openSheet(name) { closeSheets(); $("sheet-" + name).hidden = false; }
document.querySelectorAll("[data-sheet]").forEach(b => b.addEventListener("click", () => {
  const sheet = $("sheet-" + b.dataset.sheet); const open = sheet.hidden; closeSheets(); sheet.hidden = !open;
}));
document.querySelectorAll("[data-close]").forEach(b => b.addEventListener("click", closeSheets));

// ---- typing a whole text, clipboard ----------------------------------------------------------------------------------
async function typeText(enter) {
  const text = $("type-text").value; if ((!text && !enter) || !await ensureControl()) return;
  try { await withPin("PIN: this window can run commands", pin => api("/api/control/text", pin ? { text, enter, pin } : { text, enter })); $("type-text").value = ""; }
  catch (e) { status(e.message); }
}
$("type-send").addEventListener("click", () => typeText(false));
$("type-enter").addEventListener("click", () => typeText(true));
$("clip-get").addEventListener("click", async () => {
  try { const r = await withPin("PIN to read the laptop clipboard", pin => api("/api/clipboard/get", pin ? { pin } : {})); $("type-text").value = r.text; try { await navigator.clipboard.writeText(r.text); } catch {} status("Clipboard copied"); }
  catch (e) { status(e.message); }
});
$("clip-paste").addEventListener("click", async () => {
  const text = $("type-text").value; if (!text || !await ensureControl()) return;
  try { await withPin("PIN: this window can run commands", pin => api("/api/clipboard/set", pin ? { text, paste: true, pin } : { text, paste: true })); } catch (e) { status(e.message); }
});

// ---- P8: files ---------------------------------------------------------------------------------------------------------
$("upload-go").addEventListener("click", async () => {
  const file = $("upload-file").files[0]; if (!file) return;
  try { const r = await api("/api/files/upload?name=" + encodeURIComponent(file.name), file, true); $("upload-out").textContent = "Saved: " + r.saved; } catch (e) { $("upload-out").textContent = e.message; }
});
// Owner 2026-11-07: browse the laptop's files (no paths to remember), filtered by kind; download, share or view.
const ICON = { photo: "🖼", video: "🎬", pdf: "📕", doc: "📄", audio: "🎵", archive: "🗜", other: "📎" };
const MIME = { photo: "image/*", pdf: "application/pdf", video: "video/*" };
let fileKind = "all", fileView = { type: "recent" }, placesLoaded = false;
const size = n => n > 1e9 ? (n / 1e9).toFixed(1) + " GB" : n > 1e6 ? (n / 1e6).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1e3)) + " KB";
async function filesCall(path, body) { return withPin("PIN to see the laptop's files", pin => api(path, pin ? { ...body, pin } : body)); }
async function loadPlaces() {
  if (placesLoaded) return; placesLoaded = true;
  $("file-places").addEventListener("click", e => { if (e.target.tagName === "BUTTON") for (const b of $("file-places").children) b.classList.toggle("on", b === e.target); });
  try {
    const r = await filesCall("/api/files/places", {});
    const recent = el("button", "on", "🕘 Recent"); recent.addEventListener("click", () => loadFiles({ type: "recent" })); $("file-places").append(recent);
    for (const p of [...r.places, ...r.drives]) { const b = el("button", "", (r.drives.includes(p) ? "💽 " : "📁 ") + p.name); b.addEventListener("click", () => loadFiles({ type: "list", path: p.path })); $("file-places").append(b); }
  } catch (e) { placesLoaded = false; $("file-list").replaceChildren(el("p", "small", e.message)); }
}
async function loadFiles(view) {
  fileView = view || fileView; $("file-list").replaceChildren(el("p", "muted small", "Loading…"));
  try {
    const kind = fileKind;
    const r = fileView.type === "list" ? await filesCall("/api/files/list", { path: fileView.path, kind })
      : fileView.type === "search" ? await filesCall("/api/files/search", { q: fileView.q, kind })
      : await filesCall("/api/files/recent", { kind });
    $("file-crumb").replaceChildren();
    if (fileView.type === "list") {
      if (r.parent) { const up = el("button", "", "⬆ Up"); up.addEventListener("click", () => loadFiles({ type: "list", path: r.parent })); $("file-crumb").append(up); }
      $("file-crumb").append(el("span", "small", r.path));
    } else $("file-crumb").append(el("span", "small", fileView.type === "search" ? `Results for "${fileView.q}"` : "Newest files on the laptop"));
    const rows = [];
    for (const f of r.folders || []) { const row = el("button", "file folder", "📁 " + f.name); row.addEventListener("click", () => loadFiles({ type: "list", path: f.path })); rows.push(row); }
    for (const f of r.files || []) rows.push(fileRow(f));
    if (!rows.length) rows.push(el("p", "muted small", "Nothing here" + (fileKind === "all" ? "." : " of this kind.")));
    $("file-list").replaceChildren(...rows);
  } catch (e) { $("file-list").replaceChildren(el("p", "small", e.message)); }
}
function fileRow(f) {
  const row = el("div", "file"), top = el("button", "file-main");
  top.append(el("span", "file-icon", ICON[f.kind] || ICON.other), el("span", "file-name", f.name), el("span", "file-meta", size(f.size) + " · " + f.modified));
  const actions = el("div", "row file-actions"); actions.hidden = true;
  const get = el("button", "primary", "⬇ Download"), share = el("button", "", "↗ Share"), view = el("button", "", "👁 View");
  get.addEventListener("click", () => fetchFile(f).then(blob => { const a = el("a"); a.href = URL.createObjectURL(blob); a.download = f.name; a.click(); status("Downloaded " + f.name); }).catch(e => status(e.message)));
  share.addEventListener("click", () => fetchFile(f).then(blob => navigator.share({ files: [new File([blob], f.name, { type: blob.type })] })).catch(e => status(e.message)));
  view.addEventListener("click", () => fetchFile(f).then(blob => { $("file-view-img").src = URL.createObjectURL(blob); $("file-view").hidden = false; }).catch(e => status(e.message)));
  actions.append(get); if (navigator.canShare) actions.append(share); if (f.kind === "photo") actions.append(view);
  top.addEventListener("click", () => { actions.hidden = !actions.hidden; });
  row.append(top, actions); return row;
}
async function fetchFile(f) {
  if (f.size > 200e6) throw new Error("Files up to 200 MB.");
  status("Getting " + f.name + "…");
  const response = await withPin("PIN to fetch a laptop file", pin => api("/api/files/get", pin ? { path: f.path, pin } : { path: f.path }));
  const blob = await response.blob(); status("");
  return MIME[f.kind] && !MIME[f.kind].endsWith("*") ? new Blob([blob], { type: MIME[f.kind] }) : f.kind === "photo" ? new Blob([blob], { type: "image/" + (f.name.split(".").pop().toLowerCase().replace("jpg", "jpeg")) }) : blob;
}
$("file-search").addEventListener("submit", e => { e.preventDefault(); const q = $("file-q").value.trim(); if (q) loadFiles({ type: "search", q }); });
document.querySelectorAll("#file-kinds button").forEach(b => b.addEventListener("click", () => {
  fileKind = b.dataset.kind; document.querySelectorAll("#file-kinds button").forEach(x => x.classList.toggle("on", x === b)); loadFiles();
}));
$("file-view-close").addEventListener("click", () => { $("file-view").hidden = true; URL.revokeObjectURL($("file-view-img").src); });
document.querySelector('[data-sheet="files"]').addEventListener("click", () => { if (!$("sheet-files").hidden) { loadPlaces(); loadFiles(); } });

// ---- entering the app: everything starts by itself ---------------------------------------------------------------------
async function enterApp() { show("app"); await refresh(); startScreen(); }

// ---- the phone app: one account (ID + password made on the laptop), logged in once ------------------------------------
$("account-go").addEventListener("click", async () => {
  try {
    const id = $("account-id").value.trim().toLowerCase(), password = $("account-password").value;
    status("Securing the connection…");
    const keys = await ChutkuE2E.derive(password, id);   // the relay never receives the password itself
    let r;
    try { r = await api("/relay/login", { id, password: keys.auth, device: "phone", name: "phone app" }); }
    catch (first) {   // an account made before end-to-end encryption: upgrade it once
      r = await api("/relay/login", { id, password, device: "phone", name: "phone app" });
      store.token = r.token;
      await api("/relay/change", { password, new_id: null, new_password: keys.auth });
    }
    store.token = r.token; store.key = keys.raw; store.account = id; e2eKey = null;
    $("account-password").value = ""; status(r.id); await enterApp();
  } catch (e) { status(e.message); }
});
$("logout").addEventListener("click", async () => {
  if (!confirm("Log out of this phone?")) return;
  try { await api("/relay/logout", {}); } catch {}
  store.token = ""; store.key = ""; store.account = ""; e2eKey = null; show("account");
});
async function start() {
  try { const info = await fetch("/relay/info"); relay = info.ok && (await info.json()).relay === true; } catch { relay = false; }
  if (!relay) { show(store.credential ? "login" : "pair"); return; }
  if (!store.token) { show("account"); return; }
  status("…"); enterApp();
}
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
start();
