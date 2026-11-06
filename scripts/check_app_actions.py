"""Z3: every everyday app/window/browser phrase must be ONE instant step (no planner). Prints the misses and the time.

    .venv\\Scripts\\python.exe scripts\\check_app_actions.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# phrase -> the tool it must become (one step)
PHRASES = {
    # browser (Brave by default)
    "new tab kholo": "app.brave.new_tab", "open a new tab": "app.brave.new_tab", "ek new tab open kar": "app.brave.new_tab",
    "close this tab": "app.brave.close_tab", "tab band karo": "keyboard.edit",   # Ctrl+W in the app in front
    "reopen the closed tab": "app.brave.reopen_closed_tab", "band kiya hua tab wapas kholo": "app.brave.reopen_closed_tab",
    "refresh the page": "app.brave.reload", "page reload karo": "app.brave.reload",
    "next tab": "app.brave.next_tab", "agla tab": "app.brave.next_tab", "previous tab": "app.brave.previous_tab",
    "go back": "app.brave.back", "peeche jao": "app.brave.back", "go forward": "app.brave.forward",
    "zoom in": "app.brave.zoom_in", "zoom out karo": "app.brave.zoom_out",
    "open history": "app.brave.history", "downloads dikhao": "app.brave.downloads",
    "scroll down": "app.brave.scroll_down", "neeche scroll karo": "app.brave.scroll_down", "scroll up": "app.brave.scroll_up",
    # YouTube in the browser
    "full screen karo": "app.brave.yt_fullscreen", "make it full screen": "app.brave.yt_fullscreen",
    "youtube full screen karo": "app.brave.yt_fullscreen", "exit full screen": "app.brave.yt_fullscreen",
    "video aage karo": "app.brave.yt_forward", "skip 10 seconds": "app.brave.yt_forward",
    "video peeche karo": "app.brave.yt_back", "captions on karo": "app.brave.yt_captions",
    "theatre mode": "app.brave.yt_theatre", "speed badhao": "app.brave.yt_faster", "speed kam karo": "app.brave.yt_slower",
    "next video": "app.brave.yt_next", "agla video chalao": "app.brave.yt_next", "mute the video": "app.brave.yt_mute",
    # windows (the one in front) and Windows' own shortcuts
    "minimize this window": "windows.this", "window chhota karo": "windows.this",
    "maximize the window": "windows.this", "window bada karo": "windows.this", "snap this window left": "windows.this",
    "close this window": "windows.close_this", "show desktop": "keyboard.keys",
    "switch window": "keyboard.keys", "task view kholo": "keyboard.keys",
    # VLC / Spotify
    "vlc full screen karo": "app.vlc.fullscreen", "vlc pause karo": "media.control",
    "shuffle on karo": "app.spotify.shuffle", "repeat on karo": "app.spotify.repeat",
}


def main():
    from chutku.quick_intents import quick_proposal
    misses, started = {}, time.perf_counter()
    for text, tool in PHRASES.items():
        proposal = quick_proposal(text)
        steps = [s["tool"] for s in (proposal or {}).get("next_steps", [])]
        if steps != [tool]:
            misses[text] = steps or None
    seconds = time.perf_counter() - started
    for text, got in misses.items():
        print(f"MISS {text!r}: want {PHRASES[text]}, got {got}")
    print(f"instant: {len(PHRASES) - len(misses)}/{len(PHRASES)} in {seconds * 1000:.0f} ms")
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main())
