"""main: the chutku command line (every subcommand)."""
from __future__ import annotations

import argparse
import json
from chutku.chat import reply, run_chat
from chutku.runtime import Runtime
from chutku.app import create_runtime


def _runtime(grant_id="sandbox") -> Runtime:
    return create_runtime(grant_id=grant_id)


def _nightshift_command(namespace):
    """Night Shift (master plan S20). With Chutku running, the jobs run inside it (one model on the GPU)."""
    import time as _time
    from chutku import nightshift
    from chutku.app import PROJECT_ROOT
    if namespace.night_action == "install":
        print(json.dumps(nightshift.install(PROJECT_ROOT), indent=2))
        return
    if namespace.night_action == "report":
        report = nightshift.latest_report(PROJECT_ROOT)
        if report is None:
            print("No Night Shift report yet.")
            return
        print(json.dumps(report, indent=2, ensure_ascii=False))
        print(nightshift.morning_line(PROJECT_ROOT) or "")
        return
    if namespace.when_idle and not nightshift.wait_for_idle(PROJECT_ROOT):
        print("No 30 idle minutes on mains power today (or it already ran): skipped.")
        return
    if not namespace.force and nightshift.on_ac_power() is False:
        print("On battery: Night Shift skipped.")
        return
    before = nightshift.latest_report(PROJECT_ROOT)
    if not namespace.no_model and _ask_running_chutku({"action": "run"}):
        print("Started inside the running Chutku; waiting for the report ...")
        for _ in range(45 * 60):
            _time.sleep(1)
            now = nightshift.latest_report(PROJECT_ROOT)
            if now and now != before and now.get("finished"):
                print(json.dumps(now, indent=2, ensure_ascii=False)[:4000])
                return
        raise SystemExit("No report within 45 minutes.")
    model = None
    if not namespace.no_model:
        from chutku.agent_loop import LocalAgentPlanner
        from chutku.brain_service import shared_service
        model = LocalAgentPlanner(shared_service(PROJECT_ROOT))
    report = nightshift.run_once(PROJECT_ROOT, model=model, force=namespace.force)
    print(json.dumps(report, indent=2, ensure_ascii=False)[:4000])


def _ask_running_chutku(body):
    """POST /api/nightshift to the running dashboard (same user, its session token); False when it is not running."""
    import http.client
    from chutku.app import PROJECT_ROOT
    try:
        link = json.loads((PROJECT_ROOT / "data" / "dashboard-session.json").read_text(encoding="utf-8"))["url"]
        token, origin = link.split("#token=")[1], link.split("/#")[0]
        connection = http.client.HTTPConnection("127.0.0.1", int(origin.rsplit(":", 1)[1]), timeout=10)
        connection.request("POST", "/api/nightshift", json.dumps(body),
                           {"X-Chutku-Token": token, "Origin": origin, "Content-Type": "application/json"})
        response = connection.getresponse()
        ok = response.status == 200 and json.loads(response.read()).get("started") is True
        connection.close()
        return ok
    except (OSError, ValueError, KeyError, IndexError):
        return False


