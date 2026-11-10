"""Spoken/typed replies for tool results on the instant path (QUICK_ANSWERS: tool name -> reply builder)."""
from __future__ import annotations

from pathlib import Path
import re


def _say_time(out):
    return f"It's {out['local_time']}."


def _say_disk(out):
    parts = [f"{d['drive'][0]}: has {d['free_gb']} GB free of {d['total_gb']} GB ({d['free_percent']}%)"
             for d in out["drives"]]
    return "; ".join(parts) + "." + (" " + out["advice"] if out.get("advice") else "")


def _say_recent(out):
    if not out["files"]:
        where = ", ".join(Path(folder).name or folder for folder in out["searched"])
        return f"No files changed in the last {out['days']} days in {where}."
    names = ", ".join(f"{f['name']} ({f['modified'][5:]})" for f in out["files"][:5])
    return f"Most recently changed: {names}."


def _say_log(out):
    if not out["actions"]:
        return "I haven't done anything yet." if out["chain_ok"] else "My action log is damaged; run doctor."
    shown = [f"#{a['id']} {a['tool']} {a['state'].lower().replace('_', ' ')}" for a in out["actions"][:6]]
    return f"{out['count']} action(s), newest first: " + "; ".join(shown) + "."


def _say_routines(out):
    if not out["routines"]:
        return "No routines yet. Try: save routine work: open VS Code, play lofi on YouTube, set volume to 30."
    return " ".join(f"{name}: {', '.join(commands)}." for name, commands in out["routines"].items())


def _say_cleanup(out):
    if not out["suggestions"]:
        return f"Nothing big to clear on {out['drive'][0]}: right now."
    return (f"Here's where you can free space on {out['drive'][0]}: " + "; ".join(out["suggestions"]) +
            ". This was only a look: your files are untouched. Tell me which to recycle, or open Disk Cleanup for temp files.")


def _say_playing(out):
    title = out.get("title") or (out.get("now_playing") or {}).get("title")
    artist = out.get("artist") or (out.get("now_playing") or {}).get("artist")
    if not title:
        return "Nothing is playing right now."
    return f"“{title}”" + (f" by {artist}" if artist else "") + " is playing."


def _say_outputs(out):
    names = [d["name"] + (" (in use)" if d["default"] else "") for d in out["devices"]]
    return "Playback devices: " + ", ".join(names) + "."


def _say_image(out):
    return out["description"]


def _say_remote(out):
    """W6 phone access replies (her own words; the pairing code itself is shown on the laptop screen)."""
    if out.get("error"):
        return str(out["error"])
    if out.get("steps"):
        return str(out["steps"])
    if "code" in out:
        return (f"Phone pe ye link kholo: {out.get('link')} . Code {out['code']} hai, {out.get('minutes', 10)} minute "
                f"tak chalega. Dashboard ke Phone panel mein QR bhi hai.")
    if "removed" in out:
        return "Ye phone hata diye: " + ", ".join(out["removed"]) + ". Unhe dobara pair karna hoga."
    if "control_allowed" in out:
        return ("Phone se control ab allowed hai; shuru karne ke liye phone pe PIN lagega." if out["control_allowed"]
                else "Phone se control band kar diya.")
    if out.get("enabled") is True:
        return f"Phone access chalu hai: {out.get('url')} . Ab 'phone pair karo' bolo."
    if out.get("enabled") is False and "running" not in out:
        return "Phone access band kar diya."
    phones = out.get("phones") or []
    state = "chalu" if out.get("enabled") else "band"
    extra = (" Phone abhi juda hua hai." if out.get("phone_active") else "") + \
            (" Screen dekhi ja rahi hai." if out.get("viewing") else "") + \
            (" Phone se control ho raha hai." if out.get("controlling") else "")
    return f"Phone access {state} hai, {len(phones)} phone paired." + extra


def _say_show(out):
    if out.get("error"):
        return str(out["error"])
    resumed = f", {int(out['resumed_at_s']) // 60} minute se aage" if out.get("resumed_at_s") else ""
    episode = f" episode {out['episode']}" if out.get("episode") else ""
    return f"{out.get('series')}{episode} VLC mein chala diya{resumed}."


