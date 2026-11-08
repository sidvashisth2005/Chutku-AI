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

async function api(path, data, raw, pin) {
  const options = { credentials: "same-origin", headers: {} };
  if (pin) options.headers["X-Chutku-PIN"] = pin;   // a file upload's body is the file itself
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
// Owner 2026-11-08, "the message is cut off with ...": the status line is one line; over the screen the whole message
// shows wrapped for 4 s, and "resumes in N s" counts down live.
let toastTimer = null;
function status(text) {
  $("status").textContent = text;
  if ($("app").hidden) {   // 2026-11-08 review: on the Pair/Unlock cards the one-line header cut the reason off
    const card = ["account", "pair", "login"].map($).find(c => c && !c.hidden);
    if (card) { const p = card.querySelector(".card-error") || card.appendChild(el("p", "small card-error")); p.textContent = text || ""; }
    return;
  }
  const toast = $("toast"); if (!text) return;
  clearInterval(toastTimer); toast.hidden = false;
  const counting = /resumes in (\d+) s/.exec(text); let left = counting ? +counting[1] : 4;
  const draw = () => { toast.textContent = counting ? text.replace(/\d+ s/, left + " s") : text; };
  draw();
  toastTimer = setInterval(() => { left--; if (left <= 0) { clearInterval(toastTimer); toast.hidden = true; if ($("status").textContent === text) $("status").textContent = ""; } else draw(); }, 1000);
}
function askPin(why) {
  return new Promise(resolve => {
    $("pin-why").textContent = why || "Enter your PIN"; $("pin-input").value = "";
    $("pin-dialog").onclose = () => resolve($("pin-dialog").returnValue === "ok" ? $("pin-input").value : null);
    $("pin-dialog").showModal();
  });
}

// ---- P1: pairing and unlock ---------------------------------------------------------------------------------------
function codeFromLink() {   // also when the link opens in a tab that already shows the page (only the hash changes)
  const code = new URLSearchParams(location.hash.slice(1)).get("code");
  if (code) { $("pair-code").value = code; history.replaceState(null, "", "/"); }
}
codeFromLink(); window.addEventListener("hashchange", codeFromLink);
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
  const reply = (s.reply || "").replace(/\s*\[Verified:[^\]]*\]\s*$/, "");   // the tally is for the laptop's log
  box.replaceChildren(el("div", "", reply || (s.status === "done" ? "Done." : "…")));
  for (const step of s.steps || []) box.append(el("div", "step " + (step.state === "COMPLETED" ? "ok" : step.state === "FAILED" || step.state === "DENIED" ? "bad" : ""), step.purpose || step.tool));
  if (s.pending) {
    const card = el("div", "approval");
    card.append(el("strong", "", "Needs your OK: "), el("span", "", s.pending.consequence || s.pending.tool));
    if (s.pending.laptop_only) card.append(el("p", "small", "Ye laptop pe approve karna hoga."));
    else {
      const row = el("div", "row"), yes = el("button", "primary", "Approve"), no = el("button", "", "Cancel");
      for (const [button, approve] of [[yes, true], [no, false]]) button.addEventListener("click", async () => {
        try { const r = await withPin(approve ? "PIN to approve" : "PIN to cancel", pin => api("/api/approve", { id: s.id, approve, pin, nonce: s.pending.nonce })); render(box, r.session); follow(box, s.id); } catch (e) { status(e.message); }
      });
      row.append(yes, no); card.append(row);
    }
    box.append(card);
    $("log").scrollTop = 1e9;   // 2026-11-08 review: the card was added below the visible part of the chat
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
  try { await withPin("PIN to speak on the laptop", pin => api("/api/laptop/say", pin ? { text, pin } : { text })); $("laptop-text").value = ""; status("Laptop pe bol rahi hoon"); } catch (e) { status(e.message); }
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
    const r = await withPin("PIN to see the laptop screen", pin => api("/api/screen/start", pin ? { pin } : {}));
    if (r && r.monitor) monitorPx = [r.monitor[2], r.monitor[3]];
    viewing = true; note(lastHash || streaming ? "" : "Getting the first picture…");
    if (!relay && streamFails < 3) { attachStream(); measureLink(); } else frames();   // the relay can't carry a stream: frame by frame
  } catch (e) { note(e.message === "Cancelled" ? "Tap ⋯ More → Resume the screen" : e.message); }
}
// Owner 2026-11-07, "frames are still laggy": on the tailnet the screen is one continuous MJPEG stream (~18 frames/s),
// not a request per picture. Three failed streams in a row fall back to frame by frame.
// It is read here, not by <img src=stream>: Chrome shows an MJPEG part only when the NEXT one arrives (measured: every
// frame one frame late, the last change of a burst ~2 s late until the keep-alive); read here, each frame shows as soon
// as its last byte is in (measured 22-60 ms).
let streamFails = 0, streaming = false, resumeStream = false, streamStop = null;
function attachStream() {
  streaming = true; cursorAt = null; $("cursor").hidden = true;
  if (streamStop) streamStop.abort();
  const stop = streamStop = new AbortController();
  watchScreen(stop.signal).catch(() => {}).finally(() => {
    if (streamStop !== stop || !streaming) return;   // replaced or stopped on purpose
    streaming = false; streamFails++; note("Reconnecting the screen…");
    setTimeout(() => { if (!document.hidden && !$("app").hidden) startScreen(); }, 1000);
  });
  if (!watching) openPointer();   // Watch sends only video and sound
}
async function readStream(signal) {   // multipart parts, each with Content-Length: show each the moment it is complete
  const response = await fetch("/api/screen/stream?w=1280&t=" + Date.now(), { credentials: "same-origin", signal });
  if (!response.ok || !response.body) throw new Error("no stream");
  const reader = response.body.getReader(), ascii = new TextDecoder("latin1");
  let buf = new Uint8Array(0);
  for (;;) {
    const { value, done } = await reader.read(); if (done) return;
    const joined = new Uint8Array(buf.length + value.length); joined.set(buf); joined.set(value, buf.length); buf = joined;
    for (;;) {
      const text = ascii.decode(buf.subarray(0, Math.min(buf.length, 512))), head = text.indexOf("\r\n\r\n");
      if (head < 0) break;
      const length = /content-length:\s*(\d+)/i.exec(text.slice(0, head)), start = head + 4;
      if (!length) { buf = buf.subarray(start); continue; }
      if (buf.length < start + +length[1]) break;
      showFrame(buf.slice(start, start + +length[1])); buf = buf.subarray(start + +length[1]);
    }
  }
}
function showFrame(jpeg) {
  const url = URL.createObjectURL(new Blob([jpeg], { type: "image/jpeg" })), old = $("frame").src;
  $("frame").src = url; if (old.startsWith("blob:")) URL.revokeObjectURL(old);
  showing("frame"); streamFails = 0; note("");
}
function detachStream() {
  streaming = false; if (streamStop) { streamStop.abort(); streamStop = null; } $("frame").removeAttribute("src");
  if (pointerFeed) { pointerFeed.close(); pointerFeed = null; }
}
// Owner 2026-11-08, "no lag or jitter": H.264 first (~4-7 KB a frame instead of ~100 KB of JPEG, decoded by the phone's
// own video hardware through WebCodecs, drawn on a canvas), the JPEG stream when this phone or the laptop can't.
let videoWorks = "VideoDecoder" in window;
async function watchScreen(signal) {
  if (videoWorks) {
    const shown = { any: false };
    try { await readVideo(signal, shown); return; }
    catch (e) { if (signal.aborted || shown.any) throw e; videoWorks = false; }   // never worked here: JPEG from now on
  }
  await readStream(signal);
}
const picture = () => $("video").hidden ? $("frame") : $("video");
const pictureReady = () => $("video").hidden ? $("frame").naturalWidth > 0 : $("video").width > 0;
function showing(id) { if (picture().id === id) return; $("video").hidden = id !== "video"; $("frame").hidden = id !== "frame"; drawCursor(); }
function avcCodec(data) {   // "avc1.PPCCLL" from the keyframe's SPS (profile, constraints, level)
  for (let i = 0; i + 4 < data.length; i++) {
    if (data[i] === 0 && data[i + 1] === 0 && data[i + 2] === 1 && (data[i + 3] & 0x1f) === 7) {
      return "avc1." + [data[i + 4], data[i + 5], data[i + 6]].map(b => b.toString(16).padStart(2, "0")).join("");
    }
  }
  return "avc1.42e01f";
}
// Smooth playback (owner 2026-11-08, "audio laggy and cracking, video too: smoothness is the real issue"). Over
// Tailscale's relay packets bunch up and stall. Every packet now carries the laptop's capture time; each stream learns
// its fastest delivery (offset) and how late packets usually are (95th percentile), and plays everything that much
// after capture, at the spacing it was captured with: lateness is absorbed instead of heard as a crack or seen as a jerk.
function arrivals() {
  const late = [];
  return { offset: null, late95: 0,
    note(capture) {
      const seen = performance.now() - capture;
      if (this.offset === null || Math.abs(seen - this.offset) > 3e8) { this.offset = seen; late.length = 0; }   // new, or the clock wrapped
      else if (seen < this.offset) this.offset = seen;
      else this.offset += 0.002;   // follows a slow drift between the two clocks
      late.push(seen - this.offset); if (late.length > 120) late.shift();
      this.late95 = [...late].sort((a, b) => a - b)[Math.floor(late.length * 0.95)] || 0;
    } };
}
function videoDelay(clock) {   // ms after the fastest delivery: snappy (<= 80) while controlling; in Watch smooth, with the sound
  let want = Math.min(80, clock.late95);
  if (watching) {
    want = Math.min(400, Math.max(60, clock.late95));
    if (sound.on && sound.clock && sound.clock.offset !== null && sound.ctx)   // lips in time with the voice
      want = Math.min(800, Math.max(want, sound.clock.offset + sound.level * 1000 + (sound.ctx.outputLatency || 0) * 1000 - clock.offset));
  }
  // it moves by at most 2 ms a screen refresh: a jumping delay shakes the picture as much as a late frame (measured)
  clock.delay = clock.delay === undefined ? want : clock.delay + Math.max(-2, Math.min(2, want - clock.delay));
  return clock.delay;
}
async function readVideo(signal, shown) {   // packets: [4-byte length][1 byte: 1 = keyframe][4-byte capture ms][H.264 Annex B]
  const quality = usedQuality = watching ? "w=1920&kbps=" + watchKbps() : normalQuality();   // never more than the link carries
  const response = await fetch("/api/screen/h264?" + quality + "&t=" + Date.now(), { credentials: "same-origin", signal });
  if (!response.ok || !response.body) throw new Error("no video");
  const canvas = $("video"), paint = canvas.getContext("2d"), reader = response.body.getReader(), clock = arrivals(), queue = [];
  let decoder = null, broken = null, buf = new Uint8Array(0);
  const giveUp = setTimeout(() => { if (!shown.any) { broken = new Error("no frames"); reader.cancel().catch(() => {}); } }, 4000);
  const present = () => {   // every screen refresh: show the newest frame that is due
    if (signal.aborted || broken) { queue.splice(0).forEach(f => f.close()); return; }
    const due = performance.now() - clock.offset - videoDelay(clock);
    let frame = null;
    while (queue.length && queue[0].timestamp / 1000 <= due) { if (frame) frame.close(); frame = queue.shift(); }
    if (frame) {
      if (canvas.width !== frame.displayWidth) { canvas.width = frame.displayWidth; canvas.height = frame.displayHeight; }
      paint.drawImage(frame, 0, 0); frame.close();
      if (!shown.any) { shown.any = true; clearTimeout(giveUp); showing("video"); }
      streamFails = 0; note("");
    }
    requestAnimationFrame(present);
  };
  requestAnimationFrame(present);
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (broken) throw broken;
      if (done) return;
      const joined = new Uint8Array(buf.length + value.length); joined.set(buf); joined.set(value, buf.length); buf = joined;
      while (buf.length >= 9) {
        const length = ((buf[0] << 24) | (buf[1] << 16) | (buf[2] << 8) | buf[3]) >>> 0;
        if (buf.length < 9 + length) break;
        const key = (buf[4] & 1) === 1, capture = ((buf[5] << 24) | (buf[6] << 16) | (buf[7] << 8) | buf[8]) >>> 0;
        const data = buf.slice(9, 9 + length); buf = buf.subarray(9 + length);
        clock.note(capture);
        if (!decoder) {
          if (!key) continue;
          decoder = new VideoDecoder({
            output: frame => { queue.push(frame); if (queue.length > 30) queue.shift().close(); },
            error: e => { broken = e; },
          });
          decoder.configure({ codec: avcCodec(data), optimizeForLatency: true });
        }
        decoder.decode(new EncodedVideoChunk({ type: key ? "key" : "delta", timestamp: capture * 1000, data }));
      }
    }
  } finally {
    clearTimeout(giveUp); broken = broken || new Error("ended");
    if (decoder && decoder.state !== "closed") decoder.close();
  }
}
// Owner 2026-11-07, "the cursor still lags": like Chrome Remote Desktop, RustDesk and Parsec, the pointer is not in the
// video. The phone draws it and moves it the instant your finger moves; the laptop's real position (a tiny event stream,
// checked 60 times a second) corrects it once you stop, and shows moves made at the laptop itself.
let pointerFeed = null, serverAt = null, settle = null;
function openPointer() {
  if (pointerFeed) pointerFeed.close();
  pointerFeed = new EventSource("/api/cursor/stream");
  pointerFeed.onmessage = e => {
    try { serverAt = JSON.parse(e.data); } catch { return; }
    if (Date.now() - localMoveAt > 400 && !inFlight) glideTo(serverAt);   // your own move wins until the laptop caught up
  };
  pointerFeed.addEventListener("hover", e => { try { hovered = JSON.parse(e.data); } catch { hovered = null; } showHover(); });
}

