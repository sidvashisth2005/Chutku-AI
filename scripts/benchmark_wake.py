"""Synthetic wake-phrase benchmark: recall on "Oye Chutku ..." and false accepts on
near-miss and ordinary speech, for candidate Whisper prompts.

Synthetic Windows OneCore voices only; real-room false accepts per hour (TV, music,
conversation) must still be measured with the owner's consent.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chutku.voice import whisper_stt  # noqa: E402
from chutku.voice.handsfree import WAKE_PROMPT, split_wake  # noqa: E402
from scripts.benchmark_stt import synthesize  # noqa: E402
from scripts.verify_voice_agent import to_16k_mono  # noqa: E402

VOICES = [("en-IN", "Heera"), ("en-IN", "Ravi"), ("hi-IN", "Kalpana"), ("hi-IN", "Hemant"), ("en-US", "Zira")]
POSITIVE = ["Oye Chutku, open Spotify.", "Oye Chutku", "Chutku, what time is it?", "Oye Chutku, gaana roko.",
            "ओए छुटकू, टाइम बताओ", "ओए छुटकू"]
NEGATIVE = ["Oye Chotu, idhar aao.", "Ek chutki bhar namak daal do.", "Chutney bana do please.",
            "Hey Google, what's the weather?", "Okay computer, play some music.", "Kuch toh gadbad hai.",
            "Let's meet at four o'clock.", "I will open the file tomorrow.", "Open the window, it is hot.",
            "Beta, homework kar liya?", "The chutney was delicious.", "Oye, sun na yaar.",
            "छोटू इधर आओ", "एक चुटकी नमक डालो", "कल ऑफिस जाना है", "What time is the meeting?",
            "Search for flights to Delhi.", "Pause karo movie ko.", "Hello, how are you doing today?",
            "Chat GPT se pooch lo."]
PROMPTS = {"wake_prompt (used)": WAKE_PROMPT, "hinglish_command_prompt": whisper_stt.HINGLISH_PROMPT,
           "no_prompt": None}


def main():
    clips = []
    for culture, voice in VOICES:
        for text in POSITIVE + NEGATIVE:
            devanagari = any("ऀ" <= ch <= "ॿ" for ch in text)
            if devanagari != (culture == "hi-IN"):
                continue  # Hindi voices read Devanagari; English voices read Roman text
            clips.append((culture, voice, text, text in POSITIVE, to_16k_mono(*synthesize(culture, voice, text))))
    results = {}
    for name, prompt in PROMPTS.items():
        rows = []
        for culture, voice, text, positive, pcm in clips:
            heard = whisper_stt.transcribe_pcm(pcm, language="en", prompt=prompt)
            woke, command = split_wake(heard["text"])
            rows.append({"voice": voice, "said": text, "heard": heard["text"], "positive": positive, "woke": woke,
                         "command": command})
        pos = [r for r in rows if r["positive"]]
        neg = [r for r in rows if not r["positive"]]
        results[name] = {"recall": f"{sum(r['woke'] for r in pos)}/{len(pos)}",
                         "false_accepts": f"{sum(r['woke'] for r in neg)}/{len(neg)}", "rows": rows}
        print(name, results[name]["recall"], "recall;", results[name]["false_accepts"], "false accepts", flush=True)
        for r in rows:
            if r["woke"] != r["positive"]:
                print("   MISS" if r["positive"] else "   FALSE", r["voice"], repr(r["said"]), "->", repr(r["heard"]))
    report = {"generated_at": datetime.now(UTC).isoformat(), "results": results,
              "scope": "Synthetic OneCore voices, single clips; not a per-hour false-accept rate in a real room."}
    (ROOT / "verification/wake-benchmark.json").write_text(json.dumps(report, indent=1, ensure_ascii=False),
                                                          encoding="utf-8")


if __name__ == "__main__":
    main()
