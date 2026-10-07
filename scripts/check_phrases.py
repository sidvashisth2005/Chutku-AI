"""Instant-path coverage: how many real phrasings resolve without the AI model, and how fast.

Usage: .venv\\Scripts\\python.exe scripts\\check_phrases.py
Each case is (phrase, expected tool). Includes typed English/Hinglish and voice-model rewrites seen live.
"""
from __future__ import annotations

from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

APPS = [{"name": "Spotify", "app_id": "Spotify.App"}, {"name": "WhatsApp", "app_id": "WhatsApp.App"},
        {"name": "Visual Studio Code", "app_id": "Microsoft.VSCode"}, {"name": "Calculator", "app_id": "Calc"}]

CASES = [
    # messages (typed, Hinglish, and the live voice rewrites from 2026-10-03)
    ("send hi to UB on whatsapp", "message.send"),
    ('send "hi" to UB on whatsapp', "message.send"),
    ("UB ko whatsapp pe hi bhejo", "message.send"),
    ("message UB on whatsapp saying hi", "message.send"),
    ('In WhatsApp, find the chat titled "UB" and send the message "hi" to it.', "message.send"),
    ('Open WhatsApp and send the message "Hi" to the user named UB.', "message.send"),
    ('Retry sending the message "Hi" to UB on WhatsApp.', "message.send"),
    # Night Shift report (owner, 2026-10-07: asked by voice and got a made-up answer)
    ("Have you prepared the night report, bhai?", "nightshift.report"), ("raat ko kya kiya", "nightshift.report"),
    ("नाइट शिफ्ट रिपोर्ट", "nightshift.report"), ("night shift ka report batao", "nightshift.report"),
    # apps and media
    ("open spotify", "apps.launch"), ("spotify kholo", "apps.launch"), ("open whatsapp", "apps.launch"),
    ("close spotify", "apps.quit"), ("play lofi hip hop on youtube", "youtube.play"),
    ("youtube pe arijit singh chalao", "youtube.play"), ("next song", "media.control"), ("pause", "media.control"),
    ("whats playing", "media.status"), ("search youtube for lofi", "web.search"),
    ("install hollow knight on steam", "games.install"),
    # PC
    ("set volume to 30", "audio.volume"), ("awaaz kam karo", "audio.volume"), ("mute", "audio.volume"),
    ("brightness kam karo", "display.brightness"), ("lock my pc", "system.lock"),
    ("switch audio to headphones", "audio.set_output"), ("list audio devices", "audio.outputs"),
    ("how much space is left", "system.disk_space"), ("storage kitna khali hai", "system.disk_space"),
    ("free up space on my C drive", "storage.cleanup_report"), ("is my internet working", "net.check"),
    ("internet chal raha hai kya", "net.check"), ("whats my ip", "net.check"), ("ping google", "net.ping"),
    # files
    ("find my resume", "files.find"), ("meri resume file dhundo", "files.find"), ("open my downloads", "files.open"),
    ("d drive kholo", "files.open"), ("what was I working on?", "files.recent"),
    ("organize my Downloads folder", "files.organize"),
    # day
    ("what time is it", "system.get_time"), ("kitne baje hai", "system.get_time"), ("weather in Pune", "web.weather"),
    ("Pune ka mausam kaisa hai", "web.weather"), ("khabar batao", "web.news"), ("good morning", "system.get_time"),
    ("remind me in 20 minutes to drink water", "reminder.set"), ("set a timer for 25 minutes", "reminder.set"),
    ("remember city = Delhi", "memory.remember"), ("note: buy milk", "note.add"), ("show my list", "note.list"),
    ("mark 2 done", "note.done"), ("what did you do today", "log.recent"), ("aaj kya kiya", "log.recent"),
    ("screen pe kya hai", "screen.understand"), ("list my routines", "routine.list"),
    ("build me a calculator app", "code.build_project"),
    # PC info (these took 11-15 s through the model in the 2026-10-01 benchmark)
    ("which gpu do i have", "system.gpu_status"), ("what windows version do i have", "system.environment"),
    ("what is the volume", "system.volume_status"), ("is dark mode on", "settings.theme_status"),
    ("battery kitni hai", "system.health"), ("how is my pc doing", "system.health"), ("ram usage", "system.health"),
    # misses from the live timing run of 2026-10-03 (each took 13-56 s through the model)
    ("What is the current volume level?", "system.volume_status"),
    ("Is Windows using dark mode or light mode right now?", "settings.theme_status"),
    ("How much free space is left on my C drive?", "system.disk_space"),
    ("D drive mein kitni jagah khali hai?", "system.disk_space"), ("How much RAM am I using right now?", "system.health"),
    ("Am I connected to the network? Which adapter is up?", "net.check"),
    ("How many displays are connected?", "screen.displays"), ("What is my screen brightness?", "display.brightness_status"),
    ("Is VLC or Spotify installed on this PC?", "apps.installed"), ("do i have steam installed", "apps.installed"),
    ("Which games do I have installed?", "games.list"), ("mere games dikhao", "games.list"),
    # small talk: an instant friendly reply, no tool
    ("Hi Chutku, how are you?", "(reply)"), ("kaise ho", "(reply)"), ("thank you", "(reply)"),
    # personal memory (2026-10-04)
    ("UB is my gf", "mind.person"), ("UB meri gf hai", "mind.person"), ("remember Sharma Sir is my DL wale sir", "mind.person"),
    ("mammi ka number +91 98765 43210 hai", "mind.person"), ("mera ghar Pune mein hai", "mind.fact"),
    ("add assignment: DBMS report by Friday", "mind.add"), ("my skills are python, react", "mind.add"),
    ("assignment 1 done", "mind.done"), ("mere assignments dikhao", "mind.show"), ("what do you know about me", "mind.show"),
    ("who is my gf", "mind.who"),
    ("switch to dark mode", "settings.theme_set"), ("dark mode on karo", "settings.theme_set"),
    ("turn on light mode", "settings.theme_set"),
    # keyboard and mouse (2026-10-04)
    ("press ctrl+shift+t", "keyboard.keys"), ("ctrl shift t dabao", "keyboard.keys"), ("press down 5 times", "keyboard.keys"),
    ("alt tab karo", "keyboard.keys"), ("click on Downloads", "mouse.click"), ("Downloads pe click karo", "mouse.click"),
    ("right click on Recycle Bin", "mouse.click"),
    # found by the 2026-10-04 verification pass and benchmark
    ("Which windows are open right now? Just list the app names.", "windows.list"), ("kaun se apps khule hain", "windows.list"),
    ("Am I connected to the network? Which adapter is up?", "net.check"), ("time kya hua hai abhi", "system.get_time"),
    (r"What files are in D:\ChutkuBench?", "filesystem.list"), (r"D:\ChutkuBench mein kya hai", "filesystem.list"),
    (r"Read D:\ChutkuBench\todo.txt and tell me the first task.", "file.extract_text"),
    (r"Rename D:\ChutkuBench\draft.txt to final.txt", "filesystem.move"), (r"Delete D:\ChutkuBench\junk.tmp", "filesystem.recycle"),
    (r"Make a copy of D:\ChutkuBench\report.txt named D:\ChutkuBench\report-backup.txt", "filesystem.copy"),
    (r"Write 'x' into D:\ChutkuBench\x.txt", "filesystem.write_text"),
    (r"D:\ChutkuBench mein projects naam ka folder banao", "filesystem.create_directory"), ("double click on Chrome", "mouse.click"), ("hover over Settings", "mouse.move"),
    # controlling Chutku (2026-10-04)
    ("undo that", "log.undo"), ("wapas karo", "log.undo"), ("abhi kya kiya", "log.recent"),
    ("what can you do", "(reply)"), ("suno", "(reply)"), ("ruko", "(reply)"),
]


def run():
    from chutku.quick_intents import quick_proposal
    misses, slow = [], 0.0
    for phrase, expected in CASES:
        started = time.perf_counter()
        proposal = quick_proposal(phrase, apps=APPS)
        slow = max(slow, time.perf_counter() - started)
        tool = None if proposal is None else (proposal["next_steps"][0]["tool"] if proposal["next_steps"] else "(reply)")
        if tool != expected:
            misses.append((phrase, expected, tool))
    return misses, slow


def main():
    misses, slowest = run()
    print(f"instant: {len(CASES) - len(misses)}/{len(CASES)}  slowest match: {slowest * 1000:.1f} ms")
    for phrase, expected, got in misses:
        print(f"  MISS {phrase!r}: expected {expected}, got {got}")
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main())