// ---- smart tap, the magnetic pointer and text fields (owner 2026-11-08) --------------------------------------------
// The laptop reads its own buttons, links and fields (Windows UI Automation), which a plain remote desktop can't: the
// button under the pointer is outlined here, the pointer slows down over small ones so it stops on them, a tap that
// was a little off lands on what it meant (and flashes it), and a tap on a text field zooms to it and opens the keyboard.
let hovered = null;
function placeOn(box, r) {   // r: [x, y, w, h] as 0..1 of the laptop screen
  const img = frameRect(), canvas = $("canvas").getBoundingClientRect();
  Object.assign(box.style, { left: img.left - canvas.left + r[0] * img.width + "px", top: img.top - canvas.top + r[1] * img.height + "px",
                             width: r[2] * img.width + "px", height: r[3] * img.height + "px" });
}
function showHover() { $("hilite").hidden = !hovered; if (hovered) placeOn($("hilite"), hovered.rect); }
const small = r => r[2] < 0.2 && r[3] < 0.12;
const inside = (p, r) => p[0] >= r[0] && p[0] <= r[0] + r[2] && p[1] >= r[1] && p[1] <= r[1] + r[3];
function hit(target) {
  const flash = $("flash"); placeOn(flash, target.rect); flash.hidden = false;
  flash.classList.remove("go"); void flash.offsetWidth; flash.classList.add("go");
  clearTimeout(flash.timer); flash.timer = setTimeout(() => { flash.hidden = true; }, 650);
  if (target.kind === "field") typeInto(target.rect);
}
function typeInto(r) {   // at Fit: zoom until the field is ~40 px tall (readable) but still fits; upper third; keyboard
  if (zoom === 1) {
    const img = frameRect(), fieldW = Math.max(1, r[2] * img.width), fieldH = Math.max(1, r[3] * img.height);
    const want = Math.min(4, 0.95 * $("stage").clientWidth / fieldW, Math.max(1.5, 40 / fieldH));
    setZoom(want, img.left + (r[0] + r[2] / 2) * img.width, img.top + (r[1] + r[3] / 2) * img.height);
  }
  const stage = $("stage"), box = stage.getBoundingClientRect(), img = frameRect();
  stage.scrollLeft += img.left + (r[0] + r[2] / 2) * img.width - (box.left + stage.clientWidth / 2);
  stage.scrollTop += img.top + (r[1] + r[3] / 2) * img.height - (box.top + stage.clientHeight * 0.3);
  drawCursor(); $("live-keys").focus({ preventScroll: true }); $("kbd").classList.add("on");
}
function glideTo(at) { cursorAt = at; $("cursor").classList.add("glide"); drawCursor(); }
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
function frameRect() { return picture().getBoundingClientRect(); }   // the H.264 canvas or the JPEG <img>
function drawCursor(follow) {
  if (!cursorAt || !pictureReady()) {   // the position can arrive before the first picture: try again shortly
    $("cursor").hidden = true; if (cursorAt && streaming) setTimeout(drawCursor, 250); return;
  }
  const img = frameRect(), canvas = $("canvas").getBoundingClientRect();
  $("cursor").style.left = (img.left - canvas.left + cursorAt[0] * img.width) + "px";
  $("cursor").style.top = (img.top - canvas.top + cursorAt[1] * img.height) + "px";
  $("cursor").hidden = false;
  if (hovered) placeOn($("hilite"), hovered.rect);   // zoom and turning move the picture: the outline follows
  // keep the pointer in view while zoomed in, when YOU move it (new frames alone never pull the view off what you zoomed into)
  if (follow === true && $("stage").classList.contains("zoomed")) {
    const stage = $("stage"), x = img.left - canvas.left + cursorAt[0] * img.width, y = img.top - canvas.top + cursorAt[1] * img.height;
    if (x < stage.scrollLeft + 40 || x > stage.scrollLeft + stage.clientWidth - 40) stage.scrollLeft = x - stage.clientWidth / 2;
    if (y < stage.scrollTop + 40 || y > stage.scrollTop + stage.clientHeight - 40) stage.scrollTop = y - stage.clientHeight / 2;
  }
}
$("frame").addEventListener("load", drawCursor);
window.addEventListener("resize", drawCursor);
// owner 2026-11-07: sideways = full screen (no browser bar). Browsers allow it only from a touch, so the first touch after
// turning does it; upright leaves it. If you leave full screen yourself while sideways, it stays off until you turn again.
const sideways = matchMedia("(orientation: landscape) and (max-height: 540px)");
let autoFull = true;
function goFull() {
  if (autoFull && sideways.matches && !$("app").hidden && !document.fullscreenElement && document.documentElement.requestFullscreen)
    document.documentElement.requestFullscreen({ navigationUI: "hide" }).catch(() => {});
}
document.addEventListener("pointerup", goFull, true);
sideways.addEventListener("change", () => {
  if (sideways.matches) { autoFull = true; goFull(); }
  else if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
});
document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement && sideways.matches) autoFull = false; });
$("screen-go").addEventListener("click", () => { closeSheets(); startScreen(); });
$("screen-stop").addEventListener("click", () => { viewing = false; detachStream(); note("Screen paused. Tap ⋯ More → Resume the screen."); api("/api/screen/stop", {}).catch(() => {}); closeSheets(); });
document.addEventListener("visibilitychange", () => {   // a hidden page stops the stream (data, battery); back = resume
  if (document.hidden) { if (streaming) { detachStream(); resumeStream = true; } }
  else if (!$("app").hidden && (resumeStream || (!viewing && lastHash))) { resumeStream = false; startScreen(); }
});

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
// Mouse input: whatever moved meanwhile rides along in the next request (PC check 2026-11-07: queued moves piled up
// behind ~100 ms Tailscale round trips, so the more you moved the further the pointer fell behind).
let pending = { dx: 0, dy: 0, events: [] }, inFlight = 0, monitorPx = null, localMoveAt = 0;
// Owner 2026-11-08, "almost instant": moves go out up to 3 at a time (the laptop applies them one by one, none lost),
// so its pointer follows ~3x more often over the ~90 ms relay; clicks and drags wait for the moves before them.
const MOVES_IN_FLIGHT = 3;
function pump() {
  const clicks = pending.events.some(e => !e.again);   // a double tap's second tap goes at once (the laptop keeps order)
  if (clicks ? inFlight > 0 : inFlight >= MOVES_IN_FLIGHT) return;
  const events = [];
  let dx = Math.round(pending.dx), dy = Math.round(pending.dy); pending.dx -= dx; pending.dy -= dy;
  while (dx || dy) { const sx = Math.max(-400, Math.min(400, dx)), sy = Math.max(-400, Math.min(400, dy)); events.push({ kind: "nudge", dx: sx, dy: sy }); dx -= sx; dy -= sy; }
  events.push(...pending.events.splice(0));
  if (!events.length) return;
  inFlight++;
  api("/api/control/input", { events }).then(answer => { if (answer && answer.target) hit(answer.target); }).catch(async e => {
    if (/Start control/.test(e.message)) { controlling = false; showControl(); if (await ensureControl()) return api("/api/control/input", { events }).catch(x => status(x.message)); }
    else status(e.message);
  }).finally(() => { inFlight--; if (pending.events.length || Math.abs(pending.dx) >= 1 || Math.abs(pending.dy) >= 1) pump(); });
}
const send = events => { pending.events.push(...events); pump(); };
// smart tap (owner 2026-11-08): taps carry a finger's reach (as a part of the laptop screen's width); the laptop lands
// them on the button, link or field they were meant for and says which, so it is shown here
const reach = px => px / Math.max(1, frameRect().width);
const here = kind => send([{ kind, at: "cursor" }]);   // drag: press and release where the pointer is
function moveBy(dx, dy) {
  if (hovered && cursorAt && small(hovered.rect) && inside(cursorAt, hovered.rect)) { dx *= 0.45; dy *= 0.45; }   // magnetic
  pending.dx += dx; pending.dy += dy; pump();
  if (cursorAt && monitorPx) {   // the pointer moves on the phone at once; the next frames correct it
    cursorAt = [Math.min(1, Math.max(0, cursorAt[0] + dx / monitorPx[0])), Math.min(1, Math.max(0, cursorAt[1] + dy / monitorPx[1]))];
    localMoveAt = Date.now(); $("cursor").classList.remove("glide"); drawCursor(true);
    clearTimeout(settle); settle = setTimeout(() => { if (serverAt && !inFlight && streaming) glideTo(serverAt); }, 450);
  }
}

