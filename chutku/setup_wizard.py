"""First-run setup (O4 2026-11-06; assistant name and phone app account added the same day for publishing):
`python -m chutku.cli setup`, offered by Install-Chutku.cmd. Every question is skippable with Enter.

  1. your assistant's name and personality -> .env (chutku/identity.py)
  2. the owner's name                      -> mind.set_fact("name")
  3. a free brain key                      -> Windows Credential Manager
  4. a one-second microphone check         -> the voice.microphone_level_check tool (raw audio discarded)
  5. how much it does alone                -> preferences.handsfree_mode
  6. the phone app account                 -> an ID + password at the account relay (refused if the ID exists),
                                              this laptop's device token in Credential Manager, a 4-6 digit phone PIN
Keys, passwords and tokens never touch a file. The laptop stays signed in until `chutku.cli account logout`.

W5: each step is a plain function (set_assistant, set_owner_name, store_brain_key, set_autonomy, mic_level,
link_phone, finish) that this CLI and the first-run page in the dashboard both call. data/setup.json remembers
which steps were done and whether setup is finished ({"done": true} hides the first-run page).
"""
from __future__ import annotations

from pathlib import Path

import json
import time

SETUP_FILE = ("data", "setup.json")
AUTONOMY = {"safe": "auto_safe", "edits": "auto_edits", "full": "owner"}   # the page's three choices (Safe = default)
STEPS = ("assistant", "name", "brain_key", "packs", "microphone", "mode", "phone", "browser")


def _setup_path(base):
    return Path(base).joinpath(*SETUP_FILE)