def _say_library(out):
    shows = out.get("series") or []
    if not shows:
        return "Mujhe abhi koi show nahi mila tumhare videos mein."
    parts = [f"{s['series']} (last {s['last_watched']})" if s.get("last_watched") else s["series"] for s in shows[:5]]
    return "Tumhare paas: " + ", ".join(parts) + "."


def _say_profile(out):
    return ("Tum sabse zyada " + ", ".join(out.get("top_apps", [])[:5]) + " use karte ho; sites: "
            + ", ".join(out.get("top_sites", [])[:5]) + "; shows: " + ", ".join(list(out.get("series", {}))[:4]) + ".")


def _say_screen(out):
    return out.get("answer") or out.get("summary") or "I looked, but couldn't describe the screen."


def _say_notes(out):
    open_items = [f"{i['id']}. {i['text']}" for i in out["items"] if not i["done"]]
    if not open_items:
        return "Your list is empty." if not out["items"] else "Everything on your list is done."
    return f"{len(open_items)} on your list: " + "; ".join(open_items[:8]) + "."


def _say_found(out):
    if not out["matches"]:
        return f"I couldn't find a file named like “{out['query']}” in your personal folders."
    shown = "; ".join(f"{m['name']} (in {m['folder']}, {m['modified'][:10]})" for m in out["matches"][:5])
    more = f" and {out['count'] - 5} more" if out["count"] > 5 else ""
    return f"Found {out['count']}: {shown}{more}."


def _say_located(out):
    where = " in your personal folders (the drive index isn't built yet; say 'saari drives index karo')" \
        if out.get("index_built") is None else ""
    if not out["matches"]:
        return f"I couldn't find a file named like “{out['query']}”{where or ' on your drives'}."
    shown = "; ".join(f"{m['path']} ({m['modified'][:10]})" for m in out["matches"][:5])
    more = f" and {out['count'] - 5} more" if out["count"] > 5 else ""
    return f"Found {out['count']}{where}: {shown}{more}."


def _say_index(out):
    if not out.get("started"):
        return out.get("note", "The drive index is already being built.")
    return ("Building the file index of " + ", ".join(d.rstrip("\\") for d in out["drives"]) +
            " in the background (a few minutes). After that, 'X kahan hai' is instant.")


def _say_net(out):
    ip = f" Your IP is {out['local_ip']} on this network" + (f", {out['public_ip']} on the internet." if out.get("public_ip")
                                                               else ".") if out.get("local_ip") else ""
    return out["verdict"] + ip


def _say_ping(out):
    if out.get("unknown_host"):
        return f"There's no site called {out['host']}."
    if not out["received"]:
        return f"{out['host']} didn't answer any of {out['sent']} pings."
    return (f"{out['host']} answered {out['received']} of {out['sent']} pings"
            + (f", average {out['average_ms']} ms." if out.get("average_ms") is not None else "."))


def _say_message(out):
    if out.get("seen_in_chat"):
        return f"Done: “{out['text']}” is now in your {out['app']} chat with {out['to']}." + (
            " " + out["tip"] if out.get("tip") else "")
    return f"I pressed send in {out['app']} for {out['to']}, but couldn't see the message in the chat. Please check."


def _say_reliability(out):
    """Earned autonomy in plain words: how often checked actions worked, and what keeps failing."""
    if not out.get("actions_measured"):
        return "Nothing measured yet: every step that changes something is checked and counted as it runs."
    count = out["actions_measured"]
    text = (f"Of {count} checked action{'' if count == 1 else 's'}, {out['worked']} really worked "
            f"({round(out['rate'] * 100)}%).")
    weak = out.get("keeps_failing") or []
    if weak:
        text += " Keeps failing, so it asks you first: " + "; ".join(
            f"{w['tool']} on {w['target']} ({w['passes']}/{w['trials']})" for w in weak[:3]) + "."
    else:
        text += " Nothing keeps failing right now."
    return text