// ---- touch on the screen: trackpad (default), tap where I touch, or ask about a spot ----------------------------------
const SPEED = 1.8, touches = new Map();
let gesture = null, pressTimer = null, dragging = false;
const mode = () => $("tap-mode").value;
function point(x, y) { const r = frameRect(); return { x: Math.min(1, Math.max(0, (x - r.left) / r.width)), y: Math.min(1, Math.max(0, (y - r.top) / r.height)) }; }
function setDragging(on) { dragging = on; $("stage").classList.toggle("dragging", on); if (on && navigator.vibrate) navigator.vibrate(25); }
$("stage").addEventListener("pointerdown", async e => {
  if (watching) return;   // Watch: the screen is only watched
  if ("speechSynthesis" in window && speechSynthesis.speaking) speechSynthesis.cancel();   // a touch stops reading aloud
  $("stage").setPointerCapture(e.pointerId); touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (touches.size === 1) {
    const g = gesture = { at: Date.now(), travel: 0, fingers: 1, x: e.clientX, y: e.clientY, ready: false };   // zoom works before control
    g.ready = mode() === "ask" || await ensureControl();
    if (gesture !== g) return;
    clearTimeout(pressTimer);
    pressTimer = setTimeout(() => {   // a still long-press: trackpad = drag, direct = right click
      if (!gesture || !gesture.ready || gesture.travel > 10 || touches.size !== 1) return;
      if (mode() === "pad") { setDragging(true); here("down"); }
      else if (mode() === "direct") {   // on text: read it aloud here; anywhere else: right click
        const at = point(gesture.x, gesture.y); gesture.used = true;
        readAloud(at).then(read => { if (!read) send([{ kind: "right", ...at, snap: reach(22) }]); });
      }
    }, 450);
  } else if (gesture) gesture.fingers = Math.max(gesture.fingers, touches.size);
});
$("stage").addEventListener("pointermove", e => {
  const last = touches.get(e.pointerId); if (!last || !gesture) return;
  const dx = e.clientX - last.x, dy = e.clientY - last.y; touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
  gesture.travel += Math.abs(dx) + Math.abs(dy);
  if (touches.size >= 3 || gesture.three) {   // three fingers, as on a Windows touchpad (owner 2026-11-08)
    gesture.used = true;
    if (touches.size < 3) return;
    const all = [...touches.values()], c = { x: all.reduce((s, p) => s + p.x, 0) / all.length, y: all.reduce((s, p) => s + p.y, 0) / all.length };
    const three = gesture.three = gesture.three || { start: c, done: false };
    const mx = c.x - three.start.x, my = c.y - three.start.y;
    if (!three.done && gesture.ready && Math.max(Math.abs(mx), Math.abs(my)) > 60) {   // up: all windows; down: desktop; sideways: switch app
      three.done = true; key(Math.abs(my) > Math.abs(mx) ? (my < 0 ? "win+tab" : "win+d") : "alt+tab");
    }
    return;
  }
  if (touches.size >= 2) {   // two fingers: a pinch zooms the view here on the phone; moving together scrolls the laptop
    const [a, b] = [...touches.values()], dist = Math.hypot(a.x - b.x, a.y - b.y), mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    const two = gesture.two = gesture.two || { dist, mid, kind: null };
    if (!two.kind) two.kind = Math.abs(dist - two.dist) > 24 ? "pinch" : Math.abs(mid.y - two.mid.y) > 22 ? "scroll"
      : Math.abs(mid.x - two.mid.x) > 22 ? "hscroll" : null;
    if (two.kind === "pinch") {
      gesture.used = true;
      $("stage").scrollLeft += two.mid.x - mid.x; $("stage").scrollTop += two.mid.y - mid.y;   // the fingers also pan
      setZoom(zoom * dist / two.dist, mid.x, mid.y); two.dist = dist; two.mid = mid;
      return;
    }
    if (two.kind !== "scroll" && two.kind !== "hscroll") return;
  } else if (gesture.used && gesture.two) return;   // one finger left after a pinch: not a trackpad move
  else if (zoom > 1 && mode() !== "pad") { $("stage").scrollLeft -= dx; $("stage").scrollTop -= dy; return; }   // pan the zoomed view
  if (!gesture.ready || mode() === "ask") return;
  if (touches.size >= 2) {   // two fingers moving together: scroll (sideways too), the page follows the fingers
    const sideways = gesture.two && gesture.two.kind === "hscroll";
    gesture.scroll = (gesture.scroll || 0) + (sideways ? dx : dy);
    if (Math.abs(gesture.scroll) > 22) {
      const where = mode() === "direct" ? point(e.clientX, e.clientY) : { at: "cursor" };
      send([sideways ? { kind: "hscroll", ...where, dx: gesture.scroll > 0 ? -2 : 2 } : { kind: "scroll", ...where, dy: gesture.scroll > 0 ? 2 : -2 }]);
      gesture.scroll = 0;
    }
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
    return;
  }
  // Double tap (owner 2026-11-08): a second tap within 400 ms and 40 px repeats the first one exactly (a finger lands a
  // few px off, which is more than Windows' 4 px double-click box) and is sent at once, so Windows sees a double click.
  const again = lastTap && g.fingers === 1 && Date.now() - lastTap.at < 400 && Math.hypot(g.x - lastTap.x, g.y - lastTap.y) < 40;
  const event = again ? { ...lastTap.event, again: true }
    : mode() === "direct" ? { kind: g.fingers >= 2 ? "right" : "tap", ...point(g.x, g.y), snap: reach(22) }
    : { kind: g.fingers >= 2 ? "right" : "tap", at: "cursor", snap: reach(10) };
  lastTap = again || g.fingers > 1 ? null : { at: Date.now(), x: g.x, y: g.y, event };
  send([event]);
});
let lastTap = null;
$("mode").addEventListener("click", () => {
  const next = { pad: "direct", direct: "ask", ask: "pad" }[mode()]; $("tap-mode").value = next;
  $("mode-name").textContent = { pad: "Trackpad", direct: "Tap here", ask: "Ask" }[next];
});
$("tap-mode").addEventListener("change", () => { $("mode-name").textContent = { pad: "Trackpad", direct: "Tap here", ask: "Ask" }[mode()]; });
// ---- zoom (owner 2026-11-07): pinch into one part of the screen to see small text or close buttons, then tap there ----
let zoom = 1, fitWidth = 0;
function setZoom(z, cx, cy) {   // (cx, cy): the spot on the phone that stays under your fingers
  const stage = $("stage"), before = frameRect();
  if (zoom === 1) fitWidth = before.width;
  z = Math.min(6, Math.max(1, z)); if (z < 1.05) z = 1;
  const fx = (cx - before.left) / before.width, fy = (cy - before.top) / before.height;
  // zoomed: half a screen of black around the picture, so any spot (even a corner) can come under your fingers
  const padX = stage.clientWidth / 2, padY = stage.clientHeight / 2;
  zoom = z; stage.classList.toggle("zoomed", z > 1);
  Object.assign($("canvas").style, z > 1 ? { width: fitWidth * z + 2 * padX + "px", padding: `${padY}px ${padX}px` } : { width: "", padding: "" });
  if (z > 1) { const after = frameRect(); stage.scrollLeft += after.left + fx * after.width - cx; stage.scrollTop += after.top + fy * after.height - cy; }
  else { stage.scrollLeft = 0; stage.scrollTop = 0; }
  $("zoom-name").textContent = z > 1 ? z.toFixed(1) + "x" : "Fit"; $("zoom").classList.toggle("on", z > 1);
  drawCursor();
}
$("zoom").addEventListener("click", () => {   // zoomed: back to Fit; at Fit: 2x on the middle of the screen
  const r = frameRect(); setZoom(zoom > 1 ? 1 : 2, r.left + r.width / 2, r.top + r.height / 2);
});

