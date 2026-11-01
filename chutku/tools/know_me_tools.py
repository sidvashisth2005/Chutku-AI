"""Tools on top of chutku/know_me.py (2026-11-01): play a show from the owner's own library and VLC history, and say
what Chutku knows about how the owner uses the PC."""
from __future__ import annotations

from pathlib import Path
import subprocess
import time

from chutku.tools.registry import Risk, Tool, ToolResult, Verification

VLC = Path(r"C:\Program Files\VideoLAN\VLC\vlc.exe")
_PLAY_SCHEMA = {"type": "object", "properties": {
    "series": {"type": "string", "minLength": 1, "maxLength": 80},
    "episode": {"type": "integer", "minimum": 1, "maximum": 2000},
    "which": {"type": "string", "enum": ["continue", "next", "again", "latest", "first"]}},
    "required": ["series"], "additionalProperties": False}
_NONE = {"type": "object", "properties": {}, "additionalProperties": False}


def _data(base):
    from chutku import know_me
    data = know_me.load(base)
    if not data or time.time() - data.get("refreshed", 0) > 6 * 3600:
        data = know_me.refresh(base)
    return data


def _base(context):
    return context.granted_root.parent


def _vlc_shows(name, wait=8.0):
    """True once a VLC window title names the file (VLC titles are "<file> - VLC media player")."""
    from chutku.tools.everyday import Desktop
    stem = Path(name).stem.casefold()[:40]
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        desktop = Desktop()
        for hwnd in desktop.windows():
            info = desktop.describe(hwnd)
            title = str(info.get("title") or "").casefold()
            if "vlc" in title and stem in title:
                return True
        time.sleep(0.4)
    return False


def _play(arguments, context):
    from chutku import know_me
    data = _data(_base(context))
    show = know_me.find_series(arguments["series"], data)
    if show is None:
        return ToolResult({"error": f"I couldn't find '{arguments['series']}' in your videos.",
                           "series_known": list(data.get("media", {}))[:15]}, Verification.FAIL)
    try:
        path, number, start = know_me.choose_episode(show, data, arguments.get("episode"),
                                                     arguments.get("which", "continue"))
    except LookupError as error:
        return ToolResult({"error": str(error), "series": show}, Verification.FAIL)
    if not VLC.is_file() or not Path(path).is_file():
        return ToolResult({"error": "VLC or the video file is missing.", "file": path}, Verification.FAIL)
    args = [str(VLC), "--one-instance", "--no-playlist-enqueue"]
    if start:
        args.append(f"--start-time={int(start)}")
    subprocess.Popen(args + [path], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    shown = _vlc_shows(path)
    return ToolResult({"series": show, "episode": number, "file": Path(path).name, "resumed_at_s": start,
                       "playing_in": "VLC"}, Verification.PASS if shown else Verification.FAIL)


def _library(arguments, context):
    from chutku import know_me
    data = _data(_base(context))
    out = {"series": []}
    for show, entry in data.get("media", {}).items():
        numbers = sorted(int(n) for n in entry["episodes"])
        if not numbers and not entry["extras"]:
            continue
        seen = data.get("progress", {}).get(show, {})
        out["series"].append({"series": show, "episodes_here": f"{numbers[0]}-{numbers[-1]}" if numbers else "",
                              "last_watched": seen.get("last"), "extras": len(entry["extras"])})
    out["series"].sort(key=lambda s: -(s["last_watched"] or 0))
    out["series"] = out["series"][:15]
    return ToolResult(out, Verification.PASS)


def _profile(arguments, context):
    from chutku import know_me
    return ToolResult(know_me.summary(_data(_base(context))), Verification.PASS)


def _check(allowed):
    def validate(arguments):
        if not isinstance(arguments, dict) or set(arguments) - set(allowed):
            raise ValueError("Unexpected arguments.")
        if "series" in allowed:
            if not isinstance(arguments.get("series"), str) or not arguments["series"].strip():
                raise ValueError("Say which show.")
            episode = arguments.get("episode")
            if episode is not None and (isinstance(episode, bool) or not isinstance(episode, int) or not 1 <= episode <= 2000):
                raise ValueError("episode must be a number.")
            if arguments.get("which", "continue") not in {"continue", "next", "again", "latest", "first"}:
                raise ValueError("which must be continue, next, again, latest or first.")
    return validate


def register_know_me_tools(registry):
    registry.register(Tool("media.play_series", "Play a show or anime from the owner's own video folders in VLC: a given "
                           "episode, or (which) continue where they stopped / next / again / latest / first, using VLC's "
                           "watch history. Example: series='Baki', which='next'.", Risk.REVERSIBLE, _play,
                           _check(("series", "episode", "which")), argument_schema=_PLAY_SCHEMA,
                           reversibility="compensatable", success_predicate="vlc_window_shows_file"))
    registry.register(Tool("media.library", "The shows and videos on this PC and how far the owner has watched each.",
                           Risk.OBSERVATION, _library, _check(()), argument_schema=_NONE,
                           reversibility="not_applicable", success_predicate="library_listed"))
    registry.register(Tool("me.profile", "What Chutku has learned about how the owner uses this PC: most-used apps, "
                           "most-visited sites, shows being watched (local only).", Risk.OBSERVATION, _profile, _check(()),
                           argument_schema=_NONE, reversibility="not_applicable", success_predicate="profile_returned"))