def _say_timeline(out):
    if out.get("note"):
        return out["note"]
    matches = out["matches"]   # strict: an unexpected shape lets the model answer instead of a wrong fixed reply
    if not matches:
        return ("Nothing like that in the timeline for that time." if out["recording"]
                else "The timeline is off, so I don't know. Type 'timeline on' to let me remember window titles.")
    first = matches[0]
    text = f"{first['title']} ({first['app']}, {first['at']})"
    if len(matches) > 1:
        text += ". Also: " + "; ".join(f"{m['title']} ({m['at']})" for m in matches[1:4])
    return text + "."


def _say_rewind(out):
    """rewind.preview / rewind.run in plain words."""
    if "undone" not in out:
        return out.get("summary") or "Nothing to undo."
    text = out.get("summary") or ""
    if out.get("skipped_conflict"):
        text += " Kept as you changed them: " + "; ".join(s.rstrip(".") for s in out["skipped_conflict"][:3]) + "."
    if out.get("irreversible"):
        text += " Cannot be undone: " + "; ".join(out["irreversible"][:3]) + "."
    if out.get("failed"):
        text += " Failed: " + "; ".join(out["failed"][:3]) + "."
    return text


def _say_tasks(out):
    tasks = out.get("tasks") or []
    if not tasks:
        return "Nothing is scheduled right now."
    return f"{len(tasks)} scheduled: " + "; ".join(f"{t['summary']} (id {t['id']})" for t in tasks[:6]) + "."


def _say_visible(out):
    """screen.act_on_visible (2026-10-08)."""
    if out.get("playing"):
        now = f" Now playing: {out['now_playing']}" + (f" by {out['artist']}" if out.get("artist") else "") + "." \
            if out.get("now_playing") else ""
        return f"Played “{out['clicked']}” from the screen.{now}"
    if "play_button" in out:
        return f"Opened “{out['clicked']}”, but it is not playing yet. " + (out.get("error") or "")
    return f"Clicked “{out['clicked']}” on the screen."


def _say_week(out):
    """Weekly insights (Phase 3b H7)."""
    from chutku.insights import say
    return say(out)


def _say_history(out):
    """Past chats about a topic (Phase 3b H4)."""
    found = out.get("matches") or []
    topic = " ".join(out.get("terms") or []) or out.get("query", "")
    if not found:
        return f"I found nothing about “{topic}” in our past chats."
    lines = [f"{m['date']}: you said “{m['said'][:90]}”" + (f", I said “{m['reply'][:90]}”" if m.get("reply") else "")
             for m in found[:3]]
    return f"About “{topic}” ({len(found)} found): " + "; ".join(lines) + "."


def _say_background(out):
    if not out.get("paused"):
        return "Background work is running normally (scheduled tasks and the Night Shift)."
    since = f" since {str(out['since'])[:16].replace('T', ' ')}" if out.get("since") else ""
    return (f"Background work is paused{since}: scheduled tasks and the Night Shift are waiting. "
            "Type \"resume background work\" to start them again.")


def _say_night(out):
    """Last night's Night Shift report in plain words."""
    if not out.get("ran"):
        return out.get("summary") or "Night Shift has not run yet."
    counts = out.get("counts") or {}
    text = (f"Night Shift ran on {out.get('date')} ({str(out.get('started', ''))[11:16]}–"
            f"{str(out.get('finished', ''))[11:16]}): {out.get('new_skills', 0)} new instant skills; re-checked "
            f"{out.get('requests_rechecked', 0)} of your past requests: {counts.get('same', 0)} same, "
            f"{counts.get('changed', 0)} changed, {counts.get('fails now', 0)} now failing.")
    if out.get("fails_now"):
        text += " Now failing: " + "; ".join(f"\"{g}\"" for g in out["fails_now"][:3]) + "."
    if out.get("keeps_failing"):
        text += " Keeps failing: " + ", ".join(out["keeps_failing"][:3]) + "."
    if out.get("jobs_failed"):
        text += " Jobs that failed: " + ", ".join(out["jobs_failed"]) + "."
    return text + f" Fine-tune data: {out.get('fine_tune')}."