// ---- owner 2026-11-08: laptop sound, Watch, the window switcher, voice click / typing, read aloud, speed test --------
// Sound: the laptop's own sound (what its speakers play) as Opus, decoded here (WebCodecs) into a jitter buffer (an
// AudioWorklet ring) that starts once it holds the usual lateness + 40 ms (100-500 ms) and plays at an even pace; if
// it ever runs dry it fades out and in (5 ms) instead of cracking, and after a burst it skips back to that target.
const sound = { on: false, ctx: null, node: null, stop: null, clock: null, buffered: 0, level: 0, under: 0 };
async function soundOutput() {
  if (sound.node) return;
  sound.ctx = new AudioContext({ sampleRate: 48000, latencyHint: "playback" });
  await sound.ctx.audioWorklet.addModule("/jitter.js");   // a real file: the page only runs scripts from the laptop (CSP)
  sound.node = new AudioWorkletNode(sound.ctx, "chutku-jitter", { numberOfInputs: 0, outputChannelCount: [2] });
  sound.node.port.onmessage = e => {   // level: the cushion averaged over ~1.5 s (it swings as bursts arrive)
    sound.buffered = e.data.filled; sound.under = e.data.under; sound.level += (e.data.filled - sound.level) * 0.03;
  };
  sound.node.connect(sound.ctx.destination);
}
async function setSound(on) {
  sound.on = on; $("sound").classList.toggle("on", on); $("sound").firstChild.textContent = on ? "🔊" : "🔈";
  if (sound.stop) { sound.stop.abort(); sound.stop = null; }
  if (sound.node) sound.node.port.postMessage({ clear: true });
  if (!on) return;
  if (!("AudioDecoder" in window) || !window.AudioWorkletNode) { status("This browser can't play the laptop's sound."); return setSound(false); }
  try { await soundOutput(); await sound.ctx.resume(); } catch { status("This phone can't play the laptop's sound."); return setSound(false); }
  const stop = sound.stop = new AbortController();
  playSound(stop.signal).catch(e => {
    if (e.message === "nosound") { status("The laptop has no sound device to send from."); setSound(false); }
  }).finally(() => { if (sound.stop === stop && sound.on) setTimeout(() => { if (sound.stop === stop && sound.on) setSound(true); }, 1500); });
}
async function playSound(signal) {   // packets: [4-byte length][4-byte capture ms][Opus 20 ms]
  const response = await fetch("/api/screen/audio?t=" + Date.now(), { credentials: "same-origin", signal });
  if (response.status === 409) throw new Error("nosound");
  if (!response.ok || !response.body) throw new Error("no sound stream");
  const reader = response.body.getReader(), clock = sound.clock = arrivals();
  const decoder = new AudioDecoder({
    output: data => {
      const n = data.numberOfFrames, l = new Float32Array(n), r = new Float32Array(n);
      data.copyTo(l, { planeIndex: 0, format: "f32-planar" });
      data.copyTo(r, { planeIndex: Math.min(1, data.numberOfChannels - 1), format: "f32-planar" });
      data.close();
      sound.node.port.postMessage({ l, r }, [l.buffer, r.buffer]);
    },
    error: () => {},
  });
  decoder.configure({ codec: "opus", sampleRate: 48000, numberOfChannels: 2 });
  let buf = new Uint8Array(0), target = 0, floor = 0, dry = sound.under;
  try {
    for (;;) {
      const { value, done } = await reader.read(); if (done) return;
      const joined = new Uint8Array(buf.length + value.length); joined.set(buf); joined.set(value, buf.length); buf = joined;
      while (buf.length >= 8) {
        const length = ((buf[0] << 24) | (buf[1] << 16) | (buf[2] << 8) | buf[3]) >>> 0;
        if (buf.length < 8 + length) break;
        const capture = ((buf[4] << 24) | (buf[5] << 16) | (buf[6] << 8) | buf[7]) >>> 0;
        clock.note(capture);
        decoder.decode(new EncodedAudioChunk({ type: "key", timestamp: capture * 1000, data: buf.slice(8, 8 + length) }));
        buf = buf.subarray(8 + length);
        if (sound.under > dry) { dry = sound.under; floor = Math.min(0.5, floor + 0.05); }   // it ran dry: keep 50 ms more
        const want = Math.min(0.5, Math.max(watching ? 0.15 : 0.1, floor, (clock.late95 + 40) / 1000));   // seconds of cushion
        if (Math.abs(want - target) > 0.01) { target = want; sound.node.port.postMessage({ target }); }
      }
    }
  } finally { if (decoder.state !== "closed") decoder.close(); }
}
$("sound").addEventListener("click", () => setSound(!sound.on));

