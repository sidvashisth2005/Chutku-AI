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
  for (const name of ["chat", "screen", "files"]) $("tab-" + name).hidden = name !== b.dataset.tab;
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
$("control-go").addEventListener("click", async () => { const pin = await askPin("PIN to control the laptop"); if (!pin) return; try { await api("/api/control/start", { pin }); controlling = true; $("tap-mode").value = "control"; status("Controlling"); } catch (e) { status(e.message); } });
$("control-stop").addEventListener("click", () => { controlling = false; api("/api/control/stop", {}).catch(() => {}); status("Control ended"); });

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