def _voice_command(namespace):
    """Owner Voice Lock (master plan S19) from the terminal."""
    from pathlib import Path
    import wave
    from chutku.app import PROJECT_ROOT
    from chutku.core.action_control import ActionControl
    from chutku.voice import recognition, speaker
    if namespace.voice_action == "status":
        enabled, threshold = speaker.settings(PROJECT_ROOT)
        print(json.dumps({"voice_lock": enabled, "enrolled": speaker.load_voiceprint(PROJECT_ROOT) is not None,
                          "model_ready": speaker.available(), "threshold": threshold}, indent=2))
        return
    if namespace.voice_action == "forget":
        from chutku.core.preferences import Preferences
        Preferences(PROJECT_ROOT).update({"voice_lock": False})
        speaker.voiceprint_path(PROJECT_ROOT).unlink(missing_ok=True)
        speaker.anchor_path(PROJECT_ROOT).unlink(missing_ok=True)
        (PROJECT_ROOT / "data" / "voiceprint-learning.json").unlink(missing_ok=True)
        print("Voiceprint deleted and the voice lock is off.")
        return
    control = ActionControl(PROJECT_ROOT)
    clips = []
    for number, line in enumerate(speaker.ENROLL_LINES, 1):
        for _attempt in range(2):
            input(f"\n[{number}/{len(speaker.ENROLL_LINES)}] Press Enter, then read aloud:\n    {line}\n")
            pcm = recognition.capture(control)["pcm"]
            seconds = speaker.voiced_seconds(pcm)
            if seconds >= 2.0:
                print(f"    ok ({seconds:.1f} s of speech)")
                clips.append(pcm)
                break
            print(f"    only {seconds:.1f} s of speech heard; once more, a little louder")
    if namespace.voice_action == "record":
        from chutku.core.paths import user_folder
        folder = Path(namespace.folder or Path(user_folder("ChutkuScratch")) / "voicelock" / "owner")
        folder.mkdir(parents=True, exist_ok=True)
        for index, pcm in enumerate(clips):
            with wave.open(str(folder / f"owner-{index}.wav"), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(16000)
                stream.writeframes(pcm)
        print(f"Saved {len(clips)} clips to {folder} (for scripts/calibrate_voice_lock.py --owner).")
        return
    used = speaker.enroll(PROJECT_ROOT, clips)
    print(f"Enrolled with {used} clips. Type 'voice lock on' in the dashboard chat to switch the lock on.")


def _apps_command(namespace):
    """`apps list` / `apps lab <app>` (App Mastery A2)."""
    from chutku.app import PROJECT_ROOT
    from chutku.apps import atlas as atlas_module, lab
    atlases, errors = atlas_module.load_all()
    if namespace.apps_action == "list":
        done = lab.verified_actions(PROJECT_ROOT)
        for app, atlas in atlases.items():
            print(f"{app}: {len(atlas['actions'])} actions, {len(done.get(app, ()))} verified")
        for name, error in errors.items():
            print(f"REFUSED {name}: {error}")
        return
    if namespace.app not in atlases:
        raise SystemExit(f"Give an app: {', '.join(atlases)}")
    with create_runtime() as runtime:
        report = lab.run_lab(PROJECT_ROOT, runtime, atlases[namespace.app], only=namespace.action,
                             runs=max(1, min(namespace.runs, 10)), include_changes=namespace.changes)
    print(lab.describe(report))


def _wake_command(namespace):
    """`wake record` (the owner says "Oye Chutku" 12 times, near and far) / `wake train` / `wake status`."""
    from chutku.app import PROJECT_ROOT
    import subprocess
    import sys
    import time
    import wave
    folder = PROJECT_ROOT / "data" / "wake" / "owner"
    if namespace.wake_action == "status":
        from chutku.voice import wakeword
        clips = len(list(folder.glob("*.wav"))) if folder.exists() else 0
        if wakeword.available():
            meta = wakeword.Detector().meta
            print(f"Detector trained {meta['trained']} with {meta['owner_clips']} of your clips; "
                  f"threshold {meta['threshold']}. Clips saved now: {clips}.")
        else:
            print(f"No detector yet (run 'wake train'). Clips saved: {clips}.")
        return
    if namespace.wake_action == "train":
        from chutku.core.paths import CODE_ROOT
        sys.exit(subprocess.call([sys.executable, str(CODE_ROOT / "scripts" / "train_wake.py")]))
    import numpy as np
    import sounddevice as sd
    from chutku.voice.handsfree import chime
    folder.mkdir(parents=True, exist_ok=True)
    start = len(list(folder.glob("*.wav")))
    plan = [("paas se, normal awaaz mein", 4), ("paas se, dheere", 2), ("2-3 metre door se", 4),
            ("door se, kaam karte karte jaise bolte ho", 2)]
    print("Har beep ke baad 'Oye Chutku' bolo (2.5 second). Recordings stay on this PC (data/wake/owner).")
    number = start
    for where, count in plan:
        input(f"\nAb {count} baar {where}. Taiyaar ho to Enter dabao...")
        for _ in range(count):
            time.sleep(0.6)
            chime("listen")
            audio = sd.rec(int(2.5 * 16000), samplerate=16000, channels=1, dtype="int16")
            sd.wait()
            level = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)) / 32768)
            number += 1
            with wave.open(str(folder / f"{number:03d}.wav"), "wb") as out:
                out.setnchannels(1), out.setsampwidth(2), out.setframerate(16000)
                out.writeframes(audio.tobytes())
            print(f"  {number:03d}.wav saved (level {level:.4f}{', bahut dheema - thoda zor se?' if level < 0.002 else ''})")
    print(f"\n{number - start} clips saved. Now run: .venv\\Scripts\\python.exe -m chutku.cli wake train")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chutku text-first runtime")
    parser.add_argument("--resource-grant", default="sandbox",
                        help="Runtime-owned resource grant ID for filesystem tools (default: sandbox).")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("tools")
    doctor = subparsers.add_parser("doctor", help="Check foundation health without opening apps, microphone or model")
    doctor.add_argument("--fix", action="store_true", help="H26: also repair what is safe (reversible, logged)")
    plan = subparsers.add_parser("plan", help="Inspect deterministic understanding without executing anything")
    plan.add_argument("message", nargs="+")
    sequence = subparsers.add_parser("sequence", help="Review up to six explicit commands; add --execute to run")
    sequence.add_argument("--step", action="append", required=True)
    sequence.add_argument("--execute", action="store_true")
    control = subparsers.add_parser("control", help="Pause/resume actions; quit or restart Chutku cleanly; stop = the "
                                    "EMERGENCY stop, which leaves actions paused on purpose")
    control.add_argument("action", choices=("pause", "resume", "status", "stop", "quit", "restart"))
    brain = subparsers.add_parser("brain", help="Preview a general typed-tool plan with the local model; never execute automatically")
    brain.add_argument("message", nargs="+")
    brain.add_argument("--consult-gemini", action="store_true",
                       help="Also send the exact request text to Google's Gemini API for advisory consensus")
    dashboard = subparsers.add_parser("dashboard", help="Start the local Chutku dashboard")
    dashboard.add_argument("--port", type=int, default=8765)
    dashboard.add_argument("--open", action="store_true", dest="open_browser", help="Open the dashboard in your default browser")
    workflow = subparsers.add_parser("workflow", help="Preview a project setup recipe; add --execute to run it")
    workflow.add_argument("name")
    workflow.add_argument("--execute", action="store_true")
    subparsers.add_parser("chat", help="Start the interactive deterministic text console")
    history = subparsers.add_parser("history", help="Show recent task audit summaries")
    history.add_argument("--limit", type=int, default=10)
    trace = subparsers.add_parser("trace", help="Show the safe audit trace for one task ID")
    trace.add_argument("task_id")
    run = subparsers.add_parser("run")
    run.add_argument("tool")
    run.add_argument("--args", default="{}", help="JSON object arguments")
    ask = subparsers.add_parser("ask", help="Run a supported plain-language command")
    ask.add_argument("message", nargs="+", help="Supported request text; words are joined safely.")
    access = subparsers.add_parser("access", help="List, add or revoke explicit filesystem resource grants")
    access_sub = access.add_subparsers(dest="access_action", required=True)
    access_sub.add_parser("list")
    add = access_sub.add_parser("grant")
    add.add_argument("root")
    add.add_argument("--permission", choices=("observe", "modify"), default="observe")
    revoke = access_sub.add_parser("revoke")
    revoke.add_argument("grant_id")
    authority = subparsers.add_parser("authority", help="List, grant or revoke exact non-filesystem PC capabilities")
    authority_sub = authority.add_subparsers(dest="authority_action", required=True)
    authority_sub.add_parser("list")
    authority_grant = authority_sub.add_parser("grant")
    authority_grant.add_argument("capability")
    authority_revoke = authority_sub.add_parser("revoke")
    authority_revoke.add_argument("capability")
    autostart = subparsers.add_parser("autostart", help="Start Chutku automatically when you sign in to Windows")
    autostart.add_argument("autostart_action", choices=("on", "off", "status"))
    gemini = subparsers.add_parser("gemini", help="Configure Gemini as the secondary planner (off unless cloud.gemini is granted)")
    gemini.add_argument("gemini_action", choices=("status", "set-key", "add-key"))
    cloud = subparsers.add_parser("cloud", help="Free cloud brain (Groq, Cerebras): store a key, see status, test")
    cloud.add_argument("cloud_action", choices=("status", "set-key", "add-key", "test"))
    cloud.add_argument("provider", nargs="?", choices=("groq", "cerebras"), default=None)
    telegram = subparsers.add_parser("telegram", help="H16 Telegram remote: store the BotFather token, get a pairing "
                                                      "code, unpair, or see status")
    telegram.add_argument("telegram_action", choices=("status", "set-token", "pair", "unpair"))
    email = subparsers.add_parser("email", help="Email sending (X8): store a Gmail address + app password, or see status")
    email.add_argument("email_action", choices=("status", "set-account"))
    subparsers.add_parser("open", help="Open the running Chutku dashboard in your browser")
    subparsers.add_parser("setup", help="First-run setup: your assistant's name, your name, a free brain key, a mic "
                                        "check, how much it does alone, the phone app account")
    backup = subparsers.add_parser("backup", help="Back up Chutku's memory, list backups, or restore one (stopped)")
    backup.add_argument("backup_action", nargs="?", default="create", choices=("create", "list", "restore"))
    backup.add_argument("zip", nargs="?", help="the backup zip to restore")
    backup.add_argument("--voice", action="store_true", help="also include voice clips and the voiceprint")
    backup.add_argument("--include-security", action="store_true",
                        help="restore: also bring back pairings, grants, never-rules and approved skills (asks first)")
    browser = subparsers.add_parser("browser", help="The signed-in browser Chutku automates: login opens it to sign in once")
    browser.add_argument("browser_action", choices=("login",))
    browser.add_argument("url", nargs="?", default="https://accounts.google.com")
    account = subparsers.add_parser("account", help="Phone app account: status, login, logout, change ID/password, PIN")
    account.add_argument("account_action", choices=("status", "new", "login", "logout", "change", "pin"))
    night = subparsers.add_parser("nightshift", help="Night Shift: nightly self-improvement jobs (run, install, report)")
    night.add_argument("night_action", choices=("run", "install", "report"))
    night.add_argument("--no-model", action="store_true", help="run: skip the model round of the regression replay")
    night.add_argument("--force", action="store_true", help="run: also on battery")
    night.add_argument("--when-idle", action="store_true",
                       help="run: wait until the PC has been unused for 30 minutes (the 04:00 task uses this)")
    voice = subparsers.add_parser("voice", help="Owner voice lock: enroll your voice, record clips, status, forget")
    voice.add_argument("voice_action", choices=("enroll", "record", "status", "forget"))
    voice.add_argument("folder", nargs="?", help="record: where to save 16 kHz WAV clips")
    reflexes = subparsers.add_parser("reflex", help="Learned instant skills: list, compile, enable or disable")
    reflexes.add_argument("reflex_action", choices=("list", "compile", "enable", "disable"))
    reflexes.add_argument("reflex_id", nargs="?")
    apps = subparsers.add_parser("apps", help="App Mastery: list atlases, or run the Action Lab for one app")
    apps.add_argument("apps_action", choices=("list", "lab"))
    apps.add_argument("app", nargs="?")
    apps.add_argument("--action", action="append", help="only these action ids (repeatable)")
    apps.add_argument("--runs", type=int, default=3)
    apps.add_argument("--changes", action="store_true", help="also run 'changes' actions (they add things)")
    wake = subparsers.add_parser("wake", help="'Oye Chutku' detector: record your voice, train, status")
    wake.add_argument("wake_action", choices=("record", "train", "status"))
    namespace = parser.parse_args()
    if namespace.command == "wake":
        _wake_command(namespace)
        return
    if namespace.command == "apps":
        _apps_command(namespace)
        return
    if namespace.command == "setup":
        from chutku.app import PROJECT_ROOT as root
        from chutku.setup_wizard import run as setup
        try:
            setup(root)
        except (EOFError, KeyboardInterrupt):
            print("Setup stopped; run it again any time.")
        return
    if namespace.command == "browser":
        from chutku.tools import signed_in_browser
        try:
            profile = signed_in_browser.login(namespace.url)
        except OSError as error:
            parser.exit(1, f"Not done: {error}\n")
        print(f"Opened Chutku's own browser profile ({profile}). Sign in to the sites Chutku should use "
              "(Google, YouTube, shopping ...), then close that window. Your everyday browser is not touched.")
        return
    if namespace.command == "backup":
        from chutku import backup
        from chutku.app import PROJECT_ROOT as root
        try:
            if namespace.backup_action == "list":
                print(json.dumps(backup.listing(), indent=1))
            elif namespace.backup_action == "restore":
                if not namespace.zip:
                    parser.error("Name the backup zip to restore (chutku.cli backup list).")
                security = namespace.include_security
                if security:   # W1: re-enabling access needs the owner at this screen
                    print("This also restores phone/Telegram pairings, capability and folder grants, never-rules and "
                          "approved skills from the backup. Only do this with your own, recent backup.")
                    security = input("Type YES to include them: ").strip() == "YES"
                    if not security:
                        print("Not included: restoring without the security state.")
                print(json.dumps(backup.restore(root, namespace.zip, include_security=security), indent=1))
            else:
                print(json.dumps(backup.create(root, voice=namespace.voice), indent=1))
        except (RuntimeError, ValueError, OSError) as error:
            parser.exit(1, f"Not done: {error}\n")
        return
    if namespace.command == "account":
        from chutku.app import PROJECT_ROOT as root
        from chutku.relay.client import RelayCallError, account_command
        try:
            print(account_command(root, namespace.account_action))
        except (RelayCallError, ValueError) as error:
            print(f"Not done: {error}")
        except (EOFError, KeyboardInterrupt):
            print("Stopped.")
        return
    if namespace.command == "open":
        from chutku.dashboard import open_running_dashboard
        print(open_running_dashboard())
        return
    if namespace.command == "nightshift":
        _nightshift_command(namespace)
        return
    if namespace.command == "voice":
        _voice_command(namespace)
        return
    if namespace.command == "reflex":
        from chutku import reflex
        from chutku.app import PROJECT_ROOT
        if namespace.reflex_action == "compile":
            with create_runtime() as runtime:
                print(json.dumps(reflex.compile_all(PROJECT_ROOT, runtime.registry), indent=2, ensure_ascii=False))
        elif namespace.reflex_action == "list":
            print(json.dumps(reflex.summary(PROJECT_ROOT), indent=2, ensure_ascii=False))
        else:
            if not namespace.reflex_id:
                raise SystemExit("Give the skill id (see: reflex list).")
            changed = reflex.set_enabled(PROJECT_ROOT, namespace.reflex_id, namespace.reflex_action == "enable")
            if changed is None:
                raise SystemExit(f"No skill with id {namespace.reflex_id}.")
            print(json.dumps({"id": changed["id"], "enabled": changed["enabled"]}))
        return
    if namespace.command == "autostart":
        from chutku.autostart import autostart
        print(json.dumps(autostart(namespace.autostart_action), indent=2))
        return
    if namespace.command == "gemini":
        from chutku import cloud_planner
        if namespace.gemini_action == "add-key":   # H9 key pool
            import getpass
            from chutku.providers import POOL_SLOTS
            key = getpass.getpass("Gemini API key (input hidden): ").strip()
            free = next((slot for slot in range(2, POOL_SLOTS + 1)
                         if not cloud_planner.stored_key(f"{cloud_planner.CREDENTIAL_TARGET}#{slot}")), None)
            if not cloud_planner.stored_key():
                free = 1
            if free is None:
                raise SystemExit(f"All {POOL_SLOTS} Gemini key slots are used.")
            cloud_planner.store_key(key, cloud_planner.CREDENTIAL_TARGET + ("" if free == 1 else f"#{free}"))
            print(f"Stored as Gemini key {free} of {POOL_SLOTS}.")
            return
        if namespace.gemini_action == "set-key":
            import getpass
            cloud_planner.store_key(getpass.getpass("Gemini API key (input hidden): "))
            print("Stored in Windows Credential Manager as", cloud_planner.CREDENTIAL_TARGET)
        else:
            print(json.dumps({"key_available": bool(cloud_planner.api_key()),
                              "enabled_by_capability": cloud_planner.fallback_planner() is not None,
                              "enable_with": "python -m chutku.cli authority grant cloud.gemini"}, indent=2))
        return
    if namespace.command == "email":
        from chutku.tools import mail
        if namespace.email_action == "set-account":
            import getpass
            mail.store_account(input("Gmail address: "),
                               getpass.getpass("Gmail app password (myaccount.google.com/apppasswords; input hidden): "))
            print("Stored in Windows Credential Manager as", mail.CREDENTIAL_TARGET)
        saved = mail.account()
        print(json.dumps({"account": saved[0] if saved else None,
                          "sending_needs": "python -m chutku.cli authority grant email.send",
                          "every_send": "asks on screen first"}, indent=2))
        return
    if namespace.command == "telegram":
        from chutku.app import PROJECT_ROOT
        from chutku.gateway import telegram as tg
        if namespace.telegram_action == "set-token":
            import getpass
            tg.store_token(getpass.getpass("BotFather token (input hidden): "))
            print("Stored in Windows Credential Manager as", tg.CREDENTIAL, "- restart Chutku to connect.")
        elif namespace.telegram_action == "pair":
            print(f"Send this to your bot within an hour:  /pair {tg.Gateway(PROJECT_ROOT).new_code()}")
        elif namespace.telegram_action == "unpair":
            tg.Gateway(PROJECT_ROOT).unpair()
            print("Unpaired: the bot ignores every chat until you pair again.")
        else:
            print(json.dumps({"token_stored": bool(tg.token()), "paired": tg.paired(PROJECT_ROOT) is not None,
                              "handoff": tg.Gateway(PROJECT_ROOT).handed_off()}, indent=2))
        return
    if namespace.command == "cloud":
        from chutku import providers
        if namespace.cloud_action == "add-key":   # H9 key pool: one more key, tried when another hits its quota
            if namespace.provider is None:
                raise SystemExit("Say which: python -m chutku.cli cloud add-key groq   (or cerebras)")
            import getpass
            slot = providers.add_key(namespace.provider,
                                     getpass.getpass(f"{namespace.provider} API key (input hidden): ").strip())
            print(f"Stored as key {slot} of {providers.POOL_SLOTS} for {namespace.provider}.")
            return
        if namespace.cloud_action == "set-key":
            if namespace.provider is None:
                raise SystemExit("Say which: python -m chutku.cli cloud set-key groq   (or cerebras)")
            import getpass
            providers.store_key(namespace.provider, getpass.getpass(f"{namespace.provider} API key (input hidden): "))
            print("Stored in Windows Credential Manager as", providers.PROVIDERS[namespace.provider]["credential"])
        elif namespace.cloud_action == "test":
            started = __import__("time").monotonic()
            try:
                parsed, meta = providers.ask('Reply with JSON {"ok": true, "two_plus_two": <number>}.',
                                             "Answer now.", rungs=[(namespace.provider, providers.PROVIDERS[
                                                 namespace.provider]["models"][0])] if namespace.provider else None)
                print(json.dumps({"answer": parsed, "provider": meta["provider"], "model": meta["model"],
                                  "seconds": meta["seconds"], "correct": parsed.get("two_plus_two") == 4}, indent=2))
            except providers.ProviderError as error:
                print(json.dumps({"error": str(error), "seconds": round(__import__("time").monotonic() - started, 2)}))
                raise SystemExit(1)
        else:
            from chutku.app import PROJECT_ROOT as ROOT
            from chutku.core.preferences import Preferences
            print(json.dumps({"keys": {name: bool(providers.api_key(name)) for name in providers.ORDER},
                              "ladder": [f"{p}/{m}" for p, m in providers.ladder()],
                              "cooling_down": providers.cooling(),
                              "brain": Preferences(ROOT).load()["brain"],
                              "get_a_free_key": {"groq": "https://console.groq.com/keys",
                                                 "cerebras": "https://cloud.cerebras.ai"}}, indent=2))
        return
    if namespace.command == "plan":
        from chutku.planning import plan_request
        print(json.dumps(plan_request(" ".join(namespace.message)).to_dict(), indent=2))
        return
    if namespace.command == "doctor":
        from chutku.app import PROJECT_ROOT
        from chutku.doctor import inspect_foundation
        report = inspect_foundation(PROJECT_ROOT)
        if namespace.fix:   # H26: repairs run with Chutku stopped or running; the local model is the dashboard's
            from chutku.doctor import repair, summary
            report["repair"] = repair(PROJECT_ROOT, fix=True)
            report["repair"]["summary"] = summary(report["repair"])
        print(json.dumps(report, indent=2))
        if not report["ready"]:
            raise SystemExit(1)
        return
    if namespace.command == "control":
        from chutku.app import PROJECT_ROOT
        from chutku.core.action_control import ActionControl
        from chutku.core.execution_lock import ExecutionBusy
        controller = ActionControl(PROJECT_ROOT)
        try:
            if namespace.action == "stop":   # the emergency stop: Chutku comes back paused, on purpose
                controller.stop()
            elif namespace.action == "quit":   # WA6: close cleanly; the next start is not paused
                controller.quit()
                print("Chutku is closing (not paused).")
                return
            elif namespace.action == "restart":
                from chutku import restart
                print(restart.request(PROJECT_ROOT))
                return
            elif namespace.action == "pause":
                controller.pause()
            elif namespace.action == "resume":
                controller.resume()
        except (OSError, ExecutionBusy) as error:
            parser.exit(1, f"Could not change action control: {error}\n")
        print("Actions paused. An in-flight OS action may finish." if controller.paused else "Actions enabled.")
        return
    if namespace.command == "dashboard":
        from chutku.dashboard import serve
        if not 0 <= namespace.port <= 65535:
            parser.error("Port must be between 0 and 65535.")
        try:
            serve(namespace.port, namespace.open_browser)
        except OSError as error:
            parser.exit(1, f"Dashboard could not start: {error}\nIf it is already running, use its existing session link or choose another --port.\n")
        return
    runtime = _runtime(namespace.resource_grant)
    try:
        _dispatch(namespace, runtime, parser)
    finally:
        runtime.close()