// Watch: only the laptop's picture and sound, full screen, sharper (1920 wide, ~70% of the measured speed); no pointer
// stream, no buttons. The ✕ brings everything back as it was.
let watching = false, soundBeforeWatch = false, measuredKbps = +kept("chutku-kbps") || 0;
const watchKbps = () => Math.round(Math.min(8000, Math.max(1500, measuredKbps ? measuredKbps * 0.7 : 2500)));
// Owner 2026-11-08, "faster": the video never asks for more than the link carries (over Tailscale's relay a full
// buffer is seconds of lag). The link is measured once a session in the background (1 MB, kept 15 min) or by the
// speed test; the everyday view uses half of it (0.5-3 Mbit/s), 960 px wide below 1.5 Mbit/s.
let measuredAt = +kept("chutku-kbps-at") || 0, usedQuality = "";
const normalQuality = () => { const link = measuredKbps || 4000;
  return `w=${link < 1500 ? 960 : 1280}&kbps=${Math.round(Math.min(3000, Math.max(500, link * 0.5)))}`; };
function setLink(kbps) { measuredKbps = kbps; measuredAt = Date.now(); keep("chutku-kbps", String(Math.round(kbps))); keep("chutku-kbps-at", String(measuredAt)); }
async function measureLink() {
  if (relay || Date.now() - measuredAt < 15 * 60000) return;
  try {
    const t = performance.now(), r = await fetch("/api/speedtest?mb=1&t=" + Date.now(), { credentials: "same-origin" });
    if (r.ok) setLink((await r.arrayBuffer()).byteLength * 8 / ((performance.now() - t) / 1000) / 1000);
  } catch {}
  if (streaming && !watching && videoWorks && usedQuality && usedQuality !== normalQuality()) attachStream();   // the right size now
}
function setWatch(on) {
  if (on === watching) return;
  watching = on; document.body.classList.toggle("watch", on); $("watch").classList.toggle("on", on);
  if (on) {
    closeSheets(); setZoom(1, 0, 0); soundBeforeWatch = sound.on;
    if (pointerFeed) { pointerFeed.close(); pointerFeed = null; }
    if (!sound.on) setSound(true);
    if (!document.fullscreenElement && document.documentElement.requestFullscreen)
      document.documentElement.requestFullscreen({ navigationUI: "hide" }).catch(() => {});
  } else {
    if (!soundBeforeWatch) setSound(false);
    if (!sideways.matches && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }
  if (streaming) attachStream();   // the video again at the new quality (and the pointer stream when leaving Watch)
}
$("watch").addEventListener("click", () => setWatch(true));
$("watch-exit").addEventListener("click", () => setWatch(false));

// Window switcher: the laptop's open windows; one tap brings it to the front and the view fits it.
document.querySelector('[data-sheet="windows"]').addEventListener("click", loadWindows);
async function loadWindows() {
  const list = $("window-list");
  if (!await ensureControl()) { closeSheets(); return; }
  list.replaceChildren(el("p", "muted small", "Loading…"));
  try {
    const { windows } = await api("/api/control/windows");
    list.replaceChildren(...windows.map(item => {
      const b = el("button", "file-main");
      b.append(el("span", "file-icon", item.minimized ? "🗕" : "🪟"), el("span", "file-name", item.title), el("span", "file-meta", item.app));
      b.addEventListener("click", () => switchTo(item.id));
      return b;
    }));
    if (!windows.length) list.replaceChildren(el("p", "muted small", "No open windows."));
  } catch (e) { list.replaceChildren(el("p", "small", e.message)); }
}
async function switchTo(id) {
  try {
    const r = await api("/api/control/window", { id });
    closeSheets(); status("🪟 " + r.window.title);
    if (r.window.rect) fitTo(r.window.rect);
  } catch (e) { status(e.message); }
}
function fitTo(r) {   // zoom so the window fills the view (Fit when it is nearly the whole screen), then centre it
  const stage = $("stage"), img = frameRect(), fitW = img.width / zoom, fitH = img.height / zoom;
  const want = Math.min(6, stage.clientWidth / (r[2] * fitW), stage.clientHeight / (r[3] * fitH));
  if (want < 1.15) { setZoom(1, 0, 0); return; }
  setZoom(want, img.left + (r[0] + r[2] / 2) * img.width, img.top + (r[1] + r[3] / 2) * img.height);
  const box = stage.getBoundingClientRect(), now = frameRect();
  stage.scrollLeft += now.left + (r[0] + r[2] / 2) * now.width - (box.left + stage.clientWidth / 2);
  stage.scrollTop += now.top + (r[1] + r[3] / 2) * now.height - (box.top + stage.clientHeight / 2);
  drawCursor();
}

// Voice: hold 🎙 and say "Save pe click karo" / "click Save" (the button by its name) or "press Enter"; anything else
// is typed where the text cursor is.
let voiceRec = null, voiceHeld = false;
$("voice").addEventListener("pointerdown", async () => {
  voiceHeld = true;
  if (!await ensureControl()) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true }), parts = [];
    voiceRec = new MediaRecorder(stream);
    voiceRec.ondataavailable = e => parts.push(e.data);
    voiceRec.onstop = async () => {
      stream.getTracks().forEach(t => t.stop()); $("voice").classList.remove("on"); status("🎙 …");
      try {
        const r = await api("/api/control/voice", new Blob(parts, { type: voiceRec.mimeType || "audio/webm" }), true);
        if (r.target) hit(r.target);
        status(r.did === "click" ? `🎙 "${r.heard}": clicked ${r.target.name || r.target.kind}`
          : r.did === "type" ? `🎙 Typed: ${r.heard}` : r.did === "key" ? `🎙 Pressed ${r.key}` : (r.message || "🎙 ?"));
      } catch (e) { status(e.message); }
    };
    voiceRec.start(); $("voice").classList.add("on");
    if (!voiceHeld) voiceRec.stop();   // let go before the microphone was ready
    setTimeout(() => voiceRec && voiceRec.state === "recording" && voiceRec.stop(), 15000);
  } catch { status("Microphone not allowed"); }
});
for (const ev of ["pointerup", "pointerleave", "pointercancel"]) $("voice").addEventListener(ev, () => {
  voiceHeld = false; if (voiceRec && voiceRec.state === "recording") voiceRec.stop();
});

