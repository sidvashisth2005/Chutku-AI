"""First-run setup for a new owner (O4, 2026-11-06): `python -m chutku.cli setup`, offered by Install-Chutku.cmd.

Four short questions, each skippable with Enter, each reusing what already exists:
  1. the owner's name            -> mind.set_fact("name")
  2. a free brain key            -> providers.store_key("groq") / cloud_planner.store_key (Windows Credential Manager)
  3. a one-second microphone check -> the voice.microphone_level_check tool (raw audio discarded)
  4. how much she does alone     -> preferences.handsfree_mode (review / auto_safe / auto_edits / owner)
Nothing else is changed. Keys never touch a file.
"""
from __future__ import annotations

from pathlib import Path

MODES = {"1": ("review", "ask before every step"), "2": ("auto_safe", "do safe things, ask before changes"),
         "3": ("auto_edits", "also change files she can undo"), "4": ("owner", "do almost everything, ask only for "
                                                                       "deletes, risky and unknown-recipient steps")}


def run(base, *, ask=input, secret=None, out=print, mic_check=None):
    import getpass
    secret = secret or getpass.getpass
    base = Path(base)
    done = {}
    out("Chutku setup: 4 quick questions. Press Enter to skip any of them.\n")

    name = ask("1/4  What should Chutku call you? ").strip()[:60]
    if name:
        from chutku.mind import Mind
        Mind(base).set_fact("name", name)
        done["name"] = name

    out("\n2/4  A free cloud brain makes Chutku much faster and smarter when you are online.")
    out("     Groq: https://console.groq.com/keys   Gemini: https://aistudio.google.com/apikey")
    which = ask("     Which key do you have? [groq / gemini / Enter = none, local brain only] ").strip().casefold()
    if which in {"groq", "gemini"}:
        key = secret(f"     Paste your {which} key (input hidden): ").strip()
        if key:
            if which == "groq":
                from chutku import providers
                providers.store_key("groq", key)
            else:
                from chutku import cloud_planner
                from chutku.core.capability_grants import CapabilityGrantStore
                cloud_planner.store_key(key)
                CapabilityGrantStore(base / "data" / "capability_grants.db").grant("cloud.gemini")
            done["brain_key"] = which

    if ask("\n3/4  Check the microphone for one second now? [Y/n] ").strip().casefold() in {"", "y", "yes", "haan"}:
        out("     Say something now...")
        level = (mic_check or _mic_check)(base)
        done["microphone"] = level
        out("     " + ("Heard you." if level.get("heard") else "Very quiet: check the microphone in Windows "
                                                                    "Settings > Sound > Input."))

    out("\n4/4  How much should Chutku do on her own?")
    for number, (_mode, text) in MODES.items():
        out(f"     {number}. {text}")
    choice = MODES.get(ask("     Choose 1-4 [Enter = 2]: ").strip() or "2")
    if choice:
        from chutku.core.preferences import Preferences
        Preferences(base).update({"handsfree_mode": choice[0]})
        done["mode"] = choice[0]
    out("\nDone. Start Chutku with Start-Chutku.cmd; Ctrl+Alt+Space to talk, Ctrl+Alt+C for her bar.")
    return done


def _mic_check(base):
    from chutku.app import create_runtime
    with create_runtime(base) as runtime:
        runtime.capability_grants.grant("audio.observe")
        result = runtime.run("voice.microphone_level_check", {}, provenance="user_stated")
    output = result.get("output") or {}
    peak = float(output.get("peak", 0) or output.get("peak_level", 0) or 0)
    return {"peak": peak, "heard": peak > 0.02, "state": str(result.get("state"))}
