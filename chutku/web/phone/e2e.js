"use strict";
// W6: end-to-end encryption with the laptop through the account relay (the same protocol as chutku/relay/e2e.py).
// The relay forwards only ciphertext. key = PBKDF2-SHA256(password, "chutku-e2e-key:"+id, 600000) for AES-256-GCM;
// auth = PBKDF2-SHA256(password, "chutku-e2e-auth:"+id, 600000) as hex is what the relay sees as the password.
const ChutkuE2E = (() => {
  const ITERATIONS = 600000;
  const subtle = globalThis.crypto.subtle;
  const text = new TextEncoder(), untext = new TextDecoder();
  const b64 = bytes => { let s = ""; new Uint8Array(bytes).forEach(b => { s += String.fromCharCode(b); }); return btoa(s); };
  const unb64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
  const hex = bytes => Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, "0")).join("");
  const clean = id => String(id).trim().toLowerCase();
  const aad = (id, kind) => text.encode(`chutku-e2e-v1:${clean(id)}:${kind}`);

  async function bits(password, salt, iterations) {
    const base = await subtle.importKey("raw", text.encode(password), "PBKDF2", false, ["deriveBits"]);
    return subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt: text.encode(salt), iterations }, base, 256);
  }
  async function derive(password, id, iterations = ITERATIONS) {
    const raw = await bits(password, "chutku-e2e-key:" + clean(id), iterations);
    const auth = hex(await bits(password, "chutku-e2e-auth:" + clean(id), iterations));
    return { raw: b64(raw), auth };
  }
  const importKey = raw => subtle.importKey("raw", unb64(raw), "AES-GCM", false, ["encrypt", "decrypt"]);
  async function seal(key, id, kind, obj) {
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ct = await subtle.encrypt({ name: "AES-GCM", iv, additionalData: aad(id, kind) }, key, text.encode(JSON.stringify(obj)));
    return { v: 1, iv: b64(iv), ct: b64(ct) };
  }
  async function open(key, id, kind, envelope) {
    if (!envelope || envelope.v !== 1) throw new Error("Not an encrypted answer from the laptop.");
    try {
      const plain = await subtle.decrypt({ name: "AES-GCM", iv: unb64(envelope.iv), additionalData: aad(id, kind) }, key, unb64(envelope.ct));
      return JSON.parse(untext.decode(plain));
    } catch { throw new Error("The laptop's answer could not be decrypted (log in again)."); }
  }
  const nonce = () => b64(crypto.getRandomValues(new Uint8Array(18)));
  return { ITERATIONS, derive, importKey, seal, open, nonce, b64, unb64 };
})();
if (typeof module !== "undefined") module.exports = ChutkuE2E;