// Read aloud: a long press on text in Tap-here mode reads that paragraph here (a touch stops it).
async function readAloud(at) {
  try {
    const { text } = await api("/api/control/read", at);
    if (!text || !("speechSynthesis" in window)) return false;
    const say = new SpeechSynthesisUtterance(text);
    say.lang = /[\u0900-\u097F]/.test(text) ? "hi-IN" : "en-IN";
    speechSynthesis.cancel(); speechSynthesis.speak(say);
    status("🔊 " + (text.length > 70 ? text.slice(0, 70) + "…" : text));
    return true;
  } catch { return false; }
}

// Speed test: what the link from the laptop to this phone really carries right now.
$("speed-go").addEventListener("click", async () => {
  const out = $("speed-out"); out.textContent = "Testing…";
  try {
    const pings = [];
    for (let i = 0; i < 4; i++) { const t = performance.now(); await api("/api/whoami"); pings.push(performance.now() - t); }
    const t = performance.now(), r = await fetch("/api/speedtest?mb=4&t=" + Date.now(), { credentials: "same-origin" });
    if (!r.ok) throw new Error("The speed test was refused (" + r.status + ").");
    const bytes = (await r.arrayBuffer()).byteLength, mbps = bytes * 8 / ((performance.now() - t) / 1000) / 1e6;
    setLink(mbps * 1000);
    out.textContent = `${mbps.toFixed(1)} Mbit/s laptop → phone, round trip ${Math.round(Math.min(...pings))} ms. Watch will use ${(watchKbps() / 1000).toFixed(1)} Mbit/s.`;
  } catch (e) { out.textContent = e.message; }
});