def _dispatch(namespace, runtime: Runtime, parser) -> None:
    if namespace.command == "authority":
        try:
            if namespace.authority_action == "list":
                result = [grant.public() for grant in runtime.capability_grants.list()]
            elif namespace.authority_action == "grant":
                result = runtime.capability_grants.grant(namespace.capability).public()
            else:
                result = runtime.capability_grants.revoke(namespace.capability).public()
            print(json.dumps(result, indent=2))
        except (OSError, ValueError) as error:
            parser.exit(1, f"PC capability could not be changed: {error}\n")
        return
    if namespace.command == "access":
        try:
            if namespace.access_action == "list":
                result = [grant.public() for grant in runtime.resource_grants.list()]
            elif namespace.access_action == "grant":
                result = runtime.resource_grants.grant(namespace.root, {namespace.permission}).public()
            else:
                result = runtime.resource_grants.revoke(namespace.grant_id).public()
            print(json.dumps(result, indent=2))
        except (OSError, ValueError) as error:
            parser.exit(1, f"Access grant could not be changed: {error}\n")
        return
    if namespace.command == "sequence":
        from chutku.plans import build_plan, run_plan
        try:
            plan = build_plan(namespace.step, runtime)
            result = run_plan(plan, runtime) if namespace.execute else plan
            print(json.dumps(result, indent=2, ensure_ascii=False))
            if namespace.execute and result["state"] != "COMPLETED":
                raise SystemExit(1)
        except (ValueError, OSError) as error:
            parser.exit(1, f"Plan could not run: {error}\n")
        return
    if namespace.command == "brain":
        from chutku.brain import preview_tool_plan, preview_dual_tool_plan
        try:
            message = " ".join(namespace.message)
            proposal = (preview_dual_tool_plan(message, runtime, cloud_consent=True)
                        if namespace.consult_gemini else preview_tool_plan(message, runtime))
            print(json.dumps(proposal, indent=2, ensure_ascii=False))
            print("Preview only. Use the dashboard to review and run supported steps.")
        except (OSError, ValueError, RuntimeError, KeyError, PermissionError) as error:
            parser.exit(1, f"Local planning did not complete: {error}\n")
        return
    if namespace.command == "workflow":
        from chutku.workflows import project_plan, preflight, run_project
        try:
            plan = project_plan(namespace.name, runtime.granted_root)
            if namespace.execute:
                result = run_project(plan, runtime)
                print(json.dumps(result, indent=2))
                if result["state"] != "COMPLETED":
                    raise SystemExit(1)
            else:
                preflight(plan, runtime)
                print(json.dumps(plan, indent=2))
                print("Preview only. Add --execute to run this recipe.")
        except ValueError as error:
            parser.error(str(error))
        return
    if namespace.command == "tools":
        print("\n".join(f"{tool.name}: {tool.description}" for tool in runtime.registry.list()))
        return
    if namespace.command == "chat":
        run_chat(runtime)
        return
    if namespace.command == "history":
        try:
            tasks = runtime.event_log.recent_tasks(namespace.limit)
        except ValueError as error:
            parser.error(str(error))
        if not tasks:
            print("No recorded tasks.")
            return
        print("Recent tasks (sensitive arguments and tool output are not shown):")
        for task in tasks:
            print(f"{task['timestamp']} | {task['state']} | {task['tool']} | {task['task_id']}")
        return
    if namespace.command == "trace":
        trace_events = runtime.event_log.safe_trace(namespace.task_id)
        if not trace_events:
            print("No audit trace found for that task ID.")
            return
        for event in trace_events:
            print(f"{event['timestamp']} | {event['event_type']} | {json.dumps(event['details'], sort_keys=True)}")
        return
    if namespace.command == "ask":
        print(reply(" ".join(namespace.message), runtime))
        return
    try:
        arguments = json.loads(namespace.args)
        if not isinstance(arguments, dict):
            raise ValueError("--args must be a JSON object")
    except (json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(runtime.run(namespace.tool, arguments), default=str, indent=2))


if __name__ == "__main__":
    main()
