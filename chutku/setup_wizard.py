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
"""
from __future__ import annotations

from pathlib import Path

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
        from chutku.mind import Mind
        Mind(base).set_fact("name", name)
        done["name"] = name

    out(f"\n3/6  A free cloud brain makes {called} much faster and smarter when you are online.")
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

    if ask("\n4/6  Check the microphone for one second now? [Y/n] ").strip().casefold() in {"", "y", "yes", "haan"}:
        out("     Say something now...")
        level = (mic_check or _mic_check)(base)
        done["microphone"] = level
        out("     " + ("Heard you." if level.get("heard") else "Very quiet: check the microphone in Windows "
                                                                    "Settings > Sound > Input."))

    out(f"\n5/6  How much should {called} do on its own?")
    for number, (_mode, text) in MODES.items():
        out(f"     {number}. {text}")
    choice = MODES.get(ask("     Choose 1-4 [Enter = 2]: ").strip() or "2")
    if choice:
        from chutku.core.preferences import Preferences
        Preferences(base).update({"handsfree_mode": choice[0]})
        done["mode"] = choice[0]

    account = _account(base, ask, secret, out, relay)
    if account:
        done["account"] = account
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
        identity.save(updates, base / ".env")
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