// ---- keyboard: the phone keyboard types live on the laptop; the key row sends single keys ----------------------------
// Phone keyboards rarely report keys, so the field keeps two spaces: shorter = Backspace, longer = new text.
const KEEP = "  "; $("live-keys").value = KEEP;
async function key(combo) {
  if (!await ensureControl()) return;
  if (combo === "alt+f4" && !confirm("Pakka band karun?")) return;
  queued("/api/control/keys", { combo }).then(() => {});
}
$("kbd").addEventListener("click", async () => { if (!await ensureControl()) return; $("live-keys").focus({ preventScroll: true }); $("kbd").classList.add("on"); });
$("live-keys").addEventListener("focus", () => { document.body.classList.add("typing"); scrollTo(0, 0); setTimeout(drawCursor, 300); });
$("live-keys").addEventListener("blur", () => { $("kbd").classList.remove("on"); document.body.classList.remove("typing"); setTimeout(drawCursor, 300); });
if (window.visualViewport) visualViewport.addEventListener("resize", () => { scrollTo(0, 0); drawCursor(); });   // the keyboard came or went
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
const KEY_ROW = [["Esc", "esc"], ["Space", "space"], ["Tab", "tab"], ["Enter", "enter"], ["⌫", "backspace"], ["Del", "delete"], ["←", "left"], ["↑", "up"],
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
  try { const r = await withPin("PIN to send a file to the laptop", pin => api("/api/files/upload?name=" + encodeURIComponent(file.name), file, true, pin)); $("upload-out").textContent = "Saved: " + r.saved; } catch (e) { $("upload-out").textContent = e.message; }
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
  const stream = "/api/files/stream?path=" + encodeURIComponent(f.path);
  const play = el("button", "primary", f.kind === "pdf" ? "📖 Open" : "▶ Play");
  play.addEventListener("click", () => openMedia(f, stream));
  get.addEventListener("click", () => fetchFile(f).then(blob => { const a = el("a"); a.href = URL.createObjectURL(blob); a.download = f.name; a.click(); status("Downloaded " + f.name); }).catch(e => status(e.message)));
  share.addEventListener("click", () => fetchFile(f).then(blob => navigator.share({ files: [new File([blob], f.name, { type: blob.type })] })).catch(e => status(e.message)));
  view.addEventListener("click", () => relay ? fetchFile(f).then(blob => showMedia("photo", URL.createObjectURL(blob))).catch(e => status(e.message)) : openMedia(f, stream));
  if (!relay && ["video", "audio", "pdf"].includes(f.kind)) actions.append(play);
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
// Owner 2026-11-07: "an anime episode on my laptop": the file plays in the phone's own player (smooth, with sound,
// seekable through HTTP Range), not as a copy of the laptop screen.
async function openMedia(f, stream) {
  try { await filesCall("/api/files/places", {}); } catch (e) { status(e.message); return; }   // the PIN session first
  if (f.kind === "pdf") { window.open(stream, "_blank"); return; }
  showMedia(f.kind, stream);
}
function showMedia(kind, src) {
  const video = $("file-video"), img = $("file-view-img");
  img.hidden = kind !== "photo"; video.hidden = kind === "photo";
  if (kind === "photo") img.src = src; else { video.src = src; video.play().catch(() => {}); }
  $("file-view").hidden = false;
}
$("file-video").addEventListener("error", () => status("The phone can't play this file's format. Use Download instead."));
$("file-view-close").addEventListener("click", () => {
  $("file-view").hidden = true; $("file-video").pause(); $("file-video").removeAttribute("src"); $("file-video").load();
  if ($("file-view-img").src.startsWith("blob:")) URL.revokeObjectURL($("file-view-img").src); $("file-view-img").removeAttribute("src");
});
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