def _say_learned(out):
    """Learned instant skills (master plan S17) in plain words."""
    def share(value):
        return "–" if value is None else f"{round(value * 100)}%"
    week = (f" Instant answers this week: {share(out.get('instant_this_week'))} "
            f"(last week {share(out.get('instant_last_week'))}).")
    skills = out.get("skills") or []
    if not skills:
        return ("Nothing learned yet: when you ask the same kind of thing twice in different words and it works, "
                "I learn to do it instantly." + week)
    active = [s for s in skills if s.get("enabled")]
    text = f"I learned {len(skills)} skill{'' if len(skills) == 1 else 's'} ({len(active)} on): " + "; ".join(
        f"\"{s['phrase']}\" ({s['passes']}/{s['hits']} worked)" if s.get("enabled") else f"\"{s['phrase']}\" (off)"
        for s in skills[:5]) + "."
    return text + week


def _say_gpu(out):
    return "; ".join(f"{g['name']} with {round(int(g['vram_mib']) / 1024)} GB video memory ({int(g['vram_mib'])} MB, "
                     f"driver {g['driver_version']})" for g in out["gpus"]) + "."


def _say_adapters(out):
    parts = []
    for adapter in out["adapters"]:
        status = str(adapter.get("Status", "")).casefold()
        state = "up" if status == "up" else "disconnected" if "disconnect" in status else status or "unknown"
        speed = f", {adapter['LinkSpeed']}" if state == "up" and adapter.get("LinkSpeed") else ""
        parts.append(f"{adapter.get('Name', 'adapter')} is {state}{speed}")
    return ("; ".join(parts) + ".") if parts else "No network adapters found."


def _say_environment(out):
    build = int(str(out["windows_version"]).split(".")[-1] or 0)
    name = "Windows 11" if build >= 22000 else "Windows 10"
    drives = ", ".join(f"{d['drive']} {d['free_gib']} GB free" for d in out.get("drives", []))
    return f"{name} (build {out['windows_version']}, {out['machine']})." + (f" Drives: {drives}." if drives else "")


def _say_bluetooth(out):
    # Windows lists paired devices as present whenever the radio is on: that is not "connected" (live 2026-11-10)
    names = [d["name"] for d in out.get("devices") or []]
    state = "Bluetooth is on" if out.get("on") else "Bluetooth is off"
    return state + (f"; paired: {', '.join(names[:5])}." if names else ".")


def _say_volume(out):
    return "Sound is muted." if out.get("muted") else f"Volume is at {out['level']}%."


def _say_theme(out):
    return f"Apps use {out['apps']} mode and Windows uses {out['system']} mode."


def _say_health(out):
    parts = []
    power = out.get("battery")
    if power:
        parts.append(f"battery {power['percent']}%" + (" and charging" if power["charging"] else " on battery power"))
    if out.get("memory"):
        parts.append(f"RAM {out['memory']['used_percent']}% used ({out['memory']['free_gb']} GB free)")
    parts += [f"{d['drive'][0]}: {d['free_gb']} GB free" for d in out.get("disk", [])]
    low = [d["drive"][0] + ":" for d in out.get("disk", []) if d.get("low")]
    return ("Your PC: " + ", ".join(parts) + "." + (f" Low space on {', '.join(low)}." if low else ""))


