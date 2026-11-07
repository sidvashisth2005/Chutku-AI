"use strict";
// The phone's sound player (owner 2026-11-08, "the audio cracks"): a jitter buffer in an AudioWorklet. A ring of
// decoded 48 kHz sound that starts once it holds the target cushion, plays at an even pace, fades 5 ms out and in
// when it runs dry (no click), and skips back to the target after a burst. phone.js feeds it and sets the target.
class Jitter extends AudioWorkletProcessor {
  constructor() {
    super();
    this.size = sampleRate * 4; this.l = new Float32Array(this.size); this.r = new Float32Array(this.size);
    this.read = 0; this.write = 0; this.filled = 0; this.target = Math.round(0.12 * sampleRate);
    this.playing = false; this.gain = 0; this.lastL = 0; this.lastR = 0; this.under = 0; this.tick = 0;
    this.port.onmessage = e => {
      const m = e.data;
      if (m.clear) { this.read = this.write = this.filled = 0; this.playing = false; return; }
      if (m.target) this.target = Math.round(m.target * sampleRate);
      if (m.l) {
        const n = Math.min(m.l.length, this.size - this.filled);
        for (let i = 0; i < n; i++) { this.l[this.write] = m.l[i]; this.r[this.write] = m.r[i]; this.write = (this.write + 1) % this.size; }
        this.filled += n;
        if (this.filled > this.target + 0.3 * sampleRate) {   // far behind after a stall: back to the target
          const drop = this.filled - this.target; this.read = (this.read + drop) % this.size; this.filled -= drop; this.gain = 0;
        }
      }
    };
  }
  process(inputs, outputs) {
    const left = outputs[0][0], right = outputs[0][1] || left, step = 1 / (0.005 * sampleRate);
    if (!this.playing && this.filled >= this.target) this.playing = true;
    for (let i = 0; i < left.length; i++) {
      if (this.playing && this.filled > 0) {
        this.lastL = this.l[this.read]; this.lastR = this.r[this.read];
        this.read = (this.read + 1) % this.size; this.filled--; this.gain = Math.min(1, this.gain + step);
      } else {
        if (this.playing) { this.playing = false; this.under++; }
        this.gain = Math.max(0, this.gain - step);
      }
      left[i] = this.lastL * this.gain; right[i] = this.lastR * this.gain;
    }
    if (++this.tick % 16 === 0) this.port.postMessage({ filled: this.filled / sampleRate, under: this.under });
    return true;
  }
}
registerProcessor("chutku-jitter", Jitter);