def state(base):
    """{"done": bool, "steps": {step: when}}; a missing or unreadable file is a fresh install."""
    try:
        data = json.loads(_setup_path(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    steps = data.get("steps") if isinstance(data.get("steps"), dict) else {}
    return {"done": data.get("done") is True, "steps": {k: v for k, v in steps.items() if k in STEPS}}


def _mark(base, step=None, *, done=None):
    from chutku.core.jsonstore import write_json
    current = state(base)
    if step:
        current["steps"][step] = time.time()
    if done is not None:
        current["done"] = done
    write_json(_setup_path(base), current)
    return current


def finish(base):
    return _mark(base, done=True)


def set_assistant(base, updates):
    """Name and personality (.env). Every value is checked by identity.check; returns what was saved."""
    from chutku import identity
    clean = {key: identity.check(key, value) for key, value in updates.items() if str(value).strip()}
    if clean:
        identity.save(clean, Path(base) / ".env")
    _mark(base, "assistant")
    return clean


def set_owner_name(base, name):
    name = " ".join(str(name).split())[:60]
    if not name:
        raise ValueError("Type your name.")
    from chutku.mind import Mind
    Mind(base).set_fact("name", name)
    _mark(base, "name")
    return name


KEY_CHECKS = {   # a free, read-only call that only answers 200 for a working key (2026-11-08)
    "groq": ("https://api.groq.com/openai/v1/models", "Authorization", "Bearer {}", "Groq"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/models", "x-goog-api-key", "{}", "Google AI Studio"),
}


def check_brain_key(provider, key, *, opener=None):
    """Ask the provider whether this key works, before it is kept (owner 2026-11-08: a wrong key must not let a new
    user through setup). A rate-limited key works; a refused key or no internet raises a plain ValueError."""
    import urllib.error
    import urllib.request
    url, header, value, name = KEY_CHECKS[provider]
    request = urllib.request.Request(url, headers={header: value.format(key), "User-Agent": "Chutku"})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=20):
            return True
    except urllib.error.HTTPError as error:   # never the URL or headers: the key is in them
        if error.code == 429:
            return True
        raise ValueError(f"{name} did not accept this key (HTTP {error.code}). Copy it again from {name} and "
                         "paste the whole key.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError(f"Chutku could not reach {name} to check the key. Check your internet connection and "
                         "try again.") from None


def has_brain_key(base):
    try:
        from chutku import cloud_planner, providers
        return "groq" in providers.configured(base) or bool(cloud_planner.api_key())
    except Exception:
        return False


def store_brain_key(base, provider, key, *, check=None):
    """A free cloud brain key into Windows Credential Manager (never a file, never echoed back), after the provider
    has confirmed it works."""
    key = str(key or "").strip()
    if provider not in {"groq", "gemini"}:
        raise ValueError("Choose groq or gemini.")
    if not key:
        raise ValueError("Paste the key.")
    (check or check_brain_key)(provider, key)
    if provider == "groq":   # cloud_planner.store_key checks the key's shape (20-200 characters)
        from chutku import providers
        providers.store_key("groq", key)
    else:
        from chutku import cloud_planner
        from chutku.core.capability_grants import CapabilityGrantStore
        cloud_planner.store_key(key)
        CapabilityGrantStore(Path(base) / "data" / "capability_grants.db").grant("cloud.gemini")
    _mark(base, "brain_key")
    return provider


def set_autonomy(base, choice):
    """safe / edits / full (the page) or a mode name (the CLI's 4 choices)."""
    from chutku.core.preferences import Preferences
    mode = AUTONOMY.get(choice, choice)
    Preferences(base).update({"handsfree_mode": mode})
    _mark(base, "mode")
    return mode


def mic_level(base, check=None):
    level = (check or _mic_check)(base)
    _mark(base, "microphone")
    return level


def link_phone(base, url, account_id, password, pin, *, new, relay=None):
    """The phone app account: create (refused if the ID exists) or log in, store this laptop's token, set the PIN."""
    from chutku import identity
    if relay is None:
        from chutku.relay import client as relay
    if not (str(pin).isdigit() and 4 <= len(str(pin)) <= 6):
        raise ValueError("Use a 4-6 digit PIN.")
    url = relay.check_url(identity.check("CHUTKU_RELAY_URL", url))
    account_id = str(account_id).strip().casefold()
    if new:
        relay.register(url, account_id, password)
    token = relay.login(url, account_id, password, name="laptop")
    from chutku.remote.auth import RemoteStore
    RemoteStore(base).set_relay_pin(str(pin))
    relay.store_token(token)
    identity.save({"CHUTKU_RELAY_URL": url, "CHUTKU_ACCOUNT_ID": account_id}, Path(base) / ".env")
    _mark(base, "phone")
    return {"id": account_id, "relay": url}


MODES = {"1": ("review", "ask before every step"), "2": ("auto_safe", "do safe things, ask before changes"),
         "3": ("auto_edits", "also change files she can undo"), "4": ("owner", "do almost everything, ask only for "
                                                                       "deletes, risky and unknown-recipient steps")}


def run(base, *, ask=input, secret=None, out=print, mic_check=None, relay=None):
    import getpass
    secret = secret or getpass.getpass
    base = Path(base)
    done = {}
    out("Setup: 6 quick questions. Press Enter to skip any of them.\n")

    assistant = _assistant(base, ask, out)
    if assistant:
        done["assistant"] = assistant
    called = assistant.get("ASSISTANT_NAME", "Chutku") if assistant else _current_name(base)

    name = ask(f"\n2/6  What should {called} call you? ").strip()[:60]
    if name:
        done["name"] = set_owner_name(base, name)

    out(f"\n3/6  A free cloud brain makes {called} much faster and smarter when you are online.")
    out("     Groq: https://console.groq.com/keys   Gemini: https://aistudio.google.com/apikey")
    which = ask("     Which key do you have? [groq / gemini / Enter = none, local brain only] ").strip().casefold()
    if which in {"groq", "gemini"}:
        key = secret(f"     Paste your {which} key (input hidden): ").strip()
        if key:
            try:
                done["brain_key"] = store_brain_key(base, which, key)
            except ValueError as error:
                out("     " + str(error))

    if ask("\n4/6  Check the microphone for one second now? [Y/n] ").strip().casefold() in {"", "y", "yes", "haan"}:
        out("     Say something now...")
        level = mic_level(base, mic_check)
        done["microphone"] = level
        out("     " + ("Heard you." if level.get("heard") else "Very quiet: check the microphone in Windows "
                                                                    "Settings > Sound > Input."))

    out(f"\n5/6  How much should {called} do on its own?")
    for number, (_mode, text) in MODES.items():
        out(f"     {number}. {text}")
    choice = MODES.get(ask("     Choose 1-4 [Enter = 2]: ").strip() or "2")
    if choice:
        done["mode"] = set_autonomy(base, choice[0])

    account = _account(base, ask, secret, out, relay)
    if account:
        done["account"] = account
    finish(base)
    out(f"\nDone. Start {called} with Start-Chutku.cmd; Ctrl+Alt+Space to talk, Ctrl+Alt+C for the bar.")
    return done


def _current_name(base):
    from chutku import identity
    return identity.load(base / ".env")["ASSISTANT_NAME"]


def _assistant(base, ask, out):
    """1/6: the name it answers to ("Oye <name>") and how it talks. Enter keeps everything as it is."""
    from chutku import identity
    current = identity.load(base / ".env")
    out(f"1/6  Name your assistant. It answers to \"Oye {current['ASSISTANT_NAME']}\" / \"Hey "
        f"{current['ASSISTANT_NAME']}\".")
    updates = {}
    for _ in range(3):
        name = ask(f"     Name [Enter = {current['ASSISTANT_NAME']}]: ").strip()
        if not name:
            break
        try:
            updates["ASSISTANT_NAME"] = identity.check("ASSISTANT_NAME", name)
            break
        except ValueError as error:
            out("     " + str(error))
    if ask("     Personality: female voice, Hinglish, warm. Change it? [Enter = keep / c = change] ").strip()\
            .casefold() in {"c", "change", "y", "yes"}:
        for key, question in (("ASSISTANT_GENDER", "Gender (female / male / neutral)"),
                              ("ASSISTANT_LANGUAGE", "Language (hinglish / english / hindi)"),
                              ("ASSISTANT_STYLE", "Style (warm / professional / witty / calm)")):
            answer = ask(f"     {question} [Enter = {current[key]}]: ").strip()
            if answer:
                try:
                    updates[key] = identity.check(key, answer)
                except ValueError as error:
                    out("     " + str(error))
    if updates:
        set_assistant(base, updates)
    return updates


def _account(base, ask, secret, out, relay):
    """6/6: one account links this laptop and the phone app. Create an ID (refused if it exists) or log in."""
    from chutku import identity
    if relay is None:
        from chutku.relay import client as relay
    settings = identity.load(base / ".env")
    out("\n6/6  The phone app: see the screen, approve, talk and control this laptop from your phone.")
    choice = ask("     Set it up now? [n = new account / l = log in to my account / Enter = later] ").strip().casefold()
    if choice not in {"n", "new", "l", "login", "log in"}:
        return {}
    url = ask(f"     Relay address [Enter = {settings['CHUTKU_RELAY_URL'] or 'none set'}]: ").strip() \
        or settings["CHUTKU_RELAY_URL"]
    try:
        url = relay.check_url(identity.check("CHUTKU_RELAY_URL", url)) if url else ""
    except (ValueError, relay.RelayCallError) as error:
        out("     " + str(error))
        return {}
    if not url:
        out("     No relay address: set CHUTKU_RELAY_URL in .env (docs/RELAY.md), then run setup again.")
        return {}
    for _ in range(3):
        account_id = ask("     Your ID (3-32 letters, digits, . _ -): ").strip().casefold()
        password = secret("     Password (8+ characters, hidden): ")
        try:
            if choice.startswith("n"):
                if secret("     Password again: ") != password:
                    out("     The passwords differ. Try again.")
                    continue
                relay.register(url, account_id, password)
            token = relay.login(url, account_id, password, name="laptop")
            break
        except relay.RelayCallError as error:
            out("     " + str(error))   # "This ID already exists. Choose another one." / wrong password / offline
    else:
        return {}
    for _ in range(3):
        pin = secret("     Choose a 4-6 digit phone PIN (asked on the phone before approvals, screen and control): ")
        if pin.isdigit() and 4 <= len(pin) <= 6 and secret("     PIN again: ") == pin:
            break
        out("     Use 4-6 digits, the same twice.")
    else:
        return {}
    from chutku.remote.auth import RemoteStore
    RemoteStore(base).set_relay_pin(pin)
    relay.store_token(token)
    identity.save({"CHUTKU_RELAY_URL": url, "CHUTKU_ACCOUNT_ID": account_id}, base / ".env")
    _mark(base, "phone")
    out(f"     Signed in as {account_id}. Install the phone app (docs/RELAY.md) and log in with the same ID and "
        "password; both stay signed in until you log out.")
    return {"id": account_id, "relay": url}


def _mic_check(base):
    from chutku.app import create_runtime
    with create_runtime(base) as runtime:
        runtime.capability_grants.grant("audio.observe")
        result = runtime.run("voice.microphone_level_check", {}, provenance="user_stated")
    output = result.get("output") or {}
    peak = float(output.get("peak", 0) or output.get("peak_level", 0) or 0)
    return {"peak": peak, "heard": peak > 0.02, "state": str(result.get("state"))}