def _say_perf(out):
    """CPU, RAM, GPU and what uses the most memory: the instant answer to "laptop lag kar raha hai"."""
    parts = []
    if out.get("cpu_percent") is not None:
        parts.append(f"CPU {round(out['cpu_percent'])}%" + (f" at {round(out['cpu_temperature_c'])}°C" if out.get(
            "cpu_temperature_c") is not None else ""))
    memory = out.get("memory") or {}
    if memory:
        parts.append(f"RAM {memory['used_percent']}% used ({memory['used_gib']} of {memory['total_gib']} GB)")
    gpu = out.get("gpu") or {}
    if gpu.get("utilization_percent") is not None:
        parts.append(f"GPU {gpu['utilization_percent']}%" + (f" at {gpu['temperature_c']}°C" if gpu.get(
            "temperature_c") is not None else ""))
    network = out.get("network_mbps") or {}
    if network.get("down_mbps") is not None:
        parts.append(f"network {network['down_mbps']:g} Mbps down, {network.get('up_mbps') or 0:g} up")
    text = "Your PC: " + ", ".join(parts) + "." if parts else "I could not read the PC's load."
    if out.get("cpu_temperature_note"):
        text += " " + out["cpu_temperature_note"]
    totals = {}
    for process in out.get("top_memory_processes") or []:   # several "Code" windows are one app
        totals[process["name"]] = totals.get(process["name"], 0) + process["memory_mib"]
    if totals:
        label = {"llama-server": "my local brain (llama-server)", "MsMpEng": "Windows Defender", "Code": "VS Code"}
        top = sorted(totals.items(), key=lambda item: -item[1])[:3]
        text += " Using the most memory: " + ", ".join(
            f"{label.get(name, name)} {mib / 1024:.1f} GB" for name, mib in top) + "."
    hints = []
    if memory.get("used_percent", 0) >= 85:
        hints.append("RAM is almost full; closing one of those apps would help most")
    if (out.get("cpu_percent") or 0) >= 85:
        hints.append("the CPU is very busy right now")
    if gpu.get("temperature_c") and gpu["temperature_c"] >= 85:
        hints.append("the GPU is hot")
    if (out.get("cpu_temperature_c") or 0) >= 90:
        hints.append("the CPU is hot")
    hints = "; ".join(hints)
    return text + (" " + hints[:1].upper() + hints[1:] + "." if hints else "")   # not capitalize(): it lowercases "CPU"


def _describe_person(person):
    extra = [f"aka {', '.join(person['aliases'])}" if person.get("aliases") else "",
             person.get("relation") or "", f"WhatsApp chat “{person['whatsapp']}”" if person.get("whatsapp") else "",
             "number saved" if person.get("phone") else ""]
    return person["name"] + (" (" + "; ".join(e for e in extra if e) + ")" if any(extra) else "")


def _say_who(out):
    if not out["known"]:
        return (f"I don't know who {out['name']} is yet. Tell me, e.g. “AK is my {out['name']}”, "
                f"or “{out['name']} ka number +91… hai”.")
    return f"{out['name']} is {_describe_person(out['person'])}."


def _say_mind(out):
    parts = []
    if out.get("people"):
        parts.append("People: " + "; ".join(_describe_person(p) for p in out["people"][:15]) + ".")
    if out.get("facts"):
        parts.append("About you: " + "; ".join(f"{k}: {v}" for k, v in list(out["facts"].items())[:15]) + ".")
    for name, items in (out.get("lists") or {}).items():
        if not items:
            parts.append(f"Your {name} list is empty.")
            continue
        shown = "; ".join(f"{i['id']}. {i['text']}" + (" (done)" if i.get("done") else "") for i in items[:15])
        parts.append(f"{name.capitalize()}: {shown}.")
    if parts and out.get("memory_meter"):
        parts.append(out["memory_meter"])   # how much of it fits in one prompt (Phase 3b H3)
    return " ".join(parts) or "I don't know anything about you yet. Tell me: “AK is my gf”, “my home is in Pune”, " \
                              "“add assignment: DBMS report by Friday”."


def _say_games(out):
    if not out["games"]:
        return "I don't see any Steam or Epic games on this PC."
    shown = ", ".join(f"{g['name']} ({g['store']}" + (f", {g['state']})" if g.get("state") != "installed" else ")")
                      for g in out["games"][:12])
    return f"{out['count']} game{'s' if out['count'] != 1 else ''}: {shown}."


# Windows' own background windows, not apps the owner opened (seen live 2026-10-04).
_SHELL_WINDOWS = {"program manager", "windows input experience", "nvidia geforce overlay", "microsoft text input application",
                  "windows shell experience host", "search", "start", "task view", "chutku", "default ime", "msctfime ui"}


def _app_of(window):
    """'lofi - YouTube - Personal - Microsoft Edge' -> 'Microsoft Edge'; '(6) WhatsApp' -> 'WhatsApp'."""
    title = (window.get("title") or "").replace("\u200b", "").strip()
    name = title.rsplit(" - ", 1)[-1].strip() if " - " in title else title
    name = re.sub(r"^\(\d+\)\s*", "", name) or Path(window.get("executable") or "").stem   # unread counts
    return None if name.casefold() in _SHELL_WINDOWS else name


def _say_listing(out):
    entries = out.get("entries") or []
    if not entries:
        return f"{out['path']} is empty."
    if "file_count" in out:   # exact counts from the tool, files and folders told apart
        def part(label, names):
            if not names:
                return ""
            shown = ", ".join(names[:15]) + (f" and {len(names) - 15} more" if len(names) > 15 else "")
            return f"{len(names)} {label}{'s' if len(names) != 1 else ''} ({shown})"
        pieces = [p for p in (part("file", out.get("files") or []), part("folder", out.get("folders") or [])) if p]
        return f"{out['path']} has " + " and ".join(pieces) + "."
    shown = ", ".join(entries[:25]) + (f", and {len(entries) - 25} more" if len(entries) > 25 else "")
    return f"{len(entries)} item{'s' if len(entries) != 1 else ''} in {out['path']}: {shown}."


def _say_windows(out):
    apps = list(dict.fromkeys(_app_of(w) for w in out["windows"] if _app_of(w)))
    if not apps:
        return "No app windows are open."
    return f"{len(apps)} app{'s' if len(apps) != 1 else ''} open: " + ", ".join(apps[:15]) + "."


def _say_read_chat(out):
    who = out["to"]
    if not out["messages"]:
        text = f"I opened {who}'s chat but couldn't read any text messages (photos and voice notes can't be read)."
    else:
        said = "; ".join(("You" if m["from"] == "you" else who) + ": " + m["text"][:120] for m in out["messages"][-4:])
        last = out["messages"][-1]
        lead = f"{who} replied" if last["from"] == "them" else f"No reply yet from {who} after your last message"
        text = f"{lead}. Latest: {said}."
    if out.get("sync_warning"):
        text += " " + out["sync_warning"]
    return text


def _say_open_chat(out):
    return f"{out['to']}'s chat is open on WhatsApp. What should I send?"


def _say_displays(out):
    shown = ", ".join(f"{d['width']}x{d['height']}" + (" (main)" if d.get("primary") else "") for d in out["displays"])
    return f"{out['count']} display{'s' if out['count'] != 1 else ''} connected: {shown}."


def _say_brightness(out):
    return f"Screen brightness is at {out['level']}%."


def _say_installed(out):
    query = out.get("query") or "that app"
    if not out["apps"]:
        return f"{query} isn't installed (not in the Start menu)."
    return f"Yes, {query}: " + ", ".join(app["name"] for app in out["apps"][:4]) + "."


# Quick tools whose failures are final (no device, no such routine...): report them instead of re-planning.
FINAL_ERROR_TOOLS = frozenset({"audio.set_output", "audio.outputs", "system.disk_space", "files.recent",
                               "storage.cleanup_report", "routine.save", "routine.list", "log.recent",
                               "image.describe", "note.done", "note.add", "files.find", "files.locate", "files.open",
                               "games.install", "message.send", "message.open_chat", "message.read_chat", "settings.theme_set", "apps.launch", "filesystem.list",
                               "file.extract_text", "mind.person", "mind.add",
                               "mind.done", "mind.fact", "mind.feedback", "mind.map", "settings.offline_mode",
                               "settings.chutku", "media.play_series", "finance.quote", "skill.create", "skill.list"})


# Instant spoken answers for the quick tier's own observation tools (no model round needed).
def _say_backups(out):
    rows = out.get("backups") or []
    if not rows:
        return f"Abhi koi backup nahi hai ({out.get('folder')}). Bolo \"backup bana lo\"."
    return f"{len(rows)} backup(s) in {out.get('folder')}: " + ", ".join(
        f"{r['name']} ({r['bytes'] // 1024} KB)" for r in rows[:4])


def _say_backup(out):
    return f"Backup bana diya: {out['files']} files, {out['bytes'] // 1024} KB, {out['path']}."


def _say_howto(out):
    from chutku.apps.howto import say
    return say(out)


def _say_unread(out):
    from chutku.apps.extras import say_unread
    return say_unread(out)


QUICK_ANSWERS = {"apps.howto": _say_howto, "message.unread_count": _say_unread, "screen.act_on_visible": _say_visible, "insights.week": _say_week, "history.search": _say_history, "background.status": _say_background, "nightshift.report": _say_night, "timeline.search": _say_timeline, "rewind.preview": _say_rewind, "rewind.run": _say_rewind, "task.list": _say_tasks, "reflex.list": _say_learned, "ledger.summary": _say_reliability, "system.get_time": _say_time, "system.disk_space": _say_disk, "files.recent": _say_recent,
                 "log.recent": _say_log, "routine.list": _say_routines,
                 "storage.cleanup_report": _say_cleanup, "media.status": _say_playing,
                 "audio.outputs": _say_outputs,
                 "image.describe": _say_image, "screen.understand": _say_screen, "screen.ask": _say_screen, "media.play_series": _say_show, "media.library": _say_library, "me.profile": _say_profile, "remote.status": _say_remote, "remote.enable": _say_remote, "remote.disable": _say_remote, "remote.pair": _say_remote, "remote.revoke": _say_remote, "remote.arm": _say_remote,
                 "note.list": _say_notes, "files.find": _say_found, "files.locate": _say_located, "files.index": _say_index,
                 "net.check": _say_net, "net.ping": _say_ping,
                 "message.send": _say_message, "system.gpu_status": _say_gpu,
                 "system.environment": _say_environment, "system.volume_status": _say_volume, "system.bluetooth_status": _say_bluetooth, "system.bluetooth_set": _say_bluetooth,
                 "settings.theme_status": _say_theme, "system.health": _say_health, "system.performance": _say_perf,
                 "screen.displays": _say_displays, "display.brightness_status": _say_brightness,
                 "apps.installed": _say_installed, "games.list": _say_games,
                 "mind.who": _say_who, "mind.show": _say_mind, "windows.list": _say_windows,
                 "network.status": _say_adapters, "filesystem.list": _say_listing,
                 "message.open_chat": _say_open_chat, "message.read_chat": _say_read_chat,
                 "finance.quote": lambda out: out["reply"],
                 "skill.list": lambda out: out["skill_reply"], "skill.create": lambda out: out["skill_reply"],
                 "evolve.list": lambda out: out["skill_reply"], "evolve.review": lambda out: out["skill_reply"],
                 "skill.import": lambda out: out["skill_reply"], "skill.add_procedure": lambda out: out["skill_reply"],
                 "learning.inbox": lambda out: out["summary"], "learning.keep_all": lambda out: out["summary"],
                 "learning.keep": lambda out: out["summary"], "learning.discard": lambda out: out["summary"],
                 "learning.learn": lambda out: out["summary"], "learning.journey": lambda out: out["summary"],
                 "goals.list": lambda out: out["summary"], "goals.add": lambda out: "Goal set. " + out["progress"],
                 "goals.done": lambda out: out["summary"], "backup.list": _say_backups, "backup.create": _say_backup,
                 "blueprint.list": lambda out: out["summary"],
                 "task.delegate": lambda out: out["summary"], "board.add": lambda out: out["summary"],
                 "board.list": lambda out: out["summary"], "board.done": lambda out: out["summary"],
                 "board.again": lambda out: out["summary"],
                 "telegram.handoff": lambda out: out["summary"],
                 "system.self_repair": lambda out: out["summary"],
                 "teach.start": lambda out: out["summary"], "teach.stop": lambda out: out["summary"],
                 "desktop.survey": lambda out: out["summary"],
                 # WA2 system tools
                 "apps.install": lambda out: out["summary"], "apps.uninstall": lambda out: out["summary"],
                 "settings.set": lambda out: out["summary"], "startup.list": lambda out: out["summary"],
                 "startup.toggle": lambda out: out["summary"], "services.list": lambda out: out["summary"],
                 "services.set": lambda out: out["summary"], "system.undo_last": lambda out: out["summary"]}
